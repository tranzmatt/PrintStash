"""Single-process audit scheduling; durable claims survive loop restarts."""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime

from app.core.logging import get_logger
from app.db.session import get_session_factory
from app.modules.administration.vault_audit import execute_run, request_cancel
from app.modules.administration.vault_audit_policy import claim_due
from app.modules.storage.storage_backend.runtime import get_backend
from app.runtime.maintenance import begin_mutating_operation, end_mutating_operation

logger = get_logger(__name__)


def run_due_audit(
    *, now: datetime | None = None, shutdown: threading.Event | None = None
) -> int | None:
    admitted = begin_mutating_operation()
    try:
        reason = None if admitted else "maintenance"
        if admitted:
            try:
                probe = get_backend().health_probe()
                if not probe.get("ok", False):
                    reason = "storage_unavailable"
            except Exception:
                reason = "storage_unavailable"
        if shutdown is not None and shutdown.is_set():
            reason = "shutdown"
        with get_session_factory().scoped_session() as session:
            run_id = claim_due(session, now=now, deferred_reason=reason)
        if run_id is not None:
            if shutdown is not None and shutdown.is_set():
                with get_session_factory().scoped_session() as session:
                    request_cancel(session, run_id)
            execute_run(run_id)
        return run_id
    finally:
        if admitted:
            end_mutating_operation()


async def run_audit_scheduler() -> None:
    shutdown = threading.Event()
    while True:
        # Shield the admitted thread and drain it before releasing runtime dependencies.
        task = asyncio.create_task(asyncio.to_thread(run_due_audit, shutdown=shutdown))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            shutdown.set()
            await asyncio.to_thread(_cancel_active_audits)
            await task
            raise
        except Exception:
            logger.exception("scheduled vault audit tick failed")
        await asyncio.sleep(30)


def _cancel_active_audits() -> None:
    from sqlmodel import col, select

    from app.db.models import VaultAuditRun, VaultAuditRunState

    with get_session_factory().scoped_session() as session:
        for run in session.exec(
            select(VaultAuditRun).where(
                col(VaultAuditRun.active_slot).is_not(None)
                | col(VaultAuditRun.state).in_(
                    (VaultAuditRunState.PENDING, VaultAuditRunState.RUNNING)
                )
            )
        ).all():
            run.cancel_requested = True
            session.add(run)
        session.commit()
