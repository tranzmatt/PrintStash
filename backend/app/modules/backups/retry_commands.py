"""Retry a failed backup destination using its persisted execution state."""

from __future__ import annotations

import uuid

from sqlmodel import col, select

import app.runtime.maintenance as backup_maintenance
from app.core.time import utcnow
from app.db.models import (
    BackupDestinationResult,
    BackupRetryAttempt,
    BackupRun,
)
from app.db.session import get_session_factory

from .backup_runs import (
    finish_run,
    reconcile_interrupted_runs,
    run_detail,
    update_result,
)


def retry_destination(result_id: str) -> dict:
    """Retry an exact destination from verified surviving bytes, never a rebuild."""
    from sqlalchemy import update

    from app.modules.backups.backup_replica_retry import (
        RetryRefused,
        publish_retry,
        reconcile_result,
        verified_survivor,
    )

    with backup_maintenance.backup_operation_lock:
        reconcile_interrupted_runs()
        with get_session_factory().scoped_session() as session:
            result = session.get(BackupDestinationResult, result_id)
            if result is None:
                raise LookupError("backup_destination_result_not_found")
            run = session.get(BackupRun, result.run_id)
            if run is None or result.outcome != "failed":
                raise RetryRefused("backup_retry_not_failed")
            claimed = session.execute(
                update(BackupDestinationResult)
                .where(
                    col(BackupDestinationResult.id) == result_id,
                    col(BackupDestinationResult.outcome) == "failed",
                )
                .values(outcome="publishing", updated_at=utcnow())
                .returning(col(BackupDestinationResult.id))
            )
            if claimed.scalar_one_or_none() is None:
                raise RetryRefused("backup_retry_in_progress")
            attempt = BackupRetryAttempt(
                id=uuid.uuid4().hex,
                destination_result_id=result_id,
                archive_sha256=run.archive_sha256,
            )
            session.add(attempt)
            session.commit()
            attempt_id = attempt.id
            session.refresh(run)
            session.refresh(result)
            run = BackupRun.model_validate(run.model_dump())
            result = BackupDestinationResult.model_validate(result.model_dump())
            survivors = [
                BackupDestinationResult.model_validate(row.model_dump())
                for row in session.exec(
                    select(BackupDestinationResult).where(
                        BackupDestinationResult.run_id == run.id,
                        BackupDestinationResult.outcome == "completed",
                    )
                ).all()
            ]
        try:
            published = (
                reconcile_result(result, run) if result.target_identity_json else False
            )
            if published:
                with get_session_factory().scoped_session() as session:
                    attempt = session.get(BackupRetryAttempt, attempt_id)
                    assert attempt is not None
                    attempt.source_result_id = result.id
                    session.add(attempt)
                    session.commit()
            for survivor in [] if published else survivors:
                from contextlib import ExitStack

                with ExitStack() as resources:
                    try:
                        path = resources.enter_context(verified_survivor(survivor, run))
                    except Exception:
                        continue
                    with get_session_factory().scoped_session() as session:
                        attempt = session.get(BackupRetryAttempt, attempt_id)
                        assert attempt is not None
                        attempt.source_result_id = survivor.id
                        session.add(attempt)
                        session.commit()
                    publish_retry(result, run, path)
                    published = True
                    break
            if not published:
                raise RetryRefused("backup_retry_new_backup_required")
        except BaseException as exc:
            reason = (
                str(exc)
                if isinstance(exc, RetryRefused)
                else "backup_retry_publication_failed"
            )
            update_result(result_id, outcome="failed", error_code=reason)
            with get_session_factory().scoped_session() as session:
                attempt = session.get(BackupRetryAttempt, attempt_id)
                assert attempt is not None
                attempt.outcome, attempt.error_code, attempt.finished_at = (
                    "failed",
                    reason,
                    utcnow(),
                )
                session.add(attempt)
                session.commit()
            finish_run(run.id)
            if isinstance(exc, Exception):
                raise RetryRefused(reason) from exc
            raise
        with get_session_factory().scoped_session() as session:
            attempt = session.get(BackupRetryAttempt, attempt_id)
            assert attempt is not None
            attempt.outcome, attempt.finished_at = "completed", utcnow()
            session.add(attempt)
            session.commit()
        finish_run(run.id)
        return next(
            row for row in run_detail(run.id)["destinations"] if row["id"] == result_id
        )
