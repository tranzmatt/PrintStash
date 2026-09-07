from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.db.migrate import _alembic_config
from tests.factories.migration_rows import seed_schema_row


def test_preserves_populated_audits(tmp_path):
    url = f"sqlite:///{tmp_path / 'upgrade.sqlite'}"
    config = _alembic_config(url)
    command.upgrade(config, "9cbee9215a34")
    engine = create_engine(url)
    with engine.begin() as connection:
        seed_schema_row(
            connection,
            "users",
            id=1,
            username="upgrade-owner",
            hashed_password="not-a-real-password",
        )
        seed_schema_row(
            connection,
            "vault_audit_runs",
            id=1,
            requested_by=1,
            mode="QUICK",
            state="COMPLETED",
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT requested_by, trigger, result_recorded FROM vault_audit_runs WHERE id=1"
            )
        ).one()
        assert tuple(row) == (1, "manual", 0)
        assert {"vault_audit_policies", "vault_audit_events"} <= set(
            inspect(connection).get_table_names()
        )
    engine.dispose()
