from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from jobscraper.db.base import Base
from jobscraper.db.session import create_engine_and_session
from jobscraper.models.job import (
    ContractType,
    ExperienceLevel,
    SearchCriteria,
    WorkplaceType,
)
from jobscraper.repositories.saved_searches import SavedSearchRepository


@pytest.fixture
def session(tmp_path: Path) -> Session:
    engine, session_factory = create_engine_and_session(
        f"sqlite:///{tmp_path / 'jobs.db'}"
    )
    Base.metadata.create_all(engine)
    with session_factory() as database_session:
        yield database_session


def test_saved_search_crud_preserves_criteria_and_filters_active_state(
    session: Session,
) -> None:
    """Fails if create/update stop mapping criteria or querying active searches."""
    repository = SavedSearchRepository(session)
    criteria = SearchCriteria(
        keywords=["backend"],
        title="Python engineer",
        location="Paris",
        radius_km=25,
        contract_types=[ContractType.CDI],
        experience_levels=[ExperienceLevel.SENIOR],
        workplace_types=[WorkplaceType.REMOTE],
        companies=["Acme"],
        exclude_companies=["Umbrella"],
        salary_min=60_000,
        max_results=250,
    )

    created = repository.create(
        name="Backend remote", criteria=criteria, sources=["freework", "wttj"]
    )

    loaded = repository.get(created.id)
    assert loaded is not None
    assert loaded.name == "Backend remote"
    assert loaded.keywords == ["backend"]
    assert loaded.contract_types == ["cdi"]
    assert loaded.workplace_types == ["remote"]
    assert loaded.sources == ["freework", "wttj"]
    assert loaded.max_results == 250

    updated = repository.update(
        created.id,
        name="Backend Python",
        criteria=SearchCriteria(max_results=1_000),
        active=False,
    )
    assert updated is not None
    assert updated.name == "Backend Python"
    assert updated.max_results == 1_000
    assert repository.list(active=False) == [updated]
    assert repository.list(active=True) == []


def test_saved_search_returns_none_for_unknown_public_id(session: Session) -> None:
    """Fails if a public-ID lookup leaks an unrelated row or raises unexpectedly."""
    repository = SavedSearchRepository(session)

    assert repository.get("00000000-0000-0000-0000-000000000000") is None
    assert (
        repository.update("00000000-0000-0000-0000-000000000000", active=False) is None
    )
