"""Repository operations for canonical jobs and source listings."""

from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import select
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
        else:
            job = self.session.get(CanonicalJob, listing.canonical_job_id)
            if job is None:
                raise LookupError("Source listing points to a missing canonical job")
            self._apply_offer(job, job_offer)
            listing.url = str(job_offer.url)
            listing.title = job_offer.title
            listing.company = job_offer.company
            listing.location = job_offer.location
            listing.posted_at = job_offer.posted_at
            listing.active = True
            listing.last_seen_at = observed_at

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

        association = self.session.scalar(
            select(SearchListing).where(
                SearchListing.saved_search_id == saved_search.pk,
                SearchListing.canonical_job_id == job.pk,
            )
        )
        if association is None:
            association = SearchListing(
                saved_search_id=saved_search.pk, canonical_job_id=job.pk
            )
            self.session.add(association)
            self.session.flush()
        return association

    def get_job(self, job_id: str) -> CanonicalJob | None:
        """Return a canonical job by public UUID."""

        return self.session.scalar(
            select(CanonicalJob).where(CanonicalJob.id == job_id)
        )

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
        sort: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[CanonicalJob]:
        """Return canonical jobs matching all supplied aggregation filters."""

        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if duplicate_state not in {None, "duplicate", "unique"}:
            raise ValueError("duplicate_state must be 'duplicate' or 'unique'")

        jobs = list(self.session.scalars(select(CanonicalJob)))
        sources_by_job = self._sources_by_job()
        attached_job_pks = self._attached_job_pks(saved_search_id)
        duplicate_job_pks = self._duplicate_job_pks()
        query_key = _normalise(query) if query else None

        def matches(job: CanonicalJob) -> bool:
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
            if locations and _normalise(job.location) not in {
                _normalise(location) for location in locations
            }:
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
            if duplicate_state == "duplicate" and job.pk not in duplicate_job_pks:
                return False
            if duplicate_state == "unique" and job.pk in duplicate_job_pks:
                return False
            return True

        matching = [job for job in jobs if matches(job)]
        self._sort(matching, sort)
        end = None if limit is None else offset + limit
        return matching[offset:end]

    def _canonical_job_from_offer(self, job_offer: JobOffer) -> CanonicalJob:
        job = CanonicalJob(
            title=job_offer.title,
            normalized_title=_normalise(job_offer.title),
            company=job_offer.company,
            normalized_company=_normalise(job_offer.company),
            location=job_offer.location,
            normalized_location=_normalise(job_offer.location),
        )
        self._apply_offer(job, job_offer)
        return job

    def _apply_offer(self, job: CanonicalJob, job_offer: JobOffer) -> None:
        job.title = job_offer.title
        job.normalized_title = _normalise(job_offer.title)
        job.company = job_offer.company
        job.normalized_company = _normalise(job_offer.company)
        job.location = job_offer.location
        job.normalized_location = _normalise(job_offer.location)
        job.description = job_offer.description
        job.salary_min = job_offer.salary_min
        job.salary_max = job_offer.salary_max
        job.salary_currency = job_offer.salary_currency
        job.contract_type = _value(job_offer.contract_type)
        job.experience_level = _value(job_offer.experience_level)
        job.remote = job_offer.remote
        job.posted_at = job_offer.posted_at
        job.skills = list(job_offer.skills)
        job.benefits = list(job_offer.benefits)

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

    def _duplicate_job_pks(self) -> set[int]:
        relation_rows = self.session.execute(
            select(DuplicateRelation.left_job_id, DuplicateRelation.right_job_id)
        )
        return {job_pk for relation in relation_rows for job_pk in relation}

    @staticmethod
    def _sort(jobs: list[CanonicalJob], sort: str | None) -> None:
        sort_key = sort or "posted_at_desc"
        if sort_key in {"posted_at_desc", "date_desc", "newest"}:
            jobs.sort(
                key=lambda job: (job.posted_at is not None, job.posted_at, job.pk),
                reverse=True,
            )
        elif sort_key in {"posted_at_asc", "date_asc", "oldest"}:
            jobs.sort(
                key=lambda job: (
                    job.posted_at is None,
                    job.posted_at or datetime.max.replace(tzinfo=None),
                    job.pk,
                )
            )
        elif sort_key in {"title_asc", "title"}:
            jobs.sort(key=lambda job: (_normalise(job.title), job.pk))
        else:
            raise ValueError("Unsupported job sort")
