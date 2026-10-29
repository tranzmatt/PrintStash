"""Existing Artifacts survive adding 3MF plate layouts, and a downgrade drops only them.

Plate layouts are derived from an Artifact's bytes, so a self-hoster who rolls
back loses nothing but the layouts and the work that derives them: the upgrade
must keep every library row, and the downgrade must remove the plates rows and
values its CHECK constraints no longer allow while leaving the Artifact in place.
"""

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text

from alembic import command
from app.db.url import normalize_database_url
from tests.containers import fresh_postgres_database
from tests.factories.migration_rows import seed_schema_row
from tests.paths import ALEMBIC_DIR, ALEMBIC_INI

BEFORE = "08add6607321"
PLATES = "105991549e18"


class TestPlatesMigration:
    @pytest.mark.parametrize(
        "dialect", ["sqlite", pytest.param("postgresql", marks=pytest.mark.postgres)]
    )
    def test_round_trips_without_losing_the_library(self, tmp_path, dialect):
        config = Config(str(ALEMBIC_INI))
        config.set_main_option("script_location", str(ALEMBIC_DIR))
        url = (
            f"sqlite:///{tmp_path / 'plates.sqlite'}"
            if dialect == "sqlite"
            else normalize_database_url(fresh_postgres_database("plates_upgrade"))
        )
        config.set_main_option("sqlalchemy.url", url)
        engine = create_engine(url)
        command.upgrade(config, BEFORE)
        with engine.begin() as connection:
            seed_schema_row(
                connection, "models", id=1, name="Rack", slug="rack", hash="a" * 64
            )
            seed_schema_row(
                connection,
                "files",
                id=1,
                model_id=1,
                file_type="3mf",
                original_filename="rack.3mf",
                sha256="a" * 64,
                version=1,
                path="rack.3mf",
            )
        command.upgrade(config, PLATES)
        with engine.begin() as connection:
            seed_schema_row(
                connection,
                "file_plates",
                file_id=1,
                number=1,
                object_count=1,
                min_x=0.0,
                min_y=0.0,
                max_x=256.0,
                max_y=256.0,
            )
            seed_schema_row(
                connection,
                "artifact_derivatives",
                file_id=1,
                kind="plates",
                recipe_version=1,
                state="ready",
            )
            seed_schema_row(
                connection,
                "jobs",
                id="plates-job",
                kind="derivatives.plates",
                subject_key="file/1",
                priority="backfill",
                state="completed",
            )

        command.downgrade(config, BEFORE)

        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT original_filename FROM files WHERE id=1")
                ).scalar_one()
                == "rack.3mf"
            )
            assert (
                connection.execute(
                    text(
                        "SELECT (SELECT count(*) FROM artifact_derivatives)"
                        " + (SELECT count(*) FROM jobs)"
                    )
                ).scalar_one()
                == 0
            )
        command.upgrade(config, PLATES)
        engine.dispose()
