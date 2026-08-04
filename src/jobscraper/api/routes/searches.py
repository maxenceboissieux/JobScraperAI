"""Saved-search CRUD routes."""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from jobscraper.api.dependencies import get_session
from jobscraper.api.schemas import (
    SavedSearchResponse,
    SearchCreate,
    SearchUpdate,
)
from jobscraper.db.models import SavedSearch
from jobscraper.models.job import SearchCriteria
from jobscraper.repositories.saved_searches import SavedSearchRepository

router = APIRouter(prefix="/api/searches", tags=["searches"])


def _criteria(
    values: SearchCreate | SearchUpdate, current: SavedSearch | None = None
) -> SearchCriteria:
    """Turn HTTP fields into the service model, retaining omitted patch values."""

    def value(name: str) -> Any:
        if name in values.model_fields_set:
            return getattr(values, name)
        if current is not None:
            return getattr(current, name)
        return getattr(values, name)

    return SearchCriteria(
        keywords=list(cast(list[str], value("keywords"))),
        title=cast(str | None, value("title")),
        location=cast(str, value("location")),
        radius_km=cast(int | None, value("radius_km")),
        contract_types=list(cast(list[str], value("contract_types"))),
        experience_levels=list(cast(list[str], value("experience_levels"))),
        workplace_types=list(cast(list[str], value("workplace_types"))),
        companies=list(cast(list[str], value("companies"))),
        exclude_companies=list(cast(list[str], value("exclude_companies"))),
        salary_min=cast(int | None, value("salary_min")),
    )


def _response(search: SavedSearch) -> SavedSearchResponse:
    return SavedSearchResponse(
        id=search.id,
        name=search.name,
        keywords=search.keywords,
        title=search.title,
        location=search.location,
        radius_km=search.radius_km,
        contract_types=search.contract_types,
        experience_levels=search.experience_levels,
        workplace_types=search.workplace_types,
        companies=search.companies,
        exclude_companies=search.exclude_companies,
        salary_min=search.salary_min,
        sources=search.sources,
        active=search.active,
        created_at=search.created_at,
        updated_at=search.updated_at,
    )


@router.get("", response_model=list[SavedSearchResponse])
def list_searches(
    active: bool | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[SavedSearchResponse]:
    return [
        _response(item) for item in SavedSearchRepository(session).list(active=active)
    ]


@router.post(
    "", response_model=SavedSearchResponse, status_code=status.HTTP_201_CREATED
)
def create_search(
    payload: SearchCreate, session: Session = Depends(get_session)
) -> SavedSearchResponse:
    search = SavedSearchRepository(session).create(
        name=payload.name,
        criteria=_criteria(payload),
        sources=payload.sources,
        active=payload.active,
    )
    session.commit()
    return _response(search)


@router.patch("/{saved_search_id}", response_model=SavedSearchResponse)
def update_search(
    saved_search_id: str,
    payload: SearchUpdate,
    session: Session = Depends(get_session),
) -> SavedSearchResponse:
    repository = SavedSearchRepository(session)
    current = repository.get(saved_search_id)
    if current is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="La recherche enregistrée n’existe pas.",
        )

    criteria_fields = {
        "keywords",
        "title",
        "location",
        "radius_km",
        "contract_types",
        "experience_levels",
        "workplace_types",
        "companies",
        "exclude_companies",
        "salary_min",
    }
    changed = payload.model_fields_set
    updated = repository.update(
        saved_search_id,
        name=payload.name if "name" in changed else None,
        criteria=_criteria(payload, current) if changed & criteria_fields else None,
        sources=payload.sources if "sources" in changed else None,
        active=payload.active if "active" in changed else None,
    )
    assert updated is not None
    session.commit()
    return _response(updated)
