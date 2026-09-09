"""Defend cross-database audit admission and optimistic policy concurrency."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, select

from app.db.models import VaultAuditMode, VaultAuditRun, VaultAuditRunState
from app.db.session import _set_sqlite_pragmas
from app.modules.administration.vault_audit_policy import admit_run
from tests.factories import build_audit_run, build_user


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def admission_engine(request, tmp_path):
    if request.param == "sqlite":
        engine = create_engine(
            f"sqlite:///{tmp_path / 'audit-race.sqlite'}",
            connect_args={"check_same_thread": False},
        )
        event.listen(engine, "connect", _set_sqlite_pragmas)
    else:
        from app.db.url import normalize_database_url
        from tests.containers import postgres_url

        engine = create_engine(
            normalize_database_url(postgres_url()),
            connect_args={"options": "-csearch_path=audit_admission_test"},
        )
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS audit_admission_test"))
    SQLModel.metadata.create_all(engine)
    try:
        yield engine
    finally:
        if request.param == "postgres":
            with engine.begin() as connection:
                connection.execute(text("DROP SCHEMA audit_admission_test CASCADE"))
        engine.dispose()


class TestAuditAdmission:
    def test_concurrent_admission_has_one_winner(self, admission_engine):
        with Session(admission_engine) as session:
            user_id = build_user(session).id
        barrier = Barrier(2)

        def start(mode):
            with Session(admission_engine) as session:
                barrier.wait(timeout=10)
                run, created = admit_run(session, user_id, mode)
                return run.id, created

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(
                pool.map(start, [VaultAuditMode.QUICK, VaultAuditMode.FULL])
            )
        assert len({run_id for run_id, _created in outcomes}) == 1
        assert sum(created for _run_id, created in outcomes) == 1
        with Session(admission_engine) as session:
            assert len(session.exec(select(VaultAuditRun)).all()) == 1

    def test_database_refuses_duplicate_active_claim(self, admission_engine):
        with Session(admission_engine) as session:
            user = build_user(session)
            build_audit_run(
                session, user, state=VaultAuditRunState.PENDING, active_slot="audit"
            )
            with pytest.raises(IntegrityError):
                build_audit_run(
                    session, user, state=VaultAuditRunState.PENDING, active_slot="audit"
                )
            session.rollback()

    @pytest.mark.parametrize("existing", [False, True])
    def test_concurrent_policy_edit_has_one_winner(self, admission_engine, existing):
        from app.core.errors import OperationError
        from app.db.models import VaultAuditPolicy
        from app.modules.administration.vault_audit_policy import update_policy
        from tests.factories import build_audit_policy

        with Session(admission_engine) as session:
            user = build_user(session)
            user_id = user.id
            revision = build_audit_policy(session, user).revision if existing else 1
        barrier = Barrier(2)

        def edit(paused):
            with Session(admission_engine) as session:
                barrier.wait(timeout=10)
                try:
                    update_policy(
                        session,
                        VaultAuditMode.QUICK,
                        {"expected_revision": revision, "paused": paused},
                        user_id,
                    )
                    return True
                except OperationError as error:
                    assert error.code == "audit_policy_revision_conflict"
                    return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(edit, [True, False]))
        assert sum(outcomes) == 1
        with Session(admission_engine) as session:
            assert session.get(VaultAuditPolicy, "quick").revision == revision + 1
