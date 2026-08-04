from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from jobscraper.db.base import utc_now
from jobscraper.db.models import DuplicateRelation, SourceListing
from jobscraper.models.job import JobOffer, SearchCriteria
from jobscraper.repositories.jobs import JobRepository
from jobscraper.repositories.saved_searches import SavedSearchRepository


def offer(
    external_id: str,
    *,
    source: str = "freework",
    title: str = "Backend Python",
    company: str = "Acme",
    location: str = "Paris",
    posted_at_offset: timedelta | None = timedelta(hours=-2),
) -> JobOffer:
    now = utc_now()
    return JobOffer(
        id=external_id,
        source=source,
        url=f"https://example.test/{source}/{external_id}",
        title=title,
        company=company,
        location=location,
        description=f"Description {title}",
        salary_min=60_000,
        salary_max=80_000,
        contract_type="cdi",
        experience_level="senior",
        remote=True,
        posted_at=None if posted_at_offset is None else now + posted_at_offset,
        skills=["Python", "FastAPI"],
        benefits=["RTT"],
    )


def seed_jobs(session: Session) -> tuple[str, str, str, str]:
    jobs = JobRepository(session)
    searches = SavedSearchRepository(session)
    saved_search = searches.create(
        name="Backend",
        criteria=SearchCriteria(keywords=["backend"]),
        sources=["freework", "linkedin"],
    )
    recent = jobs.upsert_listing(offer("recent"), seen_at=utc_now())
    older = jobs.upsert_listing(
        offer(
            "older",
            source="linkedin",
            title="Legacy Java",
            company="Globex",
            location="Lyon",
            posted_at_offset=timedelta(days=-4),
        ),
        seen_at=utc_now(),
    )
    undated = jobs.upsert_listing(
        offer("undated", title="Undated", posted_at_offset=None), seen_at=utc_now()
    )
    jobs.attach_search(saved_search.id, recent.id)
    jobs.attach_search(saved_search.id, older.id)
    session.add(
        DuplicateRelation(
            left_job_id=min(recent.pk, older.pk),
            right_job_id=max(recent.pk, older.pk),
            kind="possible",
            score=0.71,
            reasons=["titre proche"],
        )
    )
    session.commit()
    return saved_search.id, recent.id, older.id, undated.id


def test_job_cards_apply_period_source_and_saved_search_filters(
    client: TestClient, session: Session
) -> None:
    """Fails if API query aliases do not reach the repository filters."""
    search_id, recent_id, _older_id, _undated_id = seed_jobs(session)

    response = client.get(
        "/api/jobs",
        params=[
            ("savedSearchId", search_id),
            ("period", "3d"),
            ("source", "freework"),
            ("skill", "Python"),
        ],
    )

    assert response.status_code == 200
    assert set(response.json()) == {"items", "total", "limit", "offset"}
    assert response.json()["total"] == 1
    assert [item["id"] for item in response.json()["items"]] == [recent_id]


def test_job_pagination_keeps_total_and_card_links_consistent(
    client: TestClient, session: Session
) -> None:
    """Fails if pagination changes total or duplicate/source links disappear."""
    _search_id, recent_id, older_id, _undated_id = seed_jobs(session)

    first = client.get("/api/jobs", params={"period": "all", "limit": 1})
    second = client.get("/api/jobs", params={"period": "all", "limit": 1, "offset": 1})
    all_items = client.get("/api/jobs", params={"period": "all", "limit": 10})

    assert first.status_code == second.status_code == all_items.status_code == 200
    assert first.json()["total"] == second.json()["total"] == 3
    assert len(first.json()["items"]) == len(second.json()["items"]) == 1
    recent = next(item for item in all_items.json()["items"] if item["id"] == recent_id)
    assert recent["sources"] == [
        {
            "source": "freework",
            "url": "https://example.test/freework/recent",
            "active": True,
        }
    ]
    assert recent["duplicateState"] == "possible"
    assert recent["possibleDuplicates"] == [
        {
            "id": older_id,
            "title": "Legacy Java",
            "company": "Globex",
            "location": "Lyon",
            "score": 0.71,
            "reasons": ["titre proche"],
        }
    ]


def test_multiple_source_job_is_marked_confirmed(
    client: TestClient, session: Session
) -> None:
    """Fails if a merged canonical job is presented as unique."""
    jobs = JobRepository(session)
    job = jobs.upsert_listing(offer("fw-confirmed"), seen_at=utc_now())
    session.add(
        SourceListing(
            canonical_job_id=job.pk,
            source="linkedin",
            external_id="linkedin_10001",
            url="https://www.linkedin.com/jobs/view/10001",
            title=job.title,
            company=job.company,
            location=job.location,
            posted_at=job.posted_at,
            first_seen_at=utc_now(),
            last_seen_at=utc_now(),
        )
    )
    session.commit()

    response = client.get("/api/jobs", params={"period": "all"})

    assert response.status_code == 200
    body = response.json()["items"][0]
    assert body["id"] == job.id
    assert body["duplicateState"] == "confirmed"
    assert [source["source"] for source in body["sources"]] == [
        "freework",
        "linkedin",
    ]


@pytest.mark.parametrize(
    ("params", "expected_status"),
    [
        ({"period": "yesterday"}, 422),
        ({"period": "all", "limit": 0}, 422),
        ({"period": "all", "offset": -1}, 422),
        ({"period": "all", "sort": "random"}, 422),
        ({"period": "all", "duplicateState": "maybe"}, 422),
    ],
)
def test_invalid_job_filters_return_422(
    client: TestClient, params: dict[str, object], expected_status: int
) -> None:
    """Fails if malformed local filters reach repository branches."""
    response = client.get("/api/jobs", params=params)

    assert response.status_code == expected_status


def test_unknown_saved_search_filter_returns_404(client: TestClient) -> None:
    """Fails if a stale selected-search ID is indistinguishable from no results."""
    response = client.get(
        "/api/jobs",
        params={
            "period": "all",
            "savedSearchId": "00000000-0000-0000-0000-000000000000",
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "La recherche enregistrée n’existe pas."}


def test_job_detail_returns_cache_metadata_and_linked_entities(
    client: TestClient, session: Session
) -> None:
    """Fails if detail routing bypasses cache metadata or card relationships."""
    _search_id, recent_id, older_id, _undated_id = seed_jobs(session)
    recent = JobRepository(session).get_job(recent_id)
    assert recent is not None
    recent.details_fetched_at = utc_now()
    recent.detail_provenance = {
        "description": recent.details_fetched_at.isoformat(),
        "skills": recent.details_fetched_at.isoformat(),
        "benefits": recent.details_fetched_at.isoformat(),
        "salary": recent.details_fetched_at.isoformat(),
    }
    session.commit()

    response = client.get(f"/api/jobs/{recent_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == recent_id
    assert body["cacheState"] == "fresh"
    assert body["updatedAt"].endswith("Z") or body["updatedAt"].endswith("+00:00")
    assert body["warning"] is None
    assert body["description"] == "Description Backend Python"
    assert body["skills"] == ["Python", "FastAPI"]
    assert body["benefits"] == ["RTT"]
    assert body["possibleDuplicates"][0]["id"] == older_id
    assert body["sources"][0]["url"] == "https://example.test/freework/recent"


def test_unknown_and_uncached_source_less_details_have_distinct_http_errors(
    client: TestClient, session: Session
) -> None:
    """Fails if missing jobs and temporarily unavailable details share a false 200."""
    job = JobRepository(session).upsert_listing(offer("inactive"), seen_at=utc_now())
    listing = JobRepository(session).get_listing(job.id)
    assert listing is not None
    listing.active = False
    session.commit()

    missing = client.get("/api/jobs/00000000-0000-0000-0000-000000000000")
    unavailable = client.get(f"/api/jobs/{job.id}")

    assert missing.status_code == 404
    assert unavailable.status_code == 503
    assert unavailable.json() == {
        "detail": "Les détails de cette offre sont indisponibles : aucune source active."
    }
