"""Defend scheduler deferral and shutdown behavior around admitted Vault audits."""

from app.core.time import utcnow
from app.db.models import VaultAuditRunState
from app.runtime.audit_scheduler import _cancel_active_audits, run_due_audit
from app.runtime.maintenance import begin_restore_maintenance, end_restore_maintenance


class TestRunDueAudit:
    @staticmethod
    def test_maintenance_defers_due_audit(db_session, make_user, make_audit_policy):
        now = utcnow()
        policy = make_audit_policy(
            make_user(), enabled=True, next_due_at=now, start_time=now.strftime("%H:%M")
        )
        begin_restore_maintenance()
        try:
            assert run_due_audit(now=now) is None
        finally:
            end_restore_maintenance()
        db_session.refresh(policy)
        assert policy.deferred_reason == "maintenance"

    @staticmethod
    def test_shutdown_requests_cancellation(db_session, make_user, make_audit_run):
        run = make_audit_run(make_user(), state=VaultAuditRunState.RUNNING)
        _cancel_active_audits()
        db_session.refresh(run)
        assert run.cancel_requested is True

    @staticmethod
    def test_shutdown_defers_unclaimed_work(
        db_session, make_user, make_audit_policy, local_storage
    ):
        import threading

        now = utcnow()
        policy = make_audit_policy(
            make_user(), enabled=True, next_due_at=now, start_time=now.strftime("%H:%M")
        )
        shutdown = threading.Event()
        shutdown.set()
        assert run_due_audit(now=now, shutdown=shutdown) is None
        db_session.refresh(policy)
        assert policy.deferred_reason == "shutdown"
