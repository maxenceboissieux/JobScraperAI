"""add saved-search source result limit

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "saved_searches",
        sa.Column("max_results", sa.Integer(), server_default="500", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("saved_searches", "max_results")
