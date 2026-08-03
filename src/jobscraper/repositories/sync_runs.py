"""Repository operations for resilient per-source synchronization records."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobscraper.db.base import utc_now
from jobscraper.db.models import SavedSearch, SourceSyncResult, SyncRun


class SyncRunRepository:
    """Persist synchronization lifecycle state without committing the session."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def start(
        self,
        saved_search_id: str,
        *,
        requested_sources: Sequence[str],
        started_at: datetime | None = None,
        status: str = "running",
    ) -> SyncRun:
        """Start and flush a run for an existing saved-search public UUID."""

        saved_search = self.session.scalar(
            select(SavedSearch).where(SavedSearch.id == saved_search_id)
        )
        if saved_search is None:
            raise LookupError("Saved search does not exist")
        run = SyncRun(
            saved_search_id=saved_search.pk,
            status=status,
            requested_sources=list(requested_sources),
            started_at=started_at or utc_now(),
        )
        self.session.add(run)
        self.session.flush()
        return run

    def get(self, run_id: str) -> SyncRun | None:
        """Return a run by public UUID."""

        return self.session.scalar(select(SyncRun).where(SyncRun.id == run_id))

    def record_source_result(
        self,
        run_id: str,
        source: str,
        *,
        status: str,
        offers_seen: int | None = None,
        offers_persisted: int | None = None,
        error_message: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> SourceSyncResult:
        """Create or update the one result row per source within a run."""

        run = self.get(run_id)
        if run is None:
            raise LookupError("Synchronization run does not exist")
        result = self.session.scalar(
            select(SourceSyncResult).where(
                SourceSyncResult.sync_run_id == run.pk,
                SourceSyncResult.source == source,
            )
        )
        if result is None:
            result = SourceSyncResult(
                sync_run_id=run.pk,
                source=source,
                status=status,
                offers_seen=offers_seen or 0,
                offers_persisted=offers_persisted or 0,
                error_message=error_message,
                started_at=started_at,
                finished_at=finished_at,
            )
            self.session.add(result)
        else:
            result.status = status
            if offers_seen is not None:
                result.offers_seen = offers_seen
            if offers_persisted is not None:
                result.offers_persisted = offers_persisted
            if error_message is not None:
                result.error_message = error_message
            if started_at is not None:
                result.started_at = started_at
            if finished_at is not None:
                result.finished_at = finished_at
        self.session.flush()
        return result

    def finish(
        self,
        run_id: str,
        *,
        status: str,
        finished_at: datetime | None = None,
    ) -> SyncRun | None:
        """Mark a run finished and flush, returning ``None`` for an unknown UUID."""

        run = self.get(run_id)
        if run is None:
            return None
        run.status = status
        run.finished_at = finished_at or utc_now()
        self.session.flush()
        return run
