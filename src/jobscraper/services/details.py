"""Lazy canonical-job detail refresh with a durable stale-cache fallback."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Protocol, cast

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from jobscraper.db.base import utc_now
from jobscraper.db.models import CanonicalJob, SourceListing
from jobscraper.models.job import JobOffer
from jobscraper.repositories.jobs import JobRepository
from jobscraper.scrapers.base import BaseScraper
from jobscraper.scrapers.registry import ScraperRegistry

CacheState = Literal["fresh", "refreshed", "stale"]


class JobDetailsUnavailableError(RuntimeError):
    """Raised when no cached or freshly fetched details can be returned."""


class ScraperFactory(Protocol):
    """Registry behavior needed by the synchronous detail service."""

    def create(self, source: str) -> BaseScraper:
        """Return a fresh scraper for a source listing."""


@dataclass(frozen=True, slots=True)
class JobDetailsResult:
    """A canonical job plus the freshness metadata consumed by the API."""

    job: CanonicalJob
    cache_state: CacheState
    updated_at: datetime
    warning: str | None = None


class JobDetailsService:
    """Read cached details and refresh stale entries from their best source."""

    _DETAIL_PARSER_SOURCES = frozenset(
        {"linkedin", "hellowork", "francetravail", "freework"}
    )
    _STALE_WARNING = (
        "Les détails affichés peuvent être obsolètes car leur actualisation a échoué."
    )
    _UNAVAILABLE_MESSAGE = "Les détails de cette offre sont indisponibles."

    def __init__(
        self,
        session: Session,
        *,
        registry: ScraperFactory | None = None,
        jobs: JobRepository | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.session = session
        self.registry = registry or ScraperRegistry()
        self.clock = clock
        self.jobs = jobs if jobs is not None else JobRepository(session)

    def get(
        self,
        canonical_job_id: str,
        max_age: timedelta = timedelta(days=1),
    ) -> JobDetailsResult:
        """Return fresh details, refresh stale data, or preserve a stale cache."""

        if max_age < timedelta(0):
            raise ValueError("La durée maximale doit être positive ou nulle.")

        job = self.jobs.get_job(canonical_job_id)
        if job is None:
            raise LookupError("L’offre demandée n’existe pas.")

        now = self._utc(self.clock())
        cached_at = job.details_fetched_at
        if cached_at is not None and self._utc(cached_at) >= now - max_age:
            self._normalize_job_timestamp(job)
            return JobDetailsResult(
                job=job,
                cache_state="fresh",
                updated_at=self._utc(cached_at),
            )

        listing = self._best_listing(job.pk)
        if listing is None:
            return self._stale_or_raise(
                job,
                message=(
                    "Les détails de cette offre sont indisponibles : "
                    "aucune source active."
                ),
            )

        source = listing.source
        try:
            details = self._fetch_details(listing)
            if details is None:
                raise JobDetailsUnavailableError(self._UNAVAILABLE_MESSAGE)
            groups = self._detail_groups(job, details)
            if not groups:
                raise JobDetailsUnavailableError(self._UNAVAILABLE_MESSAGE)
            refreshed = self._persist_details(job, details, fetched_at=now)
        except Exception as exc:
            self._rollback_after_failure(exc)
            fallback_job = self._reload_after_failure(canonical_job_id, exc)
            logger.opt(exception=exc).error(
                "Échec d’actualisation des détails du job {} depuis {}",
                canonical_job_id,
                source,
            )
            return self._stale_or_raise(fallback_job, cause=exc)

        if refreshed is None or refreshed.details_fetched_at is None:
            raise JobDetailsUnavailableError(self._UNAVAILABLE_MESSAGE)
        self._normalize_job_timestamp(refreshed)
        return JobDetailsResult(
            job=refreshed,
            cache_state="refreshed",
            updated_at=self._utc(refreshed.details_fetched_at),
        )

    def _best_listing(self, job_pk: int) -> SourceListing | None:
        listings = list(
            self.session.scalars(
                select(SourceListing)
                .where(
                    SourceListing.canonical_job_id == job_pk,
                    SourceListing.active.is_(True),
                )
                .order_by(
                    SourceListing.last_seen_at.desc(),
                    SourceListing.pk.desc(),
                )
            )
        )
        return next(
            (
                listing
                for listing in listings
                if listing.source in self._DETAIL_PARSER_SOURCES
            ),
            listings[0] if listings else None,
        )

    def _fetch_details(self, listing: SourceListing) -> JobOffer | None:
        scraper = self.registry.create(listing.source)
        try:
            identifier = self._detail_identifier(listing)
            details = scraper.get_job_details(identifier)
        except Exception:
            try:
                scraper.close()
            except Exception as close_error:
                logger.opt(exception=close_error).error(
                    "Échec de fermeture de la source {} après un échec de détails",
                    listing.source,
                )
            raise
        else:
            scraper.close()
            return details

    @staticmethod
    def _detail_identifier(listing: SourceListing) -> str:
        if listing.source == "freework":
            return listing.url
        if listing.source == "linkedin" and listing.external_id.startswith("linkedin_"):
            return listing.external_id.removeprefix("linkedin_")
        return listing.external_id

    def _persist_details(
        self,
        job: CanonicalJob,
        details: JobOffer,
        *,
        fetched_at: datetime,
    ) -> CanonicalJob:
        """Optimistically merge one fetched snapshot without losing a newer writer."""

        current = job
        while True:
            groups = self._eligible_detail_groups(current, details, fetched_at)
            if not groups:
                return current
            expected_version = self._utc(current.updated_at)
            current_cache_at = current.details_fetched_at
            next_cache_at = fetched_at
            if current_cache_at is not None:
                next_cache_at = max(self._utc(current_cache_at), fetched_at)
            if self._claim_refresh(
                current.pk,
                expected_version=expected_version,
                cache_at=next_cache_at,
            ):
                self._apply_details(current, details, groups)
                self.jobs.stamp_detail_groups(
                    current.id,
                    groups=groups,
                    fetched_at=fetched_at,
                )
                self.session.commit()
                durable = self._reload_job(current.id)
                if durable is None:
                    raise JobDetailsUnavailableError(self._UNAVAILABLE_MESSAGE)
                return durable

            self.session.rollback()
            durable = self._reload_job(current.id)
            if durable is None:
                raise JobDetailsUnavailableError(self._UNAVAILABLE_MESSAGE)
            current = durable

    def _eligible_detail_groups(
        self,
        job: CanonicalJob,
        details: JobOffer,
        fetched_at: datetime,
    ) -> list[str]:
        return [
            group
            for group in self._detail_groups(job, details)
            if (
                (stored_at := self.jobs._group_timestamp(job, group)) is None
                or self._utc(stored_at) < fetched_at
            )
        ]

    def _claim_refresh(
        self,
        job_pk: int,
        *,
        expected_version: datetime,
        cache_at: datetime,
    ) -> bool:
        version = self._next_version(expected_version)
        result = cast(
            CursorResult[Any],
            self.session.execute(
                update(CanonicalJob)
                .where(
                    CanonicalJob.pk == job_pk,
                    CanonicalJob.updated_at == expected_version,
                )
                .values(details_fetched_at=cache_at, updated_at=version)
                .execution_options(synchronize_session=False)
            ),
        )
        return result.rowcount == 1

    def _reload_job(self, canonical_job_id: str) -> CanonicalJob | None:
        return self.session.scalar(
            select(CanonicalJob)
            .where(CanonicalJob.id == canonical_job_id)
            .execution_options(populate_existing=True)
        )

    def _rollback_after_failure(self, primary_error: Exception) -> None:
        try:
            self.session.rollback()
        except Exception as rollback_error:
            logger.opt(exception=rollback_error).error(
                "Échec secondaire du rollback après {}",
                type(primary_error).__name__,
            )

    def _reload_after_failure(
        self, canonical_job_id: str, primary_error: Exception
    ) -> CanonicalJob | None:
        try:
            return self._reload_job(canonical_job_id)
        except Exception as reload_error:
            logger.opt(exception=reload_error).error(
                "Impossible de relire le cache durable du job {}",
                canonical_job_id,
            )
            raise JobDetailsUnavailableError(
                self._UNAVAILABLE_MESSAGE
            ) from primary_error

    @classmethod
    def _detail_groups(cls, job: CanonicalJob, details: JobOffer) -> list[str]:
        groups: list[str] = []
        if details.description is not None and details.description.strip():
            groups.append("description")
        if cls._can_refresh_salary(job, details):
            groups.append("salary")
        if details.skills:
            groups.append("skills")
        if details.benefits:
            groups.append("benefits")
        return groups

    @staticmethod
    def _can_refresh_salary(job: CanonicalJob, details: JobOffer) -> bool:
        has_incoming_salary = (
            details.salary_min is not None or details.salary_max is not None
        )
        has_currency = bool(details.salary_currency.strip())
        preserves_cached_bounds = not (
            (job.salary_min is not None and details.salary_min is None)
            or (job.salary_max is not None and details.salary_max is None)
        )
        return has_incoming_salary and has_currency and preserves_cached_bounds

    @staticmethod
    def _apply_details(job: CanonicalJob, details: JobOffer, groups: list[str]) -> None:
        if "description" in groups:
            job.description = (
                details.description.strip() if details.description else None
            )
        if "salary" in groups:
            if details.salary_min is not None:
                job.salary_min = details.salary_min
            if details.salary_max is not None:
                job.salary_max = details.salary_max
            job.salary_currency = details.salary_currency.strip()
        if "skills" in groups:
            job.skills = list(details.skills)
        if "benefits" in groups:
            job.benefits = list(details.benefits)

    def _stale_or_raise(
        self,
        job: CanonicalJob | None,
        *,
        message: str | None = None,
        cause: Exception | None = None,
    ) -> JobDetailsResult:
        if job is not None and job.details_fetched_at is not None:
            self._normalize_job_timestamp(job)
            return JobDetailsResult(
                job=job,
                cache_state="stale",
                updated_at=self._utc(job.details_fetched_at),
                warning=self._STALE_WARNING,
            )
        error = JobDetailsUnavailableError(message or self._UNAVAILABLE_MESSAGE)
        if cause is not None:
            raise error from cause
        raise error

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @classmethod
    def _normalize_job_timestamp(cls, job: CanonicalJob) -> None:
        if job.details_fetched_at is not None:
            set_committed_value(
                job,
                "details_fetched_at",
                cls._utc(job.details_fetched_at),
            )

    @classmethod
    def _next_version(cls, current: datetime) -> datetime:
        candidate = cls._utc(utc_now())
        return max(candidate, current + timedelta(microseconds=1))
