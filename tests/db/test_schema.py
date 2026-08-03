from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import JSON, Integer, String, UniqueConstraint, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from alembic.config import Config
from jobscraper.db.base import Base
from jobscraper.db.models import CanonicalJob, DuplicateRelation
from jobscraper.db.session import create_engine_and_session

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_DUPLICATE_CHECK = "ck_duplicate_relations_canonical_order"


def test_initial_schema_has_expected_tables(tmp_path: Path) -> None:
    engine, _ = create_engine_and_session(f"sqlite:///{tmp_path / 'jobs.db'}")
    Base.metadata.create_all(engine)

    assert set(inspect(engine).get_table_names()) == {
        "saved_searches",
        "canonical_jobs",
        "source_listings",
        "search_listings",
        "duplicate_relations",
        "sync_runs",
        "source_sync_results",
    }


def test_schema_uses_internal_integer_keys_and_public_uuid_strings() -> None:
    entity_tables = {
        Base.metadata.tables[name]
        for name in (
            "saved_searches",
            "canonical_jobs",
            "source_listings",
            "sync_runs",
            "source_sync_results",
        )
    }

    for table in entity_tables:
        assert isinstance(table.c.pk.type, Integer)
        assert table.c.pk.primary_key
        assert isinstance(table.c.id.type, String)
        assert table.c.id.type.length == 36
        assert table.c.id.unique


def test_saved_search_list_filters_are_json_columns() -> None:
    saved_searches = Base.metadata.tables["saved_searches"]

    for column_name in (
        "keywords",
        "contract_types",
        "experience_levels",
        "workplace_types",
        "companies",
        "exclude_companies",
        "sources",
    ):
        assert isinstance(saved_searches.c[column_name].type, JSON)


def test_canonical_detail_provenance_is_a_required_json_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fails if ORM metadata and the initial migration drift on cache provenance."""
    canonical_jobs = Base.metadata.tables["canonical_jobs"]
    column = canonical_jobs.c.detail_provenance
    assert isinstance(column.type, JSON)
    assert not column.nullable

    database_url = f"sqlite:///{tmp_path / 'provenance.db'}"
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    monkeypatch.setenv("JOBSCRAPER_DATABASE_URL", database_url)
    command.upgrade(config, "head")
    reflected = {
        column["name"]: column
        for column in inspect(create_engine_and_session(database_url)[0]).get_columns(
            "canonical_jobs"
        )
    }

    assert "detail_provenance" in reflected
    assert isinstance(reflected["detail_provenance"]["type"], JSON)
    assert not reflected["detail_provenance"]["nullable"]


def test_required_unique_constraints_are_declared() -> None:
    listings = Base.metadata.tables["source_listings"]
    relations = Base.metadata.tables["duplicate_relations"]

    listing_uniques = {
        tuple(constraint.columns.keys())
        for constraint in listings.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    relation_uniques = {
        tuple(constraint.columns.keys())
        for constraint in relations.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("source", "external_id") in listing_uniques
    assert ("left_job_id", "right_job_id") in relation_uniques


def _reflected_duplicate_check_names(database_url: str) -> set[str]:
    engine, _ = create_engine_and_session(database_url)
    return {
        str(constraint["name"])
        for constraint in inspect(engine).get_check_constraints("duplicate_relations")
    }


def test_create_all_uses_canonical_duplicate_check_name(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'metadata.db'}"
    engine, _ = create_engine_and_session(database_url)
    Base.metadata.create_all(engine)

    assert _reflected_duplicate_check_names(database_url) == {EXPECTED_DUPLICATE_CHECK}


def test_alembic_upgrade_uses_canonical_duplicate_check_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'alembic.db'}"
    sentinel_path = tmp_path / "sentinel.db"
    monkeypatch.setenv("JOBSCRAPER_DATABASE_URL", f"sqlite:///{sentinel_path}")
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    # env.py gives the environment precedence, so pin both inputs to the temp DB.
    monkeypatch.setenv("JOBSCRAPER_DATABASE_URL", database_url)

    command.upgrade(config, "head")

    assert _reflected_duplicate_check_names(database_url) == {EXPECTED_DUPLICATE_CHECK}
    assert not sentinel_path.exists()


def _database_with_two_jobs(
    database_path: Path,
) -> tuple[sessionmaker[Session], tuple[int, int]]:
    engine, session_factory = create_engine_and_session(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    with session_factory.begin() as session:
        left = CanonicalJob(
            title="Développeur Python",
            normalized_title="developpeur python",
            company="Acme",
            normalized_company="acme",
            location="Paris",
            normalized_location="paris",
        )
        right = CanonicalJob(
            title="Backend Python",
            normalized_title="backend python",
            company="Acme",
            normalized_company="acme",
            location="Paris",
            normalized_location="paris",
        )
        session.add_all((left, right))
        session.flush()
    return session_factory, (left.pk, right.pk)


def test_duplicate_relation_accepts_an_ordered_distinct_pair(tmp_path: Path) -> None:
    session_factory, (left_id, right_id) = _database_with_two_jobs(
        tmp_path / "ordered.db"
    )

    with session_factory.begin() as session:
        relation = DuplicateRelation(
            left_job_id=left_id,
            right_job_id=right_id,
            kind="possible",
            score=0.8,
        )
        session.add(relation)
        session.flush()

    assert relation.pk > 0


@pytest.mark.parametrize("pair_kind", ["reverse", "self"])
def test_duplicate_relation_rejects_noncanonical_pairs(
    tmp_path: Path, pair_kind: str
) -> None:
    session_factory, (left_id, right_id) = _database_with_two_jobs(
        tmp_path / f"{pair_kind}.db"
    )
    pair = (right_id, left_id) if pair_kind == "reverse" else (left_id, left_id)

    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.add(
                DuplicateRelation(
                    left_job_id=pair[0],
                    right_job_id=pair[1],
                    kind="possible",
                    score=0.8,
                )
            )
            session.flush()


def test_filter_columns_are_indexed_and_timestamps_are_timezone_aware() -> None:
    indexed_columns = {
        column.name
        for table in Base.metadata.tables.values()
        for index in table.indexes
        for column in index.columns
    }
    timestamp_columns = [
        column
        for table in Base.metadata.tables.values()
        for column in table.columns
        if column.name.endswith("_at")
    ]

    assert {"posted_at", "active", "last_seen_at"} <= indexed_columns
    assert timestamp_columns
    assert all(getattr(column.type, "timezone", False) for column in timestamp_columns)


def test_timestamp_defaults_are_utc_aware(tmp_path: Path) -> None:
    from jobscraper.db.models import SavedSearch

    engine, session_factory = create_engine_and_session(
        f"sqlite:///{tmp_path / 'timestamps.db'}"
    )
    Base.metadata.create_all(engine)

    with session_factory.begin() as session:
        saved_search = SavedSearch(name="Backend", sources=["freework"])
        session.add(saved_search)

    with session_factory() as session:
        persisted = session.get(SavedSearch, saved_search.pk)
        assert persisted is not None
        assert isinstance(persisted.created_at, datetime)
        assert persisted.created_at.tzinfo == timezone.utc
