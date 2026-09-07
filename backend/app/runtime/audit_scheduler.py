"""Single-process audit scheduling; durable claims survive loop restarts."""

from __future__ import annotations

import asyncio
from datetime import datetime

from app.core.logging import get_logger
from app.db.session import get_session_factory
from app.modules.administration.vault_audit import execute_run
from app.modules.administration.vault_audit_policy import claim_due
from app.modules.storage.storage_backend.runtime import get_backend
from app.runtime.maintenance import begin_mutating_operation, end_mutating_operation

logger = get_logger(__name__)


def run_due_audit(*, now: datetime | None = None) -> int | None:
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
        with get_session_factory().scoped_session() as session:
            run_id = claim_due(session, now=now, deferred_reason=reason)
        if run_id is not None:
            execute_run(run_id)
        return run_id
    finally:
        if admitted:
            end_mutating_operation()


async def run_audit_scheduler() -> None:
    while True:
        # Shield the admitted thread and drain it before releasing runtime dependencies.
        task = asyncio.create_task(asyncio.to_thread(run_due_audit))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise
        except Exception:
            logger.exception("scheduled vault audit tick failed")
        await asyncio.sleep(30)
