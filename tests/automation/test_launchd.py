from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

import jobscraper.cli as cli_module
from jobscraper.automation.launchd import (
    LAUNCH_AGENT_FILENAME,
    LAUNCH_AGENT_LABEL,
    AutomationError,
    get_launch_agent_status,
    install_launch_agent,
    installed_launch_agent_path,
    read_launch_agent_schedule,
    render_launch_agent,
    uninstall_launch_agent,
)
from jobscraper.cli import main


def test_render_launch_agent_builds_safe_deterministic_plist(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    python_path = tmp_path / "venv" / "bin" / "python"

    plist = plistlib.loads(
        render_launch_agent(project_dir, python_path, hour=8, minute=5)
    )

    assert plist == {
        "Label": "com.jobscraper.daily-sync",
        "ProgramArguments": [
            str(python_path),
            "-m",
            "jobscraper.cli",
            "sync-saved-searches",
        ],
        "RunAtLoad": False,
        "StartCalendarInterval": {"Hour": 8, "Minute": 5},
        "StandardErrorPath": str(project_dir / "data/logs/launchd.err.log"),
        "StandardOutPath": str(project_dir / "data/logs/launchd.out.log"),
        "WorkingDirectory": str(project_dir),
    }


def test_render_launch_agent_resolves_project_and_python_paths(tmp_path: Path) -> None:
    project_dir = tmp_path / "folder" / ".." / "project"
    python_path = tmp_path / "venv" / "bin" / ".." / "bin" / "python"

    plist = plistlib.loads(
        render_launch_agent(project_dir, python_path, hour=0, minute=59)
    )

    assert plist["WorkingDirectory"] == str(project_dir.resolve())
    assert plist["ProgramArguments"][0] == str(python_path.resolve())


@pytest.mark.parametrize("hour", [-1, 24])
def test_render_launch_agent_rejects_invalid_hour(tmp_path: Path, hour: int) -> None:
    with pytest.raises(ValueError, match="heure"):
        render_launch_agent(tmp_path, tmp_path / "python", hour=hour, minute=0)


@pytest.mark.parametrize("minute", [-1, 60])
def test_render_launch_agent_rejects_invalid_minute(
    tmp_path: Path, minute: int
) -> None:
    with pytest.raises(ValueError, match="minute"):
        render_launch_agent(tmp_path, tmp_path / "python", hour=8, minute=minute)


def test_installed_launch_agent_path_is_the_exact_user_plist(tmp_path: Path) -> None:
    assert installed_launch_agent_path(tmp_path) == (
        tmp_path / "Library" / "LaunchAgents" / LAUNCH_AGENT_FILENAME
    )
    assert LAUNCH_AGENT_LABEL == "com.jobscraper.daily-sync"


def test_read_launch_agent_schedule_reads_custom_installed_interval(
    tmp_path: Path,
) -> None:
    plist_path = tmp_path / LAUNCH_AGENT_FILENAME
    plist_path.write_bytes(
        render_launch_agent(tmp_path, tmp_path / "python", hour=6, minute=37)
    )

    assert read_launch_agent_schedule(plist_path) == (6, 37)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"StartCalendarInterval": {"Hour": 24, "Minute": 0}},
        {"StartCalendarInterval": {"Hour": 8, "Minute": 60}},
        {"StartCalendarInterval": {"Hour": "8", "Minute": 0}},
    ],
)
def test_read_launch_agent_schedule_rejects_missing_or_invalid_interval(
    tmp_path: Path, payload: dict[str, object]
) -> None:
    plist_path = tmp_path / LAUNCH_AGENT_FILENAME
    plist_path.write_bytes(plistlib.dumps(payload))

    with pytest.raises(ValueError, match="calendrier"):
        read_launch_agent_schedule(plist_path)


def _result(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def _install_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    home = tmp_path / "home"
    project_dir = tmp_path / "project"
    python_path = project_dir / ".venv" / "bin" / "python"
    (project_dir / "src" / "jobscraper").mkdir(parents=True)
    (project_dir / "src" / "jobscraper" / "cli.py").write_text("", encoding="utf-8")
    (project_dir / "pyproject.toml").write_text(
        '[project]\nname = "jobscraper"\n', encoding="utf-8"
    )
    python_path.parent.mkdir(parents=True)
    python_path.write_text("#!/bin/sh\n", encoding="utf-8")
    python_path.chmod(0o700)
    return home, project_dir, python_path


def test_install_validates_everything_before_mutating_or_running_launchctl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    runner = Mock(side_effect=AssertionError("launchctl ne doit pas être appelé"))
    monkeypatch.setattr("jobscraper.automation.launchd.subprocess.run", runner)

    with pytest.raises(AutomationError, match="projet"):
        install_launch_agent(
            tmp_path / "missing-project",
            tmp_path / "missing-python",
            hour=8,
            minute=0,
            home=home,
            uid=501,
        )

    assert not (home / "Library").exists()
    runner.assert_not_called()


def test_install_rejects_invalid_schedule_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, project_dir, python_path = _install_inputs(tmp_path)
    runner = Mock(side_effect=AssertionError("launchctl ne doit pas être appelé"))
    monkeypatch.setattr("jobscraper.automation.launchd.subprocess.run", runner)

    with pytest.raises(ValueError, match="heure"):
        install_launch_agent(
            project_dir,
            python_path,
            hour=24,
            minute=0,
            home=home,
            uid=501,
        )

    assert not (home / "Library").exists()
    assert not (project_dir / "data").exists()
    runner.assert_not_called()


def test_install_rejects_unrelated_directory_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    unrelated_dir = tmp_path / "unrelated"
    python_path = unrelated_dir / "python"
    unrelated_dir.mkdir()
    python_path.write_text("#!/bin/sh\n", encoding="utf-8")
    python_path.chmod(0o700)
    runner = Mock(side_effect=AssertionError("launchctl ne doit pas être appelé"))
    monkeypatch.setattr("jobscraper.automation.launchd.subprocess.run", runner)

    with pytest.raises(AutomationError, match="JobScraper"):
        install_launch_agent(
            unrelated_dir,
            python_path,
            hour=8,
            minute=0,
            home=home,
            uid=501,
        )

    assert not (home / "Library").exists()
    assert not (unrelated_dir / "data").exists()
    runner.assert_not_called()


def test_install_writes_user_plist_and_bootstraps_with_exact_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, project_dir, python_path = _install_inputs(tmp_path)
    plist_path = installed_launch_agent_path(home)
    runner = Mock(
        side_effect=[
            _result(113, stderr="Could not find service"),
            _result(),
        ]
    )
    monkeypatch.setattr("jobscraper.automation.launchd.subprocess.run", runner)

    installed = install_launch_agent(
        project_dir,
        python_path,
        hour=8,
        minute=5,
        home=home,
        uid=501,
    )

    assert installed == plist_path
    assert read_launch_agent_schedule(plist_path) == (8, 5)
    assert (project_dir / "data" / "logs").is_dir()
    assert plist_path.stat().st_mode & 0o777 == 0o600
    assert list(plist_path.parent.glob(f".{LAUNCH_AGENT_FILENAME}.*")) == []
    assert [call.args[0] for call in runner.call_args_list] == [
        ["launchctl", "print", "gui/501/com.jobscraper.daily-sync"],
        ["launchctl", "bootstrap", "gui/501", str(plist_path)],
    ]
    for call in runner.call_args_list:
        assert call.kwargs == {
            "capture_output": True,
            "check": False,
            "text": True,
        }


def test_reinstall_boots_out_loaded_agent_before_replacing_and_bootstrapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, project_dir, python_path = _install_inputs(tmp_path)
    plist_path = installed_launch_agent_path(home)
    plist_path.parent.mkdir(parents=True)
    plist_path.write_bytes(
        render_launch_agent(project_dir, python_path, hour=7, minute=0)
    )
    runner = Mock(
        side_effect=[
            _result(stdout="state = running\npid = 42\n"),
            _result(),
            _result(),
        ]
    )
    monkeypatch.setattr("jobscraper.automation.launchd.subprocess.run", runner)

    install_launch_agent(
        project_dir,
        python_path,
        hour=9,
        minute=30,
        home=home,
        uid=501,
    )

    assert read_launch_agent_schedule(plist_path) == (9, 30)
    assert [call.args[0] for call in runner.call_args_list] == [
        ["launchctl", "print", "gui/501/com.jobscraper.daily-sync"],
        ["launchctl", "bootout", "gui/501/com.jobscraper.daily-sync"],
        ["launchctl", "bootstrap", "gui/501", str(plist_path)],
    ]


def test_reinstall_boots_out_an_existing_but_not_loaded_plist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, project_dir, python_path = _install_inputs(tmp_path)
    plist_path = installed_launch_agent_path(home)
    plist_path.parent.mkdir(parents=True)
    plist_path.write_bytes(b"ancien plist")
    runner = Mock(
        side_effect=[
            _result(113, stderr="Could not find service"),
            _result(113, stderr="Could not find service"),
            _result(),
        ]
    )
    monkeypatch.setattr("jobscraper.automation.launchd.subprocess.run", runner)

    install_launch_agent(
        project_dir,
        python_path,
        hour=9,
        minute=30,
        home=home,
        uid=501,
    )

    assert [call.args[0] for call in runner.call_args_list] == [
        ["launchctl", "print", "gui/501/com.jobscraper.daily-sync"],
        ["launchctl", "bootout", "gui/501/com.jobscraper.daily-sync"],
        ["launchctl", "bootstrap", "gui/501", str(plist_path)],
    ]


def test_failed_bootstrap_restores_and_reloads_previous_plist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, project_dir, python_path = _install_inputs(tmp_path)
    plist_path = installed_launch_agent_path(home)
    plist_path.parent.mkdir(parents=True)
    previous = render_launch_agent(project_dir, python_path, hour=7, minute=15)
    plist_path.write_bytes(previous)
    runner = Mock(
        side_effect=[
            _result(stdout="state = running\n"),
            _result(),
            _result(5, stderr="Bootstrap failed: Input/output error"),
            _result(113, stderr="Could not find service"),
            _result(),
        ]
    )
    monkeypatch.setattr("jobscraper.automation.launchd.subprocess.run", runner)

    with pytest.raises(AutomationError, match="Bootstrap failed"):
        install_launch_agent(
            project_dir,
            python_path,
            hour=10,
            minute=45,
            home=home,
            uid=501,
        )

    assert plist_path.read_bytes() == previous
    assert [call.args[0] for call in runner.call_args_list] == [
        ["launchctl", "print", "gui/501/com.jobscraper.daily-sync"],
        ["launchctl", "bootout", "gui/501/com.jobscraper.daily-sync"],
        ["launchctl", "bootstrap", "gui/501", str(plist_path)],
        ["launchctl", "bootout", "gui/501/com.jobscraper.daily-sync"],
        ["launchctl", "bootstrap", "gui/501", str(plist_path)],
    ]


def test_failed_first_bootstrap_removes_only_the_new_plist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, project_dir, python_path = _install_inputs(tmp_path)
    plist_path = installed_launch_agent_path(home)
    sibling = plist_path.parent / "com.example.other.plist"
    runner = Mock(
        side_effect=[
            _result(113, stderr="Could not find service"),
            _result(5, stderr="Bootstrap failed"),
            _result(113, stderr="Could not find service"),
        ]
    )
    monkeypatch.setattr("jobscraper.automation.launchd.subprocess.run", runner)
    plist_path.parent.mkdir(parents=True)
    sibling.write_bytes(b"autre agent")

    with pytest.raises(AutomationError, match="Bootstrap failed"):
        install_launch_agent(
            project_dir,
            python_path,
            hour=8,
            minute=0,
            home=home,
            uid=501,
        )

    assert not plist_path.exists()
    assert sibling.read_bytes() == b"autre agent"


def test_missing_launchctl_is_reported_as_a_french_automation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = Mock(side_effect=FileNotFoundError("launchctl"))
    monkeypatch.setattr("jobscraper.automation.launchd.subprocess.run", runner)

    with pytest.raises(AutomationError, match="launchctl"):
        get_launch_agent_status(home=tmp_path / "home", uid=501)


def test_unexpected_bootout_error_preserves_previous_plist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, project_dir, python_path = _install_inputs(tmp_path)
    plist_path = installed_launch_agent_path(home)
    plist_path.parent.mkdir(parents=True)
    plist_path.write_bytes(b"ancien plist")
    runner = Mock(
        side_effect=[
            _result(stdout="state = waiting\n"),
            _result(1, stderr="Operation not permitted"),
        ]
    )
    monkeypatch.setattr("jobscraper.automation.launchd.subprocess.run", runner)

    with pytest.raises(AutomationError, match="Operation not permitted"):
        install_launch_agent(
            project_dir,
            python_path,
            hour=8,
            minute=0,
            home=home,
            uid=501,
        )

    assert plist_path.read_bytes() == b"ancien plist"


def test_status_parses_loaded_state_and_installed_schedule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, project_dir, python_path = _install_inputs(tmp_path)
    plist_path = installed_launch_agent_path(home)
    plist_path.parent.mkdir(parents=True)
    plist_path.write_bytes(
        render_launch_agent(project_dir, python_path, hour=6, minute=20)
    )
    runner = Mock(return_value=_result(stdout="state = running\npid = 42\n"))
    monkeypatch.setattr("jobscraper.automation.launchd.subprocess.run", runner)

    status = get_launch_agent_status(home=home, uid=501)

    assert status.loaded is True
    assert status.plist_exists is True
    assert status.state == "running"
    assert status.schedule == (6, 20)
    assert runner.call_args.args[0] == [
        "launchctl",
        "print",
        "gui/501/com.jobscraper.daily-sync",
    ]


def test_status_recognizes_explicit_not_loaded_without_confusing_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = Mock(return_value=_result(113, stderr="Could not find service"))
    monkeypatch.setattr("jobscraper.automation.launchd.subprocess.run", runner)

    status = get_launch_agent_status(home=tmp_path / "home", uid=501)

    assert status.loaded is False
    assert status.plist_exists is False
    assert status.state is None
    assert status.schedule is None


@pytest.mark.parametrize(
    ("returncode", "stderr"),
    [(5, "Input/output error"), (113, "")],
)
def test_status_propagates_unexpected_launchctl_failures_in_french(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stderr: str,
) -> None:
    runner = Mock(return_value=_result(returncode, stderr=stderr))
    monkeypatch.setattr("jobscraper.automation.launchd.subprocess.run", runner)

    with pytest.raises(AutomationError, match="état"):
        get_launch_agent_status(home=tmp_path / "home", uid=501)


def test_uninstall_boots_out_before_deleting_only_the_managed_plist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    plist_path = installed_launch_agent_path(home)
    sibling = plist_path.parent / "com.example.other.plist"
    plist_path.parent.mkdir(parents=True)
    plist_path.write_bytes(b"jobscraper")
    sibling.write_bytes(b"autre agent")
    runner = Mock(return_value=_result())
    monkeypatch.setattr("jobscraper.automation.launchd.subprocess.run", runner)

    removed = uninstall_launch_agent(home=home, uid=501)

    assert removed is True
    assert not plist_path.exists()
    assert sibling.read_bytes() == b"autre agent"
    assert runner.call_args.args[0] == [
        "launchctl",
        "bootout",
        "gui/501/com.jobscraper.daily-sync",
    ]


def test_uninstall_is_idempotent_when_agent_is_not_loaded_or_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = Mock(return_value=_result(113, stderr="Could not find service"))
    monkeypatch.setattr("jobscraper.automation.launchd.subprocess.run", runner)

    assert uninstall_launch_agent(home=tmp_path / "home", uid=501) is False


def test_uninstall_preserves_plist_on_unexpected_bootout_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    plist_path = installed_launch_agent_path(home)
    plist_path.parent.mkdir(parents=True)
    plist_path.write_bytes(b"jobscraper")
    runner = Mock(return_value=_result(1, stderr="Operation not permitted"))
    monkeypatch.setattr("jobscraper.automation.launchd.subprocess.run", runner)

    with pytest.raises(AutomationError, match="Operation not permitted"):
        uninstall_launch_agent(home=home, uid=501)

    assert plist_path.read_bytes() == b"jobscraper"


def test_cli_help_keeps_legacy_commands_and_adds_automation_group() -> None:
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "automation" in result.output
    assert "search" in result.output
    assert "sync-saved-searches" in result.output


def test_cli_automation_install_uses_current_project_and_interpreter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installer = Mock(return_value=Path("/tmp/com.jobscraper.daily-sync.plist"))
    monkeypatch.setattr(cli_module, "install_launch_agent", installer, raising=False)

    result = CliRunner().invoke(
        main, ["automation", "install", "--hour", "6", "--minute", "25"]
    )

    assert result.exit_code == 0
    assert "06:25" in result.output
    installer.assert_called_once_with(
        Path.cwd(), Path(sys.executable), hour=6, minute=25
    )


def test_cli_automation_install_rejects_invalid_time_before_installing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installer = Mock()
    monkeypatch.setattr(cli_module, "install_launch_agent", installer, raising=False)

    result = CliRunner().invoke(
        main, ["automation", "install", "--hour", "24", "--minute", "0"]
    )

    assert result.exit_code == 2
    installer.assert_not_called()


def test_cli_automation_errors_are_reported_in_french(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installer = Mock(side_effect=AutomationError("launchctl est indisponible"))
    monkeypatch.setattr(cli_module, "install_launch_agent", installer, raising=False)

    result = CliRunner().invoke(main, ["automation", "install"])

    assert result.exit_code == 1
    assert "launchctl est indisponible" in result.output


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (
            SimpleNamespace(
                loaded=True,
                plist_exists=True,
                state="running",
                schedule=(6, 20),
            ),
            "active",
        ),
        (
            SimpleNamespace(
                loaded=False,
                plist_exists=True,
                state=None,
                schedule=(7, 30),
            ),
            "inactive",
        ),
        (
            SimpleNamespace(
                loaded=False,
                plist_exists=False,
                state=None,
                schedule=None,
            ),
            "non installée",
        ),
    ],
)
def test_cli_automation_status_reports_french_state(
    monkeypatch: pytest.MonkeyPatch, status: object, expected: str
) -> None:
    status_reader = Mock(return_value=status)
    monkeypatch.setattr(
        cli_module, "get_launch_agent_status", status_reader, raising=False
    )

    result = CliRunner().invoke(main, ["automation", "status"])

    assert result.exit_code == 0
    assert expected in result.output
    if getattr(status, "schedule") is not None:
        hour, minute = getattr(status, "schedule")
        assert f"{hour:02d}:{minute:02d}" in result.output


@pytest.mark.parametrize(
    ("removed", "expected"),
    [(True, "désinstallée"), (False, "déjà absente")],
)
def test_cli_automation_uninstall_is_french_and_idempotent(
    monkeypatch: pytest.MonkeyPatch, removed: bool, expected: str
) -> None:
    uninstaller = Mock(return_value=removed)
    monkeypatch.setattr(
        cli_module, "uninstall_launch_agent", uninstaller, raising=False
    )

    result = CliRunner().invoke(main, ["automation", "uninstall"])

    assert result.exit_code == 0
    assert expected in result.output
    uninstaller.assert_called_once_with()
