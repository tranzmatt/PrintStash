"""Queued run pairs upgrade as a new table and downgrade with their verifier Jobs."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from tests.paths import ALEMBIC_DIR, ALEMBIC_INI

REVISION = "08add6607321"
PREVIOUS = "c52050b07c12"


def _config(db_path: Path) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return config


def _tables(db_path: Path) -> set[str]:
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _verifier_jobs(db_path: Path) -> int:
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.connect() as connection:
            return connection.execute(
                text("SELECT COUNT(*) FROM jobs WHERE kind = 'similarity.verify'")
            ).scalar_one()
    finally:
        engine.dispose()


def _add_verifier_job(db_path: Path) -> None:
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO jobs (id, kind, state, status_json, attempts,"
                    " created_at, updated_at, subject_key, priority, resubmits,"
                    " execution_epoch) VALUES ('verifier', 'similarity.verify',"
                    " 'completed', '{}', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,"
                    " 'similarity_run/1/verifier/0', 'backfill', 0, 'epoch')"
                )
            )
    finally:
        engine.dispose()


class TestUpgrade:
    def test_adds_the_run_pair_table(self, tmp_path: Path) -> None:
        db_path = tmp_path / "run-pairs.sqlite"
        config = _config(db_path)
        command.upgrade(config, PREVIOUS)

        command.upgrade(config, REVISION)

        assert "similarity_run_pairs" in _tables(db_path)

    def test_accepts_verifier_jobs(self, tmp_path: Path) -> None:
        db_path = tmp_path / "run-pairs-kind.sqlite"
        command.upgrade(_config(db_path), REVISION)

        _add_verifier_job(db_path)

        assert _verifier_jobs(db_path) == 1


class TestDowngrade:
    def test_removes_the_run_pair_table(self, tmp_path: Path) -> None:
        db_path = tmp_path / "run-pairs-downgrade.sqlite"
        config = _config(db_path)
        command.upgrade(config, REVISION)

        command.downgrade(config, PREVIOUS)

        assert "similarity_run_pairs" not in _tables(db_path)

    def test_removes_verifier_jobs_the_old_kinds_refuse(self, tmp_path: Path) -> None:
        db_path = tmp_path / "run-pairs-jobs.sqlite"
        config = _config(db_path)
        command.upgrade(config, REVISION)
        _add_verifier_job(db_path)

        command.downgrade(config, PREVIOUS)

        assert _verifier_jobs(db_path) == 0
