"""Repository operations for canonical jobs and source listings."""

from collections.abc import Iterable, Sequence
from datetime import datetime, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from jobscraper.db.base import utc_now
from jobscraper.db.models import (
    CanonicalJob,
    DuplicateRelation,
    SavedSearch,
    SearchListing,
    SourceListing,
)
from jobscraper.models.job import JobOffer
from jobscraper.services.location_matching import location_matches
from jobscraper.services.normalization import normalize_company


def _normalise(value: str) -> str:
    """Provide a stable local comparison key until the normalization service exists."""

    return " ".join(value.split()).casefold()


def _value(value: object | None) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _contains(values: Sequence[str], requested: Iterable[str]) -> bool:
    expected = {_normalise(value) for value in requested}
    return bool(expected) and expected.issubset({_normalise(value) for value in values})


def _contains_any(values: Sequence[str], requested: Iterable[str]) -> bool:
    expected = {_normalise(value) for value in requested}
    return bool(expected.intersection(_normalise(value) for value in values))


class JobRepository:
    """Persist source sightings while exposing canonical jobs through public UUIDs."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_listing(
        self, job_offer: JobOffer, *, seen_at: datetime | None = None
    ) -> CanonicalJob:
        """Create or refresh the canonical job for a source/external-ID pair."""

        observed_at = seen_at or utc_now()
        listing = self.session.scalar(
            select(SourceListing).where(
                SourceListing.source == job_offer.source,
                SourceListing.external_id == job_offer.id,
            )
        )
        if listing is None:
            try:
                with self.session.begin_nested():
                    job = self._canonical_job_from_offer(job_offer)
                    self.session.add(job)
                    self.session.flush()
                    listing = SourceListing(
                        canonical_job_id=job.pk,
                        source=job_offer.source,
                        external_id=job_offer.id,
                        url=str(job_offer.url),
                        title=job_offer.title,
                        company=job_offer.company,
                        location=job_offer.location,
                        posted_at=job_offer.posted_at,
                        first_seen_at=observed_at,
                        last_seen_at=observed_at,
                    )
                    self.session.add(listing)
                    self.session.flush()
            except IntegrityError:
                listing = self._source_listing(job_offer.source, job_offer.id)
                if listing is None:
                    raise
                job = self._canonical_by_pk(listing.canonical_job_id)
                self._refresh_listing(job, listing, job_offer, observed_at)
        else:
            job = self._canonical_by_pk(listing.canonical_job_id)
            self._refresh_listing(job, listing, job_offer, observed_at)

        self.session.flush()
        return job

    def attach_search(self, saved_search_id: str, job_id: str) -> SearchListing:
        """Idempotently associate one saved search and canonical job by public UUID."""

        saved_search = self.session.scalar(
            select(SavedSearch).where(SavedSearch.id == saved_search_id)
        )
        job = self.get_job(job_id)
        if saved_search is None or job is None:
            raise LookupError("Saved search or job does not exist")

        association = self._search_listing(saved_search.pk, job.pk)
        if association is None:
            try:
                with self.session.begin_nested():
                    association = SearchListing(
                        saved_search_id=saved_search.pk, canonical_job_id=job.pk
                    )
                    self.session.add(association)
                    self.session.flush()
            except IntegrityError:
                association = self._search_listing(saved_search.pk, job.pk)
                if association is None:
                    raise
        return association

    def merge_canonical_jobs(self, keep_job_id: str, merge_job_id: str) -> CanonicalJob:
        """Merge a confirmed duplicate into ``keep_job_id`` without losing links.

        Task 4 should call this after a confirmed duplicate decision, passing the
        canonical UUID to keep first and the newly upserted duplicate second.
        The surviving job owns both source listings and the union of saved-search
        links; non-conflicting duplicate relations are reassigned in canonical
        pair order.  The caller retains control of the outer transaction.
        """

        keep = self.get_job(keep_job_id)
        merge = self.get_job(merge_job_id)
        if keep is None or merge is None:
            raise LookupError("Canonical job does not exist")
        if keep.pk == merge.pk:
            return keep

        self._preserve_detail_cache(keep, merge)
        self._merge_search_listings(keep.pk, merge.pk)
        self.session.execute(
            update(SourceListing)
            .where(SourceListing.canonical_job_id == merge.pk)
            .values(canonical_job_id=keep.pk)
        )
        self._merge_duplicate_relations(keep.pk, merge.pk)
        self.session.delete(merge)
        self.session.flush()
        return keep

    def stamp_detail_groups(
        self,
        job_id: str,
        *,
        groups: Sequence[str],
        fetched_at: datetime,
    ) -> CanonicalJob:
        """Stamp detail-group provenance after Task 5 refreshes canonical fields.

        The detail service updates the canonical detail fields, then calls this
        method with each refreshed group from ``description``, ``salary``,
        ``skills``, and ``benefits``. Sparse listing refreshes intentionally do
        not call it, so their partial values cannot make cached provenance newer.
        """

        job = self.get_job(job_id)
        if job is None:
            raise LookupError("Canonical job does not exist")
        provenance = self._detail_provenance(job)
        for group in groups:
            if group not in self._DETAIL_GROUPS:
                raise ValueError("Unknown detail provenance group")
            if self._has_detail_group(job, group):
                if not provenance:
                    provenance = self._materialize_legacy_provenance(job)
                provenance[group] = self._serialize_timestamp(fetched_at)
        job.detail_provenance = provenance
        self._recompute_details_fetched_at(job)
        self.session.flush()
        return job

    def get_job(self, job_id: str) -> CanonicalJob | None:
        """Return a canonical job by public UUID."""

        return self.session.scalar(
            select(CanonicalJob).where(CanonicalJob.id == job_id)
        )

    def mark_viewed(
        self, job_id: str, viewed_at: datetime | None = None
    ) -> CanonicalJob:
        """Persist the first observed card click for a canonical job."""

        job = self.get_job(job_id)
        if job is None:
            raise LookupError("Canonical job does not exist")
        observed_at = viewed_at or utc_now()
        self.session.execute(
            update(CanonicalJob)
            .where(CanonicalJob.pk == job.pk, CanonicalJob.viewed_at.is_(None))
            .values(viewed_at=observed_at)
        )
        self.session.flush()
        self.session.refresh(job, attribute_names=["viewed_at"])
        return job

    def get_listing(self, job_id: str) -> SourceListing | None:
        """Return a source listing for a canonical-job UUID or its own public UUID."""

        job = self.get_job(job_id)
        if job is not None:
            return self.session.scalar(
                select(SourceListing)
                .where(SourceListing.canonical_job_id == job.pk)
                .order_by(SourceListing.pk.asc())
            )
        return self.session.scalar(
            select(SourceListing).where(SourceListing.id == job_id)
        )

    def list_jobs(
        self,
        *,
        saved_search_id: str | None = None,
        posted_since: datetime | None = None,
        query: str | None = None,
        locations: Sequence[str] | None = None,
        contracts: Sequence[str] | None = None,
        remote: bool | None = None,
        experience: Sequence[str] | None = None,
        salary_min: float | None = None,
        companies: Sequence[str] | None = None,
        sources: Sequence[str] | None = None,
        skills: Sequence[str] | None = None,
        duplicate_state: str | None = None,
        unseen_only: bool = False,
        sort: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[CanonicalJob]:
        """Return canonical jobs matching all supplied aggregation filters."""

        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if duplicate_state not in {
            None,
            "confirmed",
            "possible",
            "none",
            "duplicate",
            "unique",
        }:
            raise ValueError(
                "duplicate_state must be 'confirmed', 'possible', or 'none'"
            )

        jobs = list(self.session.scalars(select(CanonicalJob)))
        sources_by_job = self._sources_by_job()
        attached_job_pks = self._attached_job_pks(saved_search_id)
        confirmed_job_pks = self._confirmed_job_pks()
        possible_job_pks = self._possible_job_pks() - confirmed_job_pks
        query_key = _normalise(query) if query else None

        def matches(job: CanonicalJob) -> bool:
            if unseen_only and job.viewed_at is not None:
                return False
            if attached_job_pks is not None and job.pk not in attached_job_pks:
                return False
            if posted_since is not None and (
                job.posted_at is None or job.posted_at < posted_since
            ):
                return False
            if query_key is not None and query_key not in _normalise(
                " ".join(filter(None, (job.title, job.company, job.description)))
            ):
                return False
            if locations and not any(
                location_matches(job.location, requested) for requested in locations
            ):
                return False
            if contracts and _value(job.contract_type) not in {
                _value(value) for value in contracts
            }:
                return False
            if remote is not None and job.remote is not remote:
                return False
            if experience and _value(job.experience_level) not in {
                _value(value) for value in experience
            }:
                return False
            if salary_min is not None and (
                job.salary_max is None or job.salary_max < salary_min
            ):
                return False
            if companies and _normalise(job.company) not in {
                _normalise(company) for company in companies
            }:
                return False
            if sources and not _contains_any(sources_by_job.get(job.pk, []), sources):
                return False
            if skills and not _contains(job.skills, skills):
                return False
            if duplicate_state == "confirmed" and job.pk not in confirmed_job_pks:
                return False
            if duplicate_state == "possible" and job.pk not in possible_job_pks:
                return False
            if duplicate_state in {"none", "unique"} and job.pk in (
                confirmed_job_pks | possible_job_pks
            ):
                return False
            if duplicate_state == "duplicate" and job.pk not in (
                confirmed_job_pks | possible_job_pks
            ):
                return False
            return True

        matching = [job for job in jobs if matches(job)]
        self._sort(matching, sort, query_key)
        end = None if limit is None else offset + limit
        return matching[offset:end]

    def _canonical_job_from_offer(self, job_offer: JobOffer) -> CanonicalJob:
        job = CanonicalJob(
            title=job_offer.title,
            normalized_title=_normalise(job_offer.title),
            company=job_offer.company,
            normalized_company=normalize_company(job_offer.company),
            location=job_offer.location,
            normalized_location=_normalise(job_offer.location),
        )
        self._apply_offer(job, job_offer, preserve_cached_details=False)
        return job

    def _refresh_listing(
        self,
        job: CanonicalJob,
        listing: SourceListing,
        job_offer: JobOffer,
        observed_at: datetime,
    ) -> None:
        self._apply_offer(job, job_offer, preserve_cached_details=True)
        listing.url = str(job_offer.url)
        listing.title = job_offer.title
        listing.company = job_offer.company
        listing.location = job_offer.location
        listing.posted_at = job_offer.posted_at
        self.session.execute(
            update(SourceListing)
            .where(
                SourceListing.pk == listing.pk,
                SourceListing.last_seen_at <= observed_at,
            )
            .values(active=True, last_seen_at=observed_at)
        )

    def _apply_offer(
        self, job: CanonicalJob, job_offer: JobOffer, *, preserve_cached_details: bool
    ) -> None:
        job.title = job_offer.title
        job.normalized_title = _normalise(job_offer.title)
        job.company = job_offer.company
        job.normalized_company = normalize_company(job_offer.company)
        job.location = job_offer.location
        job.normalized_location = _normalise(job_offer.location)
        if self._meaningful_text(job_offer.description) or not preserve_cached_details:
            job.description = job_offer.description
        if job_offer.salary_min is not None or not preserve_cached_details:
            job.salary_min = job_offer.salary_min
        if job_offer.salary_max is not None or not preserve_cached_details:
            job.salary_max = job_offer.salary_max
        if (
            job_offer.salary_min is not None
            or job_offer.salary_max is not None
            or not preserve_cached_details
        ):
            job.salary_currency = job_offer.salary_currency
        job.contract_type = _value(job_offer.contract_type)
        job.experience_level = _value(job_offer.experience_level)
        job.remote = job_offer.remote
        job.posted_at = job_offer.posted_at
        if job_offer.skills or not preserve_cached_details:
            job.skills = list(job_offer.skills)
        if job_offer.benefits or not preserve_cached_details:
            job.benefits = list(job_offer.benefits)

    @staticmethod
    def _meaningful_text(value: str | None) -> bool:
        return value is not None and bool(value.strip())

    def _source_listing(self, source: str, external_id: str) -> SourceListing | None:
        return self.session.scalar(
            select(SourceListing).where(
                SourceListing.source == source,
                SourceListing.external_id == external_id,
            )
        )

    def _canonical_by_pk(self, job_pk: int) -> CanonicalJob:
        job = self.session.get(CanonicalJob, job_pk)
        if job is None:
            raise LookupError("Source listing points to a missing canonical job")
        return job

    def _search_listing(
        self, saved_search_pk: int, canonical_job_pk: int
    ) -> SearchListing | None:
        return self.session.scalar(
            select(SearchListing).where(
                SearchListing.saved_search_id == saved_search_pk,
                SearchListing.canonical_job_id == canonical_job_pk,
            )
        )

    def _preserve_detail_cache(self, keep: CanonicalJob, merge: CanonicalJob) -> None:
        provenance = self._materialize_legacy_provenance(keep)
        keep_description_at = self._group_timestamp(keep, "description")
        merge_description_at = self._group_timestamp(merge, "description")
        if self._meaningful_text(merge.description) and (
            not self._meaningful_text(keep.description)
            or self._is_newer_timestamp(merge_description_at, keep_description_at)
        ):
            keep.description = merge.description
            keep_description_at = merge_description_at
        self._set_group_timestamp(provenance, "description", keep_description_at)

        keep_salary_at = self._group_timestamp(keep, "salary")
        merge_salary_at = self._group_timestamp(merge, "salary")
        if self._has_salary_snapshot(merge) and (
            not self._has_salary_snapshot(keep)
            or self._is_newer_timestamp(merge_salary_at, keep_salary_at)
        ):
            keep.salary_min = merge.salary_min
            keep.salary_max = merge.salary_max
            keep.salary_currency = merge.salary_currency
            keep_salary_at = merge_salary_at
        self._set_group_timestamp(provenance, "salary", keep_salary_at)

        keep_skills_at = self._group_timestamp(keep, "skills")
        merge_skills_at = self._group_timestamp(merge, "skills")
        keep.skills = self._stable_union(keep.skills, merge.skills)
        self._set_group_timestamp(
            provenance,
            "skills",
            self._newest_timestamp(keep_skills_at, merge_skills_at),
        )

        keep_benefits_at = self._group_timestamp(keep, "benefits")
        merge_benefits_at = self._group_timestamp(merge, "benefits")
        keep.benefits = self._stable_union(keep.benefits, merge.benefits)
        self._set_group_timestamp(
            provenance,
            "benefits",
            self._newest_timestamp(keep_benefits_at, merge_benefits_at),
        )
        keep.detail_provenance = provenance
        self._recompute_details_fetched_at(
            keep, extra_timestamps=(merge.details_fetched_at,)
        )

    @staticmethod
    def _has_salary_snapshot(job: CanonicalJob) -> bool:
        return bool(job.salary_currency) and (
            job.salary_min is not None or job.salary_max is not None
        )

    _DETAIL_GROUPS = ("description", "salary", "skills", "benefits")

    @staticmethod
    def _is_newer_timestamp(
        candidate: datetime | None, current: datetime | None
    ) -> bool:
        if candidate is None:
            return False
        if current is None:
            return True
        return candidate > current

    @staticmethod
    def _newest_timestamp(
        left: datetime | None, right: datetime | None
    ) -> datetime | None:
        return max(
            (timestamp for timestamp in (left, right) if timestamp is not None),
            default=None,
        )

    @classmethod
    def _has_detail_group(cls, job: CanonicalJob, group: str) -> bool:
        if group == "description":
            return cls._meaningful_text(job.description)
        if group == "salary":
            return cls._has_salary_snapshot(job)
        if group == "skills":
            return bool(job.skills)
        if group == "benefits":
            return bool(job.benefits)
        raise ValueError("Unknown detail provenance group")

    @staticmethod
    def _detail_provenance(job: CanonicalJob) -> dict[str, str]:
        return dict(job.detail_provenance or {})

    @classmethod
    def _materialize_legacy_provenance(cls, job: CanonicalJob) -> dict[str, str]:
        provenance = cls._detail_provenance(job)
        legacy_timestamp = job.details_fetched_at
        if provenance or legacy_timestamp is None:
            return provenance
        serialized = cls._serialize_timestamp(legacy_timestamp)
        return {
            group: serialized
            for group in cls._DETAIL_GROUPS
            if cls._has_detail_group(job, group)
        }

    @classmethod
    def _group_timestamp(cls, job: CanonicalJob, group: str) -> datetime | None:
        if not cls._has_detail_group(job, group):
            return None
        provenance = cls._detail_provenance(job)
        stored = provenance.get(group)
        parsed = cls._deserialize_timestamp(stored)
        if parsed is not None:
            return parsed
        if provenance:
            return None
        return job.details_fetched_at

    @staticmethod
    def _serialize_timestamp(timestamp: datetime) -> str:
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _deserialize_timestamp(value: object | None) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            timestamp = datetime.fromisoformat(value)
        except ValueError:
            return None
        if timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc)

    @classmethod
    def _set_group_timestamp(
        cls, provenance: dict[str, str], group: str, timestamp: datetime | None
    ) -> None:
        if timestamp is None:
            provenance.pop(group, None)
        else:
            provenance[group] = cls._serialize_timestamp(timestamp)

    @classmethod
    def _recompute_details_fetched_at(
        cls,
        job: CanonicalJob,
        *,
        extra_timestamps: Sequence[datetime | None] = (),
    ) -> None:
        timestamps = [job.details_fetched_at, *extra_timestamps]
        timestamps.extend(
            cls._group_timestamp(job, group) for group in cls._DETAIL_GROUPS
        )
        meaningful_timestamps = [
            timestamp for timestamp in timestamps if timestamp is not None
        ]
        if meaningful_timestamps:
            job.details_fetched_at = max(meaningful_timestamps)

    @staticmethod
    def _stable_union(existing: Sequence[str], incoming: Sequence[str]) -> list[str]:
        seen: set[str] = set()
        combined: list[str] = []
        for value in (*existing, *incoming):
            key = _normalise(value)
            if key not in seen:
                seen.add(key)
                combined.append(value)
        return combined

    def _merge_search_listings(self, keep_pk: int, merge_pk: int) -> None:
        kept_searches = set(
            self.session.scalars(
                select(SearchListing.saved_search_id).where(
                    SearchListing.canonical_job_id == keep_pk
                )
            )
        )
        for association in self.session.scalars(
            select(SearchListing).where(SearchListing.canonical_job_id == merge_pk)
        ):
            if association.saved_search_id in kept_searches:
                self.session.delete(association)
            else:
                association.canonical_job_id = keep_pk

    def _merge_duplicate_relations(self, keep_pk: int, merge_pk: int) -> None:
        relations = list(
            self.session.scalars(
                select(DuplicateRelation).where(
                    or_(
                        DuplicateRelation.left_job_id == merge_pk,
                        DuplicateRelation.right_job_id == merge_pk,
                    )
                )
            )
        )
        replacements: list[tuple[int, str, float, list[str]]] = []
        for relation in relations:
            other_pk = (
                relation.right_job_id
                if relation.left_job_id == merge_pk
                else relation.left_job_id
            )
            self.session.delete(relation)
            if other_pk != keep_pk:
                replacements.append(
                    (other_pk, relation.kind, relation.score, list(relation.reasons))
                )
        self.session.flush()
        for other_pk, kind, score, reasons in replacements:
            left_pk, right_pk = sorted((keep_pk, other_pk))
            existing = self.session.scalar(
                select(DuplicateRelation).where(
                    DuplicateRelation.left_job_id == left_pk,
                    DuplicateRelation.right_job_id == right_pk,
                )
            )
            if existing is None:
                self.session.add(
                    DuplicateRelation(
                        left_job_id=left_pk,
                        right_job_id=right_pk,
                        kind=kind,
                        score=score,
                        reasons=reasons,
                    )
                )
            elif score > existing.score:
                existing.kind = kind
                existing.score = score
                existing.reasons = reasons

    def _attached_job_pks(self, saved_search_id: str | None) -> set[int] | None:
        if saved_search_id is None:
            return None
        search_pk = self.session.scalar(
            select(SavedSearch.pk).where(SavedSearch.id == saved_search_id)
        )
        if search_pk is None:
            return set()
        return set(
            self.session.scalars(
                select(SearchListing.canonical_job_id).where(
                    SearchListing.saved_search_id == search_pk
                )
            )
        )

    def _sources_by_job(self) -> dict[int, list[str]]:
        by_job: dict[int, list[str]] = {}
        for job_pk, source in self.session.execute(
            select(SourceListing.canonical_job_id, SourceListing.source).where(
                SourceListing.active.is_(True)
            )
        ):
            by_job.setdefault(job_pk, []).append(source)
        return by_job

    def _confirmed_job_pks(self) -> set[int]:
        return set(
            self.session.scalars(
                select(SourceListing.canonical_job_id)
                .group_by(SourceListing.canonical_job_id)
                .having(func.count(SourceListing.pk) > 1)
            )
        )

    def _possible_job_pks(self) -> set[int]:
        relation_rows = self.session.execute(
            select(DuplicateRelation.left_job_id, DuplicateRelation.right_job_id).where(
                DuplicateRelation.kind == "possible"
            )
        )
        return {job_pk for relation in relation_rows for job_pk in relation}

    @staticmethod
    def _sort(
        jobs: list[CanonicalJob], sort: str | None, query_key: str | None
    ) -> None:
        sort_key = sort or "posted_at_desc"
        if sort_key in {"posted_at_desc", "date_desc", "newest", "date"}:
            JobRepository._date_sort(jobs)
        elif sort_key in {"posted_at_asc", "date_asc", "oldest"}:
            dated = sorted(
                (job for job in jobs if job.posted_at is not None),
                key=lambda job: (job.posted_at, job.pk),
            )
            undated = sorted(
                (job for job in jobs if job.posted_at is None),
                key=lambda job: job.pk,
            )
            jobs[:] = dated + undated
        elif sort_key == "relevance":
            JobRepository._date_sort(jobs)
            if query_key is not None:
                jobs.sort(
                    key=lambda job: JobRepository._relevance_score(job, query_key),
                    reverse=True,
                )
        elif sort_key in {"title_asc", "title"}:
            jobs.sort(key=lambda job: (_normalise(job.title), job.pk))
        else:
            raise ValueError("Unsupported job sort")

    @staticmethod
    def _date_sort(jobs: list[CanonicalJob]) -> None:
        dated = sorted(
            (job for job in jobs if job.posted_at is not None),
            key=lambda job: (job.posted_at, job.pk),
            reverse=True,
        )
        undated = sorted(
            (job for job in jobs if job.posted_at is None),
            key=lambda job: job.pk,
            reverse=True,
        )
        jobs[:] = dated + undated

    @staticmethod
    def _relevance_score(job: CanonicalJob, query_key: str) -> int:
        return (
            3 * _normalise(job.title).count(query_key)
            + 2 * _normalise(job.company).count(query_key)
            + _normalise(job.description or "").count(query_key)
        )
