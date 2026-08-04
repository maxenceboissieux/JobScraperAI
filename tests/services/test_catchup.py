from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from jobscraper.db.models import SavedSearch, SyncRun
from jobscraper.models.job import SearchCriteria
from jobscraper.runtime import build_runtime
from jobscraper.scrapers.base import BaseScraper
from jobscraper.services.catchup import CatchupService

PARIS = ZoneInfo("Europe/Paris")


@dataclass
class FakeSyncRuns:
    completed_at: dict[str, datetime | None]

    def latest_completed_at(self, saved_search_id: str) -> datetime | None:
        return self.completed_at.get(saved_search_id)


@dataclass
class FakeSyncService:
    calls: list[tuple[str, set[str] | None]] = field(default_factory=list)
    reject_active_calls: list[bool] = field(default_factory=list)

    def run(
        self,
        saved_search_id: str,
        only_sources: set[str] | None = None,
        *,
        reject_active: bool = False,
    ) -> str:
        self.calls.append((saved_search_id, only_sources))
        self.reject_active_calls.append(reject_active)
        return f"run-{saved_search_id}"


class FakeRuntime:
    def __init__(
        self,
        *,
        searches: list[Any],
        completed_at: dict[str, datetime | None],
    ) -> None:
        self.saved_searches = SimpleNamespace(
            list=lambda *, active: [item for item in searches if item.active is active]
        )
        self.sync_runs = FakeSyncRuns(completed_at)
        self.sync_service = FakeSyncService()

    @contextmanager
    def session_services(self) -> Iterator[FakeRuntime]:
        yield self


class EmptyScraper(BaseScraper):
    name = "freework"

    def search(self, criteria: SearchCriteria) -> Iterator[Any]:
        del criteria
        return iter(())

    def get_job_details(self, job_id: str) -> None:
        del job_id
        return None


class EmptyRegistry:
    def create(self, source: str) -> EmptyScraper:
        assert source == "freework"
        return EmptyScraper()


@pytest.mark.parametrize(
    ("now", "last_completed_at", "expected"),
    [
        (datetime(2026, 8, 3, 7, 59, tzinfo=PARIS), None, False),
        (datetime(2026, 8, 3, 8, 0, tzinfo=PARIS), None, True),
        (datetime(2026, 8, 3, 9, 0, tzinfo=PARIS), None, True),
        (
            datetime(2026, 8, 3, 9, 0, tzinfo=PARIS),
            datetime(2026, 8, 2, 8, 0, tzinfo=PARIS),
            True,
        ),
        (
            datetime(2026, 8, 3, 9, 0, tzinfo=PARIS),
            datetime(2026, 8, 3, 8, 5, tzinfo=PARIS),
            False,
        ),
    ],
)
def test_is_due_uses_the_current_calendar_schedule_boundary(
    now: datetime, last_completed_at: datetime | None, expected: bool
) -> None:
    """Fails if catch-up ignores today's schedule or a relevant completion."""

    assert CatchupService().is_due(now, last_completed_at, 8) is expected


def test_is_due_honours_a_custom_scheduled_minute() -> None:
    """Fails if a custom launchd minute is rounded down to the hour."""

    service = CatchupService()

    assert not service.is_due(
        datetime(2026, 8, 3, 8, 36, tzinfo=PARIS),
        None,
        scheduled_hour=8,
        scheduled_minute=37,
    )
    assert service.is_due(
        datetime(2026, 8, 3, 8, 37, tzinfo=PARIS),
        None,
        scheduled_hour=8,
        scheduled_minute=37,
    )


def test_is_due_compares_calendar_instants_across_spring_dst() -> None:
    """Fails if catch-up waits for 24 elapsed hours after the spring change."""

    assert CatchupService().is_due(
        datetime(2026, 3, 29, 8, 15, tzinfo=PARIS),
        datetime(2026, 3, 28, 8, 30, tzinfo=PARIS),
        scheduled_hour=8,
    )


def test_is_due_never_runs_early_across_autumn_dst() -> None:
    """Fails if 24 elapsed hours trigger catch-up before today's schedule."""

    assert not CatchupService().is_due(
        datetime(2026, 10, 25, 7, 45, tzinfo=PARIS),
        datetime(2026, 10, 24, 8, 30, tzinfo=PARIS),
        scheduled_hour=8,
    )


def test_is_due_uses_the_first_scheduled_instant_during_autumn_fold() -> None:
    """Fails if the repeated wall-clock hour postpones an already missed run."""

    second_occurrence = datetime(2026, 10, 25, 2, 15, tzinfo=PARIS, fold=1)

    assert CatchupService().is_due(
        second_occurrence,
        None,
        scheduled_hour=2,
        scheduled_minute=30,
    )


def test_is_due_accepts_a_utc_completion_for_a_local_schedule() -> None:
    """Fails if persisted UTC timestamps are compared as naive wall times."""

    assert not CatchupService().is_due(
        datetime(2026, 8, 3, 9, 0, tzinfo=PARIS),
        datetime(2026, 8, 3, 6, 5, tzinfo=timezone.utc),
        scheduled_hour=8,
    )


@pytest.mark.parametrize(
    ("now", "last_completed_at"),
    [
        (datetime(2026, 8, 3, 9), None),
        (datetime(2026, 8, 3, 9, tzinfo=PARIS), datetime(2026, 8, 3, 8, 5)),
    ],
)
def test_is_due_rejects_naive_datetimes(
    now: datetime, last_completed_at: datetime | None
) -> None:
    """Fails if timezone-unsafe inputs are silently interpreted as local time."""

    with pytest.raises(ValueError, match="fuseau horaire"):
        CatchupService().is_due(now, last_completed_at)


def test_run_if_due_refreshes_all_active_searches_when_one_is_missing() -> None:
    """Fails if one fresh search hides another search that still needs catch-up."""

    runtime = FakeRuntime(
        searches=[
            SimpleNamespace(id="fresh", active=True),
            SimpleNamespace(id="missing", active=True),
            SimpleNamespace(id="inactive", active=False),
        ],
        completed_at={
            "fresh": datetime(2026, 8, 3, 8, 15, tzinfo=timezone.utc),
            "missing": None,
        },
    )

    submitted = CatchupService().run_if_due(
        runtime,
        now=datetime(2026, 8, 3, 11, tzinfo=PARIS),
        scheduled_hour=8,
        scheduled_minute=37,
    )

    assert submitted is True
    assert runtime.sync_service.calls == [("fresh", None), ("missing", None)]
    assert runtime.sync_service.reject_active_calls == [True, True]


def test_run_if_due_skips_when_every_active_search_completed_today() -> None:
    """Fails if succeeded/partial daily completions are ignored at startup."""

    runtime = FakeRuntime(
        searches=[
            SimpleNamespace(id="succeeded", active=True),
            SimpleNamespace(id="partial", active=True),
        ],
        completed_at={
            "succeeded": datetime(2026, 8, 3, 8, 40, tzinfo=PARIS),
            "partial": datetime(2026, 8, 3, 9, 5, tzinfo=PARIS),
        },
    )

    submitted = CatchupService().run_if_due(
        runtime,
        now=datetime(2026, 8, 3, 11, tzinfo=PARIS),
        scheduled_hour=8,
        scheduled_minute=37,
    )

    assert submitted is False
    assert runtime.sync_service.calls == []


def test_latest_completed_at_counts_partial_but_not_failed_runs(
    tmp_path: Path,
) -> None:
    """Fails if failed work suppresses retry or a partial completion is forgotten."""

    runtime = build_runtime(f"sqlite:///{tmp_path / 'catchup.db'}")
    runtime.migrate()
    try:
        with runtime.session_services() as services:
            search = services.saved_searches.create(
                name="Python",
                criteria=SearchCriteria(keywords=["python"], location="Paris"),
                sources=["freework"],
            )
            partial_at = datetime(2026, 8, 3, 8, 45, tzinfo=timezone.utc)
            partial = services.sync_runs.start(
                search.id,
                requested_sources=["freework"],
                status="partial",
            )
            services.sync_runs.finish(
                partial.id, status="partial", finished_at=partial_at
            )
            failed = services.sync_runs.start(
                search.id,
                requested_sources=["freework"],
                status="failed",
            )
            services.sync_runs.finish(
                failed.id,
                status="failed",
                finished_at=datetime(2026, 8, 3, 9, tzinfo=timezone.utc),
            )

            failed_only = services.saved_searches.create(
                name="Data",
                criteria=SearchCriteria(keywords=["data"], location="Lyon"),
                sources=["freework"],
            )
            failed_run = services.sync_runs.start(
                failed_only.id,
                requested_sources=["freework"],
                status="failed",
            )
            services.sync_runs.finish(
                failed_run.id,
                status="failed",
                finished_at=datetime(2026, 8, 3, 9, tzinfo=timezone.utc),
            )

            assert services.sync_runs.latest_completed_at(search.id) == partial_at
            assert services.sync_runs.latest_completed_at(failed_only.id) is None
    finally:
        runtime.close()


def test_cross_session_active_collision_does_not_stop_later_due_searches(
    tmp_path: Path,
) -> None:
    """Fails if one manually active search aborts catch-up for the next search."""

    runtime = build_runtime(f"sqlite:///{tmp_path / 'collision.db'}")
    runtime.registry = EmptyRegistry()  # type: ignore[assignment]
    runtime.migrate()
    try:
        with runtime.session_services() as services:
            later_due = services.saved_searches.create(
                name="B due",
                criteria=SearchCriteria(keywords=["data"], location="Lyon"),
                sources=["freework"],
            )
            manually_active = services.saved_searches.create(
                name="A active",
                criteria=SearchCriteria(keywords=["python"], location="Paris"),
                sources=["freework"],
            )
            services.saved_searches.session.commit()

        with runtime.session_services() as manual_services:
            manual_services.sync_service.create_run(
                manually_active.id, reject_active=True
            )

        assert CatchupService().run_if_due(
            runtime,
            now=datetime(2026, 8, 4, 9, tzinfo=PARIS),
            scheduled_hour=8,
        )

        with runtime.session_factory() as observer:
            active_pk = observer.scalar(
                select(SavedSearch.pk).where(SavedSearch.id == manually_active.id)
            )
            assert (
                observer.scalar(
                    select(func.count(SyncRun.pk)).where(
                        SyncRun.saved_search_id == active_pk
                    )
                )
                == 1
            )
            caught_up = runtime.services(observer).sync_runs.latest(
                saved_search_id=later_due.id
            )
            assert caught_up is not None
            assert caught_up.status == "succeeded"
    finally:
        runtime.close()
