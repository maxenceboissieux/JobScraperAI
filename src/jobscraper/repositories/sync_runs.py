"""Repository operations for resilient per-source synchronization records."""

from collections.abc import Sequence
from datetime import datetime
from time import sleep
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from jobscraper.db.base import utc_now
from jobscraper.db.models import SavedSearch, SourceSyncResult, SyncRun


class _Unset:
    """Differentiate an omitted update field from an explicit SQL NULL."""


UNSET = _Unset()


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
        status: str = "pending",
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
            started_at=None if status == "pending" else started_at or utc_now(),
        )
        self.session.add(run)
        self.session.flush()
        return run

    def start_if_no_active(
        self,
        saved_search_id: str,
        *,
        requested_sources: Sequence[str],
    ) -> SyncRun | None:
        """Create a pending run unless this search already has active work."""

        try:
            with self.session.begin_nested():
                return self.start(saved_search_id, requested_sources=requested_sources)
        except IntegrityError:
            self.session.rollback()
            if self._active_run_appears(saved_search_id):
                return None
            raise
        except OperationalError as exc:
            if "database is locked" not in str(exc.orig).casefold():
                raise
            self.session.rollback()
            if self._active_run_appears(saved_search_id):
                return None
            raise

    def _active_run_appears(self, saved_search_id: str) -> bool:
        for attempt in range(4):
            try:
                if self._active_run_exists(saved_search_id):
                    return True
            except OperationalError as observation_error:
                if "database is locked" not in str(observation_error.orig).casefold():
                    raise
            self.session.rollback()
            if attempt < 3:
                sleep(0.01 * (attempt + 1))
        return False

    def _active_run_exists(self, saved_search_id: str) -> bool:
        return (
            self.session.scalar(
                select(SyncRun.pk)
                .join(SavedSearch, SyncRun.saved_search_id == SavedSearch.pk)
                .where(
                    SavedSearch.id == saved_search_id,
                    SyncRun.status.in_({"pending", "running"}),
                )
                .limit(1)
            )
            is not None
        )

    def latest(self, *, saved_search_id: str | None = None) -> SyncRun | None:
        """Return the newest attempt globally or for one saved search."""

        statement = select(SyncRun)
        if saved_search_id is not None:
            statement = statement.join(
                SavedSearch, SyncRun.saved_search_id == SavedSearch.pk
            ).where(SavedSearch.id == saved_search_id)
        return self.session.scalar(
            statement.order_by(SyncRun.created_at.desc(), SyncRun.pk.desc())
        )

    def latest_completed_at(self, saved_search_id: str) -> datetime | None:
        """Return the newest useful completion for one saved search."""

        return self.session.scalar(
            select(SyncRun.finished_at)
            .join(SavedSearch, SyncRun.saved_search_id == SavedSearch.pk)
            .where(
                SavedSearch.id == saved_search_id,
                SyncRun.status.in_({"succeeded", "partial"}),
                SyncRun.finished_at.is_not(None),
            )
            .order_by(SyncRun.finished_at.desc(), SyncRun.pk.desc())
            .limit(1)
        )

    def source_results(self, run_id: str) -> list[SourceSyncResult]:
        """Return persisted source state for a public run UUID."""

        run = self.get(run_id)
        if run is None:
            return []
        return list(
            self.session.scalars(
                select(SourceSyncResult)
                .where(SourceSyncResult.sync_run_id == run.pk)
                .order_by(SourceSyncResult.pk.asc())
            )
        )

    def fail_pending(self, run_id: str, *, finished_at: datetime | None = None) -> bool:
        """Atomically fail queued work without overwriting a claimed run."""

        result = cast(
            CursorResult[Any],
            self.session.execute(
                update(SyncRun)
                .where(SyncRun.id == run_id, SyncRun.status == "pending")
                .values(status="failed", finished_at=finished_at or utc_now())
            ),
        )
        self.session.flush()
        return result.rowcount == 1

    def get(self, run_id: str) -> SyncRun | None:
        """Return a run by public UUID."""

        return self.session.scalar(select(SyncRun).where(SyncRun.id == run_id))

    def mark_running(
        self, run_id: str, *, started_at: datetime | None = None
    ) -> SyncRun | None:
        """Transition a pending run to running without committing the session."""

        run = self.get(run_id)
        if run is None:
            return None
        run.status = "running"
        if run.started_at is None:
            run.started_at = started_at or utc_now()
        self.session.flush()
        return run

    def claim_pending(
        self, run_id: str, *, started_at: datetime | None = None
    ) -> SyncRun | None:
        """Atomically claim one pending run, returning ``None`` if already claimed."""

        claimed_at = started_at or utc_now()
        result: CursorResult[Any] | None = None
        last_lock_error: OperationalError | None = None
        for attempt in range(10):
            try:
                result = cast(
                    CursorResult[Any],
                    self.session.execute(
                        update(SyncRun)
                        .where(SyncRun.id == run_id, SyncRun.status == "pending")
                        .values(status="running", started_at=claimed_at)
                    ),
                )
                break
            except OperationalError as exc:
                if "locked" not in str(exc.orig).casefold():
                    raise
                last_lock_error = exc
                self.session.rollback()
                if attempt < 9:
                    sleep(0.01 * (attempt + 1))
        if result is None:
            assert last_lock_error is not None
            raise last_lock_error
        if result.rowcount != 1:
            return None
        self.session.flush()
        return self.get(run_id)

    def record_source_result(
        self,
        run_id: str,
        source: str,
        *,
        status: str,
        offers_seen: int | None = None,
        offers_persisted: int | None = None,
        error_message: str | None | _Unset = UNSET,
        started_at: datetime | None | _Unset = UNSET,
        finished_at: datetime | None | _Unset = UNSET,
    ) -> SourceSyncResult:
        """Create or update the one result row per source within a run."""

        run = self.get(run_id)
        if run is None:
            raise LookupError("Synchronization run does not exist")
        result = self._source_result(run.pk, source)
        if result is None:
            try:
                with self.session.begin_nested():
                    result = SourceSyncResult(
                        sync_run_id=run.pk,
                        source=source,
                        status=status,
                    )
                    self.session.add(result)
                    self.session.flush()
            except IntegrityError:
                result = self._source_result(run.pk, source)
                if result is None:
                    raise
        self._apply_result_update(
            result,
            status=status,
            offers_seen=offers_seen,
            offers_persisted=offers_persisted,
            error_message=error_message,
            started_at=started_at,
            finished_at=finished_at,
        )
        if status == "running":
            self.mark_running(
                run.id,
                started_at=None if isinstance(started_at, _Unset) else started_at,
            )
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
        if finished_at is not None:
            run.finished_at = finished_at
        elif run.finished_at is None:
            run.finished_at = utc_now()
        self.session.flush()
        return run

    def _source_result(self, run_pk: int, source: str) -> SourceSyncResult | None:
        return self.session.scalar(
            select(SourceSyncResult).where(
                SourceSyncResult.sync_run_id == run_pk,
                SourceSyncResult.source == source,
            )
        )

    @staticmethod
    def _apply_result_update(
        result: SourceSyncResult,
        *,
        status: str,
        offers_seen: int | None,
        offers_persisted: int | None,
        error_message: str | None | _Unset,
        started_at: datetime | None | _Unset,
        finished_at: datetime | None | _Unset,
    ) -> None:
        result.status = status
        if offers_seen is not None:
            result.offers_seen = offers_seen
        if offers_persisted is not None:
            result.offers_persisted = offers_persisted
        if isinstance(error_message, _Unset):
            if status in {"pending", "running", "succeeded"}:
                result.error_message = None
        else:
            result.error_message = error_message
        if isinstance(started_at, _Unset):
            if status == "running" and result.started_at is None:
                result.started_at = utc_now()
        else:
            result.started_at = started_at
        if isinstance(finished_at, _Unset):
            if status in {"pending", "running"}:
                result.finished_at = None
            elif status == "succeeded":
                result.finished_at = utc_now()
        else:
            result.finished_at = finished_at
