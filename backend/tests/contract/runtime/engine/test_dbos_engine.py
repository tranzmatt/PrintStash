"""Persistent tick scheduling and real DBOS 2.31.1 system-state upgrades."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest
from dbos import DBOS
from sqlalchemy import create_engine
from sqlmodel import select

from app.db.models import Job, JobState, WorkPriority
from app.db.session import get_session_factory
from app.modules.work import catalog as catalog_module
from app.modules.work.contracts import Deduplicated, JobSubmission, SubmitOutcome
from app.runtime.engine.dbos_engine import TICK_WORKFLOW, system_database_url
from tests.containers import fresh_postgres_database
from tests.contract.modules.work._harness import (
    PLAIN,
    RECORD,
    DbosHarness,
    contract_catalog,
    shared_app_db,
)
from tests.factories.ops import build_job

FIXTURES = Path(__file__).parents[3] / "fixtures" / "dbos-2.31.1"
VERSION = "contract-sdk-upgrade"


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def system_db(request, tmp_path):
    if request.param == "sqlite":
        return f"sqlite:///{tmp_path / 'engine.sqlite'}", None
    return system_database_url(fresh_postgres_database("dbos_upgrade"))


@contextmanager
def running_engine(system_db):
    RECORD.steps.clear()
    RECORD.behaviour.clear()
    RECORD.discover.clear()
    RECORD.running = RECORD.peak = 0
    catalog = contract_catalog()
    with shared_app_db():
        harness = DbosHarness(
            catalog,
            system_db[0],
            schema=system_db[1],
            app_version=VERSION,
            listen_lanes=[],
        )
        catalog_module.bind(harness.engine, catalog)
        try:
            yield harness
        finally:
            harness.close()
            catalog_module.bind(None, None)


@pytest.fixture
def engine(system_db):
    with running_engine(system_db) as harness:
        yield harness


@pytest.fixture
def upgraded(system_db):
    url, schema = system_db
    dialect = "postgres" if schema else "sqlite"
    sql = (FIXTURES / f"{dialect}.sql").read_text()
    if schema:
        db = create_engine(url)
        with db.begin() as connection:
            connection.exec_driver_sql(sql)
            assert (
                connection.exec_driver_sql(
                    "SELECT version FROM dbos.dbos_migrations"
                ).scalar_one()
                == 108
            )
        db.dispose()
    else:
        with sqlite3.connect(url.removeprefix("sqlite:///")) as connection:
            connection.executescript(sql)
            assert connection.execute(
                "SELECT version FROM dbos_migrations"
            ).fetchone() == (108,)
    with running_engine(system_db) as harness:
        with get_session_factory().scoped_session() as session:
            build_job(
                session,
                id="dbos-231-job",
                kind=PLAIN,
                subject="upgrade/queued",
                attempts=1,
            )
        yield harness


class TestPersistentTick:
    def test_relaunch_keeps_one_schedule(self, engine):
        engine.relaunch(app_version=VERSION, listen_lanes=[])

        schedules = DBOS.list_schedules()
        assert [schedule["schedule_name"] for schedule in schedules] == [TICK_WORKFLOW]

    def test_relaunch_updates_the_cadence(self, engine):
        engine.tick_seconds = 300
        engine.relaunch(app_version=VERSION, listen_lanes=[])

        schedule = DBOS.get_schedule(TICK_WORKFLOW)
        assert schedule is not None
        assert schedule["schedule"] == "*/5 * * * *"

    def test_reset_recreates_the_schedule(self, engine):
        engine.engine.reset()
        engine.engine.launch(listen_lanes=[])

        assert [s["schedule_name"] for s in DBOS.list_schedules()] == [TICK_WORKFLOW]

    def test_tick_recovers_work_without_a_nudge(self, engine):
        engine.tick_seconds = 1
        engine.relaunch(app_version=VERSION, listen_lanes=None)
        RECORD.discover.add("tick/missed-nudge")

        engine.wait_for(lambda: "tick/missed-nudge" in RECORD.firsts())
        engine.settle()

        with get_session_factory().scoped_session() as session:
            found = session.exec(
                select(Job).where(Job.subject_key == "tick/missed-nudge")
            ).one()
            assert found.state == JobState.COMPLETED
        assert "tick/missed-nudge" not in RECORD.discover


def _recover_legacy_job(harness):
    from datetime import timedelta

    from app.core.config import settings
    from app.core.time import utcnow
    from app.modules.work.reconciler import PassResult, _repair

    # Legacy persisted arguments cannot prove current execution ownership.
    DBOS.retrieve_workflow("dbos-231-job:1").get_result()
    assert harness.state("dbos-231-job") is JobState.QUEUED
    assert RECORD.steps == []
    result = PassResult()
    _repair(
        harness.catalog.definition(PLAIN),
        now=utcnow() + timedelta(seconds=settings.jobs_submit_grace_seconds + 1),
        result=result,
    )
    assert result.submitted == 1
    harness.settle()


class TestSdkUpgrade:
    def test_saved_result_remains_readable(self, upgraded):
        assert DBOS.retrieve_workflow("dbos-231-result:1").get_result() == {
            "job_id": "dbos-231-result",
            "attempt": 1,
        }

    def test_saved_queued_job_recovers_with_current_execution_authority(self, upgraded):
        upgraded.relaunch(app_version=VERSION, listen_lanes=None)
        _recover_legacy_job(upgraded)

        assert upgraded.state("dbos-231-job") == JobState.COMPLETED
        assert RECORD.steps == [
            ("upgrade/queued", "first"),
            ("upgrade/queued", "second"),
        ]

    def test_replayed_id_preserves_the_saved_input(self, upgraded):
        outcome = upgraded.engine.submit(
            JobSubmission(
                execution_id="dbos-231-job:1",
                job_id="wrong-input",
                attempt=1,
                definition=PLAIN,
                subject_key="wrong-subject",
                routing=Deduplicated("wrong-input"),
                lane=upgraded.catalog.definitions[PLAIN].lane,
                priority=WorkPriority.INTERACTIVE,
                execution_epoch="test-epoch",
            )
        )
        assert outcome == SubmitOutcome.EXISTING
        upgraded.relaunch(app_version=VERSION, listen_lanes=None)
        _recover_legacy_job(upgraded)

        assert upgraded.state("dbos-231-job") == JobState.COMPLETED
        assert RECORD.firsts() == ["upgrade/queued"]
