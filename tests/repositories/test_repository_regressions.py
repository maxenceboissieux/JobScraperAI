from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

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

NOW = datetime(2026, 8, 3, 12, tzinfo=timezone.utc)


@pytest.fixture
def session(tmp_path: Path) -> Session:
    engine, factory = create_engine_and_session(f"sqlite:///{tmp_path / 'jobs.db'}")
    Base.metadata.create_all(engine)
    with factory() as database_session:
        yield database_session


def offer(
    external_id: str,
    *,
    source: str = "freework",
    title: str = "Python engineer",
    company: str = "Acme",
    location: str = "Paris",
    description: str | None = "Detailed description",
    salary_min: float | None = 60_000,
    salary_max: float | None = 75_000,
    salary_currency: str = "EUR",
    posted_at: datetime | None = NOW,
    skills: list[str] | None = None,
    benefits: list[str] | None = None,
) -> JobOffer:
    return JobOffer(
        id=external_id,
        source=source,
        url=f"https://example.test/{source}/{external_id}",
        title=title,
        company=company,
        location=location,
        description=description,
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=salary_currency,
        posted_at=posted_at,
        skills=skills or [],
        benefits=benefits or [],
    )


def saved_search(session: Session, name: str = "Python") -> str:
    return (
        SavedSearchRepository(session)
        .create(
            name=name,
            criteria=SearchCriteria(keywords=["python"]),
            sources=["freework", "wttj"],
        )
        .id
    )


def test_sparse_listing_refresh_preserves_fetched_detail_cache(
    session: Session,
) -> None:
    """Fails if a sparse search-card refresh clears cached detail fields."""
    jobs = JobRepository(session)
    detailed = jobs.upsert_listing(
        offer("1", skills=["Python", "SQL"], benefits=["Remote budget"]), seen_at=NOW
    )
    detailed.details_fetched_at = NOW
    session.flush()
    jobs.stamp_detail_groups(
        detailed.id,
        groups=["description", "salary", "skills", "benefits"],
        fetched_at=NOW,
    )

    refreshed = jobs.upsert_listing(
        offer(
            "1",
            title="Python engineer (updated)",
            description=None,
            salary_min=None,
            salary_max=None,
            skills=[],
            benefits=[],
        ),
        seen_at=NOW + timedelta(days=1),
    )

    assert refreshed.description == "Detailed description"
    assert refreshed.salary_min == 60_000
    assert refreshed.salary_max == 75_000
    assert refreshed.skills == ["Python", "SQL"]
    assert refreshed.benefits == ["Remote budget"]
    assert refreshed.details_fetched_at == NOW
    assert refreshed.detail_provenance == {
        "description": NOW.isoformat(),
        "salary": NOW.isoformat(),
        "skills": NOW.isoformat(),
        "benefits": NOW.isoformat(),
    }
    assert refreshed.title == "Python engineer (updated)"


def test_merge_canonical_jobs_preserves_listings_searches_detail_and_relations(
    session: Session,
) -> None:
    """Fails if confirmed merging loses source links, search links, cached detail, or relations."""
    jobs = JobRepository(session)
    first_search = saved_search(session, "First")
    second_search = saved_search(session, "Second")
    sparse = jobs.upsert_listing(
        offer(
            "1",
            description=None,
            salary_min=None,
            salary_max=None,
            skills=[],
            benefits=[],
        ),
        seen_at=NOW,
    )
    detailed = jobs.upsert_listing(
        offer(
            "2",
            source="wttj",
            description="Fetched from WTTJ",
            skills=["Python", "FastAPI"],
            benefits=["Training"],
        ),
        seen_at=NOW,
    )
    detailed.details_fetched_at = NOW
    third = jobs.upsert_listing(offer("3", source="linkedin"), seen_at=NOW)
    jobs.attach_search(first_search, sparse.id)
    jobs.attach_search(first_search, detailed.id)
    jobs.attach_search(second_search, detailed.id)
    session.add(
        DuplicateRelation(
            left_job_id=min(detailed.pk, third.pk),
            right_job_id=max(detailed.pk, third.pk),
            kind="possible",
            score=0.7,
        )
    )
    session.flush()

    merged = jobs.merge_canonical_jobs(sparse.id, detailed.id)

    assert merged.id == sparse.id
    assert jobs.get_job(detailed.id) is None
    assert merged.description == "Fetched from WTTJ"
    assert merged.skills == ["Python", "FastAPI"]
    assert merged.details_fetched_at == NOW
    assert (
        session.scalar(
            select(func.count())
            .select_from(SourceListing)
            .where(SourceListing.canonical_job_id == merged.pk)
        )
        == 2
    )
    assert (
        session.scalar(
            select(func.count())
            .select_from(SearchListing)
            .where(SearchListing.canonical_job_id == merged.pk)
        )
        == 2
    )
    relation = session.scalar(select(DuplicateRelation))
    assert relation is not None
    assert {relation.left_job_id, relation.right_job_id} == {merged.pk, third.pk}


def test_merge_uses_the_newest_atomic_salary_snapshot_without_currency_mix(
    session: Session,
) -> None:
    """Fails if a merge keeps one currency's minimum with another's maximum."""
    jobs = JobRepository(session)
    usd_partial = jobs.upsert_listing(
        offer(
            "usd",
            salary_min=110_000,
            salary_max=None,
            salary_currency="USD",
        ),
        seen_at=NOW,
    )
    eur_complete = jobs.upsert_listing(
        offer(
            "eur",
            source="wttj",
            salary_min=75_000,
            salary_max=90_000,
            salary_currency="EUR",
        ),
        seen_at=NOW,
    )
    usd_partial.details_fetched_at = NOW
    eur_complete.details_fetched_at = NOW + timedelta(minutes=1)
    session.flush()

    merged = jobs.merge_canonical_jobs(usd_partial.id, eur_complete.id)

    assert (merged.salary_min, merged.salary_max, merged.salary_currency) == (
        75_000,
        90_000,
        "EUR",
    )
    assert merged.details_fetched_at == NOW + timedelta(minutes=1)


def test_merge_unions_lists_and_uses_newer_scalar_cache_in_either_direction(
    session: Session,
) -> None:
    """Fails if merge loses complementary list data or lets an older detail overwrite newer data."""
    jobs = JobRepository(session)
    older = jobs.upsert_listing(
        offer(
            "older",
            description="Older cached description",
            skills=["Python", "SQL"],
            benefits=["Remote", "Training"],
        ),
        seen_at=NOW,
    )
    newer = jobs.upsert_listing(
        offer(
            "newer",
            source="wttj",
            description="Newer cached description",
            skills=["SQL", "FastAPI"],
            benefits=["Training", "Health"],
        ),
        seen_at=NOW,
    )
    older.details_fetched_at = NOW
    newer.details_fetched_at = NOW + timedelta(minutes=2)
    session.flush()

    merged = jobs.merge_canonical_jobs(older.id, newer.id)

    assert merged.description == "Newer cached description"
    assert merged.skills == ["Python", "SQL", "FastAPI"]
    assert merged.benefits == ["Remote", "Training", "Health"]
    assert merged.details_fetched_at == NOW + timedelta(minutes=2)

    newer_survivor = jobs.upsert_listing(
        offer("survivor", description="Newest survivor detail"), seen_at=NOW
    )
    older_merge = jobs.upsert_listing(
        offer(
            "merged-old",
            source="linkedin",
            description="Older merge detail",
        ),
        seen_at=NOW,
    )
    newer_survivor.details_fetched_at = NOW + timedelta(minutes=4)
    older_merge.details_fetched_at = NOW + timedelta(minutes=3)
    session.flush()

    kept = jobs.merge_canonical_jobs(newer_survivor.id, older_merge.id)

    assert kept.description == "Newest survivor detail"
    assert kept.details_fetched_at == NOW + timedelta(minutes=4)


def test_chained_merge_uses_group_provenance_not_unrelated_global_cache_time(
    session: Session,
) -> None:
    """Fails if a newer skills cache blocks newer salary or description snapshots."""
    jobs = JobRepository(session)
    survivor = jobs.upsert_listing(
        offer(
            "survivor-sparse",
            description=None,
            salary_min=None,
            salary_max=None,
            skills=[],
            benefits=[],
        ),
        seen_at=NOW,
    )
    first_detail = jobs.upsert_listing(
        offer(
            "first-detail",
            source="wttj",
            description="Description at T2",
            salary_min=70_000,
            salary_max=90_000,
            salary_currency="EUR",
            skills=["Python"],
        ),
        seen_at=NOW,
    )
    later_salary = jobs.upsert_listing(
        offer(
            "later-salary",
            source="linkedin",
            description="Description at T3",
            salary_min=120_000,
            salary_max=None,
            salary_currency="USD",
        ),
        seen_at=NOW,
    )
    jobs.stamp_detail_groups(
        first_detail.id,
        groups=["description", "salary"],
        fetched_at=NOW + timedelta(minutes=2),
    )
    jobs.stamp_detail_groups(
        first_detail.id,
        groups=["skills"],
        fetched_at=NOW + timedelta(minutes=4),
    )
    jobs.stamp_detail_groups(
        later_salary.id,
        groups=["description", "salary"],
        fetched_at=NOW + timedelta(minutes=3),
    )

    after_first_merge = jobs.merge_canonical_jobs(survivor.id, first_detail.id)
    merged = jobs.merge_canonical_jobs(after_first_merge.id, later_salary.id)

    assert merged.description == "Description at T3"
    assert (merged.salary_min, merged.salary_max, merged.salary_currency) == (
        120_000,
        None,
        "USD",
    )
    assert merged.detail_provenance == {
        "description": (NOW + timedelta(minutes=3)).isoformat(),
        "salary": (NOW + timedelta(minutes=3)).isoformat(),
        "skills": (NOW + timedelta(minutes=4)).isoformat(),
    }
    assert merged.details_fetched_at == NOW + timedelta(minutes=4)


def test_legacy_provenance_survives_partial_stamp_reload_and_chained_merge(
    session: Session,
) -> None:
    """Fails if a partial stamp makes an unstamped legacy group globally newest."""
    jobs = JobRepository(session)
    legacy = jobs.upsert_listing(
        offer(
            "legacy-description",
            description="Legacy description at T2",
            salary_min=None,
            salary_max=None,
        ),
        seen_at=NOW,
    )
    legacy.details_fetched_at = NOW + timedelta(minutes=2)
    session.flush()

    legacy.salary_min = 80_000
    legacy.salary_max = 100_000
    legacy.salary_currency = "EUR"
    jobs.stamp_detail_groups(
        legacy.id,
        groups=["salary"],
        fetched_at=NOW + timedelta(minutes=4),
    )
    legacy_id = legacy.id
    session.commit()
    session.expunge_all()

    reloaded = jobs.get_job(legacy_id)
    assert reloaded is not None
    assert reloaded.detail_provenance == {
        "description": (NOW + timedelta(minutes=2)).isoformat(),
        "salary": (NOW + timedelta(minutes=4)).isoformat(),
    }

    description_at_t3 = jobs.upsert_listing(
        offer(
            "description-at-t3",
            source="wttj",
            description="Description at T3",
            salary_min=None,
            salary_max=None,
        ),
        seen_at=NOW,
    )
    jobs.stamp_detail_groups(
        description_at_t3.id,
        groups=["description"],
        fetched_at=NOW + timedelta(minutes=3),
    )
    jobs.merge_canonical_jobs(reloaded.id, description_at_t3.id)
    session.commit()
    session.expunge_all()

    merged = jobs.get_job(legacy_id)
    assert merged is not None
    assert merged.description == "Description at T3"
    assert (merged.salary_min, merged.salary_max, merged.salary_currency) == (
        80_000,
        100_000,
        "EUR",
    )
    assert merged.detail_provenance == {
        "description": (NOW + timedelta(minutes=3)).isoformat(),
        "salary": (NOW + timedelta(minutes=4)).isoformat(),
    }
    assert merged.details_fetched_at == NOW + timedelta(minutes=4)


def test_duplicate_state_distinguishes_confirmed_possible_and_none(
    session: Session,
) -> None:
    """Fails if the three public duplicate-state categories overlap or disappear."""
    jobs = JobRepository(session)
    confirmed = jobs.upsert_listing(offer("1"), seen_at=NOW)
    confirmation_source = jobs.upsert_listing(offer("2", source="wttj"), seen_at=NOW)
    jobs.merge_canonical_jobs(confirmed.id, confirmation_source.id)
    possible_left = jobs.upsert_listing(offer("3", source="linkedin"), seen_at=NOW)
    possible_right = jobs.upsert_listing(offer("4", source="adzuna"), seen_at=NOW)
    none = jobs.upsert_listing(offer("5", source="hellowork"), seen_at=NOW)
    session.add(
        DuplicateRelation(
            left_job_id=min(possible_left.pk, possible_right.pk),
            right_job_id=max(possible_left.pk, possible_right.pk),
            kind="possible",
            score=0.7,
        )
    )
    session.flush()

    assert [job.id for job in jobs.list_jobs(duplicate_state="confirmed")] == [
        confirmed.id
    ]
    assert {job.id for job in jobs.list_jobs(duplicate_state="possible")} == {
        possible_left.id,
        possible_right.id,
    }
    assert [job.id for job in jobs.list_jobs(duplicate_state="none")] == [none.id]


def test_date_and_relevance_sorts_have_deterministic_public_behavior(
    session: Session,
) -> None:
    """Fails if supported public sort values raise or rank stale/unrelated jobs first."""
    jobs = JobRepository(session)
    title_match = jobs.upsert_listing(
        offer("1", title="Python developer", posted_at=NOW - timedelta(days=1)),
        seen_at=NOW,
    )
    description_match = jobs.upsert_listing(
        offer(
            "2",
            title="Backend developer",
            description="Python Python platform work",
            posted_at=NOW,
        ),
        seen_at=NOW,
    )
    undated = jobs.upsert_listing(
        offer("3", title="Graduate role", description="Python", posted_at=None),
        seen_at=NOW,
    )

    assert [job.id for job in jobs.list_jobs(sort="date")] == [
        description_match.id,
        title_match.id,
        undated.id,
    ]
    assert [job.id for job in jobs.list_jobs(query="python", sort="relevance")] == [
        title_match.id,
        description_match.id,
        undated.id,
    ]
    assert [job.id for job in jobs.list_jobs(sort="relevance")] == [
        description_match.id,
        title_match.id,
        undated.id,
    ]


def test_sync_retry_clears_failure_state_and_finish_is_idempotent(
    session: Session,
) -> None:
    """Fails if retrying keeps stale source failure data or moves an existing finish time."""
    search_id = saved_search(session)
    sync_runs = SyncRunRepository(session)
    run = sync_runs.start(search_id, requested_sources=["freework"])
    assert run.status == "pending"
    assert run.started_at is None

    failed = sync_runs.record_source_result(
        run.id,
        "freework",
        status="failed",
        error_message="Timeout",
        finished_at=NOW,
    )
    retried = sync_runs.record_source_result(
        run.id,
        "freework",
        status="running",
        started_at=NOW + timedelta(minutes=1),
    )
    assert retried.error_message is None
    assert retried.finished_at is None
    succeeded = sync_runs.record_source_result(
        run.id,
        "freework",
        status="succeeded",
        offers_seen=3,
        offers_persisted=2,
        finished_at=NOW + timedelta(minutes=2),
    )
    finished = sync_runs.finish(
        run.id, status="succeeded", finished_at=NOW + timedelta(minutes=2)
    )
    repeated = sync_runs.finish(run.id, status="succeeded")

    assert failed.id == retried.id == succeeded.id
    assert succeeded.error_message is None
    assert finished is not None
    assert repeated is not None
    assert repeated.finished_at == NOW + timedelta(minutes=2)


def test_latest_sync_run_can_be_scoped_to_one_saved_search(
    session: Session,
) -> None:
    """Fails if another search's newer run hides the requested search's run."""
    first_search_id = saved_search(session, "First")
    second_search_id = saved_search(session, "Second")
    sync_runs = SyncRunRepository(session)
    first_run = sync_runs.start(
        first_search_id,
        requested_sources=["freework"],
        status="failed",
    )
    second_run = sync_runs.start(
        second_search_id,
        requested_sources=["wttj"],
        status="pending",
    )

    assert sync_runs.latest() == second_run
    assert sync_runs.latest(saved_search_id=first_search_id) == first_run
    assert (
        sync_runs.latest(
            saved_search_id="00000000-0000-0000-0000-000000000000"
        )
        is None
    )


def test_file_sqlite_concurrency_keeps_listing_search_and_result_uniques(
    tmp_path: Path,
) -> None:
    """Fails if independent writers race past any repository unique constraint."""
    engine, factory = create_engine_and_session(f"sqlite:///{tmp_path / 'shared.db'}")
    Base.metadata.create_all(engine)
    with factory.begin() as session:
        search_id = saved_search(session)
        run_id = (
            SyncRunRepository(session)
            .start(search_id, requested_sources=["freework"])
            .id
        )

    def concurrently(operation: object) -> list[object]:
        barrier = Barrier(2)

        def invoke() -> object:
            barrier.wait()
            with factory.begin() as session:
                return operation(session)  # type: ignore[operator]

        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(lambda _unused: invoke(), range(2)))

    listing_ids = concurrently(
        lambda session: JobRepository(session)
        .upsert_listing(offer("same"), seen_at=NOW)
        .id
    )
    job_id = str(listing_ids[0])
    concurrently(
        lambda session: JobRepository(session).attach_search(search_id, job_id)
    )
    result_ids = concurrently(
        lambda session: SyncRunRepository(session)
        .record_source_result(run_id, "freework", status="running")
        .id
    )

    with factory() as session:
        assert len(set(listing_ids)) == 1
        assert len(set(result_ids)) == 1
        assert session.scalar(select(func.count()).select_from(CanonicalJob)) == 1
        assert session.scalar(select(func.count()).select_from(SourceListing)) == 1
        assert session.scalar(select(func.count()).select_from(SearchListing)) == 1
        assert session.scalar(select(func.count()).select_from(SourceSyncResult)) == 1
