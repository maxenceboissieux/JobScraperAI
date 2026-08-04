"""Shared application composition for database-backed entry points."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

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
    """Resources and session-scoped services owned by one headless invocation."""

    database_url: str
    engine: Engine
    session_factory: sessionmaker[Session]
    session: Session
    saved_searches: SavedSearchRepository
    jobs: JobRepository
    sync_runs: SyncRunRepository
    registry: ScraperRegistry
    deduplicator: Callable[[JobLike, JobLike], DuplicateDecision]
    sync_service: SyncService
    detail_service: JobDetailsService
    _closed: bool = field(default=False, init=False, repr=False)

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
            self.session.close()
        finally:
            self.engine.dispose()
            self._closed = True

    def __enter__(self) -> RuntimeServices:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()


def build_runtime(database_url: str) -> RuntimeServices:
    """Compose one reusable set of database, scraper, and domain services."""

    _ensure_sqlite_parent(database_url)
    engine, session_factory = create_engine_and_session(database_url)
    session = session_factory()
    registry = ScraperRegistry()
    sync_service = SyncService(session, registry=registry)
    detail_service = JobDetailsService(session, registry=registry)
    return RuntimeServices(
        database_url=database_url,
        engine=engine,
        session_factory=session_factory,
        session=session,
        saved_searches=SavedSearchRepository(session),
        jobs=sync_service.jobs,
        sync_runs=sync_service.sync_runs,
        registry=registry,
        deduplicator=classify_duplicate,
        sync_service=sync_service,
        detail_service=detail_service,
    )
