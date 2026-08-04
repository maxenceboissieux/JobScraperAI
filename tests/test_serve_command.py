from __future__ import annotations

import plistlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, current_thread
from types import SimpleNamespace
from typing import Any, Iterator
from zoneinfo import ZoneInfo

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

import jobscraper.cli as cli_module
from jobscraper.api.app import create_app
from jobscraper.automation.launchd import installed_launch_agent_path
from jobscraper.cli import main
from jobscraper.services.catchup import CatchupService, resolve_local_timezone

PARIS = ZoneInfo("Europe/Paris")


class FakeRuntime:
    def __init__(self) -> None:
        self.engine = object()
        self.session_factory = object()
        self.events: list[str] = []
        self.closed = False
        self.sync_service = SimpleNamespace(run=self._run)
        self.sync_runs = SimpleNamespace(latest_completed_at=self._completed_at)
        self.saved_searches = SimpleNamespace(list=self._list_searches)

    def migrate(self) -> None:
        self.events.append("migrate")

    def close(self) -> None:
        self.events.append("close")
        self.closed = True

    @contextmanager
    def session_services(self) -> Iterator[FakeRuntime]:
        self.events.append(f"session:{current_thread().name}")
        yield self

    def _list_searches(self, *, active: bool | None = None) -> list[Any]:
        self.events.append("list")
        searches = [
            SimpleNamespace(id="fresh", active=True),
            SimpleNamespace(id="missing", active=True),
        ]
        return [item for item in searches if active is None or item.active is active]

    @staticmethod
    def _completed_at(saved_search_id: str) -> datetime | None:
        if saved_search_id == "fresh":
            return datetime(2026, 8, 3, 8, 45, tzinfo=timezone.utc)
        return None

    def _run(
        self,
        saved_search_id: str,
        only_sources: object = None,
        *,
        reject_active: bool = False,
    ) -> str:
        del only_sources
        assert reject_active is True
        self.events.append(f"sync:{saved_search_id}")
        return f"run-{saved_search_id}"


@pytest.fixture
def built_frontend(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        '<script type="module" src="/assets/app.js"></script>', encoding="utf-8"
    )
    (assets / "app.js").write_text("window.app = true", encoding="utf-8")
    return dist


def test_serve_migrates_once_and_submits_catchup_in_the_app_executor(
    monkeypatch: pytest.MonkeyPatch, built_frontend: Path
) -> None:
    """Fails if serve duplicates runtime ownership or runs catch-up on the event loop."""

    runtime = FakeRuntime()
    observed: dict[str, object] = {}

    def fake_uvicorn_run(app: object, **kwargs: object) -> None:
        observed["app"] = app
        observed.update(kwargs)
        with TestClient(app):  # type: ignore[arg-type]
            pass
        assert runtime.closed is False

    monkeypatch.setattr(cli_module, "build_runtime", lambda _url: runtime)
    monkeypatch.setattr(
        cli_module, "DEFAULT_FRONTEND_DIST", built_frontend, raising=False
    )
    monkeypatch.setattr(
        cli_module, "resolve_local_timezone", lambda: PARIS, raising=False
    )
    monkeypatch.setattr(
        cli_module, "_read_launch_agent_schedule", lambda: (8, 37), raising=False
    )
    monkeypatch.setattr(
        cli_module,
        "_local_now",
        lambda _timezone: datetime(2026, 8, 3, 11, tzinfo=PARIS),
        raising=False,
    )
    monkeypatch.setattr("uvicorn.run", fake_uvicorn_run)
    monkeypatch.setattr(
        "webbrowser.open",
        lambda _url: pytest.fail("--no-open ne doit jamais ouvrir le navigateur"),
    )

    result = CliRunner().invoke(
        main,
        ["serve", "--host", "0.0.0.0", "--port", "4321", "--no-open"],
    )

    assert result.exit_code == 0, result.output
    assert observed["host"] == "0.0.0.0"
    assert observed["port"] == 4321
    assert runtime.events.count("migrate") == 1
    assert runtime.events.count("sync:fresh") == 1
    assert runtime.events.count("sync:missing") == 1
    session_event = next(item for item in runtime.events if item.startswith("session:"))
    assert "jobscraper-sync" in session_event
    assert runtime.events[-1] == "close"


def test_external_runtime_and_startup_task_have_single_clear_owners(
    built_frontend: Path,
) -> None:
    """Fails if app lifespan remigrates/closes serve's runtime or resubmits catch-up."""

    runtime = FakeRuntime()

    def catch_up() -> None:
        runtime.events.append(f"catchup:{current_thread().name}")

    app = create_app(
        frontend_dist=built_frontend,
        runtime=runtime,  # type: ignore[arg-type]
        startup_task=catch_up,
    )

    with TestClient(app):
        pass
    with TestClient(app):
        pass

    assert runtime.events == ["catchup:jobscraper-sync_0"]
    assert runtime.closed is False


def test_serve_does_not_submit_catchup_before_the_custom_schedule(
    monkeypatch: pytest.MonkeyPatch, built_frontend: Path
) -> None:
    """Fails if startup work is queued before the configured launchd minute."""

    runtime = FakeRuntime()

    def fake_uvicorn_run(app: object, **_kwargs: object) -> None:
        with TestClient(app):  # type: ignore[arg-type]
            pass

    monkeypatch.setattr(cli_module, "build_runtime", lambda _url: runtime)
    monkeypatch.setattr(
        cli_module, "DEFAULT_FRONTEND_DIST", built_frontend, raising=False
    )
    monkeypatch.setattr(
        cli_module, "resolve_local_timezone", lambda: PARIS, raising=False
    )
    monkeypatch.setattr(
        cli_module, "_read_launch_agent_schedule", lambda: (8, 37), raising=False
    )
    monkeypatch.setattr(
        cli_module,
        "_local_now",
        lambda _timezone: datetime(2026, 8, 3, 8, 36, tzinfo=PARIS),
        raising=False,
    )
    monkeypatch.setattr("uvicorn.run", fake_uvicorn_run)

    result = CliRunner().invoke(main, ["serve", "--no-open"])

    assert result.exit_code == 0, result.output
    assert all(not event.startswith("session:") for event in runtime.events)
    assert all(not event.startswith("sync:") for event in runtime.events)


def test_serve_reads_clock_after_migration_crosses_the_schedule(
    monkeypatch: pytest.MonkeyPatch, built_frontend: Path
) -> None:
    """Fails if a 07:59 timestamp captured before migration suppresses an 08:00 run."""

    runtime = FakeRuntime()
    clock = {"now": datetime(2026, 8, 3, 7, 59, tzinfo=PARIS)}

    def migrate_across_schedule() -> None:
        runtime.events.append("migrate")
        clock["now"] = datetime(2026, 8, 3, 8, 0, tzinfo=PARIS)

    def fake_uvicorn_run(app: object, **_kwargs: object) -> None:
        with TestClient(app):  # type: ignore[arg-type]
            pass

    runtime.migrate = migrate_across_schedule  # type: ignore[method-assign]
    monkeypatch.setattr(cli_module, "build_runtime", lambda _url: runtime)
    monkeypatch.setattr(
        cli_module, "DEFAULT_FRONTEND_DIST", built_frontend, raising=False
    )
    monkeypatch.setattr(
        cli_module, "resolve_local_timezone", lambda: PARIS, raising=False
    )
    monkeypatch.setattr(
        cli_module, "_read_launch_agent_schedule", lambda: (8, 0), raising=False
    )
    monkeypatch.setattr(cli_module, "_local_now", lambda _timezone: clock["now"])
    monkeypatch.setattr("uvicorn.run", fake_uvicorn_run)

    result = CliRunner().invoke(main, ["serve", "--no-open"])

    assert result.exit_code == 0, result.output
    assert runtime.events.count("sync:missing") == 1


@pytest.mark.parametrize("missing_part", ["index", "assets", "asset-file"])
def test_serve_requires_a_complete_frontend_build_before_database_startup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    missing_part: str,
) -> None:
    """Fails if serve starts an API-only shell instead of explaining how to build."""

    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    if missing_part != "index":
        (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    if missing_part == "assets":
        assets.rmdir()
    elif missing_part != "asset-file":
        (assets / "app.js").write_text("app", encoding="utf-8")

    monkeypatch.setattr(cli_module, "DEFAULT_FRONTEND_DIST", dist, raising=False)
    monkeypatch.setattr(
        cli_module,
        "build_runtime",
        lambda _url: pytest.fail("la base ne doit pas démarrer sans frontend"),
    )

    result = CliRunner().invoke(main, ["serve", "--no-open"])

    assert result.exit_code == 1
    assert "pnpm build" in result.output
    assert "frontend" in result.output.casefold()


def test_serve_reports_migration_failure_in_french_and_closes_runtime(
    monkeypatch: pytest.MonkeyPatch, built_frontend: Path
) -> None:
    """Fails if a migration error leaks internals or leaves the engine open."""

    runtime = FakeRuntime()

    def reject_migration() -> None:
        raise RuntimeError("database-token=secret")

    runtime.migrate = reject_migration  # type: ignore[method-assign]
    monkeypatch.setattr(cli_module, "build_runtime", lambda _url: runtime)
    monkeypatch.setattr(
        cli_module, "DEFAULT_FRONTEND_DIST", built_frontend, raising=False
    )

    result = CliRunner().invoke(main, ["serve", "--no-open"])

    assert result.exit_code == 1
    assert "migration" in result.output.casefold()
    assert "alembic upgrade head" in result.output
    assert "database-token" not in result.output
    assert runtime.closed is True


def test_close_failure_never_masks_the_actionable_migration_error(
    monkeypatch: pytest.MonkeyPatch, built_frontend: Path
) -> None:
    """Fails if cleanup replaces the primary ClickException from migration."""

    runtime = FakeRuntime()

    def reject_migration() -> None:
        raise RuntimeError("migration-token=secret")

    def reject_close() -> None:
        raise RuntimeError("close-token=secret")

    runtime.migrate = reject_migration  # type: ignore[method-assign]
    runtime.close = reject_close  # type: ignore[method-assign]
    monkeypatch.setattr(cli_module, "build_runtime", lambda _url: runtime)
    monkeypatch.setattr(
        cli_module, "DEFAULT_FRONTEND_DIST", built_frontend, raising=False
    )

    result = CliRunner().invoke(main, ["serve", "--no-open"])

    assert result.exit_code == 1
    assert "migration" in result.output.casefold()
    assert "alembic upgrade head" in result.output
    assert "close-token" not in result.output


def test_close_failure_never_masks_the_uvicorn_error(
    monkeypatch: pytest.MonkeyPatch, built_frontend: Path
) -> None:
    """Fails if cleanup replaces a primary server startup/runtime exception."""

    runtime = FakeRuntime()
    uvicorn_error = RuntimeError("uvicorn-primary")

    def reject_close() -> None:
        raise RuntimeError("close-secondary")

    runtime.close = reject_close  # type: ignore[method-assign]
    monkeypatch.setattr(cli_module, "build_runtime", lambda _url: runtime)
    monkeypatch.setattr(
        cli_module, "DEFAULT_FRONTEND_DIST", built_frontend, raising=False
    )
    monkeypatch.setattr(
        cli_module, "resolve_local_timezone", lambda: PARIS, raising=False
    )
    monkeypatch.setattr(
        cli_module, "_read_launch_agent_schedule", lambda: (8, 0), raising=False
    )
    monkeypatch.setattr(
        "uvicorn.run", lambda _app, **_kwargs: (_ for _ in ()).throw(uvicorn_error)
    )

    result = CliRunner().invoke(main, ["serve", "--no-open"])

    assert result.exception is uvicorn_error


def test_close_failure_alone_becomes_an_actionable_french_error(
    monkeypatch: pytest.MonkeyPatch, built_frontend: Path
) -> None:
    """Fails if a lone cleanup failure escapes without an actionable CLI message."""

    runtime = FakeRuntime()

    def reject_close() -> None:
        raise RuntimeError("close-token=secret")

    runtime.close = reject_close  # type: ignore[method-assign]
    monkeypatch.setattr(cli_module, "build_runtime", lambda _url: runtime)
    monkeypatch.setattr(
        cli_module, "DEFAULT_FRONTEND_DIST", built_frontend, raising=False
    )
    monkeypatch.setattr(
        cli_module, "resolve_local_timezone", lambda: PARIS, raising=False
    )
    monkeypatch.setattr(
        cli_module, "_read_launch_agent_schedule", lambda: (8, 0), raising=False
    )
    monkeypatch.setattr("uvicorn.run", lambda _app, **_kwargs: None)

    result = CliRunner().invoke(main, ["serve", "--no-open"])

    assert result.exit_code == 1
    assert "fermer" in result.output.casefold()
    assert "ressources" in result.output.casefold()
    assert "close-token" not in result.output


def test_schedule_defaults_only_when_the_user_plist_is_absent(tmp_path: Path) -> None:
    """Fails if an absent installation prevents the documented 08:00 default."""

    assert cli_module._read_launch_agent_schedule(tmp_path / "absent.plist") == (8, 0)


def test_schedule_reads_the_custom_user_plist(tmp_path: Path) -> None:
    """Fails if serve ignores the hour/minute installed for launchd."""

    plist_path = tmp_path / "daily.plist"
    plist_path.write_bytes(
        plistlib.dumps({"StartCalendarInterval": {"Hour": 6, "Minute": 23}})
    )

    assert cli_module._read_launch_agent_schedule(plist_path) == (6, 23)


def test_corrupt_schedule_is_actionable_instead_of_silently_defaulting(
    monkeypatch: pytest.MonkeyPatch, built_frontend: Path, tmp_path: Path
) -> None:
    """Fails if corrupt automation configuration silently becomes 08:00."""

    plist_path = tmp_path / "daily.plist"
    plist_path.write_bytes(b"not-a-plist")
    monkeypatch.setattr(
        cli_module, "DEFAULT_FRONTEND_DIST", built_frontend, raising=False
    )
    monkeypatch.setattr(
        cli_module, "installed_launch_agent_path", lambda: plist_path, raising=False
    )
    monkeypatch.setattr(
        cli_module,
        "build_runtime",
        lambda _url: pytest.fail("la base ne doit pas démarrer avec un plist corrompu"),
    )

    result = CliRunner().invoke(main, ["serve", "--no-open"])

    assert result.exit_code == 1
    assert "plist" in result.output.casefold()
    assert "jobscraper automation install" in result.output


def test_schedule_rejects_a_redirected_user_plist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fails if serve follows a managed plist symlink outside LaunchAgents."""

    home = tmp_path / "home"
    launch_agents = home / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True)
    external = tmp_path / "external.plist"
    external.write_bytes(
        plistlib.dumps({"StartCalendarInterval": {"Hour": 5, "Minute": 12}})
    )
    managed = launch_agents / "com.jobscraper.daily-sync.plist"
    managed.symlink_to(external)
    monkeypatch.setattr(
        cli_module,
        "installed_launch_agent_path",
        lambda: installed_launch_agent_path(home),
    )

    with pytest.raises(cli_module.click.ClickException, match="plist launchd"):
        cli_module._read_launch_agent_schedule()


def test_browser_opens_loopback_only_after_readiness_while_binding_requested_host(
    monkeypatch: pytest.MonkeyPatch, built_frontend: Path
) -> None:
    """Fails if serve opens a wildcard URL, opens early, or ignores host/port."""

    runtime = FakeRuntime()
    reachable = Event()
    opened = Event()
    observed: dict[str, object] = {}

    def fake_wait(host: str, port: int, cancelled: Event) -> bool:
        assert host == "127.0.0.1"
        assert port == 4567
        assert not cancelled.is_set()
        reachable.set()
        return True

    def fake_open(url: str) -> bool:
        assert reachable.is_set()
        observed["url"] = url
        opened.set()
        return True

    def fake_uvicorn_run(_app: object, **kwargs: object) -> None:
        observed.update(kwargs)
        assert opened.wait(timeout=1)

    monkeypatch.setattr(cli_module, "build_runtime", lambda _url: runtime)
    monkeypatch.setattr(
        cli_module, "DEFAULT_FRONTEND_DIST", built_frontend, raising=False
    )
    monkeypatch.setattr(
        cli_module, "resolve_local_timezone", lambda: PARIS, raising=False
    )
    monkeypatch.setattr(
        cli_module, "_read_launch_agent_schedule", lambda: (8, 0), raising=False
    )
    monkeypatch.setattr(
        cli_module,
        "_local_now",
        lambda _timezone: datetime(2026, 8, 3, 7, 0, tzinfo=PARIS),
        raising=False,
    )
    monkeypatch.setattr(cli_module, "_wait_until_reachable", fake_wait, raising=False)
    monkeypatch.setattr("webbrowser.open", fake_open)
    monkeypatch.setattr("uvicorn.run", fake_uvicorn_run)

    result = CliRunner().invoke(main, ["serve", "--host", "0.0.0.0", "--port", "4567"])

    assert result.exit_code == 0, result.output
    assert observed == {
        "host": "0.0.0.0",
        "port": 4567,
        "url": "http://127.0.0.1:4567",
    }


@pytest.mark.parametrize(
    ("bind_host", "probe_host", "browser_url"),
    [
        ("::", "::1", "http://[::1]:4568"),
        ("192.0.2.10", "192.0.2.10", "http://192.0.2.10:4568"),
        ("2001:db8::10", "2001:db8::10", "http://[2001:db8::10]:4568"),
    ],
)
def test_browser_probe_matches_ipv6_wildcard_or_concrete_bind_host(
    monkeypatch: pytest.MonkeyPatch,
    built_frontend: Path,
    bind_host: str,
    probe_host: str,
    browser_url: str,
) -> None:
    """Fails if a concrete bind is probed through unrelated IPv4 loopback."""

    runtime = FakeRuntime()
    opened = Event()
    observed: dict[str, object] = {}

    def fake_wait(host: str, port: int, _cancelled: Event) -> bool:
        observed["probe"] = (host, port)
        return True

    def fake_open(url: str) -> bool:
        observed["url"] = url
        opened.set()
        return True

    def fake_uvicorn_run(_app: object, **kwargs: object) -> None:
        observed["bind"] = (kwargs["host"], kwargs["port"])
        assert opened.wait(timeout=1)

    monkeypatch.setattr(cli_module, "build_runtime", lambda _url: runtime)
    monkeypatch.setattr(
        cli_module, "DEFAULT_FRONTEND_DIST", built_frontend, raising=False
    )
    monkeypatch.setattr(
        cli_module, "resolve_local_timezone", lambda: PARIS, raising=False
    )
    monkeypatch.setattr(
        cli_module, "_read_launch_agent_schedule", lambda: (8, 0), raising=False
    )
    monkeypatch.setattr(
        cli_module,
        "_local_now",
        lambda _timezone: datetime(2026, 8, 3, 7, 0, tzinfo=PARIS),
        raising=False,
    )
    monkeypatch.setattr(cli_module, "_wait_until_reachable", fake_wait)
    monkeypatch.setattr("webbrowser.open", fake_open)
    monkeypatch.setattr("uvicorn.run", fake_uvicorn_run)

    result = CliRunner().invoke(main, ["serve", "--host", bind_host, "--port", "4568"])

    assert result.exit_code == 0, result.output
    assert observed == {
        "bind": (bind_host, 4568),
        "probe": (probe_host, 4568),
        "url": browser_url,
    }


def test_no_open_never_starts_browser_readiness_work(
    monkeypatch: pytest.MonkeyPatch, built_frontend: Path
) -> None:
    """Fails if --no-open leaves browser/socket work running in automation."""

    runtime = FakeRuntime()
    monkeypatch.setattr(cli_module, "build_runtime", lambda _url: runtime)
    monkeypatch.setattr(
        cli_module, "DEFAULT_FRONTEND_DIST", built_frontend, raising=False
    )
    monkeypatch.setattr(
        cli_module, "resolve_local_timezone", lambda: PARIS, raising=False
    )
    monkeypatch.setattr(
        cli_module, "_read_launch_agent_schedule", lambda: (8, 0), raising=False
    )
    monkeypatch.setattr(
        cli_module,
        "_local_now",
        lambda _timezone: datetime(2026, 8, 3, 7, 0, tzinfo=PARIS),
        raising=False,
    )
    monkeypatch.setattr(
        cli_module,
        "_wait_until_reachable",
        lambda *_args: pytest.fail("--no-open ne doit pas attendre le socket"),
        raising=False,
    )
    monkeypatch.setattr(
        "webbrowser.open",
        lambda _url: pytest.fail("--no-open ne doit pas ouvrir le navigateur"),
    )
    monkeypatch.setattr("uvicorn.run", lambda _app, **_kwargs: None)

    result = CliRunner().invoke(main, ["serve", "--no-open"])

    assert result.exit_code == 0, result.output


def test_explicit_timezone_uses_an_iana_zone() -> None:
    """Fails if JOBSCRAPER_TIMEZONE is ignored or converted to a fixed offset."""

    timezone_value = resolve_local_timezone(
        environ={"JOBSCRAPER_TIMEZONE": "Europe/Paris"}
    )

    assert timezone_value.key == "Europe/Paris"


def test_local_timezone_is_detected_from_a_unix_zoneinfo_symlink(
    tmp_path: Path,
) -> None:
    """Fails if local detection loses the IANA key needed for DST."""

    zone_root = tmp_path / "usr" / "share" / "zoneinfo"
    zone_file = zone_root / "Europe" / "Paris"
    zone_file.parent.mkdir(parents=True)
    zone_file.write_bytes(b"fixture")
    localtime = tmp_path / "etc" / "localtime"
    localtime.parent.mkdir()
    localtime.symlink_to(zone_file)

    timezone_value = resolve_local_timezone(
        environ={},
        localtime_path=localtime,
        timezone_file=tmp_path / "missing-timezone",
    )

    assert timezone_value.key == "Europe/Paris"


def test_timezone_detection_failure_is_actionable_and_never_uses_fixed_offset(
    tmp_path: Path,
) -> None:
    """Fails if an unknown local timezone silently becomes DST-unsafe."""

    with pytest.raises(RuntimeError, match="JOBSCRAPER_TIMEZONE"):
        resolve_local_timezone(
            environ={},
            localtime_path=tmp_path / "missing-localtime",
            timezone_file=tmp_path / "missing-timezone",
        )
