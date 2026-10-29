"""Upgrading and downgrading Trash keeps existing composition identities."""

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text

from alembic import command
from tests.paths import ALEMBIC_DIR, ALEMBIC_INI


@pytest.mark.parametrize(
    "round_trip", [False, True], ids=["upgrade", "downgrade-upgrade"]
)
def test_migration_preserves_existing_parts(tmp_path, round_trip):
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    url = f"sqlite:///{tmp_path / 'multipart.sqlite'}"
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "08add6607321")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO multipart_models (id, name, slug, created_at, updated_at) VALUES (1, 'Kit', 'kit', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO multipart_parts (id, multipart_model_id, name, name_key, sort_order, created_at, updated_at) VALUES (1, 1, 'Base', 'base', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
    with engine.connect() as conn:
        before = conn.execute(
            text(
                "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' ORDER BY name"
            )
        ).all()
    command.upgrade(config, "462588d49de9")
    if round_trip:
        command.downgrade(config, "08add6607321")
        command.upgrade(config, "462588d49de9")
    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT name, deleted_at, purge_token FROM multipart_models")
        ).all() == [("Kit", None, None)]
        assert conn.execute(
            text("SELECT multipart_model_id, name, quantity FROM multipart_parts")
        ).all() == [(1, "Base", 1)]
        assert conn.execute(text("PRAGMA foreign_key_check")).all() == []
        assert (
            conn.execute(
                text(
                    "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' ORDER BY name"
                )
            ).all()
            == before
        )
    engine.dispose()
