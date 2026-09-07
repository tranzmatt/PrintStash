"""The nullable cache policy upgrade preserves existing system configuration."""

from alembic.config import Config
from sqlalchemy import create_engine
from sqlmodel import Session

from alembic import command
from app.db.models import SystemConfig
from tests.factories import build_system_config
from tests.paths import ALEMBIC_DIR, ALEMBIC_INI


class TestArtifactCachePolicyMigration:
    def test_preserves_existing_configuration_on_upgrade(self, tmp_path):
        url = f"sqlite:///{tmp_path / 'upgrade.sqlite'}"
        config = Config(str(ALEMBIC_INI))
        config.set_main_option("script_location", str(ALEMBIC_DIR))
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "00cb0e8975d1")
        engine = create_engine(url)
        try:
            with Session(engine) as session:
                build_system_config(session, currency="EUR")
            command.downgrade(config, "9cbee9215a34")
            command.upgrade(config, "00cb0e8975d1")
            with Session(engine) as session:
                row = session.get(SystemConfig, 1)
                assert row.currency == "EUR"
                assert row.artifact_cache_policy_json is None
        finally:
            engine.dispose()
