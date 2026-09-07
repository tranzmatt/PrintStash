"""Successful audit comparisons, safe storage events, and conservative repairs."""

from __future__ import annotations

import hashlib
import json

from sqlmodel import Session, select

from app.core.time import ensure_utc, utcnow
from app.db.models import (
    File,
    Metadata,
    NotificationEventType,
    VaultAuditEvent,
    VaultAuditFinding,
    VaultAuditFindingState,
    VaultAuditPolicy,
    VaultAuditRun,
    VaultAuditRunState,
)
from app.modules.administration.vault_audit_policy import SAFE_REPAIR_ACTIONS, next_slot
from app.modules.notifications.notifications import enqueue_storage_event
from app.modules.storage.storage_backend.runtime import get_backend


def finding_identity(row: VaultAuditFinding) -> str:
    details = json.loads(row.details_json)
    identity = next(
        (
            str(details[key])
            for key in (
                "resource_id",
                "file_id",
                "model_id",
                "library_id",
                "job_id",
                "inbox_item_id",
            )
            if details.get(key) is not None
        ),
        row.resource_identifier,
    )
    return hashlib.sha256(
        f"{row.resource_type}:{identity}:{row.code}".encode()
    ).hexdigest()


def finding_snapshot(session: Session, run_id: int) -> dict[str, int]:
    ranks = {"info": 1, "warning": 2, "critical": 3}
    return {
        finding_identity(row): ranks[row.severity.value]
        for row in session.exec(
            select(VaultAuditFinding).where(VaultAuditFinding.run_id == run_id)
        ).all()
        if row.state != VaultAuditFindingState.RESOLVED
    }


def compare(previous: dict[str, int], current: dict[str, int]) -> dict[str, int]:
    return {
        "new": sum(key not in previous for key in current),
        "worsened": sum(
            key in previous and value > previous[key] for key, value in current.items()
        ),
        "unchanged": sum(
            key in previous and value == previous[key] for key, value in current.items()
        ),
        "improved": sum(
            key in previous and value < previous[key] for key, value in current.items()
        ),
        "resolved": sum(key not in current for key in previous),
    }


def record_event(
    session: Session,
    run: VaultAuditRun,
    event_type: NotificationEventType,
    summary: dict[str, int],
    *,
    phase: str = "result",
) -> None:
    key = f"audit:{run.id}:{phase}:{event_type.value}"
    if (
        session.exec(
            select(VaultAuditEvent).where(VaultAuditEvent.dedup_key == key)
        ).first()
        is not None
    ):
        return
    session.add(
        VaultAuditEvent(
            run_id=run.id,
            dedup_key=key,
            event_type=event_type.value,
            summary_json=json.dumps(summary, sort_keys=True),
        )
    )
    enqueue_storage_event(
        session, event_type, run_id=run.id, mode=run.mode.value, summary=summary
    )


def record_success(session: Session, run: VaultAuditRun) -> None:
    """Caller commits run completion, baseline and outbox as one transaction."""
    if run.state != VaultAuditRunState.COMPLETED or run.result_recorded:
        return
    baseline = session.exec(
        select(VaultAuditRun)
        .where(
            VaultAuditRun.id != run.id,
            VaultAuditRun.mode == run.mode,
            VaultAuditRun.scope == run.scope,
            VaultAuditRun.storage_generation == run.storage_generation,
            VaultAuditRun.state == VaultAuditRunState.COMPLETED,
            VaultAuditRun.result_recorded.is_(True),
        )
        .order_by(VaultAuditRun.finished_at.desc(), VaultAuditRun.id.desc())
    ).first()  # noqa: E712
    run.baseline_run_id = baseline.id if baseline else None
    # Save the immutable observation, so later manual repairs cannot rewrite history.
    previous = (
        json.loads(baseline.regression_json).get("snapshot", {}) if baseline else {}
    )
    snapshot = finding_snapshot(session, run.id)
    summary = compare(previous, snapshot)
    run.regression_json = json.dumps(
        {"snapshot": snapshot, "summary": summary}, sort_keys=True
    )
    run.result_recorded = True
    if summary["new"] or summary["worsened"]:
        record_event(session, run, NotificationEventType.STORAGE_REGRESSION, summary)
    if summary["resolved"] or summary["improved"]:
        record_event(session, run, NotificationEventType.STORAGE_RECOVERY, summary)
    policy = session.get(VaultAuditPolicy, run.mode.value)
    if policy is not None and run.scope == "vault":
        policy.last_success_at = run.finished_at
        if (
            policy.next_due_at is not None
            and run.started_at is not None
            and ensure_utc(run.started_at) >= ensure_utc(policy.next_due_at)
        ):
            policy.next_due_at = next_slot(policy, ensure_utc(run.finished_at))
        session.add(policy)
    session.add(run)


def _authoritative_hash(file: File) -> str:
    digest = hashlib.sha256()
    for chunk in get_backend().stream_chunks(file.path):
        digest.update(chunk)
    return digest.hexdigest()


def repair_safe_findings(session: Session, run: VaultAuditRun) -> None:
    """Only derived outputs with live, verified, managed source identity qualify."""
    from PIL import Image

    from app.modules.administration import audit
    from app.modules.ingestion.ingestion import strategy_for_artifact
    from app.modules.media.thumbnail_engine import ThumbnailEngine
    from app.modules.media.thumbnail_generations import ensure_thumbnail

    allowed = set(json.loads(run.repair_actions_json)) & SAFE_REPAIR_ACTIONS
    if not allowed:
        return
    before = finding_snapshot(session, run.id)
    for finding in session.exec(
        select(VaultAuditFinding).where(
            VaultAuditFinding.run_id == run.id,
            VaultAuditFinding.state == VaultAuditFindingState.OPEN,
        )
    ).all():
        if finding.repair_action not in allowed:
            continue
        if run.deadline_at is not None and utcnow() >= ensure_utc(run.deadline_at):
            break
        details = json.loads(finding.details_json)
        file = (
            session.get(File, details.get("file_id"))
            if details.get("file_id")
            else None
        )
        if (
            file is None
            or file.is_external
            or file.deleted_at is not None
            or not file.sha256
        ):
            continue
        ok = False
        try:
            if _authoritative_hash(file) != file.sha256.lower():
                continue
            if (
                finding.repair_action == "reparse_metadata"
                and finding.code == "metadata_missing"
            ):
                if (
                    session.exec(
                        select(Metadata).where(Metadata.file_id == file.id)
                    ).first()
                    is None
                ):
                    with get_backend().local_path(file.path) as path:
                        values, _ = strategy_for_artifact(file.file_type).process(path)
                    session.add(
                        Metadata(
                            file_id=file.id,
                            **{
                                key: value
                                for key, value in values.items()
                                if key in Metadata.model_fields
                            },
                        )
                    )
                    session.commit()
                ok = (
                    session.exec(
                        select(Metadata).where(Metadata.file_id == file.id)
                    ).first()
                    is not None
                )
            elif finding.repair_action == "regenerate_thumbnail" and finding.code in {
                "thumbnail_missing",
                "thumbnail_unreadable",
            }:
                result = ensure_thumbnail(
                    session,
                    file,
                    force=True,
                    promote=True,
                    backend=get_backend(),
                    engine=ThumbnailEngine(),
                )
                session.refresh(file)
                if result.available and file.thumbnail_path:
                    with (
                        get_backend().local_path(file.thumbnail_path) as path,
                        Image.open(path) as image,
                    ):
                        image.verify()
                    ok = True
            ok = ok and _authoritative_hash(file) == file.sha256.lower()
        except Exception:
            session.rollback()
            ok = False
        audit.record(
            session,
            action="audit.auto_repair",
            resource_type="vault_audit_finding",
            resource_id=finding.id,
            actor_id=None,
            diff={"action": finding.repair_action, "verified": ok, "run_id": run.id},
        )
        if ok:
            finding.state = VaultAuditFindingState.RESOLVED
            finding.resolved_at = utcnow()
            session.add(finding)
            session.commit()
    after = finding_snapshot(session, run.id)
    summary = compare(before, after)
    if summary["resolved"]:
        record_event(
            session,
            run,
            NotificationEventType.STORAGE_RECOVERY,
            summary,
            phase="repair",
        )
        recorded = json.loads(run.regression_json)
        recorded["snapshot"] = after
        recorded["repair_summary"] = summary
        run.regression_json = json.dumps(recorded, sort_keys=True)
        session.add(run)
        session.commit()
