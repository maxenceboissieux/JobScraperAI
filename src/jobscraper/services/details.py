"""Lazy canonical-job detail refresh with a durable stale-cache fallback."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Protocol

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

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
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.session = session
        self.registry = registry or ScraperRegistry()
        self.clock = clock
        self.jobs = JobRepository(session)

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
            return JobDetailsResult(
                job=job,
                cache_state="fresh",
                updated_at=cached_at,
            )

        listing = self._best_listing(job.pk)
        if listing is None:
            return self._stale_or_raise(
                job,
                cached_at,
                message=(
                    "Les détails de cette offre sont indisponibles : "
                    "aucune source active."
                ),
            )

        persistence_started = False
        try:
            details = self._fetch_details(listing)
            if details is None:
                raise JobDetailsUnavailableError(self._UNAVAILABLE_MESSAGE)
            groups = self._detail_groups(job, details)
            if not groups:
                raise JobDetailsUnavailableError(self._UNAVAILABLE_MESSAGE)
            persistence_started = True
            self._apply_details(job, details, groups)
            self.jobs.stamp_detail_groups(
                job.id,
                groups=groups,
                fetched_at=now,
            )
            self.session.commit()
        except Exception as exc:
            fallback_job = job
            if persistence_started:
                self.session.rollback()
                fallback_job = self.jobs.get_job(canonical_job_id) or job
            logger.opt(exception=exc).error(
                "Échec d’actualisation des détails du job {} depuis {}",
                canonical_job_id,
                listing.source,
            )
            return self._stale_or_raise(fallback_job, cached_at, cause=exc)

        refreshed = self.jobs.get_job(canonical_job_id)
        if refreshed is None or refreshed.details_fetched_at is None:
            raise JobDetailsUnavailableError(self._UNAVAILABLE_MESSAGE)
        return JobDetailsResult(
            job=refreshed,
            cache_state="refreshed",
            updated_at=refreshed.details_fetched_at,
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
            identifier = (
                listing.url if listing.source == "freework" else listing.external_id
            )
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
        preserves_cached_bounds = not (
            (job.salary_min is not None and details.salary_min is None)
            or (job.salary_max is not None and details.salary_max is None)
        )
        return has_incoming_salary and preserves_cached_bounds

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
            job.salary_currency = details.salary_currency
        if "skills" in groups:
            job.skills = list(details.skills)
        if "benefits" in groups:
            job.benefits = list(details.benefits)

    def _stale_or_raise(
        self,
        job: CanonicalJob,
        cached_at: datetime | None,
        *,
        message: str | None = None,
        cause: Exception | None = None,
    ) -> JobDetailsResult:
        if cached_at is not None:
            return JobDetailsResult(
                job=job,
                cache_state="stale",
                updated_at=cached_at,
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
