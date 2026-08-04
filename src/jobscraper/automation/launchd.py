"""Intégration utilisateur avec launchd sur macOS."""

import os
import plistlib
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LAUNCH_AGENT_LABEL = "com.jobscraper.daily-sync"
LAUNCH_AGENT_FILENAME = f"{LAUNCH_AGENT_LABEL}.plist"


class AutomationError(RuntimeError):
    """Raised when launchd cannot safely complete an automation operation."""


@dataclass(frozen=True)
class LaunchAgentStatus:
    """User-visible launch agent state."""

    loaded: bool
    plist_exists: bool
    state: str | None
    schedule: tuple[int, int] | None


def installed_launch_agent_path(home: Path | None = None) -> Path:
    """Return the single user-scoped plist path managed by JobScraper."""

    return _validated_user_plist_path(home)


def _validate_schedule(hour: object, minute: object) -> tuple[int, int]:
    if type(hour) is not int or not 0 <= hour <= 23:
        raise ValueError("L’heure doit être comprise entre 0 et 23.")
    if type(minute) is not int or not 0 <= minute <= 59:
        raise ValueError("La minute doit être comprise entre 0 et 59.")
    return hour, minute


def render_launch_agent(
    project_dir: Path, python_path: Path, hour: int, minute: int
) -> bytes:
    """Render a launch agent without consulting or mutating system state."""

    validated_hour, validated_minute = _validate_schedule(hour, minute)
    resolved_project = project_dir.resolve()
    resolved_python = python_path.resolve()
    logs_dir = resolved_project / "data" / "logs"
    payload: dict[str, Any] = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [
            str(resolved_python),
            "-m",
            "jobscraper.cli",
            "sync-saved-searches",
        ],
        "RunAtLoad": False,
        "StartCalendarInterval": {
            "Hour": validated_hour,
            "Minute": validated_minute,
        },
        "StandardErrorPath": str(logs_dir / "launchd.err.log"),
        "StandardOutPath": str(logs_dir / "launchd.out.log"),
        "WorkingDirectory": str(resolved_project),
    }
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True)


def read_launch_agent_schedule(plist_path: Path) -> tuple[int, int]:
    """Read the configured hour and minute from an installed plist."""

    try:
        payload = plistlib.loads(plist_path.read_bytes())
        interval = payload["StartCalendarInterval"]
        if not isinstance(interval, dict):
            raise TypeError
        return _validate_schedule(interval["Hour"], interval["Minute"])
    except (KeyError, TypeError, ValueError, plistlib.InvalidFileException) as exc:
        raise ValueError("Le calendrier du plist launchd est invalide.") from exc


def get_launch_agent_status(
    *, home: Path | None = None, uid: int | None = None
) -> LaunchAgentStatus:
    """Inspect launchd without conflating an absent job with command failure."""

    plist_path = _validated_user_plist_path(home)
    plist_exists = _path_exists(plist_path)
    result = _run_launchctl(["print", _service_target(uid)])
    if result.returncode == 0:
        state_match = re.search(
            r"^[ \t]*state[ \t]*=[ \t]*([^\r\n]*\S)[ \t]*$",
            result.stdout,
            flags=re.MULTILINE,
        )
        schedule = _read_schedule_if_valid(plist_path) if plist_exists else None
        return LaunchAgentStatus(
            loaded=True,
            plist_exists=plist_exists,
            state=state_match.group(1).strip() if state_match else None,
            schedule=schedule,
        )
    if _is_not_loaded(result):
        schedule = _read_schedule_if_valid(plist_path) if plist_exists else None
        return LaunchAgentStatus(
            loaded=False,
            plist_exists=plist_exists,
            state=None,
            schedule=schedule,
        )
    raise AutomationError(
        "Impossible de lire l’état de l’automatisation launchd : "
        f"{_failure_detail(result)}"
    )


def install_launch_agent(
    project_dir: Path,
    python_path: Path,
    hour: int,
    minute: int,
    *,
    home: Path | None = None,
    uid: int | None = None,
) -> Path:
    """Install or replace the one JobScraper user launch agent."""

    _validate_schedule(hour, minute)
    resolved_project = project_dir.resolve()
    resolved_python = python_path.resolve()
    if not resolved_project.is_dir():
        raise AutomationError(
            f"Le répertoire du projet est introuvable : {resolved_project}"
        )
    if (
        not (resolved_project / "pyproject.toml").is_file()
        or not (resolved_project / "src" / "jobscraper" / "cli.py").is_file()
    ):
        raise AutomationError(
            "Le répertoire choisi n’est pas une racine de projet JobScraper valide : "
            f"{resolved_project}"
        )
    if not resolved_python.is_file() or not os.access(resolved_python, os.X_OK):
        raise AutomationError(
            "L’interpréteur Python est introuvable ou non exécutable : "
            f"{resolved_python}"
        )

    plist_path = _validated_user_plist_path(home)
    previous_exists = _path_exists(plist_path)
    previous_content: bytes | None = None
    previous_mode = 0o600
    if previous_exists:
        try:
            previous_content = plist_path.read_bytes()
            previous_mode = stat.S_IMODE(plist_path.stat().st_mode)
        except OSError as exc:
            raise AutomationError(
                f"Impossible de sauvegarder le plist existant : {exc}"
            ) from exc

    status = get_launch_agent_status(home=home, uid=uid)
    _prepare_runtime_directories(plist_path, resolved_project)
    if status.loaded or previous_exists:
        _bootout(uid)

    rendered = render_launch_agent(
        resolved_project, resolved_python, hour=hour, minute=minute
    )
    try:
        _atomic_write(plist_path, rendered, mode=0o600)
    except OSError as write_error:
        reactivation_error: AutomationError | None = None
        if status.loaded and previous_exists:
            try:
                _bootstrap(uid, plist_path)
            except AutomationError as exc:
                reactivation_error = exc
        reactivation_detail = (
            " Échec de la réactivation de l’ancien agent : " f"{reactivation_error}"
            if reactivation_error is not None
            else ""
        )
        raise AutomationError(
            "Impossible d’écrire le plist launchd : "
            f"{write_error}.{reactivation_detail}"
        ) from write_error

    try:
        _bootstrap(uid, plist_path)
    except AutomationError as install_error:
        restoration_errors: list[str] = []
        safe_to_reload = True
        try:
            _bootout(uid)
        except AutomationError as exc:
            restoration_errors.append(str(exc))
            safe_to_reload = False
        try:
            if previous_content is None:
                if _path_exists(plist_path):
                    plist_path.unlink()
            else:
                _atomic_write(plist_path, previous_content, mode=previous_mode)
        except OSError as exc:
            restoration_errors.append(f"restauration du plist impossible : {exc}")
            safe_to_reload = False
        if status.loaded and previous_content is not None and safe_to_reload:
            try:
                _bootstrap(uid, plist_path)
            except AutomationError as exc:
                restoration_errors.append(
                    f"rechargement de l’ancien agent impossible : {exc}"
                )
        restoration_detail = (
            " Erreurs pendant la restauration : " + "; ".join(restoration_errors)
            if restoration_errors
            else ""
        )
        raise AutomationError(f"{install_error}{restoration_detail}") from install_error
    return plist_path


def uninstall_launch_agent(*, home: Path | None = None, uid: int | None = None) -> bool:
    """Unload the agent, then remove only JobScraper's exact user plist."""

    plist_path = _validated_user_plist_path(home)
    existed = _path_exists(plist_path)
    _bootout(uid)
    if existed:
        try:
            plist_path.unlink()
        except OSError as exc:
            raise AutomationError(
                f"Impossible de supprimer le plist JobScraper : {exc}"
            ) from exc
    return existed


def _effective_uid(uid: int | None) -> int:
    return os.getuid() if uid is None else uid


def _service_target(uid: int | None) -> str:
    return f"gui/{_effective_uid(uid)}/{LAUNCH_AGENT_LABEL}"


def _domain_target(uid: int | None) -> str:
    return f"gui/{_effective_uid(uid)}"


def _run_launchctl(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    command = ["launchctl", *arguments]
    try:
        return subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError as exc:
        raise AutomationError(f"Impossible d’exécuter launchctl : {exc}") from exc


def _failure_detail(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout).strip() or (
        f"launchctl a retourné le code {result.returncode}."
    )


def _is_not_loaded(result: subprocess.CompletedProcess[str]) -> bool:
    output = f"{result.stderr}\n{result.stdout}".casefold()
    return any(
        marker in output
        for marker in (
            "could not find service",
            "could not find specified service",
            "service not found",
            "boot-out failed: 3: no such process",
        )
    )


def _bootout(uid: int | None) -> None:
    result = _run_launchctl(["bootout", _service_target(uid)])
    if result.returncode != 0 and not _is_not_loaded(result):
        raise AutomationError(
            "Impossible de désactiver l’automatisation launchd : "
            f"{_failure_detail(result)}"
        )


def _bootstrap(uid: int | None, plist_path: Path) -> None:
    result = _run_launchctl(["bootstrap", _domain_target(uid), str(plist_path)])
    if result.returncode != 0:
        raise AutomationError(
            "Impossible d’activer l’automatisation launchd : "
            f"{_failure_detail(result)}"
        )


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _prepare_runtime_directories(plist_path: Path, project_dir: Path) -> None:
    launch_agents_dir = plist_path.parent
    logs_dir = project_dir / "data" / "logs"
    try:
        launch_agents_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        launch_agents_dir.chmod(0o700)
        logs_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        logs_dir.chmod(0o700)
    except OSError as exc:
        raise AutomationError(
            "Impossible de préparer les dossiers de l’automatisation launchd : "
            f"{exc}"
        ) from exc


def _validated_user_plist_path(home: Path | None) -> Path:
    """Reject redirected user paths before any launchd or filesystem mutation."""

    user_home = (home or Path.home()).resolve()
    library_dir = user_home / "Library"
    launch_agents_dir = library_dir / "LaunchAgents"
    plist_path = launch_agents_dir / LAUNCH_AGENT_FILENAME
    try:
        for ancestor in (library_dir, launch_agents_dir):
            if ancestor.is_symlink():
                raise AutomationError(
                    "Le chemin launchd utilisateur contient un lien symbolique "
                    f"interdit : {ancestor}"
                )
            if ancestor.exists() and not ancestor.is_dir():
                raise AutomationError(
                    f"Le chemin launchd utilisateur n’est pas un dossier : {ancestor}"
                )
        if plist_path.is_symlink():
            raise AutomationError(
                "Le plist launchd géré ne peut pas être un lien symbolique : "
                f"{plist_path}"
            )
        resolved_parent = launch_agents_dir.resolve()
        resolved_parent.relative_to(user_home)
    except AutomationError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise AutomationError(
            "Le chemin launchd utilisateur sort du dossier personnel ou ne peut "
            f"pas être validé : {exc}"
        ) from exc
    return plist_path


def _read_schedule_if_valid(plist_path: Path) -> tuple[int, int] | None:
    try:
        return read_launch_agent_schedule(plist_path)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None


def _atomic_write(path: Path, content: bytes, *, mode: int) -> None:
    """Write through a permission-restricted sibling, then atomically replace."""

    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}."
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        temporary_path.chmod(mode)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)
