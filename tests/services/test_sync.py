from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from jobscraper.config import Config, FreeWorkConfig
from jobscraper.db.base import Base
from jobscraper.db.models import (
    CanonicalJob,
    DuplicateRelation,
    SearchListing,
    SourceListing,
    SourceSyncResult,
)
from jobscraper.db.session import create_engine_and_session
from jobscraper.models.job import JobOffer, SearchCriteria
from jobscraper.repositories.jobs import JobRepository
from jobscraper.repositories.saved_searches import SavedSearchRepository
from jobscraper.repositories.sync_runs import SyncRunRepository
from jobscraper.scrapers.adzuna import AdzunaScraper
from jobscraper.scrapers.base import BaseScraper
from jobscraper.scrapers.francetravail import FranceTravailScraper
from jobscraper.scrapers.freework import FreeWorkScraper
from jobscraper.scrapers.hellowork import HelloWorkScraper
from jobscraper.scrapers.linkedin import LinkedInScraper
from jobscraper.scrapers.registry import ScraperRegistry
from jobscraper.scrapers.wttj import WTTJScraper
from jobscraper.services.deduplication import DuplicateDecision
from jobscraper.services.sync import SyncService

NOW = datetime(2026, 8, 4, 12, tzinfo=timezone.utc)


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine, session_factory = create_engine_and_session(
        f"sqlite:///{tmp_path / 'sync.db'}"
    )
    Base.metadata.create_all(engine)
    with session_factory() as database_session:
        yield database_session


def offer(
    external_id: str,
    *,
    source: str = "freework",
    title: str = "Python backend engineer",
    company: str = "Acme",
    location: str = "Paris",
) -> JobOffer:
    return JobOffer(
        id=external_id,
        source=source,
        url=f"https://example.test/jobs/{source}/{external_id}",
        title=title,
        company=company,
        location=location,
    )


@dataclass
class ScrapeScenario:
    offers: list[JobOffer] = field(default_factory=list)
    error: Exception | None = None
    close_error: Exception | None = None
    after_yield: Callable[[], None] | None = None


class FakeScraper(BaseScraper):
    def __init__(self, source: str, scenario: ScrapeScenario) -> None:
        super().__init__()
        self.name = source
        self.scenario = scenario
        self.closed = False
        self.criteria_seen: list[SearchCriteria] = []

    def search(self, criteria: SearchCriteria) -> Iterator[JobOffer]:
        self.criteria_seen.append(criteria)
        for scraped_offer in self.scenario.offers:
            yield scraped_offer
            if self.scenario.after_yield is not None:
                self.scenario.after_yield()
        if self.scenario.error is not None:
            raise self.scenario.error

    def get_job_details(self, job_id: str) -> JobOffer | None:
        return None

    def close(self) -> None:
        self.closed = True
        super().close()
        if self.scenario.close_error is not None:
            raise self.scenario.close_error


class FakeRegistry:
    def __init__(self, scenarios: dict[str, ScrapeScenario]) -> None:
        self.scenarios = scenarios
        self.created: list[str] = []
        self.instances: list[FakeScraper] = []

    def create(self, source: str) -> BaseScraper:
        self.created.append(source)
        scraper = FakeScraper(source, self.scenarios[source])
        self.instances.append(scraper)
        return scraper


def source_results(session: Session, run_id: str) -> dict[str, SourceSyncResult]:
    run = SyncRunRepository(session).get(run_id)
    assert run is not None
    return {
        result.source: result
        for result in session.scalars(
            select(SourceSyncResult).where(SourceSyncResult.sync_run_id == run.pk)
        )
    }


def test_mixed_source_outcomes_persist_success_and_finish_partial(
    session: Session,
) -> None:
    """Fails if one source failure rolls back another source or aborts the run."""
    saved_search = SavedSearchRepository(session).create(
        name="Python",
        criteria=SearchCriteria(keywords=["python"]),
        sources=["freework", "linkedin"],
    )
    registry = FakeRegistry(
        {
            "freework": ScrapeScenario(offers=[offer("fw-1")]),
            "linkedin": ScrapeScenario(error=requests.Timeout("token=secret-value")),
        }
    )

    run_id = SyncService(session, registry=registry).run(saved_search.id)

    run = SyncRunRepository(session).get(run_id)
    assert run is not None
    assert run.status == "partial"
    results = source_results(session, run_id)
    assert results["freework"].status == "succeeded"
    assert (results["freework"].offers_seen, results["freework"].offers_persisted) == (
        1,
        1,
    )
    assert results["linkedin"].status == "failed"
    assert "secret-value" not in (results["linkedin"].error_message or "")
    assert session.scalar(select(func.count(CanonicalJob.pk))) == 1
    assert session.scalar(select(func.count(SearchListing.pk))) == 1
    assert registry.created == ["freework", "linkedin"]
    assert all(scraper.closed for scraper in registry.instances)


def test_sync_service_calls_injected_duplicate_classifier(session: Session) -> None:
    saved_search = SavedSearchRepository(session).create(
        name="Python",
        criteria=SearchCriteria(keywords=["python"]),
        sources=["freework", "linkedin"],
    )
    registry = FakeRegistry(
        {
            "freework": ScrapeScenario(offers=[offer("fw-1")]),
            "linkedin": ScrapeScenario(offers=[offer("li-1", source="linkedin")]),
        }
    )
    classified: list[tuple[CanonicalJob, CanonicalJob]] = []

    def classifier(left: CanonicalJob, right: CanonicalJob) -> DuplicateDecision:
        classified.append((left, right))
        return DuplicateDecision("none", 0.0, ("test_classifier",))

    SyncService(session, registry=registry, classifier=classifier).run(saved_search.id)

    assert len(classified) == 1


def test_partial_source_keeps_each_committed_offer_and_closes_scraper(
    session: Session,
) -> None:
    """Fails if a late iterator error loses its durable counts or accepted offers."""
    saved_search = SavedSearchRepository(session).create(
        name="Python",
        criteria=SearchCriteria(keywords=["python"]),
        sources=["freework"],
    )
    registry = FakeRegistry(
        {
            "freework": ScrapeScenario(
                offers=[offer("before-timeout")],
                error=requests.Timeout("https://user:password@example.test"),
            )
        }
    )

    run_id = SyncService(session, registry=registry).run(saved_search.id)

    run = SyncRunRepository(session).get(run_id)
    assert run is not None
    assert run.status == "partial"
    result = source_results(session, run_id)["freework"]
    assert result.status == "partial"
    assert (result.offers_seen, result.offers_persisted) == (1, 1)
    assert "password" not in (result.error_message or "")
    assert session.scalar(select(func.count(CanonicalJob.pk))) == 1
    assert registry.instances[0].closed is True


def test_all_failed_sources_finish_failed_without_hiding_persisted_offers(
    session: Session,
) -> None:
    """Fails if total outage becomes partial or deactivates prior readable data."""
    saved_searches = SavedSearchRepository(session)
    saved_search = saved_searches.create(
        name="Python",
        criteria=SearchCriteria(keywords=["python"]),
        sources=["freework", "linkedin"],
    )
    existing = SourceListing(
        canonical_job_id=1,
        source="freework",
        external_id="existing",
        url="https://example.test/existing",
        title="Existing role",
        company="Globex",
        location="Paris",
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    persisted_job = CanonicalJob(
        title="Existing role",
        normalized_title="existing role",
        company="Globex",
        normalized_company="globex",
        location="Paris",
        normalized_location="paris",
    )
    session.add(persisted_job)
    session.flush()
    existing.canonical_job_id = persisted_job.pk
    session.add_all(
        [
            existing,
            SearchListing(
                saved_search_id=saved_search.pk, canonical_job_id=persisted_job.pk
            ),
        ]
    )
    session.commit()
    registry = FakeRegistry(
        {
            "freework": ScrapeScenario(error=RuntimeError("api_key=local-secret")),
            "linkedin": ScrapeScenario(error=requests.ConnectionError("private")),
        }
    )

    run_id = SyncService(session, registry=registry).run(saved_search.id)

    run = SyncRunRepository(session).get(run_id)
    assert run is not None
    assert run.status == "failed"
    assert {
        source: result.status
        for source, result in source_results(session, run_id).items()
    } == {"freework": "failed", "linkedin": "failed"}
    session.refresh(existing)
    assert existing.active is True
    assert all(
        "secret" not in (result.error_message or "")
        for result in source_results(session, run_id).values()
    )


def test_source_only_retry_never_constructs_other_adapters(session: Session) -> None:
    """Fails if a targeted retry silently repeats healthy or unrelated sources."""
    saved_search = SavedSearchRepository(session).create(
        name="Python",
        criteria=SearchCriteria(keywords=["python"]),
        sources=["freework", "linkedin", "wttj"],
    )
    registry = FakeRegistry(
        {
            "freework": ScrapeScenario(),
            "linkedin": ScrapeScenario(offers=[offer("li-1", source="linkedin")]),
            "wttj": ScrapeScenario(),
        }
    )

    run_id = SyncService(session, registry=registry).run(
        saved_search.id, only_sources={"linkedin"}
    )

    run = SyncRunRepository(session).get(run_id)
    assert run is not None
    assert run.requested_sources == ["linkedin"]
    assert run.status == "succeeded"
    assert registry.created == ["linkedin"]
    assert registry.instances[0].criteria_seen[0].keywords == ["python"]
    assert set(source_results(session, run_id)) == {"linkedin"}


def test_close_failure_is_isolated_and_sanitized(session: Session) -> None:
    """Fails if cleanup is skipped or a close exception escapes the source boundary."""
    saved_search = SavedSearchRepository(session).create(
        name="Python",
        criteria=SearchCriteria(keywords=["python"]),
        sources=["freework", "linkedin"],
    )
    registry = FakeRegistry(
        {
            "freework": ScrapeScenario(
                offers=[offer("kept")], close_error=RuntimeError("token=close-secret")
            ),
            "linkedin": ScrapeScenario(
                offers=[offer("li", source="linkedin", company="Globex")]
            ),
        }
    )

    run_id = SyncService(session, registry=registry).run(saved_search.id)

    run = SyncRunRepository(session).get(run_id)
    assert run is not None
    assert run.status == "partial"
    results = source_results(session, run_id)
    assert results["freework"].status == "partial"
    assert "close-secret" not in (results["freework"].error_message or "")
    assert results["linkedin"].status == "succeeded"
    assert all(scraper.closed for scraper in registry.instances)
    assert session.scalar(select(func.count(CanonicalJob.pk))) == 2


def test_confirmed_duplicates_merge_and_preserve_both_source_listings(
    session: Session,
) -> None:
    """Fails if a confirmed cross-source pair stays split or loses source/search links."""
    saved_search = SavedSearchRepository(session).create(
        name="Python",
        criteria=SearchCriteria(keywords=["python"]),
        sources=["freework", "linkedin"],
    )
    registry = FakeRegistry(
        {
            "freework": ScrapeScenario(offers=[offer("fw")]),
            "linkedin": ScrapeScenario(
                offers=[offer("li", source="linkedin", company="ACME")]
            ),
        }
    )

    first_run_id = SyncService(session, registry=registry).run(saved_search.id)
    second_run_id = SyncService(session, registry=registry).run(saved_search.id)

    assert SyncRunRepository(session).get(first_run_id).status == "succeeded"  # type: ignore[union-attr]
    assert SyncRunRepository(session).get(second_run_id).status == "succeeded"  # type: ignore[union-attr]
    assert session.scalar(select(func.count(CanonicalJob.pk))) == 1
    assert session.scalar(select(func.count(SourceListing.pk))) == 2
    assert session.scalar(select(func.count(SearchListing.pk))) == 1
    assert session.scalar(select(func.count(DuplicateRelation.pk))) == 0


def test_possible_duplicate_relation_is_ordered_and_idempotent_across_reruns(
    session: Session,
) -> None:
    """Fails if reciprocal possible matches create two rows or duplicate on rerun."""
    saved_search = SavedSearchRepository(session).create(
        name="Python",
        criteria=SearchCriteria(keywords=["python"]),
        sources=["freework", "linkedin"],
    )
    registry = FakeRegistry(
        {
            "freework": ScrapeScenario(
                offers=[offer("fw", title="Développeur Python")]
            ),
            "linkedin": ScrapeScenario(
                offers=[
                    offer(
                        "li",
                        source="linkedin",
                        title="Développeur Python Backend",
                    )
                ]
            ),
        }
    )

    SyncService(session, registry=registry).run(saved_search.id)
    first_relation = session.scalar(select(DuplicateRelation))
    assert first_relation is not None
    first_created_at = first_relation.created_at

    SyncService(session, registry=registry).run(saved_search.id)

    relations = list(session.scalars(select(DuplicateRelation)))
    assert len(relations) == 1
    relation = relations[0]
    assert relation.created_at == first_created_at
    assert relation.left_job_id < relation.right_job_id
    assert relation.kind == "possible"
    assert relation.score == pytest.approx(0.8181818181818182)
    assert relation.reasons == [
        "entreprise_identique",
        "lieu_compatible",
        "titre_proche",
    ]


def test_only_complete_scan_inactivates_unseen_listings(session: Session) -> None:
    """Fails if failed, partial, or max-result-truncated scans hide unseen offers."""
    saved_search = SavedSearchRepository(session).create(
        name="Python",
        criteria=SearchCriteria(keywords=["python"]),
        sources=["freework"],
    )
    scenario = ScrapeScenario(offers=[offer("stale")])
    registry = FakeRegistry({"freework": scenario})
    service = SyncService(session, registry=registry)

    service.run(saved_search.id)
    stale = session.scalar(
        select(SourceListing).where(SourceListing.external_id == "stale")
    )
    assert stale is not None
    initial_seen_at = stale.last_seen_at

    scenario.offers = [offer("fresh-during-partial")]
    scenario.error = requests.Timeout("private-timeout")
    partial_run_id = service.run(saved_search.id)
    session.refresh(stale)
    assert source_results(session, partial_run_id)["freework"].status == "partial"
    assert stale.active is True
    assert stale.last_seen_at == initial_seen_at

    scenario.offers = [offer(f"cap-{index}") for index in range(100)]
    scenario.error = None
    truncated_run_id = service.run(saved_search.id)
    session.refresh(stale)
    assert source_results(session, truncated_run_id)["freework"].status == "partial"
    assert stale.active is True

    scenario.offers = [offer("stale")]
    complete_refresh_id = service.run(saved_search.id)
    session.refresh(stale)
    assert (
        source_results(session, complete_refresh_id)["freework"].status == "succeeded"
    )
    assert stale.last_seen_at > initial_seen_at

    scenario.offers = []
    complete_empty_id = service.run(saved_search.id)
    session.refresh(stale)
    assert source_results(session, complete_empty_id)["freework"].status == "succeeded"
    assert stale.active is False


def test_real_adapter_operational_error_cannot_masquerade_as_complete(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fails if a real adapter swallows a timeout and hides a prior listing."""
    saved_search = SavedSearchRepository(session).create(
        name="Python",
        criteria=SearchCriteria(keywords=["python"]),
        sources=["freework"],
    )
    SyncService(
        session,
        registry=FakeRegistry(
            {"freework": ScrapeScenario(offers=[offer("prior-listing")])}
        ),
    ).run(saved_search.id)
    prior = session.scalar(
        select(SourceListing).where(SourceListing.external_id == "prior-listing")
    )
    assert prior is not None

    def raise_timeout(_scraper: FreeWorkScraper, _url: str) -> str:
        raise requests.Timeout("token=real-adapter-secret")

    monkeypatch.setattr(FreeWorkScraper, "_fetch_page", raise_timeout)

    run_id = SyncService(session, registry=ScraperRegistry(Config())).run(
        saved_search.id
    )

    session.refresh(prior)
    result = source_results(session, run_id)["freework"]
    assert result.status == "failed"
    assert "real-adapter-secret" not in (result.error_message or "")
    assert prior.active is True


def test_real_adapter_all_parse_fail_cannot_masquerade_as_complete(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fails if non-empty but unparseable source results inactivate prior data."""
    saved_search = SavedSearchRepository(session).create(
        name="Python",
        criteria=SearchCriteria(keywords=["python"]),
        sources=["freework"],
    )
    SyncService(
        session,
        registry=FakeRegistry(
            {"freework": ScrapeScenario(offers=[offer("prior-parseable")])}
        ),
    ).run(saved_search.id)
    prior = session.scalar(
        select(SourceListing).where(SourceListing.external_id == "prior-parseable")
    )
    assert prior is not None
    monkeypatch.setattr(
        FreeWorkScraper,
        "_fetch_page",
        lambda _scraper, _url: '<div data-job-id="broken"></div>',
    )

    run_id = SyncService(session, registry=ScraperRegistry(Config())).run(
        saved_search.id
    )

    session.refresh(prior)
    assert source_results(session, run_id)["freework"].status == "failed"
    assert prior.active is True


def test_two_searches_must_both_verify_absence_before_global_inactivation(
    session: Session,
) -> None:
    """Fails if the last search to run globally hides a listing seen by another."""
    searches = SavedSearchRepository(session)
    search_a = searches.create(
        name="Python",
        criteria=SearchCriteria(keywords=["python"]),
        sources=["freework"],
    )
    search_b = searches.create(
        name="Backend",
        criteria=SearchCriteria(keywords=["backend"]),
        sources=["freework"],
    )
    scenario = ScrapeScenario(offers=[offer("shared")])
    service = SyncService(session, registry=FakeRegistry({"freework": scenario}))
    service.run(search_a.id)
    service.run(search_b.id)
    shared = session.scalar(
        select(SourceListing).where(SourceListing.external_id == "shared")
    )
    assert shared is not None

    scenario.offers = []
    service.run(search_a.id)
    session.refresh(shared)
    assert shared.active is True

    service.run(search_b.id)
    session.refresh(shared)
    assert shared.active is False


def test_identical_same_source_external_ids_remain_distinct(session: Session) -> None:
    """Fails if cross-source canonicalization merges two vacancies from one source."""
    saved_search = SavedSearchRepository(session).create(
        name="Python",
        criteria=SearchCriteria(keywords=["python"]),
        sources=["freework"],
    )
    registry = FakeRegistry(
        {"freework": ScrapeScenario(offers=[offer("vacancy-1"), offer("vacancy-2")])}
    )

    SyncService(session, registry=registry).run(saved_search.id)

    assert session.scalar(select(func.count(CanonicalJob.pk))) == 2
    assert session.scalar(select(func.count(SourceListing.pk))) == 2
    assert session.scalar(select(func.count(DuplicateRelation.pk))) == 0


def test_cross_source_bridge_never_collapses_two_same_source_vacancies(
    session: Session,
) -> None:
    """Fails if a bridge merge skips rechecking the survivor's expanded sources."""
    saved_search = SavedSearchRepository(session).create(
        name="Python",
        criteria=SearchCriteria(keywords=["python"]),
        sources=["linkedin", "freework"],
    )
    registry = FakeRegistry(
        {
            "linkedin": ScrapeScenario(
                offers=[
                    offer("li-1", source="linkedin"),
                    offer("li-2", source="linkedin"),
                ]
            ),
            "freework": ScrapeScenario(offers=[offer("fw-bridge")]),
        }
    )

    SyncService(session, registry=registry).run(saved_search.id)

    assert session.scalar(select(func.count(CanonicalJob.pk))) == 2
    linkedin_counts = list(
        session.execute(
            select(SourceListing.canonical_job_id, func.count(SourceListing.pk))
            .where(SourceListing.source == "linkedin")
            .group_by(SourceListing.canonical_job_id)
        )
    )
    assert sorted(count for _job_pk, count in linkedin_counts) == [1, 1]
    for relation in session.scalars(select(DuplicateRelation)):
        left_sources = set(
            session.scalars(
                select(SourceListing.source).where(
                    SourceListing.canonical_job_id == relation.left_job_id
                )
            )
        )
        right_sources = set(
            session.scalars(
                select(SourceListing.source).where(
                    SourceListing.canonical_job_id == relation.right_job_id
                )
            )
        )
        assert left_sources.isdisjoint(right_sources)


def test_confirmed_bridge_removes_transferred_possible_same_source_relation(
    session: Session,
) -> None:
    """Fails if a later merge leaves an earlier possible relation source-invalid."""
    saved_search = SavedSearchRepository(session).create(
        name="Python",
        criteria=SearchCriteria(keywords=["python"]),
        sources=["linkedin", "wttj"],
    )
    registry = FakeRegistry(
        {
            "linkedin": ScrapeScenario(
                offers=[
                    offer(
                        "li-possible",
                        source="linkedin",
                        title="Développeur Python Backend",
                    ),
                    offer(
                        "li-confirmed",
                        source="linkedin",
                        title="Développeur Python",
                    ),
                ]
            ),
            "wttj": ScrapeScenario(
                offers=[
                    offer(
                        "wttj-bridge",
                        source="wttj",
                        title="Développeur Python",
                    )
                ]
            ),
        }
    )

    SyncService(session, registry=registry).run(saved_search.id)

    assert session.scalar(select(func.count(CanonicalJob.pk))) == 2
    assert list(session.scalars(select(DuplicateRelation))) == []


def test_company_legal_suffix_reaches_duplicate_classifier(session: Session) -> None:
    """Fails if persisted prefilter keys disagree with Task 3 company normalization."""
    saved_search = SavedSearchRepository(session).create(
        name="Python",
        criteria=SearchCriteria(keywords=["python"]),
        sources=["freework", "linkedin"],
    )
    registry = FakeRegistry(
        {
            "freework": ScrapeScenario(offers=[offer("fw", company="Acme SAS")]),
            "linkedin": ScrapeScenario(
                offers=[offer("li", source="linkedin", company="ACME")]
            ),
        }
    )

    SyncService(session, registry=registry).run(saved_search.id)

    canonical = list(session.scalars(select(CanonicalJob)))
    assert len(canonical) == 1
    assert canonical[0].normalized_company == "acme"


def test_independent_sessions_cannot_regress_last_seen_at(tmp_path: Path) -> None:
    """Fails if a delayed older observation overwrites a newer committed sighting."""
    engine, session_factory = create_engine_and_session(
        f"sqlite:///{tmp_path / 'monotonic.db'}"
    )
    Base.metadata.create_all(engine)
    with session_factory() as setup:
        JobRepository(setup).upsert_listing(offer("race"), seen_at=NOW)
        setup.commit()

    with session_factory() as newer:
        JobRepository(newer).upsert_listing(
            offer("race", title="Newer"), seen_at=NOW.replace(hour=14)
        )
        newer.commit()
    with session_factory() as delayed_older:
        JobRepository(delayed_older).upsert_listing(
            offer("race", title="Older"), seen_at=NOW.replace(hour=13)
        )
        delayed_older.commit()

    with session_factory() as observer:
        listing = observer.scalar(
            select(SourceListing).where(SourceListing.external_id == "race")
        )
        assert listing is not None
        assert listing.last_seen_at == NOW.replace(hour=14)


def test_pending_run_claim_is_atomic_across_sessions(tmp_path: Path) -> None:
    """Fails if two workers can both transition the same pending run to running."""
    engine, session_factory = create_engine_and_session(
        f"sqlite:///{tmp_path / 'claim.db'}"
    )
    Base.metadata.create_all(engine)
    with session_factory() as setup:
        saved_search = SavedSearchRepository(setup).create(
            name="Python",
            criteria=SearchCriteria(keywords=["python"]),
            sources=["freework"],
        )
        run_id = (
            SyncRunRepository(setup)
            .start(saved_search.id, requested_sources=["freework"])
            .id
        )
        setup.commit()

    with session_factory() as first, session_factory() as second:
        assert SyncRunRepository(first).claim_pending(run_id) is not None
        first.commit()
        assert SyncRunRepository(second).claim_pending(run_id) is None
        second.rollback()


def test_registry_rejects_disabled_source_and_passes_transport_controls() -> None:
    """Fails if enabled, timeout, or retry configuration is ignored."""
    disabled = ScraperRegistry(Config(freework=FreeWorkConfig(enabled=False)))
    with pytest.raises(ValueError, match="désactivée"):
        disabled.create("freework")

    configured = ScraperRegistry(
        Config(freework=FreeWorkConfig(timeout=17, max_retries=2))
    ).create("freework")
    try:
        assert configured.config["timeout"] == 17
        assert configured.config["max_retries"] == 2
    finally:
        configured.close()


def test_offer_and_progress_commits_are_visible_from_another_session(
    tmp_path: Path,
) -> None:
    """Fails if repository flushes remain hidden until the whole source finishes."""
    engine, session_factory = create_engine_and_session(
        f"sqlite:///{tmp_path / 'observable.db'}"
    )
    Base.metadata.create_all(engine)
    observations: list[tuple[int, int]] = []
    with session_factory() as writer, session_factory() as observer:
        saved_search = SavedSearchRepository(writer).create(
            name="Python",
            criteria=SearchCriteria(keywords=["python"]),
            sources=["freework"],
        )

        def observe_committed_progress() -> None:
            observer.expire_all()
            job_count = observer.scalar(select(func.count(CanonicalJob.pk))) or 0
            progress = observer.scalar(select(SourceSyncResult.offers_persisted)) or 0
            observations.append((job_count, progress))

        registry = FakeRegistry(
            {
                "freework": ScrapeScenario(
                    offers=[offer("visible")], after_yield=observe_committed_progress
                )
            }
        )

        service = SyncService(writer, registry=registry)
        commit_snapshots: list[tuple[int, int]] = []

        def observe_every_commit(_session: Session) -> None:
            observer.expire_all()
            job_count = observer.scalar(select(func.count(CanonicalJob.pk))) or 0
            progress = observer.scalar(select(SourceSyncResult.offers_persisted)) or 0
            observer.rollback()
            if job_count:
                commit_snapshots.append((job_count, progress))

        event.listen(writer, "after_commit", observe_every_commit)
        run_id = service.create_run(saved_search.id)
        pending = SyncRunRepository(observer).get(run_id)
        assert pending is not None
        assert pending.status == "pending"
        assert pending.requested_sources == ["freework"]

        service.execute(run_id)

        observer.expire_all()
        finished = SyncRunRepository(observer).get(run_id)
        assert finished is not None
        assert finished.status == "succeeded"
        event.remove(writer, "after_commit", observe_every_commit)

    assert observations == [(1, 1)]
    assert (1, 0) not in commit_snapshots


def test_registry_builds_all_six_supported_scrapers() -> None:
    """Fails if a documented source is absent or routed to the wrong adapter."""
    registry = ScraperRegistry(Config())

    expected_types = {
        "linkedin": LinkedInScraper,
        "hellowork": HelloWorkScraper,
        "francetravail": FranceTravailScraper,
        "wttj": WTTJScraper,
        "adzuna": AdzunaScraper,
        "freework": FreeWorkScraper,
    }
    created = {source: registry.create(source) for source in expected_types}
    try:
        assert {
            source: type(scraper) for source, scraper in created.items()
        } == expected_types
        assert created["freework"].config["delay"] == 2.0
        assert all(
            scraper.config["propagate_search_errors"] is True
            for scraper in created.values()
        )
    finally:
        for scraper in created.values():
            scraper.close()

    with pytest.raises(ValueError, match="inconnue"):
        registry.create("indeed")
