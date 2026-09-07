"""Shared SQLModel metadata with stable constraint naming for both databases."""

from sqlmodel import SQLModel

# Deterministic constraint names, applied to every constraint declared below that does
# not name itself.
#
# This is not cosmetic. SQLite cannot `ALTER` a constraint, so Alembic changes one by
# rebuilding the table — and to rebuild it, it has to `DROP` the old constraint *by
# name*. An anonymous constraint therefore cannot be altered on SQLite at all:
# `batch_alter_table` fails with `ValueError: Constraint must have a name`. The
# convention is what makes a schema migratable on the database this product ships
# with by default.
#
# It also makes the two supported schemas comparable. `create_all` and the migration
# chain otherwise generate different names for the same constraint, and
# `tests/integration/db/migrations/test_models_versus_chain.py` cannot tell that
# apart from a real divergence.
#
# `%(column_0_name)s` rather than `%(column_0_label)s`: the label form includes the
# table name twice for a single-column constraint.
SQLModel.metadata.naming_convention = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
