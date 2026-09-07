"""Existing library data survives additive capacity schema upgrades."""

from alembic.config import Config
from sqlalchemy import inspect, text
from sqlmodel import Session, create_engine

from alembic import command
from tests.factories import build_model
from tests.paths import ALEMBIC_DIR, ALEMBIC_INI


def test_capacity_upgrade_preserves_existing_models(tmp_path):
    database = tmp_path / "capacity.sqlite"
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "0a6b1f868ae0")
    engine = create_engine(f"sqlite:///{database}")
    with Session(engine) as session:
        model = build_model(session, name="Preserved model")
        identity = model.id
    command.upgrade(config, "head")
    assert {
        "capacity_locks",
        "capacity_reservations",
        "storage_inventory_samples",
    } <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT name FROM models WHERE id=:id"), {"id": identity}
            ).scalar_one()
            == "Preserved model"
        )
    engine.dispose()
