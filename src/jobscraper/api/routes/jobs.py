"""Canonical job list and detail routes."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from jobscraper.api.dependencies import get_session
from jobscraper.api.schemas import (
    JobCard,
    JobDetails,
    JobViewedResponse,
    JobsPage,
    PossibleDuplicate,
    SourceLink,
)
from jobscraper.db.base import utc_now
from jobscraper.db.models import CanonicalJob, DuplicateRelation, SourceListing
from jobscraper.repositories.jobs import JobRepository
from jobscraper.repositories.saved_searches import SavedSearchRepository
from jobscraper.services.details import JobDetailsUnavailableError

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _relations(session: Session, job: CanonicalJob) -> list[DuplicateRelation]:
    return list(
        session.scalars(
            select(DuplicateRelation).where(
                DuplicateRelation.kind == "possible",
                or_(
                    DuplicateRelation.left_job_id == job.pk,
                    DuplicateRelation.right_job_id == job.pk,
                ),
            )
        )
    )


def _card(session: Session, job: CanonicalJob) -> JobCard:
    listings = list(
        session.scalars(
            select(SourceListing)
            .where(SourceListing.canonical_job_id == job.pk)
            .order_by(SourceListing.pk.asc())
        )
    )
    relations = _relations(session, job)
    duplicates: list[PossibleDuplicate] = []
    for relation in relations:
        other_pk = (
            relation.right_job_id
            if relation.left_job_id == job.pk
            else relation.left_job_id
        )
        other = session.get(CanonicalJob, other_pk)
        if other is not None:
            duplicates.append(
                PossibleDuplicate(
                    id=other.id,
                    title=other.title,
                    company=other.company,
                    location=other.location,
                    score=relation.score,
                    reasons=relation.reasons,
                )
            )
    duplicate_state: Literal["confirmed", "possible", "none"]
    duplicate_state = (
        "confirmed" if len(listings) > 1 else "possible" if duplicates else "none"
    )
    return JobCard(
        id=job.id,
        title=job.title,
        company=job.company,
        location=job.location,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        salary_currency=job.salary_currency,
        contract_type=job.contract_type,
        experience_level=job.experience_level,
        remote=job.remote,
        posted_at=job.posted_at,
        viewed_at=job.viewed_at,
        sources=[
            SourceLink(source=item.source, url=item.url, active=item.active)
            for item in listings
        ],
        duplicate_state=duplicate_state,
        possible_duplicates=duplicates,
    )


def _cutoff(period: str) -> datetime | None:
    if period == "all":
        return None
    hours = {"24h": 24, "3d": 72, "7d": 168}[period]
    return utc_now() - timedelta(hours=hours)


@router.get("", response_model=JobsPage)
def list_jobs(
    saved_search_id: str | None = Query(default=None, alias="savedSearchId"),
    period: Literal["24h", "3d", "7d", "all"] = "all",
    query: str | None = None,
    location: list[str] | None = Query(default=None),
    contract: list[str] | None = Query(default=None),
    remote: bool | None = None,
    experience: list[str] | None = Query(default=None),
    salary_min: float | None = Query(default=None, alias="salaryMin", ge=0),
    company: list[str] | None = Query(default=None),
    source: list[str] | None = Query(default=None),
    skill: list[str] | None = Query(default=None),
    duplicate_state: Literal["confirmed", "possible", "none"] | None = Query(
        default=None, alias="duplicateState"
    ),
    unseen_only: bool = Query(default=False, alias="unseenOnly"),
    sort: Literal["date", "relevance"] | None = None,
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> JobsPage:
    if (
        saved_search_id is not None
        and SavedSearchRepository(session).get(saved_search_id) is None
    ):
        raise HTTPException(
            status_code=404, detail="La recherche enregistrée n’existe pas."
        )
    repository = JobRepository(session)
    matching = repository.list_jobs(
        saved_search_id=saved_search_id,
        posted_since=_cutoff(period),
        query=query,
        locations=location,
        contracts=contract,
        remote=remote,
        experience=experience,
        salary_min=salary_min,
        companies=company,
        sources=source,
        skills=skill,
        duplicate_state=duplicate_state,
        unseen_only=unseen_only,
        sort=sort,
    )
    return JobsPage(
        items=[_card(session, item) for item in matching[offset : offset + limit]],
        total=len(matching),
        limit=limit,
        offset=offset,
    )


@router.post("/{canonical_job_id}/viewed", response_model=JobViewedResponse)
def mark_job_viewed(
    canonical_job_id: str,
    session: Session = Depends(get_session),
) -> JobViewedResponse:
    try:
        job = JobRepository(session).mark_viewed(canonical_job_id)
    except LookupError:
        raise HTTPException(
            status_code=404, detail="L’offre demandée n’existe pas."
        ) from None
    session.commit()
    if job.viewed_at is None:
        raise RuntimeError("Viewed timestamp was not persisted")
    return JobViewedResponse(id=job.id, viewed_at=job.viewed_at)


@router.get("/{canonical_job_id}", response_model=JobDetails)
def get_job(
    canonical_job_id: str,
    request: Request,
    session: Session = Depends(get_session),
) -> JobDetails:
    try:
        details = request.app.state.runtime.services(session).detail_service.get(
            canonical_job_id
        )
    except LookupError:
        raise HTTPException(
            status_code=404, detail="L’offre demandée n’existe pas."
        ) from None
    except JobDetailsUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from None
    card = _card(session, details.job)
    return JobDetails(
        **card.model_dump(),
        description=details.job.description,
        skills=details.job.skills,
        benefits=details.job.benefits,
        cache_state=details.cache_state,
        updated_at=details.updated_at,
        warning=details.warning,
    )
