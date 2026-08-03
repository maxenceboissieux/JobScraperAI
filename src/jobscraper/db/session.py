"""SQLite engine and session factory construction."""

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

# Importing models registers every table on Base.metadata for create_all and Alembic.
from jobscraper.db import models as _models  # noqa: F401


def create_engine_and_session(
    database_url: str,
) -> tuple[Engine, sessionmaker[Session]]:
    """Create a SQLite engine and a reusable, explicitly transactional sessionmaker."""

    url = URL.create("sqlite") if database_url == "sqlite://" else database_url
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False},
    )

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
