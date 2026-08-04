from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from jobscraper.db.base import Base
from jobscraper.db.models import CanonicalJob, SourceListing
from jobscraper.db.session import create_engine_and_session
from jobscraper.models.job import JobOffer, SearchCriteria
from jobscraper.repositories.jobs import JobRepository
from jobscraper.scrapers.base import BaseScraper
from jobscraper.scrapers.linkedin import LinkedInScraper
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
    on_fetch: Callable[[], None] | None = None


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
        if self.scenario.on_fetch is not None:
            self.scenario.on_fetch()
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


class FixedRegistry:
    def __init__(self, source: str, scraper: BaseScraper) -> None:
        self.source = source
        self.scraper = scraper

    def create(self, source: str) -> BaseScraper:
        if source != self.source:
            raise AssertionError(f"unexpected source: {source}")
        return self.scraper


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


def test_detail_service_uses_injected_job_repository(session: Session) -> None:
    jobs = JobRepository(session)

    service = JobDetailsService(session, jobs=jobs)

    assert service.jobs is jobs


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


def test_linkedin_persisted_identifier_builds_real_numeric_detail_url(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fails if the canonical source prefix leaks into LinkedIn's real detail URL."""
    job = JobRepository(session).upsert_listing(
        listing_offer(
            "linkedin_10001",
            source="linkedin",
            description=None,
        ).model_copy(
            update={"url": "https://www.linkedin.com/jobs/view/python-engineer-10001"}
        ),
        seen_at=NOW,
    )
    observed_urls: list[str] = []
    scraper = LinkedInScraper({"delay": 0})

    def fetch_page(url: str) -> str:
        observed_urls.append(url)
        return """
            <h1 class="top-card-layout__title">Python engineer</h1>
            <a class="topcard__org-name-link">Acme</a>
            <span class="topcard__flavor--bullet">Paris</span>
            <div class="description__text">Détail LinkedIn</div>
        """

    monkeypatch.setattr(scraper, "_fetch_page", fetch_page)
    service = JobDetailsService(
        session,
        registry=FixedRegistry("linkedin", scraper),
        clock=Clock(),
    )

    result = service.get(job.id)

    assert result.job.description == "Détail LinkedIn"
    assert observed_urls == ["https://www.linkedin.com/jobs/view/10001"]


def test_get_refreshes_from_latest_inactive_linkedin_when_no_source_is_active(
    session: Session,
) -> None:
    """Fails if a still-readable historical LinkedIn permalink is discarded."""
    job = JobRepository(session).upsert_listing(
        listing_offer("linkedin_4444457297", source="linkedin"), seen_at=NOW
    )
    listing = JobRepository(session).get_listing(job.id)
    assert listing is not None
    listing.active = False
    session.flush()
    service, registry = service_for(
        session,
        Clock(),
        {
            "linkedin": DetailScenario(
                result=listing_offer(
                    "linkedin_4444457297",
                    source="linkedin",
                    description="Détail LinkedIn conservé",
                )
            )
        },
    )

    result = service.get(job.id)

    assert result.cache_state == "refreshed"
    assert result.job.description == "Détail LinkedIn conservé"
    assert registry.created == ["linkedin"]
    assert registry.instances[0].detail_identifiers == ["4444457297"]


def test_get_prefers_active_supported_listing_over_inactive_linkedin(
    session: Session,
) -> None:
    """Fails if the historical fallback displaces a currently active source."""
    jobs = JobRepository(session)
    job = jobs.upsert_listing(listing_offer(), seen_at=NOW - timedelta(days=1))
    session.add(
        SourceListing(
            canonical_job_id=job.pk,
            source="linkedin",
            external_id="linkedin_4444457297",
            url="https://www.linkedin.com/jobs/view/4444457297",
            title=job.title,
            company=job.company,
            location=job.location,
            active=False,
            first_seen_at=NOW,
            last_seen_at=NOW,
        )
    )
    session.flush()
    service, registry = service_for(
        session,
        Clock(),
        {
            "freework": DetailScenario(
                result=listing_offer(description="Détail actif Free-Work")
            ),
            "linkedin": DetailScenario(
                result=listing_offer(
                    source="linkedin", description="Détail LinkedIn inactif"
                )
            ),
        },
    )

    result = service.get(job.id)

    assert result.job.description == "Détail actif Free-Work"
    assert registry.created == ["freework"]


@pytest.mark.parametrize("source", ["freework", "hellowork"])
def test_get_never_falls_back_to_other_inactive_sources(
    session: Session, source: str
) -> None:
    """Fails if the narrow LinkedIn fallback silently widens to other adapters."""
    job = JobRepository(session).upsert_listing(
        listing_offer(f"{source}_42", source=source), seen_at=NOW
    )
    listing = JobRepository(session).get_listing(job.id)
    assert listing is not None
    listing.active = False
    session.flush()
    service, registry = service_for(
        session,
        Clock(),
        {source: DetailScenario(result=listing_offer(source=source))},
    )

    with pytest.raises(JobDetailsUnavailableError, match="source active"):
        service.get(job.id)

    assert registry.created == []


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


def test_empty_salary_currency_never_mutates_or_stamps_the_salary_group(
    session: Session,
) -> None:
    """Fails if blank currency makes an otherwise complete salary snapshot durable."""
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
    session.commit()
    detail = listing_offer(
        salary_min=70_000,
        salary_max=80_000,
        skills=["FastAPI"],
    ).model_copy(update={"salary_currency": ""})
    service, _ = service_for(
        session,
        Clock(),
        {"freework": DetailScenario(result=detail)},
    )

    result = service.get(job.id)

    assert (
        result.job.salary_min,
        result.job.salary_max,
        result.job.salary_currency,
    ) == (90_000, 110_000, "USD")
    assert result.job.detail_provenance["salary"] == old_timestamp.isoformat()
    assert result.job.skills == ["FastAPI"]
    assert result.job.detail_provenance["skills"] == NOW.isoformat()


def test_real_commit_failure_never_returns_an_uncommitted_cache(
    session: Session,
) -> None:
    """Fails if rollback trusts a cache timestamp that was never durable."""
    jobs = JobRepository(session)
    job = jobs.upsert_listing(
        listing_offer(description="Description durable de carte"),
        seen_at=NOW - timedelta(days=3),
    )
    session.commit()
    old_timestamp = NOW - timedelta(days=2)
    job.description = "Description de cache non commitée"
    job.details_fetched_at = old_timestamp
    job.detail_provenance = {"description": old_timestamp.isoformat()}
    session.flush()
    service, _ = service_for(
        session,
        Clock(),
        {
            "freework": DetailScenario(
                result=listing_offer(description="Description non commitée")
            )
        },
    )

    def fail_commit(_session: Session) -> None:
        raise RuntimeError("database commit failed")

    event.listen(session, "before_commit", fail_commit)
    try:
        with pytest.raises(JobDetailsUnavailableError) as caught:
            service.get(job.id)
    finally:
        event.remove(session, "before_commit", fail_commit)

    assert isinstance(caught.value.__cause__, RuntimeError)
    durable = session.scalar(select(CanonicalJob).where(CanonicalJob.id == job.id))
    assert durable is not None
    assert durable.description == "Description durable de carte"
    assert durable.details_fetched_at is None


def test_commit_failure_for_uncommitted_job_preserves_the_primary_error(
    session: Session,
) -> None:
    """Fails if expired rolled-back ORM rows mask the primary database failure."""
    session.connection().exec_driver_sql("BEGIN")
    job = JobRepository(session).upsert_listing(
        listing_offer(description="Description transitoire"),
        seen_at=NOW - timedelta(days=3),
    )
    job_id = job.id
    service, _ = service_for(
        session,
        Clock(),
        {
            "freework": DetailScenario(
                result=listing_offer(description="Rafraîchissement transitoire")
            )
        },
    )
    primary_error = RuntimeError("primary commit failure")

    def fail_commit(_session: Session) -> None:
        raise primary_error

    event.listen(session, "before_commit", fail_commit)
    try:
        with pytest.raises(JobDetailsUnavailableError) as caught:
            service.get(job_id)
    finally:
        event.remove(session, "before_commit", fail_commit)

    assert caught.value.__cause__ is primary_error
    assert session.scalar(select(CanonicalJob).where(CanonicalJob.id == job_id)) is None


def test_late_older_refresh_preserves_newer_groups_and_merges_disjoint_groups(
    tmp_path: Path,
) -> None:
    """Fails if a late stale ORM writer regresses a newer committed refresh."""
    engine, session_factory = create_engine_and_session(
        f"sqlite:///{tmp_path / 'details-race.db'}"
    )
    Base.metadata.create_all(engine)
    old_timestamp = NOW - timedelta(days=2)
    with session_factory() as setup:
        job = JobRepository(setup).upsert_listing(
            listing_offer(
                description="Description initiale",
                skills=["Python"],
                benefits=["Mutuelle"],
            ),
            seen_at=NOW - timedelta(days=3),
        )
        job.details_fetched_at = old_timestamp
        job.detail_provenance = {
            group: old_timestamp.isoformat()
            for group in ("description", "skills", "benefits")
        }
        setup.commit()
        job_id = job.id

    with session_factory() as older_session, session_factory() as newer_session:
        newer_service, _ = service_for(
            newer_session,
            Clock(NOW + timedelta(hours=2)),
            {
                "freework": DetailScenario(
                    result=listing_offer(
                        description="Description gagnante",
                        skills=["FastAPI"],
                    )
                )
            },
        )
        newer_results = []

        def commit_newer_refresh() -> None:
            newer_results.append(newer_service.get(job_id, max_age=timedelta(0)))

        older_service, _ = service_for(
            older_session,
            Clock(NOW + timedelta(hours=1)),
            {
                "freework": DetailScenario(
                    result=listing_offer(
                        description="Description ancienne arrivée en retard",
                        benefits=["RTT"],
                    ),
                    on_fetch=commit_newer_refresh,
                )
            },
        )

        result = older_service.get(job_id, max_age=timedelta(0))

        assert len(newer_results) == 1
        assert result.job.description == "Description gagnante"
        assert result.job.skills == ["FastAPI"]
        assert result.job.benefits == ["RTT"]
        assert result.updated_at == NOW + timedelta(hours=2)
        assert result.job.detail_provenance == {
            "description": (NOW + timedelta(hours=2)).isoformat(),
            "skills": (NOW + timedelta(hours=2)).isoformat(),
            "benefits": (NOW + timedelta(hours=1)).isoformat(),
        }

    with session_factory() as observer:
        durable = observer.scalar(select(CanonicalJob).where(CanonicalJob.id == job_id))
        assert durable is not None
        assert durable.description == "Description gagnante"
        assert durable.skills == ["FastAPI"]
        assert durable.benefits == ["RTT"]
        assert durable.details_fetched_at == NOW + timedelta(hours=2)
        assert durable.detail_provenance == {
            "description": (NOW + timedelta(hours=2)).isoformat(),
            "skills": (NOW + timedelta(hours=2)).isoformat(),
            "benefits": (NOW + timedelta(hours=1)).isoformat(),
        }


def test_result_timestamps_are_always_aware_utc(session: Session) -> None:
    """Fails if an in-session naive cache timestamp leaks through the result API."""
    job = JobRepository(session).upsert_listing(listing_offer(), seen_at=NOW)
    job.details_fetched_at = NOW.replace(tzinfo=None)
    session.flush()
    service, registry = service_for(session, Clock(), {})

    result = service.get(job.id)

    assert result.updated_at == NOW
    assert result.updated_at.tzinfo is timezone.utc
    assert result.job.details_fetched_at == NOW
    assert result.job.details_fetched_at.tzinfo is timezone.utc
    assert registry.created == []


def test_stale_result_timestamps_are_always_aware_utc(session: Session) -> None:
    """Fails if stale fallback returns a naive timestamp on either result object."""
    job = JobRepository(session).upsert_listing(listing_offer(), seen_at=NOW)
    job.details_fetched_at = (NOW - timedelta(days=2)).replace(tzinfo=None)
    listing = session.scalar(
        select(SourceListing).where(SourceListing.canonical_job_id == job.pk)
    )
    assert listing is not None
    listing.active = False
    session.flush()
    service, registry = service_for(session, Clock(), {})

    result = service.get(job.id)

    assert result.cache_state == "stale"
    assert result.updated_at.tzinfo is timezone.utc
    assert result.job.details_fetched_at is not None
    assert result.job.details_fetched_at.tzinfo is timezone.utc
    assert registry.created == []


def test_rollback_hook_failure_never_masks_the_primary_refresh_error(
    session: Session,
) -> None:
    """Fails if a SQLAlchemy rollback error replaces the upstream root cause."""
    job = JobRepository(session).upsert_listing(listing_offer(), seen_at=NOW)
    session.commit()
    primary_error = TimeoutError("primary scraper timeout")
    service, _ = service_for(
        session,
        Clock(),
        {"freework": DetailScenario(error=primary_error)},
    )

    def fail_after_rollback(_session: Session) -> None:
        raise RuntimeError("secondary rollback hook failure")

    event.listen(session, "after_rollback", fail_after_rollback)
    try:
        with pytest.raises(JobDetailsUnavailableError) as caught:
            service.get(job.id)
    finally:
        event.remove(session, "after_rollback", fail_after_rollback)

    assert caught.value.__cause__ is primary_error


def test_stale_cache_survives_scraper_cleanup_failure(session: Session) -> None:
    """Fails if a close failure leaks or turns an uncommitted refresh into fresh data."""
    jobs = JobRepository(session)
    job = jobs.upsert_listing(
        listing_offer(description="Description conservée"),
        seen_at=NOW - timedelta(days=3),
    )
    job.details_fetched_at = NOW - timedelta(days=2)
    session.commit()
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
    session.commit()
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
