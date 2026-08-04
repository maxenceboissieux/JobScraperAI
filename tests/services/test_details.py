from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from jobscraper.db.base import Base
from jobscraper.db.models import SourceListing
from jobscraper.db.session import create_engine_and_session
from jobscraper.models.job import JobOffer, SearchCriteria
from jobscraper.repositories.jobs import JobRepository
from jobscraper.scrapers.base import BaseScraper
from jobscraper.services.details import (
    JobDetailsService,
    JobDetailsUnavailableError,
)

NOW = datetime(2026, 8, 4, 12, tzinfo=timezone.utc)


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine, session_factory = create_engine_and_session(
        f"sqlite:///{tmp_path / 'details.db'}"
    )
    Base.metadata.create_all(engine)
    with session_factory() as database_session:
        yield database_session


@dataclass
class Clock:
    current: datetime = NOW

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **kwargs: float) -> None:
        self.current += timedelta(**kwargs)


@dataclass
class DetailScenario:
    result: JobOffer | None = None
    error: Exception | None = None
    close_error: Exception | None = None


class FakeScraper(BaseScraper):
    def __init__(self, source: str, scenario: DetailScenario) -> None:
        super().__init__()
        self.name = source
        self.scenario = scenario
        self.detail_identifiers: list[str] = []
        self.closed = False

    def search(self, criteria: SearchCriteria) -> Iterator[JobOffer]:
        return iter(())

    def get_job_details(self, job_id: str) -> JobOffer | None:
        self.detail_identifiers.append(job_id)
        if self.scenario.error is not None:
            raise self.scenario.error
        return self.scenario.result

    def close(self) -> None:
        self.closed = True
        super().close()
        if self.scenario.close_error is not None:
            raise self.scenario.close_error


class FakeRegistry:
    def __init__(self, scenarios: dict[str, DetailScenario | Exception]) -> None:
        self.scenarios = scenarios
        self.created: list[str] = []
        self.instances: list[FakeScraper] = []

    def create(self, source: str) -> BaseScraper:
        self.created.append(source)
        scenario = self.scenarios[source]
        if isinstance(scenario, Exception):
            raise scenario
        scraper = FakeScraper(source, scenario)
        self.instances.append(scraper)
        return scraper


def listing_offer(
    external_id: str = "freework_42",
    *,
    source: str = "freework",
    description: str | None = None,
    salary_min: float | None = None,
    salary_max: float | None = None,
    skills: list[str] | None = None,
    benefits: list[str] | None = None,
) -> JobOffer:
    return JobOffer(
        id=external_id,
        source=source,
        url=f"https://example.test/jobs/{source}/{external_id}",
        title="Python backend engineer",
        company="Acme",
        location="Paris",
        description=description,
        salary_min=salary_min,
        salary_max=salary_max,
        skills=skills or [],
        benefits=benefits or [],
    )


def service_for(
    session: Session,
    clock: Clock,
    scenarios: dict[str, DetailScenario | Exception],
) -> tuple[JobDetailsService, FakeRegistry]:
    registry = FakeRegistry(scenarios)
    return JobDetailsService(session, registry=registry, clock=clock), registry


def test_get_refreshes_then_reuses_fresh_cache_and_falls_back_to_stale(
    session: Session,
) -> None:
    """Fails if cache age, persistence, or fetch-failure fallback takes the wrong branch."""
    job = JobRepository(session).upsert_listing(listing_offer(), seen_at=NOW)
    scenario = DetailScenario(
        result=listing_offer(
            description="Description conservée",
            salary_min=60_000,
            salary_max=75_000,
            skills=["Python"],
            benefits=["RTT"],
        )
    )
    clock = Clock()
    service, registry = service_for(session, clock, {"freework": scenario})

    refreshed = service.get(job.id)
    fresh = service.get(job.id)
    clock.advance(days=2)
    scenario.error = TimeoutError("upstream timeout")
    stale = service.get(job.id)

    assert refreshed.cache_state == "refreshed"
    assert refreshed.updated_at == NOW
    assert refreshed.warning is None
    assert (refreshed.job.salary_min, refreshed.job.salary_max) == (60_000, 75_000)
    assert refreshed.job.skills == ["Python"]
    assert refreshed.job.benefits == ["RTT"]
    assert fresh.cache_state == "fresh"
    assert len(registry.instances) == 2
    assert stale.cache_state == "stale"
    assert stale.updated_at == NOW
    assert stale.job.description == "Description conservée"
    assert stale.warning is not None
    assert "obsolètes" in stale.warning
    assert all(scraper.closed for scraper in registry.instances)


def test_get_prefers_known_detail_parser_over_newer_active_listing(
    session: Session,
) -> None:
    """Fails if recency beats parser capability or Free-Work receives an unusable ID."""
    jobs = JobRepository(session)
    job = jobs.upsert_listing(listing_offer("adzuna-new", source="adzuna"), seen_at=NOW)
    freework_url = "https://www.free-work.com/fr/tech-it/job-mission/python/42"
    session.add(
        SourceListing(
            canonical_job_id=job.pk,
            source="freework",
            external_id="freework_42",
            url=freework_url,
            title=job.title,
            company=job.company,
            location=job.location,
            posted_at=NOW - timedelta(days=1),
            first_seen_at=NOW - timedelta(days=1),
            last_seen_at=NOW - timedelta(days=1),
        )
    )
    session.flush()
    detail = listing_offer(description="Détail Free-Work")
    service, registry = service_for(
        session,
        Clock(),
        {
            "adzuna": DetailScenario(result=None),
            "freework": DetailScenario(result=detail),
        },
    )

    result = service.get(job.id)

    assert result.cache_state == "refreshed"
    assert registry.created == ["freework"]
    assert registry.instances[0].detail_identifiers == [freework_url]


def test_get_falls_back_to_newest_active_listing_when_none_has_a_parser(
    session: Session,
) -> None:
    """Fails if the fallback ignores active-listing recency."""
    jobs = JobRepository(session)
    job = jobs.upsert_listing(
        listing_offer("wttj-old", source="wttj"), seen_at=NOW - timedelta(hours=2)
    )
    session.add(
        SourceListing(
            canonical_job_id=job.pk,
            source="adzuna",
            external_id="adzuna-new",
            url="https://example.test/jobs/adzuna/adzuna-new",
            title=job.title,
            company=job.company,
            location=job.location,
            posted_at=NOW,
            first_seen_at=NOW,
            last_seen_at=NOW,
        )
    )
    session.flush()
    service, registry = service_for(
        session,
        Clock(),
        {
            "wttj": DetailScenario(result=None),
            "adzuna": DetailScenario(result=None),
        },
    )

    with pytest.raises(JobDetailsUnavailableError, match="indisponibles"):
        service.get(job.id)

    assert registry.created == ["adzuna"]
    assert registry.instances[0].detail_identifiers == ["adzuna-new"]
    assert registry.instances[0].closed is True


def test_partial_refresh_never_erases_cached_detail_groups(session: Session) -> None:
    """Fails if sparse detail responses clear fields or stamp absent groups as refreshed."""
    jobs = JobRepository(session)
    job = jobs.upsert_listing(
        listing_offer(
            description="Description en cache",
            salary_min=65_000,
            salary_max=80_000,
            skills=["Python"],
            benefits=["Mutuelle"],
        ),
        seen_at=NOW - timedelta(days=3),
    )
    old_timestamp = NOW - timedelta(days=2)
    job.details_fetched_at = old_timestamp
    job.detail_provenance = {
        group: old_timestamp.isoformat()
        for group in ("description", "salary", "skills", "benefits")
    }
    session.flush()
    scenario = DetailScenario(result=listing_offer(skills=["FastAPI", "Docker"]))
    service, _ = service_for(session, Clock(), {"freework": scenario})

    result = service.get(job.id)

    assert result.cache_state == "refreshed"
    assert result.updated_at == NOW
    assert result.job.description == "Description en cache"
    assert (result.job.salary_min, result.job.salary_max) == (65_000, 80_000)
    assert result.job.skills == ["FastAPI", "Docker"]
    assert result.job.benefits == ["Mutuelle"]
    assert result.job.detail_provenance == {
        "description": old_timestamp.isoformat(),
        "salary": old_timestamp.isoformat(),
        "skills": NOW.isoformat(),
        "benefits": old_timestamp.isoformat(),
    }


def test_partial_salary_does_not_mix_new_currency_with_a_cached_bound(
    session: Session,
) -> None:
    """Fails if one new salary bound makes a mixed snapshot look wholly refreshed."""
    jobs = JobRepository(session)
    job = jobs.upsert_listing(
        listing_offer(
            salary_min=90_000,
            salary_max=110_000,
            skills=["Python"],
        ).model_copy(update={"salary_currency": "USD"}),
        seen_at=NOW - timedelta(days=3),
    )
    old_timestamp = NOW - timedelta(days=2)
    job.details_fetched_at = old_timestamp
    job.detail_provenance = {
        "salary": old_timestamp.isoformat(),
        "skills": old_timestamp.isoformat(),
    }
    session.flush()
    detail = listing_offer(salary_min=70_000, skills=["FastAPI"])
    service, _ = service_for(
        session,
        Clock(),
        {"freework": DetailScenario(result=detail)},
    )

    result = service.get(job.id)

    assert result.cache_state == "refreshed"
    assert (
        result.job.salary_min,
        result.job.salary_max,
        result.job.salary_currency,
    ) == (90_000, 110_000, "USD")
    assert result.job.detail_provenance["salary"] == old_timestamp.isoformat()
    assert result.job.skills == ["FastAPI"]
    assert result.job.detail_provenance["skills"] == NOW.isoformat()


def test_commit_failure_rolls_back_new_fields_before_returning_stale(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fails if stale fallback exposes mutations from a failed cache commit."""
    jobs = JobRepository(session)
    job = jobs.upsert_listing(
        listing_offer(description="Description validée"),
        seen_at=NOW - timedelta(days=3),
    )
    old_timestamp = NOW - timedelta(days=2)
    job.details_fetched_at = old_timestamp
    job.detail_provenance = {"description": old_timestamp.isoformat()}
    session.commit()
    service, _ = service_for(
        session,
        Clock(),
        {
            "freework": DetailScenario(
                result=listing_offer(description="Description non commitée")
            )
        },
    )

    def fail_commit() -> None:
        raise RuntimeError("database commit failed")

    monkeypatch.setattr(session, "commit", fail_commit)

    result = service.get(job.id)

    assert result.cache_state == "stale"
    assert result.updated_at == old_timestamp
    assert result.job.description == "Description validée"
    assert result.job.details_fetched_at == old_timestamp


def test_stale_cache_survives_scraper_cleanup_failure(session: Session) -> None:
    """Fails if a close failure leaks or turns an uncommitted refresh into fresh data."""
    jobs = JobRepository(session)
    job = jobs.upsert_listing(
        listing_offer(description="Description conservée"),
        seen_at=NOW - timedelta(days=3),
    )
    job.details_fetched_at = NOW - timedelta(days=2)
    session.flush()
    scenario = DetailScenario(
        result=listing_offer(description="Description non validée"),
        close_error=RuntimeError("close failed"),
    )
    service, registry = service_for(session, Clock(), {"freework": scenario})

    result = service.get(job.id)

    assert result.cache_state == "stale"
    assert result.job.description == "Description conservée"
    assert result.updated_at == NOW - timedelta(days=2)
    assert registry.instances[0].closed is True


def test_refresh_failure_without_cache_raises_french_service_error(
    session: Session,
) -> None:
    """Fails if an absent cache is mislabeled stale or exposes an upstream exception."""
    job = JobRepository(session).upsert_listing(listing_offer(), seen_at=NOW)
    service, registry = service_for(
        session,
        Clock(),
        {"freework": DetailScenario(error=TimeoutError("secret upstream text"))},
    )

    with pytest.raises(JobDetailsUnavailableError, match="indisponibles") as caught:
        service.get(job.id)

    assert "secret upstream text" not in str(caught.value)
    assert registry.instances[0].closed is True


def test_cleanup_failure_does_not_mask_the_primary_fetch_failure(
    session: Session,
) -> None:
    """Fails if close replaces the fetch exception used for local diagnosis."""
    job = JobRepository(session).upsert_listing(listing_offer(), seen_at=NOW)
    service, registry = service_for(
        session,
        Clock(),
        {
            "freework": DetailScenario(
                error=TimeoutError("primary fetch failure"),
                close_error=RuntimeError("secondary close failure"),
            )
        },
    )

    with pytest.raises(JobDetailsUnavailableError) as caught:
        service.get(job.id)

    assert isinstance(caught.value.__cause__, TimeoutError)
    assert registry.instances[0].closed is True


def test_stale_cache_survives_registry_failure(session: Session) -> None:
    """Fails if scraper construction failure bypasses stale fallback."""
    job = JobRepository(session).upsert_listing(
        listing_offer(description="Copie locale"), seen_at=NOW - timedelta(days=3)
    )
    job.details_fetched_at = NOW - timedelta(days=2)
    session.flush()
    service, registry = service_for(
        session, Clock(), {"freework": ValueError("source disabled")}
    )

    result = service.get(job.id)

    assert result.cache_state == "stale"
    assert result.job.description == "Copie locale"
    assert registry.created == ["freework"]


def test_get_rejects_unknown_job_and_negative_max_age(session: Session) -> None:
    """Fails if invalid public inputs reach scraper construction."""
    service, registry = service_for(session, Clock(), {})

    with pytest.raises(ValueError, match="positive ou nulle"):
        service.get("missing", max_age=timedelta(seconds=-1))
    with pytest.raises(LookupError, match="n’existe pas"):
        service.get("missing")

    assert registry.created == []


def test_get_without_active_listing_is_unavailable_without_scraper_creation(
    session: Session,
) -> None:
    """Fails if inactive sources are scraped or an absent cache is reported stale."""
    jobs = JobRepository(session)
    job = jobs.upsert_listing(listing_offer(), seen_at=NOW)
    listing = jobs.get_listing(job.id)
    assert listing is not None
    listing.active = False
    session.flush()
    service, registry = service_for(session, Clock(), {})

    with pytest.raises(JobDetailsUnavailableError, match="source active"):
        service.get(job.id)

    assert registry.created == []
