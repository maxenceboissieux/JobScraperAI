"""SQLite engine and session factory construction."""

from uuid import uuid4

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

# Importing models registers every table on Base.metadata for create_all and Alembic.
from jobscraper.db import models as _models  # noqa: F401


def create_engine_and_session(
    database_url: str,
) -> tuple[Engine, sessionmaker[Session]]:
    """Create a SQLite engine and a reusable, explicitly transactional sessionmaker."""

    url = database_url
    options: dict[str, object] = {"connect_args": {"check_same_thread": False}}
    if database_url == "sqlite://":
        # A named shared-memory database is visible to every pooled connection,
        # while each concurrent Session retains its own transaction boundary.
        memory_name = f"jobscraper-{uuid4().hex}"
        url = f"sqlite:///file:{memory_name}" "?mode=memory&cache=shared&uri=true"
        options["poolclass"] = QueuePool
    engine = create_engine(url, **options)

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    factory = sessionmaker(
        bind=engine,
        class_=Session,
        expire_on_commit=False,
    )
    return engine, factory
