"""Empty similarity verifications upgrade as a new table and downgrade cleanly."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command
from tests.paths import ALEMBIC_DIR, ALEMBIC_INI

REVISION = "bccfd76cee7a"
PREVIOUS = "6871122f2d36"
TABLE = "similarity_empty_verifications"


def _config(db_path: Path) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return config


def _schema(db_path: Path):
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        schema = inspect(engine)
        if TABLE not in schema.get_table_names():
            return None
        return {
            "unique": [
                tuple(row["column_names"])
                for row in schema.get_unique_constraints(TABLE)
            ],
            "foreign_keys": sorted(
                (
                    row["constrained_columns"][0],
                    row["referred_table"],
                    row["options"].get("ondelete"),
                )
                for row in schema.get_foreign_keys(TABLE)
            ),
        }
    finally:
        engine.dispose()


class TestUpgrade:
    def test_creates_the_outcome_table_keyed_by_inputs(self, tmp_path: Path) -> None:
        db_path = tmp_path / "empty-verifications.sqlite"
        config = _config(db_path)
        command.upgrade(config, PREVIOUS)

        command.upgrade(config, REVISION)

        assert _schema(db_path) == {
            "unique": [
                (
                    "fingerprint_a_id",
                    "fingerprint_b_id",
                    "input_hash_a",
                    "input_hash_b",
                    "verification_version",
                    "sample_points",
                    "triangle_cap",
                )
            ],
            "foreign_keys": [
                ("fingerprint_a_id", "geometry_fingerprints", "CASCADE"),
                ("fingerprint_b_id", "geometry_fingerprints", "CASCADE"),
            ],
        }


class TestDowngrade:
    def test_removes_the_outcome_table(self, tmp_path: Path) -> None:
        db_path = tmp_path / "empty-verifications-downgrade.sqlite"
        config = _config(db_path)
        command.upgrade(config, REVISION)

        command.downgrade(config, PREVIOUS)

        assert _schema(db_path) is None
