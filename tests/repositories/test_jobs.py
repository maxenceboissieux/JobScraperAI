from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from jobscraper.db.base import Base
from jobscraper.db.models import DuplicateRelation
from jobscraper.db.session import create_engine_and_session
from jobscraper.models.job import JobOffer, SearchCriteria
from jobscraper.repositories.jobs import JobRepository
from jobscraper.repositories.saved_searches import SavedSearchRepository
from jobscraper.repositories.sync_runs import SyncRunRepository

NOW = datetime(2026, 8, 3, 12, tzinfo=timezone.utc)


@pytest.fixture
def session(tmp_path: Path) -> Session:
    engine, session_factory = create_engine_and_session(
        f"sqlite:///{tmp_path / 'jobs.db'}"
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
    posted_at: datetime | None = NOW,
    contract_type: str | None = "cdi",
    experience_level: str | None = "senior",
    remote: bool | None = True,
    salary_min: float | None = 60_000,
    salary_max: float | None = 75_000,
    skills: list[str] | None = None,
) -> JobOffer:
    return JobOffer(
        id=external_id,
        source=source,
        url=f"https://example.test/jobs/{source}/{external_id}",
        title=title,
        company=company,
        location=location,
        description=f"{title} at {company}",
        posted_at=posted_at,
        contract_type=contract_type,
        experience_level=experience_level,
        remote=remote,
        salary_min=salary_min,
        salary_max=salary_max,
        skills=skills or ["Python"],
    )


def test_upsert_listing_is_idempotent_and_refreshes_the_canonical_offer(
    session: Session,
) -> None:
    """Fails if source/external-ID upserts duplicate a job or leave stale offer fields."""
    repository = JobRepository(session)
    first = repository.upsert_listing(offer("42"), seen_at=NOW)
    second = repository.upsert_listing(
        offer("42", title="Titre corrigé"), seen_at=NOW + timedelta(hours=1)
    )

    assert first.id == second.id
    loaded = repository.get_job(first.id)
    assert loaded is not None
    assert loaded.title == "Titre corrigé"
    listing = repository.get_listing(first.id)
    assert listing is not None
    assert listing.title == "Titre corrigé"
    assert listing.last_seen_at == NOW + timedelta(hours=1)


def test_mark_viewed_persists_only_the_first_timestamp(session: Session) -> None:
    jobs = JobRepository(session)
    job = jobs.upsert_listing(offer("viewed-once"), seen_at=NOW)
    first_view = NOW + timedelta(minutes=1)
    later_view = NOW + timedelta(minutes=5)

    first = jobs.mark_viewed(job.id, viewed_at=first_view)
    second = jobs.mark_viewed(job.id, viewed_at=later_view)

    assert first.viewed_at == first_view
    assert second.viewed_at == first_view
    with pytest.raises(LookupError, match="Canonical job does not exist"):
        jobs.mark_viewed("00000000-0000-0000-0000-000000000000")


def test_competing_mark_viewed_requests_preserve_the_first_commit(
    tmp_path: Path,
) -> None:
    engine, session_factory = create_engine_and_session(
        f"sqlite:///{tmp_path / 'viewed-race.db'}"
    )
    Base.metadata.create_all(engine)
    with session_factory.begin() as seed_session:
        seeded = JobRepository(seed_session).upsert_listing(
            offer("viewed-race"), seen_at=NOW
        )
        job_id = seeded.id

    first_view = NOW + timedelta(minutes=1)
    later_view = NOW + timedelta(minutes=2)
    with session_factory() as first_session, session_factory() as second_session:
        assert JobRepository(second_session).get_job(job_id) is not None
        JobRepository(first_session).mark_viewed(job_id, viewed_at=first_view)
        first_session.commit()
        result = JobRepository(second_session).mark_viewed(job_id, viewed_at=later_view)
        second_session.commit()

    with session_factory() as verification_session:
        persisted = JobRepository(verification_session).get_job(job_id)
        assert persisted is not None
        assert persisted.viewed_at == first_view


def test_unseen_only_excludes_viewed_jobs_before_pagination(session: Session) -> None:
    jobs = JobRepository(session)
    viewed = jobs.upsert_listing(offer("viewed-filter", posted_at=NOW), seen_at=NOW)
    unseen = jobs.upsert_listing(
        offer("unseen-filter", posted_at=NOW - timedelta(hours=1)), seen_at=NOW
    )
    jobs.mark_viewed(viewed.id, viewed_at=NOW + timedelta(minutes=1))

    assert [job.id for job in jobs.list_jobs(unseen_only=True, limit=1)] == [unseen.id]
    assert {job.id for job in jobs.list_jobs(unseen_only=False)} == {
        viewed.id,
        unseen.id,
    }


def test_job_filters_association_and_pagination_use_persisted_offers(
    session: Session,
) -> None:
    """Fails if any public filter drops, includes, or orders the wrong canonical job."""
    jobs = JobRepository(session)
    searches = SavedSearchRepository(session)
    saved_search = searches.create(
        name="Python",
        criteria=SearchCriteria(keywords=["python"]),
        sources=["freework"],
    )
    matching = jobs.upsert_listing(
        offer("1", posted_at=NOW - timedelta(days=1)), seen_at=NOW
    )
    other = jobs.upsert_listing(
        offer(
            "2",
            source="wttj",
            title="Java platform engineer",
            company="Globex",
            location="Lyon",
            posted_at=NOW - timedelta(days=2),
            contract_type="cdd",
            experience_level="junior",
            remote=False,
            salary_min=35_000,
            salary_max=45_000,
            skills=["Java", "Kotlin"],
        ),
        seen_at=NOW,
    )
    undated = jobs.upsert_listing(
        offer("3", company="No date Inc", posted_at=None, salary_max=50_000),
        seen_at=NOW,
    )
    newer = jobs.upsert_listing(
        offer("4", title="Python staff engineer", posted_at=NOW), seen_at=NOW
    )
    jobs.attach_search(saved_search.id, matching.id)
    session.add(
        DuplicateRelation(
            left_job_id=min(matching.pk, newer.pk),
            right_job_id=max(matching.pk, newer.pk),
            kind="possible",
            score=0.8,
        )
    )
    session.flush()

    assert [job.id for job in jobs.list_jobs(saved_search_id=saved_search.id)] == [
        matching.id
    ]
    assert [job.id for job in jobs.list_jobs(posted_since=NOW - timedelta(days=3))] == [
        newer.id,
        matching.id,
        other.id,
    ]
    assert [job.id for job in jobs.list_jobs(query="staff")] == [newer.id]
    assert [job.id for job in jobs.list_jobs(locations=["lyon"])] == [other.id]
    assert [job.id for job in jobs.list_jobs(contracts=["cdd"])] == [other.id]
    assert [job.id for job in jobs.list_jobs(remote=False)] == [other.id]
    assert [job.id for job in jobs.list_jobs(experience=["junior"])] == [other.id]
    assert [job.id for job in jobs.list_jobs(salary_min=70_000)] == [
        newer.id,
        matching.id,
    ]
    assert [job.id for job in jobs.list_jobs(companies=["globex"])] == [other.id]
    assert [job.id for job in jobs.list_jobs(sources=["wttj"])] == [other.id]
    assert {job.id for job in jobs.list_jobs(sources=["freework", "wttj"])} == {
        matching.id,
        other.id,
        undated.id,
        newer.id,
    }
    assert [job.id for job in jobs.list_jobs(skills=["kotlin"])] == [other.id]
    assert {job.id for job in jobs.list_jobs(duplicate_state="duplicate")} == {
        matching.id,
        newer.id,
    }
    assert {job.id for job in jobs.list_jobs(duplicate_state="unique")} == {
        other.id,
        undated.id,
    }
    assert [
        job.id for job in jobs.list_jobs(sort="posted_at_asc", limit=2, offset=1)
    ] == [matching.id, newer.id]


def test_location_filter_expands_center_alias_and_keeps_member_filter_municipal(
    session: Session,
) -> None:
    jobs = JobRepository(session)
    lyon = jobs.upsert_listing(offer("lyon", location="Lyon - 69"), seen_at=NOW)
    villeurbanne = jobs.upsert_listing(
        offer("villeurbanne", location="Villeurbanne"), seen_at=NOW
    )
    bron = jobs.upsert_listing(offer("bron", location="Bron"), seen_at=NOW)
    outside = jobs.upsert_listing(
        offer("outside", location="Villefranche-sur-Saône"), seen_at=NOW
    )

    assert {job.id for job in jobs.list_jobs(locations=["Lyon"])} == {
        lyon.id,
        villeurbanne.id,
        bron.id,
    }
    assert [job.id for job in jobs.list_jobs(locations=["Villeurbanne"])] == [
        villeurbanne.id
    ]
    assert outside.id not in {
        job.id for job in jobs.list_jobs(locations=["Métropole de Lyon"])
    }


def test_multiple_location_filters_keep_or_semantics(session: Session) -> None:
    jobs = JobRepository(session)
    bron = jobs.upsert_listing(offer("bron-or", location="Bron"), seen_at=NOW)
    rennes = jobs.upsert_listing(offer("rennes-or", location="Rennes"), seen_at=NOW)
    excluded = jobs.upsert_listing(offer("dijon-or", location="Dijon"), seen_at=NOW)

    result = jobs.list_jobs(locations=["Lyon", "Rennes"])

    assert {job.id for job in result} == {bron.id, rennes.id}
    assert excluded.id not in {job.id for job in result}


def test_source_sync_results_are_updated_without_hiding_existing_jobs(
    session: Session,
) -> None:
    """Fails if a failed source result removes readable offers or duplicates its result row."""
    jobs = JobRepository(session)
    saved_searches = SavedSearchRepository(session)
    sync_runs = SyncRunRepository(session)
    saved_search = saved_searches.create(
        name="Python",
        criteria=SearchCriteria(keywords=["python"]),
        sources=["freework"],
    )
    persisted = jobs.upsert_listing(offer("kept"), seen_at=NOW)
    run = sync_runs.start(saved_search.id, requested_sources=["freework"])

    first = sync_runs.record_source_result(
        run.id, "freework", status="running", started_at=NOW
    )
    result = sync_runs.record_source_result(
        run.id,
        "freework",
        status="failed",
        offers_seen=0,
        offers_persisted=0,
        error_message="La source ne répond pas.",
        finished_at=NOW + timedelta(minutes=1),
    )
    finished = sync_runs.finish(
        run.id, status="failed", finished_at=NOW + timedelta(minutes=1)
    )

    assert first.id == result.id
    assert result.status == "failed"
    assert result.error_message == "La source ne répond pas."
    assert finished is not None
    assert finished.status == "failed"
    assert jobs.get_job(persisted.id) is not None
