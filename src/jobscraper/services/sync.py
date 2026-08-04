"""Resilient, transactionally observable synchronization orchestration."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import requests
from loguru import logger
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from jobscraper.db.base import utc_now
from jobscraper.db.models import (
    CanonicalJob,
    DuplicateRelation,
    SavedSearch,
    SearchListing,
    SourceListing,
    SourceSyncResult,
    SyncRun,
)
from jobscraper.models.job import JobOffer, SearchCriteria
from jobscraper.repositories.jobs import JobRepository
from jobscraper.repositories.sync_runs import SyncRunRepository
from jobscraper.scrapers.base import BaseScraper
from jobscraper.scrapers.registry import ScraperRegistry
from jobscraper.services.deduplication import (
    DuplicateDecision,
    JobLike,
    classify_duplicate,
    ordered_duplicate_pair_ids,
)
from jobscraper.services.normalization import normalize_company


class ScraperFactory(Protocol):
    """The registry behavior used by synchronization and its offline fakes."""

    def create(self, source: str) -> BaseScraper:
        """Return a fresh scraper for ``source``."""


class ActiveSyncRunError(RuntimeError):
    """Raised when a saved search already has a pending or running attempt."""


@dataclass(slots=True)
class _SourceProgress:
    """Keep durable counters available when iterator consumption raises."""

    offers_seen: int = 0
    offers_persisted: int = 0
    exhausted: bool = False


class SyncService:
    """Run each source independently while retaining already committed offers.

    The existing scraper contract has no explicit pagination metadata. A scan is
    therefore considered complete only when its iterator ends normally *before*
    ``SearchCriteria.max_results``. Reaching that cap is conservatively treated
    as truncated. Exceptions, close failures, and truncated scans never
    inactivate unseen listings.

    Repository methods deliberately flush without committing. This service owns
    commits at lifecycle boundaries and after every accepted offer so progress is
    observable from a separate database session during a long-running sync.
    """

    def __init__(
        self,
        session: Session,
        *,
        registry: ScraperFactory | None = None,
        jobs: JobRepository | None = None,
        sync_runs: SyncRunRepository | None = None,
        classifier: Callable[
            [JobLike, JobLike], DuplicateDecision
        ] = classify_duplicate,
    ) -> None:
        self.session = session
        self.registry = registry or ScraperRegistry()
        self.jobs = jobs if jobs is not None else JobRepository(session)
        self.sync_runs = (
            sync_runs if sync_runs is not None else SyncRunRepository(session)
        )
        self.classifier = classifier

    def create_run(
        self,
        saved_search_id: str,
        only_sources: set[str] | None = None,
        *,
        reject_active: bool = False,
    ) -> str:
        """Persist and commit a pending run with a stable requested-source order."""

        saved_search = self.session.scalar(
            select(SavedSearch).where(SavedSearch.id == saved_search_id)
        )
        if saved_search is None:
            raise LookupError("Saved search does not exist")

        configured_sources = list(dict.fromkeys(saved_search.sources))
        if only_sources is None:
            requested_sources = configured_sources
        else:
            unavailable = only_sources.difference(configured_sources)
            if unavailable:
                raise ValueError(
                    "Les sources demandées ne font pas partie de la recherche."
                )
            requested_sources = [
                source for source in configured_sources if source in only_sources
            ]
        if not requested_sources:
            raise ValueError(
                "Aucune source n’est sélectionnée pour la synchronisation."
            )

        try:
            if reject_active:
                run = self.sync_runs.start_if_no_active(
                    saved_search_id, requested_sources=requested_sources
                )
                if run is None:
                    raise ActiveSyncRunError()
            else:
                run = self.sync_runs.start(
                    saved_search_id, requested_sources=requested_sources
                )
            run_id = run.id
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return run_id

    def execute(self, run_id: str) -> None:
        """Execute one pending run and isolate every source failure boundary."""

        run = self.sync_runs.get(run_id)
        if run is None:
            raise LookupError("Synchronization run does not exist")
        claimed = self.sync_runs.claim_pending(run_id)
        if claimed is None:
            self.session.rollback()
            raise ValueError("Synchronization run is not pending")
        saved_search = self.session.get(SavedSearch, claimed.saved_search_id)
        if saved_search is None:
            raise LookupError("Saved search does not exist")
        requested_sources = list(claimed.requested_sources)
        saved_search_pk = saved_search.pk
        saved_search_id = saved_search.id
        criteria = self._criteria(saved_search)

        self.session.commit()

        source_statuses = [
            self._execute_source(
                run_id=run_id,
                saved_search_id=saved_search_id,
                saved_search_pk=saved_search_pk,
                source=source,
                criteria=criteria,
            )
            for source in requested_sources
        ]
        final_status = self._run_status(source_statuses)
        self.sync_runs.finish(run_id, status=final_status)
        self.session.commit()

    def run(self, saved_search_id: str, only_sources: set[str] | None = None) -> str:
        """Create and synchronously execute a run for CLI-style callers."""

        run_id = self.create_run(saved_search_id, only_sources=only_sources)
        self.execute(run_id)
        return run_id

    def _execute_source(
        self,
        *,
        run_id: str,
        saved_search_id: str,
        saved_search_pk: int,
        source: str,
        criteria: SearchCriteria,
    ) -> str:
        source_started = utc_now()
        progress = _SourceProgress()
        source_error: Exception | None = None
        scraper: BaseScraper | None = None

        self.sync_runs.record_source_result(
            run_id, source, status="running", started_at=source_started
        )
        self.session.commit()

        try:
            scraper = self.registry.create(source)
            iterator = iter(scraper.search(criteria))
            self._consume_offers(
                iterator=iterator,
                run_id=run_id,
                saved_search_id=saved_search_id,
                source=source,
                criteria=criteria,
                progress=progress,
            )
            if scraper.strict_search and not scraper.search_complete:
                scraper._incomplete_search(
                    "La source n’a pas confirmé une recherche complète"
                )
        except Exception as exc:
            source_error = exc
            self.session.rollback()
            logger.exception(
                "Échec de la source {} pendant la synchronisation {}",
                source,
                run_id,
            )
        finally:
            if scraper is not None:
                try:
                    scraper.close()
                except Exception as exc:
                    self.session.rollback()
                    logger.exception(
                        "Échec de fermeture de la source {} pour la synchronisation {}",
                        source,
                        run_id,
                    )
                    if source_error is None:
                        source_error = exc

        if source_error is not None:
            status = "partial" if progress.offers_persisted else "failed"
            self._record_source_finished(
                run_id=run_id,
                source=source,
                status=status,
                offers_seen=progress.offers_seen,
                offers_persisted=progress.offers_persisted,
                error_message=self._sanitized_error(source_error),
            )
            return status

        if not progress.exhausted:
            self._record_source_finished(
                run_id=run_id,
                source=source,
                status="partial",
                offers_seen=progress.offers_seen,
                offers_persisted=progress.offers_persisted,
                error_message=(
                    "La limite de résultats a été atteinte; "
                    "la vérification de la source est incomplète."
                ),
            )
            return "partial"

        try:
            self._mark_unseen_inactive(
                saved_search_pk=saved_search_pk,
                source=source,
                scan_started_at=source_started,
            )
            self._record_source_finished(
                run_id=run_id,
                source=source,
                status="succeeded",
                offers_seen=progress.offers_seen,
                offers_persisted=progress.offers_persisted,
                error_message=None,
            )
        except Exception as exc:
            self.session.rollback()
            logger.exception(
                "Échec de finalisation de la source {} pour la synchronisation {}",
                source,
                run_id,
            )
            status = "partial" if progress.offers_persisted else "failed"
            self._record_source_finished(
                run_id=run_id,
                source=source,
                status=status,
                offers_seen=progress.offers_seen,
                offers_persisted=progress.offers_persisted,
                error_message=self._sanitized_error(exc),
            )
            return status
        return "succeeded"

    def _consume_offers(
        self,
        *,
        iterator: Iterator[JobOffer],
        run_id: str,
        saved_search_id: str,
        source: str,
        criteria: SearchCriteria,
        progress: _SourceProgress,
    ) -> None:
        while progress.offers_seen < criteria.max_results:
            try:
                offer = next(iterator)
            except StopIteration:
                progress.exhausted = True
                return
            progress.offers_seen += 1
            if offer.source != source:
                raise ValueError("A scraper returned an offer for another source")
            try:
                observed_at = utc_now()
                next_persisted = progress.offers_persisted + 1
                # Issue a real outer UPDATE before repository SAVEPOINTs. This
                # keeps SQLite's legacy transaction mode from publishing the
                # listing before its matching progress counters.
                self.sync_runs.record_source_result(
                    run_id,
                    source,
                    status="running",
                    offers_seen=progress.offers_seen,
                    offers_persisted=next_persisted,
                )
                self._persist_offer(
                    offer=offer,
                    saved_search_id=saved_search_id,
                    seen_at=observed_at,
                )
                self.session.commit()
            except Exception:
                self.session.rollback()
                raise
            progress.offers_persisted = next_persisted

    def _persist_offer(
        self, *, offer: JobOffer, saved_search_id: str, seen_at: datetime
    ) -> None:
        job = self.jobs.upsert_listing(offer, seen_at=seen_at)
        self.jobs.attach_search(saved_search_id, job.id)
        self._refresh_duplicate_relations(job, source=offer.source)

    def _refresh_duplicate_relations(self, job: CanonicalJob, *, source: str) -> None:
        normalized_company = normalize_company(job.company)
        job.normalized_company = normalized_company
        jobs_already_on_source = select(SourceListing.canonical_job_id).where(
            SourceListing.source == source
        )
        candidates = list(
            self.session.scalars(
                select(CanonicalJob)
                .where(
                    CanonicalJob.normalized_company == normalized_company,
                    CanonicalJob.pk != job.pk,
                    CanonicalJob.pk.not_in(jobs_already_on_source),
                )
                .order_by(CanonicalJob.pk.asc())
            )
        )
        candidate_pks = {candidate.pk for candidate in candidates}
        for relation in self.session.scalars(
            select(DuplicateRelation).where(
                DuplicateRelation.kind == "possible",
                or_(
                    DuplicateRelation.left_job_id == job.pk,
                    DuplicateRelation.right_job_id == job.pk,
                ),
            )
        ):
            other_pk = (
                relation.right_job_id
                if relation.left_job_id == job.pk
                else relation.left_job_id
            )
            if other_pk not in candidate_pks:
                self.session.delete(relation)

        current = job
        for candidate in candidates:
            if candidate.pk == current.pk:
                continue
            if not self._job_sources(current.pk).isdisjoint(
                self._job_sources(candidate.pk)
            ):
                self._remove_possible_relation(candidate.pk, current.pk)
                continue
            decision = self.classifier(candidate, current)
            if decision.kind == "confirmed":
                current = self.jobs.merge_canonical_jobs(candidate.id, current.id)
                self._remove_source_overlapping_possible_relations(current.pk)
            elif decision.kind == "possible":
                self._record_possible_relation(candidate, current, decision)
            else:
                self._remove_possible_relation(candidate.pk, current.pk)

    def _job_sources(self, job_pk: int) -> set[str]:
        return set(
            self.session.scalars(
                select(SourceListing.source).where(
                    SourceListing.canonical_job_id == job_pk
                )
            )
        )

    def _remove_possible_relation(self, left_job_pk: int, right_job_pk: int) -> None:
        left_pk, right_pk = ordered_duplicate_pair_ids(left_job_pk, right_job_pk)
        relation = self.session.scalar(
            select(DuplicateRelation).where(
                DuplicateRelation.left_job_id == left_pk,
                DuplicateRelation.right_job_id == right_pk,
                DuplicateRelation.kind == "possible",
            )
        )
        if relation is not None:
            self.session.delete(relation)

    def _remove_source_overlapping_possible_relations(self, job_pk: int) -> None:
        sources = self._job_sources(job_pk)
        relations = list(
            self.session.scalars(
                select(DuplicateRelation).where(
                    DuplicateRelation.kind == "possible",
                    or_(
                        DuplicateRelation.left_job_id == job_pk,
                        DuplicateRelation.right_job_id == job_pk,
                    ),
                )
            )
        )
        for relation in relations:
            other_pk = (
                relation.right_job_id
                if relation.left_job_id == job_pk
                else relation.left_job_id
            )
            if not sources.isdisjoint(self._job_sources(other_pk)):
                self.session.delete(relation)

    def _record_possible_relation(
        self,
        left_job: CanonicalJob,
        right_job: CanonicalJob,
        decision: DuplicateDecision,
    ) -> None:
        left_pk, right_pk = ordered_duplicate_pair_ids(left_job.pk, right_job.pk)
        relation = self.session.scalar(
            select(DuplicateRelation).where(
                DuplicateRelation.left_job_id == left_pk,
                DuplicateRelation.right_job_id == right_pk,
            )
        )
        if relation is None:
            relation = DuplicateRelation(
                left_job_id=left_pk,
                right_job_id=right_pk,
                kind="possible",
                score=decision.score,
                reasons=list(decision.reasons),
            )
            self.session.add(relation)
        else:
            relation.kind = "possible"
            relation.score = decision.score
            relation.reasons = list(decision.reasons)
        self.session.flush()

    def _mark_unseen_inactive(
        self,
        *,
        saved_search_pk: int,
        source: str,
        scan_started_at: datetime,
    ) -> None:
        active_source_search_pks = {
            saved_search.pk
            for saved_search in self.session.scalars(
                select(SavedSearch).where(SavedSearch.active.is_(True))
            )
            if source in saved_search.sources
        }
        attached_job_ids = select(SearchListing.canonical_job_id).where(
            SearchListing.saved_search_id == saved_search_pk
        )
        stale_listings = list(
            self.session.scalars(
                select(SourceListing).where(
                    SourceListing.source == source,
                    SourceListing.active.is_(True),
                    SourceListing.last_seen_at < scan_started_at,
                    SourceListing.canonical_job_id.in_(attached_job_ids),
                )
            )
        )
        for listing in stale_listings:
            attached_search_pks = set(
                self.session.scalars(
                    select(SearchListing.saved_search_id).where(
                        SearchListing.canonical_job_id == listing.canonical_job_id
                    )
                )
            )
            other_relevant_searches = (
                attached_search_pks & active_source_search_pks
            ) - {saved_search_pk}
            if all(
                self._has_verified_absence_after(
                    saved_search_pk=other_search_pk,
                    source=source,
                    last_seen_at=listing.last_seen_at,
                )
                for other_search_pk in other_relevant_searches
            ):
                self.session.execute(
                    update(SourceListing)
                    .where(
                        SourceListing.pk == listing.pk,
                        SourceListing.active.is_(True),
                        SourceListing.last_seen_at == listing.last_seen_at,
                        SourceListing.last_seen_at < scan_started_at,
                    )
                    .values(active=False)
                )

    def _has_verified_absence_after(
        self,
        *,
        saved_search_pk: int,
        source: str,
        last_seen_at: datetime,
    ) -> bool:
        verification = self.session.scalar(
            select(SourceSyncResult.pk)
            .join(SyncRun, SourceSyncResult.sync_run_id == SyncRun.pk)
            .where(
                SyncRun.saved_search_id == saved_search_pk,
                SourceSyncResult.source == source,
                SourceSyncResult.status == "succeeded",
                SourceSyncResult.started_at > last_seen_at,
                SourceSyncResult.finished_at.is_not(None),
            )
            .limit(1)
        )
        return verification is not None

    def _record_source_finished(
        self,
        *,
        run_id: str,
        source: str,
        status: str,
        offers_seen: int,
        offers_persisted: int,
        error_message: str | None,
    ) -> None:
        self.sync_runs.record_source_result(
            run_id,
            source,
            status=status,
            offers_seen=offers_seen,
            offers_persisted=offers_persisted,
            error_message=error_message,
            finished_at=utc_now(),
        )
        self.session.commit()

    @staticmethod
    def _criteria(saved_search: SavedSearch) -> SearchCriteria:
        return SearchCriteria(
            keywords=list(saved_search.keywords),
            title=saved_search.title,
            location=saved_search.location,
            radius_km=saved_search.radius_km,
            contract_types=list(saved_search.contract_types),
            experience_levels=list(saved_search.experience_levels),
            workplace_types=list(saved_search.workplace_types),
            companies=list(saved_search.companies),
            exclude_companies=list(saved_search.exclude_companies),
            salary_min=saved_search.salary_min,
        )

    @staticmethod
    def _sanitized_error(exc: Exception) -> str:
        if isinstance(exc, requests.Timeout):
            return "La source n’a pas répondu dans le délai imparti."
        if isinstance(exc, requests.ConnectionError):
            return "La source est temporairement inaccessible."
        if isinstance(exc, requests.RequestException):
            return "La source a rencontré une erreur réseau."
        return "La synchronisation de la source a échoué."

    @staticmethod
    def _run_status(source_statuses: list[str]) -> str:
        if source_statuses and all(status == "succeeded" for status in source_statuses):
            return "succeeded"
        if any(status in {"succeeded", "partial"} for status in source_statuses):
            return "partial"
        return "failed"
