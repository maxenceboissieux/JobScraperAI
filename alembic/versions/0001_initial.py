"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-03 21:21:59.864701
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "canonical_jobs",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("normalized_title", sa.String(length=500), nullable=False),
        sa.Column("company", sa.String(length=300), nullable=False),
        sa.Column("normalized_company", sa.String(length=300), nullable=False),
        sa.Column("location", sa.String(length=300), nullable=False),
        sa.Column("normalized_location", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("salary_min", sa.Float(), nullable=True),
        sa.Column("salary_max", sa.Float(), nullable=True),
        sa.Column("salary_currency", sa.String(length=3), nullable=False),
        sa.Column("contract_type", sa.String(length=50), nullable=True),
        sa.Column("experience_level", sa.String(length=50), nullable=True),
        sa.Column("remote", sa.Boolean(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("skills", sa.JSON(), nullable=False),
        sa.Column("benefits", sa.JSON(), nullable=False),
        sa.Column("details_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("pk", name=op.f("pk_canonical_jobs")),
        sa.UniqueConstraint("id", name=op.f("uq_canonical_jobs_id")),
    )
    op.create_index(
        op.f("ix_canonical_jobs_posted_at"),
        "canonical_jobs",
        ["posted_at"],
        unique=False,
    )
    op.create_table(
        "saved_searches",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("location", sa.String(length=300), nullable=False),
        sa.Column("radius_km", sa.Integer(), nullable=True),
        sa.Column("contract_types", sa.JSON(), nullable=False),
        sa.Column("experience_levels", sa.JSON(), nullable=False),
        sa.Column("workplace_types", sa.JSON(), nullable=False),
        sa.Column("companies", sa.JSON(), nullable=False),
        sa.Column("exclude_companies", sa.JSON(), nullable=False),
        sa.Column("salary_min", sa.Integer(), nullable=True),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("pk", name=op.f("pk_saved_searches")),
        sa.UniqueConstraint("id", name=op.f("uq_saved_searches_id")),
    )
    op.create_index(
        op.f("ix_saved_searches_active"), "saved_searches", ["active"], unique=False
    )
    op.create_table(
        "duplicate_relations",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("left_job_id", sa.Integer(), nullable=False),
        sa.Column("right_job_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "left_job_id < right_job_id",
            name=op.f("ck_duplicate_relations_canonical_order"),
        ),
        sa.ForeignKeyConstraint(
            ["left_job_id"],
            ["canonical_jobs.pk"],
            name=op.f("fk_duplicate_relations_left_job_id_canonical_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["right_job_id"],
            ["canonical_jobs.pk"],
            name=op.f("fk_duplicate_relations_right_job_id_canonical_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("pk", name=op.f("pk_duplicate_relations")),
        sa.UniqueConstraint(
            "left_job_id", "right_job_id", name="uq_duplicate_relations_left_right"
        ),
    )
    op.create_table(
        "search_listings",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("saved_search_id", sa.Integer(), nullable=False),
        sa.Column("canonical_job_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["canonical_job_id"],
            ["canonical_jobs.pk"],
            name=op.f("fk_search_listings_canonical_job_id_canonical_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["saved_search_id"],
            ["saved_searches.pk"],
            name=op.f("fk_search_listings_saved_search_id_saved_searches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("pk", name=op.f("pk_search_listings")),
        sa.UniqueConstraint(
            "saved_search_id", "canonical_job_id", name="uq_search_listings_search_job"
        ),
    )
    op.create_table(
        "source_listings",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("canonical_job_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("external_id", sa.String(length=500), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("company", sa.String(length=300), nullable=False),
        sa.Column("location", sa.String(length=300), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["canonical_job_id"],
            ["canonical_jobs.pk"],
            name=op.f("fk_source_listings_canonical_job_id_canonical_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("pk", name=op.f("pk_source_listings")),
        sa.UniqueConstraint("id", name=op.f("uq_source_listings_id")),
        sa.UniqueConstraint(
            "source", "external_id", name="uq_source_listings_source_external_id"
        ),
    )
    op.create_index(
        op.f("ix_source_listings_active"), "source_listings", ["active"], unique=False
    )
    op.create_index(
        op.f("ix_source_listings_last_seen_at"),
        "source_listings",
        ["last_seen_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_source_listings_posted_at"),
        "source_listings",
        ["posted_at"],
        unique=False,
    )
    op.create_table(
        "sync_runs",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("saved_search_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("requested_sources", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["saved_search_id"],
            ["saved_searches.pk"],
            name=op.f("fk_sync_runs_saved_search_id_saved_searches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("pk", name=op.f("pk_sync_runs")),
        sa.UniqueConstraint("id", name=op.f("uq_sync_runs_id")),
    )
    op.create_table(
        "source_sync_results",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("sync_run_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("offers_seen", sa.Integer(), nullable=False),
        sa.Column("offers_persisted", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["sync_run_id"],
            ["sync_runs.pk"],
            name=op.f("fk_source_sync_results_sync_run_id_sync_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("pk", name=op.f("pk_source_sync_results")),
        sa.UniqueConstraint("id", name=op.f("uq_source_sync_results_id")),
        sa.UniqueConstraint(
            "sync_run_id", "source", name="uq_source_sync_results_run_source"
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("source_sync_results")
    op.drop_table("sync_runs")
    op.drop_index(op.f("ix_source_listings_posted_at"), table_name="source_listings")
    op.drop_index(op.f("ix_source_listings_last_seen_at"), table_name="source_listings")
    op.drop_index(op.f("ix_source_listings_active"), table_name="source_listings")
    op.drop_table("source_listings")
    op.drop_table("search_listings")
    op.drop_table("duplicate_relations")
    op.drop_index(op.f("ix_saved_searches_active"), table_name="saved_searches")
    op.drop_table("saved_searches")
    op.drop_index(op.f("ix_canonical_jobs_posted_at"), table_name="canonical_jobs")
    op.drop_table("canonical_jobs")
