"""Audit diagnostics and detail retention, independent of scheduler transport."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from prometheus_client import Gauge
from sqlalchemy import delete
from sqlalchemy.engine import CursorResult
from sqlmodel import Session, col, select

from app.core.metrics import registry
from app.core.time import ensure_utc, utcnow
from app.db.models import (
    NotificationDelivery,
    NotificationEventType,
    VaultAuditEvent,
    VaultAuditFinding,
    VaultAuditPolicy,
    VaultAuditRun,
    VaultAuditRunState,
)
from app.modules.notifications.notifications import enqueue_storage_event

runs = Gauge(
    "printstash_audit_runs",
    "Persisted audit runs by trigger and result.",
    ["trigger", "result"],
    registry=registry,
)
bytes_read = Gauge(
    "printstash_audit_bytes_read",
    "Persisted authoritative bytes read.",
    ["mode"],
    registry=registry,
)
duration = Gauge(
    "printstash_audit_duration_seconds",
    "Total persisted completed audit duration.",
    ["mode"],
    registry=registry,
)
findings = Gauge(
    "printstash_audit_findings",
    "Findings in retained detailed history.",
    ["severity", "category"],
    registry=registry,
)
deferrals = Gauge(
    "printstash_audit_deferred",
    "Current deferred audit policies.",
    ["reason"],
    registry=registry,
)
overdue = Gauge(
    "printstash_audit_overdue",
    "Current overdue audit policies.",
    ["mode"],
    registry=registry,
)
notifications = Gauge(
    "printstash_audit_notifications",
    "Durable storage notification evidence.",
    ["event"],
    registry=registry,
)
repairs = Gauge(
    "printstash_audit_repairs",
    "Persisted automatic repair attempts.",
    ["result"],
    registry=registry,
)


def record_overdue(
    session: Session, policy: VaultAuditPolicy, *, now: datetime
) -> None:
    if policy.next_due_at is None or now <= ensure_utc(policy.next_due_at) + timedelta(
        minutes=policy.max_lateness_minutes
    ):
        return
    slot = ensure_utc(policy.next_due_at).isoformat()
    key = f"policy:{policy.mode}:{policy.revision}:{slot}:overdue"
    if session.exec(
        select(VaultAuditEvent).where(VaultAuditEvent.dedup_key == key)
    ).first():
        return
    event_type = NotificationEventType.STORAGE_AUDIT_OVERDUE
    session.add(
        VaultAuditEvent(
            dedup_key=key,
            event_type=event_type.value,
            summary_json=json.dumps({"mode": policy.mode, "scheduled_for": slot}),
        )
    )
    if policy.notification_threshold != "off":
        enqueue_storage_event(
            session,
            event_type,
            run_id=None,
            mode=policy.mode,
            summary={},
            channel_ids=json.loads(policy.notification_channels_json),
        )
        deliveries = [
            row for row in session.new if isinstance(row, NotificationDelivery)
        ]
        if deliveries:
            due = (
                max(
                    now,
                    ensure_utc(policy.last_notified_at)
                    + timedelta(minutes=policy.notification_cooldown_minutes),
                )
                if policy.last_notified_at
                else now
            )
            for row in deliveries:
                row.next_retry_at = due
            policy.last_notified_at = due
            session.add(policy)
    # Same transaction as the durable evidence; do not advance the missed slot.
    session.commit()


def prune_details(
    session: Session, *, now: datetime | None = None, retention_days: int = 90
) -> int:
    """Retain summaries/events indefinitely; preserve current comparison evidence.

    Old details can contain filenames, so they expire after 90 days. Protect every
    active run, newest successful mode/scope/generation and its referenced baseline.
    Immutable comparison digests and aggregate evidence never depend on detail rows.
    """
    cutoff = ensure_utc(now or utcnow()) - timedelta(days=retention_days)
    rows = session.exec(
        select(VaultAuditRun).order_by(col(VaultAuditRun.id).desc())
    ).all()
    protected: set[int] = set()
    groups: set[tuple] = set()
    for run in rows:
        assert run.id is not None
        group = (run.mode, run.scope, run.storage_generation)
        if run.active_slot or run.state in {
            VaultAuditRunState.PENDING,
            VaultAuditRunState.RUNNING,
        }:
            protected.add(run.id)
        if (
            run.state == VaultAuditRunState.COMPLETED
            and run.result_recorded
            and group not in groups
        ):
            groups.add(group)
            protected.add(run.id)
            if run.baseline_run_id:
                protected.add(run.baseline_run_id)
    expired = [
        run.id
        for run in rows
        if run.id not in protected
        and run.finished_at
        and ensure_utc(run.finished_at) < cutoff
    ]
    if not expired:
        return 0
    result = session.execute(
        delete(VaultAuditFinding).where(col(VaultAuditFinding.run_id).in_(expired))
    )
    session.commit()
    assert isinstance(result, CursorResult)
    return result.rowcount


def refresh_metrics(session: Session) -> None:
    """Bounded labels from durable rows; safe across process restart."""
    from collections import Counter

    from app.db.models import AuditLog
    from app.modules.administration.vault_audit_policy import health
    from app.modules.administration.vault_audit_results import category

    run_rows = session.exec(select(VaultAuditRun)).all()
    for metric in (
        runs,
        bytes_read,
        duration,
        findings,
        deferrals,
        overdue,
        notifications,
        repairs,
    ):
        metric.clear()
    for (trigger, result), count in Counter(
        ("scheduled" if row.trigger == "scheduled" else "manual", row.state.value)
        for row in run_rows
    ).items():
        runs.labels(trigger, result).set(count)
    for mode in ("quick", "full"):
        selected = [row for row in run_rows if row.mode.value == mode]
        bytes_read.labels(mode).set(sum(row.bytes_read for row in selected))
        duration.labels(mode).set(
            sum(
                max(
                    0,
                    (
                        ensure_utc(row.finished_at) - ensure_utc(row.started_at)
                    ).total_seconds(),
                )
                for row in selected
                if row.finished_at and row.started_at
            )
        )
    for (severity, group), count in Counter(
        (row.severity.value, category(row.code))
        for row in session.exec(select(VaultAuditFinding)).all()
    ).items():
        findings.labels(severity, group).set(count)
    for row in health(session)["policies"]:
        overdue.labels(row["mode"]).set(int(row["overdue"]))
        if row["deferred_reason"]:
            reason = row["deferred_reason"]
            if reason not in {
                "maintenance",
                "storage_unavailable",
                "shutdown",
                "outside_window",
                "audit_active",
                "skipped_once",
                "jitter",
                "launch_retry",
            }:
                reason = "other"
            deferrals.labels(reason).inc()
    for event, count in Counter(
        row.event_type for row in session.exec(select(VaultAuditEvent)).all()
    ).items():
        if event in {
            item.value
            for item in NotificationEventType
            if item.value.startswith("storage_")
        }:
            notifications.labels(event).set(count)
    for result, count in Counter(
        "verified" if json.loads(row.diff_json).get("verified") else "failed"
        for row in session.exec(
            select(AuditLog).where(AuditLog.action == "audit.auto_repair")
        ).all()
    ).items():
        repairs.labels(result).set(count)
