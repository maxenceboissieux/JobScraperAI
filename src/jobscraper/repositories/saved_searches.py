"""Repository operations for reusable saved searches."""

from collections.abc import Sequence

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from jobscraper.db.models import SavedSearch
from jobscraper.models.job import SearchCriteria


def _values(items: Sequence[object]) -> list[str]:
    """Return serialized enum-or-string values suitable for JSON persistence."""

    return [str(getattr(item, "value", item)) for item in items]


class SavedSearchRepository:
    """Persist saved searches using public UUIDs at the repository boundary."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        name: str,
        criteria: SearchCriteria,
        sources: Sequence[str],
        active: bool = True,
    ) -> SavedSearch:
        """Create and flush a saved search without committing the caller's session."""

        saved_search = SavedSearch(
            name=name,
            keywords=list(criteria.keywords),
            title=criteria.title,
            location=criteria.location,
            radius_km=criteria.radius_km,
            contract_types=_values(criteria.contract_types),
            experience_levels=_values(criteria.experience_levels),
            workplace_types=_values(criteria.workplace_types),
            companies=list(criteria.companies),
            exclude_companies=list(criteria.exclude_companies),
            salary_min=criteria.salary_min,
            max_results=criteria.max_results,
            sources=list(sources),
            active=active,
        )
        self.session.add(saved_search)
        self.session.flush()
        return saved_search

    def get(self, saved_search_id: str) -> SavedSearch | None:
        """Return a saved search identified by its public UUID."""

        return self.session.scalar(
            select(SavedSearch).where(SavedSearch.id == saved_search_id)
        )

    def update(
        self,
        saved_search_id: str,
        *,
        name: str | None = None,
        criteria: SearchCriteria | None = None,
        sources: Sequence[str] | None = None,
        active: bool | None = None,
    ) -> SavedSearch | None:
        """Update supplied fields and flush, returning ``None`` for an unknown UUID."""

        saved_search = self.get(saved_search_id)
        if saved_search is None:
            return None

        if name is not None:
            saved_search.name = name
        if criteria is not None:
            saved_search.keywords = list(criteria.keywords)
            saved_search.title = criteria.title
            saved_search.location = criteria.location
            saved_search.radius_km = criteria.radius_km
            saved_search.contract_types = _values(criteria.contract_types)
            saved_search.experience_levels = _values(criteria.experience_levels)
            saved_search.workplace_types = _values(criteria.workplace_types)
            saved_search.companies = list(criteria.companies)
            saved_search.exclude_companies = list(criteria.exclude_companies)
            saved_search.salary_min = criteria.salary_min
            saved_search.max_results = criteria.max_results
        if sources is not None:
            saved_search.sources = list(sources)
        if active is not None:
            saved_search.active = active

        self.session.flush()
        return saved_search

    def list(self, *, active: bool | None = None) -> list[SavedSearch]:
        """List saved searches, optionally limited to one active state."""

        statement: Select[tuple[SavedSearch]] = select(SavedSearch).order_by(
            SavedSearch.created_at.desc(), SavedSearch.pk.desc()
        )
        if active is not None:
            statement = statement.where(SavedSearch.active.is_(active))
        return list(self.session.scalars(statement))
