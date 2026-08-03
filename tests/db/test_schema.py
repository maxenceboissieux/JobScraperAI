from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import JSON, Integer, String, UniqueConstraint, inspect

from jobscraper.db.base import Base
from jobscraper.db.session import create_engine_and_session


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
