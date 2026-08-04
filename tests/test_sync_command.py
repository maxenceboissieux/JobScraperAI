from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from click.testing import CliRunner
from sqlalchemy import inspect, text

from jobscraper.cli import main
from jobscraper.runtime import build_runtime
from jobscraper.services.deduplication import classify_duplicate

ACTIVE_SEARCH_ID = "11111111-1111-4111-8111-111111111111"
INACTIVE_SEARCH_ID = "22222222-2222-4222-8222-222222222222"


@dataclass
class FakeSavedSearchRepository:
    searches: list[Any]
    events: list[str]

    def list(self, *, active: bool | None = None) -> list[Any]:
        self.events.append("list")
        if active is None:
            return list(self.searches)
        return [search for search in self.searches if search.active is active]

    def get(self, saved_search_id: str) -> Any | None:
        self.events.append("get")
        return next(
            (search for search in self.searches if search.id == saved_search_id), None
        )


@dataclass
class FakeSyncRunRepository:
    runs: dict[str, Any] = field(default_factory=dict)
    results: dict[str, list[Any]] = field(default_factory=dict)

    def get(self, run_id: str) -> Any | None:
        return self.runs.get(run_id)

    def source_results(self, run_id: str) -> list[Any]:
        return self.results.get(run_id, [])


@dataclass
class FakeSyncService:
    sync_runs: FakeSyncRunRepository
    outcomes: dict[str, tuple[str, list[tuple[str, str]]]] = field(default_factory=dict)
    calls: list[tuple[str, set[str] | None]] = field(default_factory=list)

    def run(self, saved_search_id: str, only_sources: set[str] | None = None) -> str:
        self.calls.append((saved_search_id, only_sources))
        run_id = f"run-{saved_search_id}"
        status, source_outcomes = self.outcomes.get(
            saved_search_id, ("succeeded", [("linkedin", "succeeded")])
        )
        self.sync_runs.runs[run_id] = SimpleNamespace(id=run_id, status=status)
        self.sync_runs.results[run_id] = [
            SimpleNamespace(
                source=source,
                status=source_status,
                offers_seen=3,
                offers_persisted=2,
                error_message=(
                    "La source est indisponible"
                    if source_status in {"failed", "partial"}
                    else None
                ),
            )
            for source, source_status in source_outcomes
        ]
        return run_id


@dataclass
class FakeRuntime:
    searches: list[Any]
    outcomes: dict[str, tuple[str, list[tuple[str, str]]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.events: list[str] = []
        self.saved_searches = FakeSavedSearchRepository(self.searches, self.events)
        self.sync_runs = FakeSyncRunRepository()
        self.sync_service = FakeSyncService(self.sync_runs, self.outcomes)
        self.closed = False

    def migrate(self) -> None:
        self.events.append("migrate")

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def runtime() -> FakeRuntime:
    return FakeRuntime(
        searches=[
            SimpleNamespace(id=ACTIVE_SEARCH_ID, name="Python Paris", active=True),
            SimpleNamespace(
                id=INACTIVE_SEARCH_ID, name="Ancienne recherche", active=False
            ),
        ]
    )


def test_sync_saved_searches_runs_all_active_searches(
    runner: CliRunner, runtime: FakeRuntime
) -> None:
    result = runner.invoke(main, ["sync-saved-searches"], obj={"runtime": runtime})

    assert result.exit_code == 0
    assert runtime.sync_service.calls == [(ACTIVE_SEARCH_ID, None)]
    assert "Synchronisation terminée" in result.output


def test_sync_saved_searches_migrates_before_reading_and_closes_runtime(
    runner: CliRunner, runtime: FakeRuntime
) -> None:
    result = runner.invoke(main, ["sync-saved-searches"], obj={"runtime": runtime})

    assert result.exit_code == 0
    assert runtime.events[:2] == ["migrate", "list"]
    assert runtime.closed is True


def test_sync_saved_searches_ignores_inactive_searches(
    runner: CliRunner, runtime: FakeRuntime
) -> None:
    result = runner.invoke(main, ["sync-saved-searches"], obj={"runtime": runtime})

    assert result.exit_code == 0
    assert all(
        search_id != INACTIVE_SEARCH_ID
        for search_id, _sources in runtime.sync_service.calls
    )


def test_sync_saved_searches_runs_only_selected_search(
    runner: CliRunner, runtime: FakeRuntime
) -> None:
    result = runner.invoke(
        main,
        ["sync-saved-searches", "--search-id", INACTIVE_SEARCH_ID],
        obj={"runtime": runtime},
    )

    assert result.exit_code == 0
    assert runtime.sync_service.calls == [(INACTIVE_SEARCH_ID, None)]


def test_sync_saved_searches_passes_validated_source_filter(
    runner: CliRunner, runtime: FakeRuntime
) -> None:
    result = runner.invoke(
        main,
        ["sync-saved-searches", "--source", "freework"],
        obj={"runtime": runtime},
    )

    assert result.exit_code == 0
    assert runtime.sync_service.calls == [(ACTIVE_SEARCH_ID, {"freework"})]


def test_sync_saved_searches_rejects_unknown_source(
    runner: CliRunner, runtime: FakeRuntime
) -> None:
    result = runner.invoke(
        main,
        ["sync-saved-searches", "--source", "inconnue"],
        obj={"runtime": runtime},
    )

    assert result.exit_code == 2
    assert "Invalid value for '--source'" in result.output
    assert runtime.sync_service.calls == []


def test_sync_saved_searches_returns_two_for_partial_failure(
    runner: CliRunner,
) -> None:
    runtime = FakeRuntime(
        searches=[
            SimpleNamespace(id=ACTIVE_SEARCH_ID, name="Python Paris", active=True)
        ],
        outcomes={
            ACTIVE_SEARCH_ID: (
                "partial",
                [("linkedin", "succeeded"), ("freework", "failed")],
            )
        },
    )

    result = runner.invoke(main, ["sync-saved-searches"], obj={"runtime": runtime})

    assert result.exit_code == 2
    assert "partielle" in result.output.casefold()
    assert "freework" in result.output


def test_sync_saved_searches_returns_one_for_total_failure(
    runner: CliRunner,
) -> None:
    runtime = FakeRuntime(
        searches=[
            SimpleNamespace(id=ACTIVE_SEARCH_ID, name="Python Paris", active=True)
        ],
        outcomes={
            ACTIVE_SEARCH_ID: ("failed", [("linkedin", "failed")]),
        },
    )

    result = runner.invoke(main, ["sync-saved-searches"], obj={"runtime": runtime})

    assert result.exit_code == 1
    assert "échoué" in result.output.casefold()


def test_sync_saved_searches_with_no_active_search_is_actionable_success(
    runner: CliRunner,
) -> None:
    runtime = FakeRuntime(
        searches=[
            SimpleNamespace(
                id=INACTIVE_SEARCH_ID, name="Ancienne recherche", active=False
            )
        ]
    )

    result = runner.invoke(main, ["sync-saved-searches"], obj={"runtime": runtime})

    assert result.exit_code == 0
    assert runtime.sync_service.calls == []
    assert "Aucune recherche active" in result.output


def test_build_runtime_composes_shared_services_once() -> None:
    runtime = build_runtime("sqlite://")
    try:
        assert runtime.jobs is runtime.sync_service.jobs
        assert runtime.sync_runs is runtime.sync_service.sync_runs
        assert runtime.sync_service.registry is runtime.registry
        assert runtime.detail_service.registry is runtime.registry
        assert runtime.deduplicator is classify_duplicate
    finally:
        runtime.close()


def test_runtime_migrates_the_configured_database(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'headless.db'}"
    runtime = build_runtime(database_url)
    try:
        runtime.migrate()

        assert "saved_searches" in inspect(runtime.engine).get_table_names()
        with runtime.engine.connect() as connection:
            revision = connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
        assert revision is not None
    finally:
        runtime.close()
