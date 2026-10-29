"""Retain multipart groupings in Trash without deleting member Models.

Revision ID: 462588d49de9
Revises: b2be6484da3f
Create Date: 2026-10-29 15:18:03.887910

"""

from typing import Sequence, Union
from contextlib import contextmanager

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "462588d49de9"
down_revision: Union[str, Sequence[str], None] = "b2be6484da3f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


@contextmanager
def _preserve_sqlite_triggers():
    """SQLite validates cross-table triggers while renaming a rebuilt table.

    Save the installed definitions verbatim, including browse/edit revision
    triggers on both the grouping and its link tables, then reinstall them.
    PostgreSQL alters the table in place and retains its triggers itself.
    """
    bind = op.get_bind()
    triggers = []
    if bind.dialect.name == "sqlite":
        triggers = bind.execute(
            sa.text(
                "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND (tbl_name = 'multipart_models' OR sql LIKE '%multipart_models%')"
            )
        ).all()
        for name, _sql in triggers:
            quoted = name.replace('"', '""')
            bind.exec_driver_sql(f'DROP TRIGGER "{quoted}"')
    try:
        yield
    finally:
        for _name, sql in triggers:
            bind.exec_driver_sql(sql)


def upgrade() -> None:
    """Upgrade schema."""
    with (
        _preserve_sqlite_triggers(),
        op.batch_alter_table("multipart_models", schema=None) as batch_op,
    ):
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("deleted_by", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("purge_token", sa.String(length=64), nullable=True)
        )
        batch_op.create_index(
            batch_op.f("ix_multipart_models_deleted_at"), ["deleted_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_multipart_models_purge_token"), ["purge_token"], unique=False
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_multipart_models_deleted_by_users"),
            "users",
            ["deleted_by"],
            ["id"],
        )


def downgrade() -> None:
    """Downgrade schema."""
    with (
        _preserve_sqlite_triggers(),
        op.batch_alter_table("multipart_models", schema=None) as batch_op,
    ):
        batch_op.drop_constraint(
            batch_op.f("fk_multipart_models_deleted_by_users"), type_="foreignkey"
        )
        batch_op.drop_index(batch_op.f("ix_multipart_models_purge_token"))
        batch_op.drop_index(batch_op.f("ix_multipart_models_deleted_at"))
        batch_op.drop_column("purge_token")
        batch_op.drop_column("deleted_by")
        batch_op.drop_column("deleted_at")
