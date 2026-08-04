"""enforce one active run per saved search

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Reject overlapping pending or running attempts for one search."""

    connection = op.get_bind()
    active_runs = list(connection.execute(sa.text("""
                SELECT pk, saved_search_id
                FROM sync_runs
                WHERE status IN ('pending', 'running')
                ORDER BY saved_search_id, created_at DESC, pk DESC
                """)).mappings())
    retained_searches: set[int] = set()
    for run in active_runs:
        saved_search_id = int(run["saved_search_id"])
        if saved_search_id not in retained_searches:
            retained_searches.add(saved_search_id)
            continue
        connection.execute(
            sa.text("""
                UPDATE sync_runs
                SET status = 'failed',
                    finished_at = COALESCE(finished_at, CURRENT_TIMESTAMP)
                WHERE pk = :run_pk AND status IN ('pending', 'running')
                """),
            {"run_pk": int(run["pk"])},
        )

    op.create_index(
        "uq_sync_runs_one_active_search",
        "sync_runs",
        ["saved_search_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('pending', 'running')"),
    )


def downgrade() -> None:
    """Remove the active-run guard."""

    op.drop_index("uq_sync_runs_one_active_search", table_name="sync_runs")
