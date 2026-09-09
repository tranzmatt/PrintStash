"""Defend scheduler deferral and shutdown behavior around admitted Vault audits."""

import pytest

from app.core.time import utcnow
from app.db.models import VaultAuditRunState
from app.runtime import audit_scheduler
from app.runtime.audit_scheduler import _cancel_active_audits, run_due_audit
from app.runtime.maintenance import begin_restore_maintenance, end_restore_maintenance


class TestRunDueAudit:
    def test_storage_probe_failure_defers_due_audit(
        self,
        db_session,
        make_user,
        make_audit_policy,
        local_storage,
        monkeypatch,
    ):
        now = utcnow()
        policy = make_audit_policy(
            make_user(), enabled=True, next_due_at=now, start_time=now.strftime("%H:%M")
        )

        def fail_probe():
            raise OSError("storage probe failed")

        monkeypatch.setattr(audit_scheduler.get_backend(), "health_probe", fail_probe)

        assert run_due_audit(now=now) is None
        db_session.refresh(policy)
        assert policy.deferred_reason == "storage_unavailable"

    def test_launch_failure_schedules_a_bounded_retry(
        self,
        db_session,
        make_user,
        make_audit_policy,
        local_storage,
        monkeypatch,
    ):
        now = utcnow()
        policy = make_audit_policy(
            make_user(), enabled=True, next_due_at=now, start_time=now.strftime("%H:%M")
        )

        def fail_claim(*_args, **_kwargs):
            raise RuntimeError("launch failed")

        monkeypatch.setattr(audit_scheduler, "claim_due", fail_claim)

        with pytest.raises(RuntimeError, match="launch failed"):
            run_due_audit(now=now)
        db_session.refresh(policy)
        assert policy.deferred_reason == "launch_retry"
        assert policy.retry_after is not None

    def test_maintenance_defers_due_audit(
        self, db_session, make_user, make_audit_policy
    ):
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

    def test_shutdown_requests_cancellation(
        self, db_session, make_user, make_audit_run
    ):
        run = make_audit_run(make_user(), state=VaultAuditRunState.RUNNING)
        _cancel_active_audits()
        db_session.refresh(run)
        assert run.cancel_requested is True

    def test_shutdown_defers_unclaimed_work(
        self, db_session, make_user, make_audit_policy, local_storage
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
