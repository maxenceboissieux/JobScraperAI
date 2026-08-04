from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Event, get_ident

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from alembic import command
from alembic.config import Config
from jobscraper.api.app import create_app, run
from jobscraper.db.base import utc_now
from jobscraper.db.models import SavedSearch, SyncRun
from jobscraper.models.job import SearchCriteria
from jobscraper.repositories.saved_searches import SavedSearchRepository
from jobscraper.repositories.sync_runs import SyncRunRepository
from jobscraper.services.sync import SyncService

PROJECT_ROOT = Path(__file__).parents[2]


def create_search(client: TestClient, *, sources: list[str] | None = None) -> str:
    response = client.post(
        "/api/searches",
        json={
            "name": "Backend",
            "keywords": ["backend"],
            "location": "France",
            "sources": sources or ["freework", "linkedin"],
            "active": True,
        },
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def test_sync_runs_outside_request_thread_and_exposes_source_progress(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fails if POST executes scraping inline or shares its request session."""
    search_id = create_search(client)
    caller_thread = get_ident()
    finished = Event()
    worker_threads: list[int] = []

    def execute(self: SyncService, run_id: str) -> None:
        worker_threads.append(get_ident())
        claimed = self.sync_runs.claim_pending(run_id)
        assert claimed is not None
        self.sync_runs.record_source_result(
            run_id,
            "freework",
            status="succeeded",
            offers_seen=3,
            offers_persisted=2,
            finished_at=utc_now(),
        )
        self.sync_runs.record_source_result(
            run_id,
            "linkedin",
            status="succeeded",
            offers_seen=1,
            offers_persisted=1,
            finished_at=utc_now(),
        )
        self.sync_runs.finish(run_id, status="succeeded")
        self.session.commit()
        finished.set()

    monkeypatch.setattr(SyncService, "execute", execute)

    response = client.post("/api/syncs", json={"savedSearchId": search_id})

    assert response.status_code == 202
    pending = response.json()
    assert pending["savedSearchId"] == search_id
    assert pending["status"] == "pending"
    assert pending["requestedSources"] == ["freework", "linkedin"]
    assert [item["status"] for item in pending["sources"]] == [
        "pending",
        "pending",
    ]
    assert finished.wait(timeout=3)
    assert worker_threads and worker_threads[0] != caller_thread

    current = client.get(f"/api/syncs/{pending['id']}")
    assert current.status_code == 200
    assert current.json()["status"] == "succeeded"
    assert [
        (item["source"], item["offersPersisted"]) for item in current.json()["sources"]
    ] == [
        ("freework", 2),
        ("linkedin", 1),
    ]


def test_simultaneous_same_search_posts_allow_exactly_one_active_run(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fails if the duplicate-run preflight races between concurrent requests."""
    search_id = create_search(client, sources=["freework"])
    release = Event()
    barrier = Barrier(2)

    def hold_execute(self: SyncService, run_id: str) -> None:
        del self, run_id
        release.wait(timeout=5)

    monkeypatch.setattr(SyncService, "execute", hold_execute)

    def post_sync() -> object:
        barrier.wait()
        return client.post("/api/syncs", json={"savedSearchId": search_id})

    try:
        with ThreadPoolExecutor(max_workers=2) as callers:
            responses = list(callers.map(lambda _index: post_sync(), range(2)))
    finally:
        release.set()

    assert sorted(response.status_code for response in responses) == [202, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json() == {"detail": "Une synchronisation est déjà en cours."}


@pytest.mark.parametrize("retry_status", ["failed", "partial"])
def test_retry_creates_a_new_run_for_only_failed_or_partial_source(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    retry_status: str,
) -> None:
    """Fails if retry repeats healthy sources or mutates the completed run."""
    search = SavedSearchRepository(session).create(
        name="Backend",
        criteria=SearchCriteria(keywords=["backend"]),
        sources=["freework", "linkedin"],
    )
    runs = SyncRunRepository(session)
    original = runs.start(
        search.id, requested_sources=["freework", "linkedin"], status="running"
    )
    runs.record_source_result(original.id, "freework", status="succeeded")
    runs.record_source_result(
        original.id,
        "linkedin",
        status=retry_status,
        error_message="La source a échoué.",
    )
    runs.finish(original.id, status="partial")
    session.commit()
    monkeypatch.setattr(SyncService, "execute", lambda self, run_id: None)

    healthy = client.post(
        f"/api/syncs/{original.id}/retry", json={"source": "freework"}
    )
    retried = client.post(
        f"/api/syncs/{original.id}/retry", json={"source": "linkedin"}
    )

    assert healthy.status_code == 422
    assert retried.status_code == 202
    assert retried.json()["id"] != original.id
    assert retried.json()["requestedSources"] == ["linkedin"]
    assert [item["source"] for item in retried.json()["sources"]] == ["linkedin"]


def test_sync_404_and_validation_semantics(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fails if public lookup and source-validation errors become internal failures."""
    monkeypatch.setattr(SyncService, "execute", lambda self, run_id: None)
    search_id = create_search(client, sources=["freework"])

    missing_search = client.post(
        "/api/syncs",
        json={"savedSearchId": "00000000-0000-0000-0000-000000000000"},
    )
    invalid_source = client.post(
        "/api/syncs",
        json={"savedSearchId": search_id, "sources": ["linkedin"]},
    )
    missing_run = client.get("/api/syncs/00000000-0000-0000-0000-000000000000")
    missing_retry = client.post(
        "/api/syncs/00000000-0000-0000-0000-000000000000/retry",
        json={"source": "freework"},
    )

    assert missing_search.status_code == 404
    assert invalid_source.status_code == 422
    assert missing_run.status_code == 404
    assert missing_retry.status_code == 404


def test_latest_returns_null_then_newest_run(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fails if the empty state or global newest ordering is ambiguous."""
    assert client.get("/api/syncs/latest").json() is None
    monkeypatch.setattr(SyncService, "execute", lambda self, run_id: None)
    first_search = create_search(client, sources=["freework"])
    first = client.post("/api/syncs", json={"savedSearchId": first_search}).json()
    run = session.scalar(select(SyncRun).where(SyncRun.id == first["id"]))
    assert run is not None
    run.status = "failed"
    run.finished_at = utc_now()
    session.commit()
    second_search = create_search(client, sources=["linkedin"])
    second = client.post("/api/syncs", json={"savedSearchId": second_search}).json()

    latest = client.get("/api/syncs/latest")

    assert latest.status_code == 200
    assert latest.json()["id"] == second["id"]


def test_executor_submit_failure_marks_run_failed_and_sanitizes_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fails if a rejected executor leaves a permanent pending run or leaks details."""
    search_id = create_search(client, sources=["freework"])

    def reject_submit(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("executor-token=secret")

    monkeypatch.setattr(client.app.state.executor, "submit", reject_submit)

    response = client.post("/api/syncs", json={"savedSearchId": search_id})
    latest = client.get("/api/syncs/latest")

    assert response.status_code == 503
    assert response.json() == {"detail": "La synchronisation n’a pas pu être démarrée."}
    assert "secret" not in response.text
    assert latest.status_code == 200
    assert latest.json()["status"] == "failed"


def test_executor_shutdown_is_owned_by_application_lifespan(database_url: str) -> None:
    """Fails if worker threads outlive deterministic application shutdown."""
    app = create_app(database_url)
    with TestClient(app):
        executor = app.state.executor

    with pytest.raises(RuntimeError, match="shutdown"):
        executor.submit(lambda: None)


def test_startup_upgrades_an_existing_revision_to_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fails if API startup assumes create_all can migrate an existing database."""
    database_url = f"sqlite:///{tmp_path / 'upgrade.db'}"
    monkeypatch.delenv("JOBSCRAPER_DATABASE_URL", raising=False)
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "0001")

    with TestClient(create_app(database_url)):
        pass

    from jobscraper.db.session import create_engine_and_session

    engine, _factory = create_engine_and_session(database_url)
    try:
        with engine.connect() as connection:
            revision = connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
    finally:
        engine.dispose()
    assert revision == "0002"


def test_in_memory_sqlite_is_shared_with_executor_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fails if sqlite:// gives the worker a separate empty database connection."""
    app = create_app("sqlite://")
    completed = Event()

    def execute(self: SyncService, run_id: str) -> None:
        assert self.sync_runs.claim_pending(run_id) is not None
        self.sync_runs.finish(run_id, status="succeeded")
        self.session.commit()
        completed.set()

    monkeypatch.setattr(SyncService, "execute", execute)
    with TestClient(app, raise_server_exceptions=False) as client:
        search_id = create_search(client, sources=["freework"])
        response = client.post("/api/syncs", json={"savedSearchId": search_id})
        assert response.status_code == 202
        assert completed.wait(timeout=3)
        assert (
            client.get(f"/api/syncs/{response.json()['id']}").json()["status"]
            == "succeeded"
        )


def test_run_uses_environment_database_and_fixed_loopback_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fails if the installed entrypoint ignores its database or exposes the API broadly."""
    sentinel_app = object()
    observed: dict[str, object] = {}
    monkeypatch.setenv("JOBSCRAPER_DATABASE_URL", "sqlite:////tmp/entrypoint.db")

    def fake_create_app(database_url: str | None = None) -> object:
        observed["database_url"] = database_url
        return sentinel_app

    def fake_uvicorn_run(app: object, **kwargs: object) -> None:
        observed["app"] = app
        observed.update(kwargs)

    monkeypatch.setattr("jobscraper.api.app.create_app", fake_create_app)
    monkeypatch.setattr("uvicorn.run", fake_uvicorn_run)

    run()

    assert observed == {
        "database_url": "sqlite:////tmp/entrypoint.db",
        "app": sentinel_app,
        "host": "127.0.0.1",
        "port": 8000,
    }
