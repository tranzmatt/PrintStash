import pytest
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.db.migrate import _alembic_config
from tests.factories.migration_rows import seed_schema_row


def test_preserves_populated_audits(tmp_path):
    url = f"sqlite:///{tmp_path / 'upgrade.sqlite'}"
    config = _alembic_config(url)
    command.upgrade(config, "d6e9d78801ef")
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


@pytest.mark.postgres
def test_preserves_populated_postgres_audits():
    from uuid import uuid4

    from sqlalchemy.engine import make_url

    from app.db.url import normalize_database_url
    from tests.containers import postgres_url
    from tests.factories.migration_rows import (
        RELEASED_V0121_REVISION,
        create_released_v0121_postgres_schema,
    )

    url = normalize_database_url(postgres_url())
    database = f"audit_upgrade_{uuid4().hex}"
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{database}"')
    isolated_url = (
        make_url(url).set(database=database).render_as_string(hide_password=False)
    )
    engine = create_engine(isolated_url)
    config = _alembic_config(isolated_url)
    try:
        with engine.begin() as connection:
            create_released_v0121_postgres_schema(connection)
        command.stamp(config, RELEASED_V0121_REVISION)
        command.upgrade(config, "d6e9d78801ef")
        with engine.begin() as connection:
            seed_schema_row(
                connection,
                "users",
                id=1,
                username="upgrade-owner",
                hashed_password="test-only",
            )
            seed_schema_row(
                connection,
                "vault_audit_runs",
                id=1,
                requested_by=1,
                mode="QUICK",
                state="COMPLETED",
            )
            seed_schema_row(
                connection,
                "notification_channels",
                id=1,
                name="Preserved channel",
                target="NTFY",
            )
            seed_schema_row(
                connection,
                "notification_deliveries",
                id=1,
                channel_id=1,
                event_type="PRINT_COMPLETED",
                status="PENDING",
            )
        command.upgrade(config, "4b21cbe868b6")
        with engine.begin() as connection:
            seed_schema_row(
                connection,
                "vault_audit_policies",
                mode="quick",
                requested_by=1,
                enabled=True,
                paused=False,
                revision=8,
            )
        command.upgrade(config, "head")
        with engine.begin() as connection:
            assert connection.execute(
                text(
                    "SELECT revision, jitter_seconds, max_lateness_minutes, notification_threshold FROM vault_audit_policies WHERE mode='quick'"
                )
            ).one() == (8, 0, 120, "warning")
            assert connection.execute(
                text(
                    "SELECT requested_by, trigger, result_recorded FROM vault_audit_runs WHERE id=1"
                )
            ).one() == (1, "manual", False)
            assert (
                connection.execute(
                    text("SELECT event_type FROM notification_deliveries WHERE id=1")
                ).scalar_one()
                == "PRINT_COMPLETED"
            )
            seed_schema_row(
                connection,
                "notification_deliveries",
                id=2,
                channel_id=1,
                event_type="STORAGE_REGRESSION",
                status="PENDING",
            )
            assert (
                connection.execute(
                    text("SELECT event_type FROM notification_deliveries WHERE id=2")
                ).scalar_one()
                == "STORAGE_REGRESSION"
            )
            connection.execute(text("DELETE FROM notification_deliveries WHERE id=2"))
            for index, event in enumerate(
                (
                    "STORAGE_AUDIT_FAILED",
                    "STORAGE_AUDIT_CANCELLED",
                    "STORAGE_AUDIT_OVERDUE",
                    "STORAGE_REPAIR_FAILED",
                ),
                start=3,
            ):
                seed_schema_row(
                    connection,
                    "notification_deliveries",
                    id=index,
                    channel_id=1,
                    event_type=event,
                    status="PENDING",
                )
            connection.execute(
                text("DELETE FROM notification_deliveries WHERE id >= 3")
            )
        command.downgrade(config, "d6e9d78801ef")
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT requested_by FROM vault_audit_runs WHERE id=1")
                ).scalar_one()
                == 1
            )
            assert (
                connection.execute(
                    text(
                        "SELECT udt_name FROM information_schema.columns WHERE table_name='notification_deliveries' AND column_name='event_type'"
                    )
                ).scalar_one()
                == "notificationeventtype"
            )
        command.upgrade(config, "head")
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{database}" WITH (FORCE)')
        admin.dispose()


def test_preserves_populated_policy_controls(tmp_path):
    url = f"sqlite:///{tmp_path / 'policy-upgrade.sqlite'}"
    config = _alembic_config(url)
    command.upgrade(config, "4b21cbe868b6")
    engine = create_engine(url)
    with engine.begin() as connection:
        seed_schema_row(
            connection,
            "vault_audit_policies",
            mode="quick",
            enabled=True,
            paused=True,
            revision=9,
        )
    command.upgrade(config, "head")
    with engine.begin() as connection:
        assert connection.execute(
            text(
                "SELECT revision, paused, jitter_seconds, max_lateness_minutes, notification_threshold FROM vault_audit_policies WHERE mode='quick'"
            )
        ).one() == (9, 1, 0, 120, "warning")
    command.downgrade(config, "4b21cbe868b6")
    command.upgrade(config, "head")
    engine.dispose()
