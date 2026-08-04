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
