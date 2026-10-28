"""Surface clouds upgrade as a nullable fingerprint column and downgrade cleanly."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command
from tests.paths import ALEMBIC_DIR, ALEMBIC_INI

REVISION = "c52050b07c12"
PREVIOUS = "bccfd76cee7a"


def _config(db_path: Path) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return config


def _cloud_column(db_path: Path):
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        columns = {
            column["name"]: column
            for column in inspect(engine).get_columns("geometry_fingerprints")
        }
        return columns.get("cloud_blob")
    finally:
        engine.dispose()


class TestUpgrade:
    def test_adds_a_nullable_cloud_column(self, tmp_path: Path) -> None:
        db_path = tmp_path / "surface-cloud.sqlite"
        config = _config(db_path)
        command.upgrade(config, PREVIOUS)

        command.upgrade(config, REVISION)

        column = _cloud_column(db_path)
        assert column is not None
        assert column["nullable"] is True


class TestDowngrade:
    def test_removes_the_cloud_column(self, tmp_path: Path) -> None:
        db_path = tmp_path / "surface-cloud-downgrade.sqlite"
        config = _config(db_path)
        command.upgrade(config, REVISION)

        command.downgrade(config, PREVIOUS)

        assert _cloud_column(db_path) is None
