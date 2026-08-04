"""Shared application composition for database-backed entry points."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from alembic.config import Config as AlembicConfig
from jobscraper.db.base import Base
from jobscraper.db.session import create_engine_and_session
from jobscraper.repositories.jobs import JobRepository
from jobscraper.repositories.saved_searches import SavedSearchRepository
from jobscraper.repositories.sync_runs import SyncRunRepository
from jobscraper.scrapers.registry import ScraperRegistry
from jobscraper.services.deduplication import (
    DuplicateDecision,
    JobLike,
    classify_duplicate,
)
from jobscraper.services.details import JobDetailsService
from jobscraper.services.sync import SyncService

DEFAULT_DATABASE_URL = "sqlite:///./data/jobscraper.db"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _scraper_registry_from_environment() -> ScraperRegistry:
    """Select live adapters by default and opt into the E2E registry explicitly."""

    mode = os.getenv("JOBSCRAPER_SCRAPER_MODE", "live").strip().casefold()
    if mode in {"", "live"}:
        return ScraperRegistry()
    if mode != "fake":
        raise RuntimeError(f"Mode de scrapers inconnu : {mode}.")
    environment = os.getenv("JOBSCRAPER_ENV", "").strip().casefold()
    if environment == "production":
        raise RuntimeError("Le mode fake est interdit dans l’environnement production.")

    try:
        from jobscraper.testing.fake_scrapers import build_fake_registry

        registry = build_fake_registry()
    except Exception as exc:
        raise RuntimeError(
            "Le registry fake E2E est indisponible; vérifiez "
            "JOBSCRAPER_FAKE_NOW et JOBSCRAPER_FAKE_DETAIL_LOG."
        ) from exc
    if not isinstance(registry, ScraperRegistry):
        raise RuntimeError("Le registry fake E2E est invalide.")
    return registry


def _ensure_sqlite_parent(database_url: str) -> None:
    """Create the containing directory for a file-backed SQLite database."""

    url = make_url(database_url)
    if not url.drivername.startswith("sqlite") or url.database in {
        None,
        "",
        ":memory:",
    }:
        return
    Path(url.database).expanduser().parent.mkdir(parents=True, exist_ok=True)


@dataclass(slots=True)
class RuntimeServices:
    """Session-neutral resources shared safely by application entry points."""

    database_url: str
    engine: Engine
    session_factory: sessionmaker[Session]
    registry: ScraperRegistry
    classifier: Callable[[JobLike, JobLike], DuplicateDecision]
    _closed: bool = field(default=False, init=False, repr=False)

    def services(self, session: Session) -> SessionServices:
        """Compose one repository/service graph for a caller-owned session."""

        jobs = JobRepository(session)
        sync_runs = SyncRunRepository(session)
        return SessionServices(
            saved_searches=SavedSearchRepository(session),
            jobs=jobs,
            sync_runs=sync_runs,
            sync_service=SyncService(
                session,
                registry=self.registry,
                jobs=jobs,
                sync_runs=sync_runs,
                classifier=self.classifier,
            ),
            detail_service=JobDetailsService(
                session,
                registry=self.registry,
                jobs=jobs,
            ),
        )

    @contextmanager
    def session_services(self) -> Iterator[SessionServices]:
        """Yield a graph backed by a short-lived, rollback-safe session."""

        with self.session_factory() as session:
            try:
                yield self.services(session)
            except Exception:
                session.rollback()
                raise

    def migrate(self) -> None:
        """Bring the configured database schema to the current revision."""

        if self.database_url == "sqlite://":
            Base.metadata.create_all(self.engine)
            return
        config = AlembicConfig(str(PROJECT_ROOT / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", self.database_url)
        config.attributes["database_url"] = self.database_url
        command.upgrade(config, "head")

    def close(self) -> None:
        """Release the session and connection pool exactly once."""

        if self._closed:
            return
        try:
            self.engine.dispose()
        finally:
            self._closed = True

    def __enter__(self) -> RuntimeServices:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()


def build_runtime(database_url: str) -> RuntimeServices:
    """Compose one reusable set of database, scraper, and domain services."""

    registry = _scraper_registry_from_environment()
    _ensure_sqlite_parent(database_url)
    engine, session_factory = create_engine_and_session(database_url)
    try:
        return RuntimeServices(
            database_url=database_url,
            engine=engine,
            session_factory=session_factory,
            registry=registry,
            classifier=classify_duplicate,
        )
    except Exception:
        engine.dispose()
        raise


@dataclass(frozen=True, slots=True)
class SessionServices:
    """Repositories and services sharing exactly one caller-owned session."""

    saved_searches: SavedSearchRepository
    jobs: JobRepository
    sync_runs: SyncRunRepository
    sync_service: SyncService
    detail_service: JobDetailsService
