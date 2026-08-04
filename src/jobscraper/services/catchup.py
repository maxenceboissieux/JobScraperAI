"""Calendar-aware missed synchronization detection."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from loguru import logger

from jobscraper.services.sync import ActiveSyncRunError

if TYPE_CHECKING:
    from jobscraper.runtime import RuntimeServices


def resolve_local_timezone(
    environ: Mapping[str, str] | None = None,
    *,
    localtime_path: Path = Path("/etc/localtime"),
    timezone_file: Path = Path("/etc/timezone"),
) -> ZoneInfo:
    """Resolve the configured or system-local IANA timezone."""

    environment = os.environ if environ is None else environ
    configured = environment.get("JOBSCRAPER_TIMEZONE")
    if configured is not None:
        return _load_timezone(configured)

    candidates: list[str] = []
    try:
        resolved = localtime_path.resolve(strict=True)
        parts = resolved.parts
        if "zoneinfo" in parts:
            index = len(parts) - 1 - list(reversed(parts)).index("zoneinfo")
            suffix = list(parts[index + 1 :])
            if suffix and suffix[0] in {"posix", "right"}:
                suffix.pop(0)
            if suffix:
                candidates.append("/".join(suffix))
    except OSError:
        pass

    try:
        timezone_key = timezone_file.read_text(encoding="utf-8").strip()
        if timezone_key:
            candidates.append(timezone_key)
    except OSError:
        pass

    for candidate in candidates:
        try:
            return ZoneInfo(candidate)
        except (ValueError, ZoneInfoNotFoundError):
            continue
    raise RuntimeError(
        "Impossible de détecter un fuseau horaire IANA local. "
        "Définissez JOBSCRAPER_TIMEZONE, par exemple Europe/Paris."
    )


def _load_timezone(key: str) -> ZoneInfo:
    try:
        if not key.strip():
            raise ValueError
        return ZoneInfo(key.strip())
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise RuntimeError(
            "JOBSCRAPER_TIMEZONE doit contenir une clé IANA valide, "
            "par exemple Europe/Paris."
        ) from exc


class CatchupService:
    """Decide whether the configured daily synchronization was missed."""

    def is_due(
        self,
        now: datetime,
        last_completed_at: datetime | None,
        scheduled_hour: int = 8,
        scheduled_minute: int = 0,
    ) -> bool:
        """Return whether today's daily synchronization still needs to run."""

        self._require_aware(now)
        if last_completed_at is not None:
            self._require_aware(last_completed_at)

        scheduled_at = now.replace(
            hour=scheduled_hour,
            minute=scheduled_minute,
            second=0,
            microsecond=0,
            fold=0,
        )
        scheduled_utc = scheduled_at.astimezone(timezone.utc)
        if now.astimezone(timezone.utc) < scheduled_utc:
            return False
        return last_completed_at is None or (
            last_completed_at.astimezone(timezone.utc) < scheduled_utc
        )

    @staticmethod
    def _require_aware(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("La date doit inclure un fuseau horaire.")

    def run_if_due(
        self,
        runtime: RuntimeServices,
        *,
        now: datetime,
        scheduled_hour: int = 8,
        scheduled_minute: int = 0,
    ) -> bool:
        """Run every active search when any one missed today's synchronization."""

        with runtime.session_services() as services:
            searches = services.saved_searches.list(active=True)
            due = any(
                self.is_due(
                    now,
                    services.sync_runs.latest_completed_at(saved_search.id),
                    scheduled_hour,
                    scheduled_minute,
                )
                for saved_search in searches
            )
            if not due:
                return False
            for saved_search in searches:
                try:
                    services.sync_service.run(saved_search.id, reject_active=True)
                except ActiveSyncRunError:
                    logger.info(
                        "Rattrapage ignoré pour la recherche {} : "
                        "une synchronisation est déjà active",
                        saved_search.id,
                    )
        return True
