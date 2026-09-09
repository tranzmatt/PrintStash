"""Merge the capacity and scheduled-audit migration histories.

Both parent revisions add independent tables and columns, so this revision only
records convergence and intentionally performs no DDL.

Revision ID: 36872a2fc034
Revises: 321c51b5aa8e, 71bd0ebbf381
Create Date: 2026-09-08 23:51:51.784083

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "36872a2fc034"
down_revision: str | Sequence[str] | None = ("321c51b5aa8e", "71bd0ebbf381")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
