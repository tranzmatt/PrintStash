"""The nullable cache policy upgrade preserves populated current-head databases."""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from alembic import command
from app.db.migrate import _alembic_config
from app.db.url import normalize_database_url
from tests.factories.migration_rows import seed_schema_row

_PREDECESSOR = "36872a2fc034"
_REVISION = "00cb0e8975d1"


def _seed_and_upgrade(url: str) -> None:
    config = _alembic_config(url)
    command.upgrade(config, _PREDECESSOR)
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            seed_schema_row(connection, "system_config", id=1, currency="EUR")

        command.upgrade(config, _REVISION)

        with engine.connect() as connection:
            columns = {
                column["name"]
                for column in inspect(connection).get_columns("system_config")
            }
            row = connection.execute(
                text(
                    "SELECT currency, artifact_cache_policy_json "
                    "FROM system_config WHERE id=1"
                )
            ).one()
            assert "artifact_cache_policy_json" in columns
            assert tuple(row) == ("EUR", None)
    finally:
        engine.dispose()


class TestArtifactCachePolicyMigration:
    def test_preserves_populated_sqlite_configuration(self, tmp_path):
        _seed_and_upgrade(f"sqlite:///{tmp_path / 'upgrade.sqlite'}")

    @pytest.mark.postgres
    def test_preserves_populated_postgres_configuration(self):
        from tests.containers import postgres_url

        root_url = normalize_database_url(postgres_url())
        database = f"artifact_cache_upgrade_{uuid4().hex}"
        admin = create_engine(root_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database}"')
        isolated_url = (
            make_url(root_url)
            .set(database=database)
            .render_as_string(hide_password=False)
        )
        try:
            _seed_and_upgrade(isolated_url)
        finally:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{database}" WITH (FORCE)')
            admin.dispose()
