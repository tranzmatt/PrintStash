from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import select

from app.core.time import ensure_utc
from app.db.models import (
    VaultAuditMode,
    VaultAuditPolicy,
    VaultAuditRun,
    VaultAuditRunState,
)
from app.modules.administration import vault_audit
from app.modules.administration.vault_audit_policy import (
    claim_due,
    health,
    list_policies,
    next_slot,
    skip_once,
)

NOW = datetime(2026, 9, 6, 2, 30, tzinfo=UTC)


def test_defaults_disabled(db_session):
    assert [
        (row.mode, row.enabled, row.cadence) for row in list_policies(db_session)
    ] == [("quick", False, "weekly"), ("full", False, "monthly")]


def test_claims_one_due_audit(db_session, make_user, make_audit_policy):
    policy = make_audit_policy(
        make_user(), enabled=True, next_due_at=NOW - timedelta(minutes=30)
    )
    run_id = claim_due(db_session, now=NOW)
    run = db_session.get(VaultAuditRun, run_id)
    assert run.trigger == "scheduled"
    assert ensure_utc(run.scheduled_for) == NOW - timedelta(minutes=30)
    assert run.requested_by == policy.requested_by
    assert run.active_slot == "audit"
    assert ensure_utc(policy.next_due_at) > NOW


def test_prevents_manual_scheduling_overlap(db_session, make_user, make_audit_policy):
    user = make_user()
    make_audit_policy(user, enabled=True, next_due_at=NOW)
    run, created = vault_audit.create_run(db_session, user.id, VaultAuditMode.QUICK)
    assert created
    assert claim_due(db_session, now=NOW) is None
    assert [row.id for row in db_session.exec(select(VaultAuditRun)).all()] == [run.id]


def test_catches_up_once(db_session, make_user, make_audit_policy):
    policy = make_audit_policy(
        make_user(), enabled=True, next_due_at=NOW - timedelta(days=100)
    )
    run_id = claim_due(db_session, now=NOW)
    run = db_session.get(VaultAuditRun, run_id)
    run.state = VaultAuditRunState.FAILED
    run.active_slot = None
    db_session.add(run)
    db_session.commit()
    assert claim_due(db_session, now=NOW) is None
    assert ensure_utc(policy.next_due_at) > NOW


@pytest.mark.parametrize("reason", ["maintenance", "storage_unavailable", "shutdown"])
def test_defers_work(db_session, make_user, make_audit_policy, reason):
    policy = make_audit_policy(make_user(), enabled=True, next_due_at=NOW)
    assert claim_due(db_session, now=NOW, deferred_reason=reason) is None
    assert policy.deferred_reason == reason
    assert db_session.exec(select(VaultAuditRun)).all() == []


def test_defers_outside_window(db_session, make_user, make_audit_policy):
    policy = make_audit_policy(make_user(), enabled=True, next_due_at=NOW)
    assert claim_due(db_session, now=NOW + timedelta(hours=4)) is None
    assert policy.deferred_reason == "outside_window"


def test_paused_policy_does_not_run(db_session, make_user, make_audit_policy):
    make_audit_policy(make_user(), enabled=True, paused=True, next_due_at=NOW)
    assert claim_due(db_session, now=NOW) is None


def test_skip_advances_once(db_session, make_user, make_audit_policy):
    from app.db.models import VaultAuditMode

    policy = make_audit_policy(make_user(), enabled=True, next_due_at=NOW)
    skip_once(db_session, VaultAuditMode.QUICK, now=NOW)
    assert ensure_utc(policy.next_due_at) == datetime(2026, 9, 13, 2, tzinfo=UTC)


def test_clamps_month_day(db_session, make_user, make_audit_policy):
    policy = make_audit_policy(make_user(), mode="full", month_day=31)
    assert next_slot(policy, datetime(2026, 2, 1, tzinfo=UTC)) == datetime(
        2026, 2, 28, 2, tzinfo=UTC
    )


def test_reports_overdue_health(db_session, make_user, make_audit_policy):
    make_audit_policy(make_user(), enabled=True, next_due_at=NOW - timedelta(days=1))
    assert health(db_session, now=NOW)["ok"] is False


def test_deadline_cancels_run(db_session, make_user, make_audit_run):
    run = make_audit_run(
        make_user(),
        state=VaultAuditRunState.PENDING,
        active_slot="audit",
        deadline_at=NOW,
    )
    vault_audit.execute_run(run.id)
    db_session.refresh(run)
    assert run.state == VaultAuditRunState.CANCELLED
    assert run.error_code == "audit_window_expired"
    assert run.result_recorded is False
    assert run.active_slot is None


@pytest.mark.parametrize(
    "payload",
    [
        {"timezone": "Invalid/Zone"},
        {"start_time": "24:99"},
        {"read_concurrency": 2},
        {"repair_actions": ["restore_recommended_revision"]},
        {"window_minutes": 0},
    ],
)
def test_rejects_invalid_policy(client, auth_headers, payload):
    response = client.put(
        "/api/v1/maintenance/audit-policies/quick", json=payload, headers=auth_headers
    )
    assert response.status_code == 422


def test_requires_full_cost_acknowledgement(client, auth_headers):
    response = client.put(
        "/api/v1/maintenance/audit-policies/full",
        json={"enabled": True},
        headers=auth_headers,
    )
    assert response.status_code == 400


def test_saves_policy_through_api(client, auth_headers, db_session):
    response = client.put(
        "/api/v1/maintenance/audit-policies/quick",
        json={"enabled": True},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["next_due_at"]
    assert db_session.get(VaultAuditPolicy, "quick").enabled


def test_denies_anonymous_policy_control(client):
    assert (
        client.put(
            "/api/v1/maintenance/audit-policies/quick", json={"enabled": True}
        ).status_code
        == 401
    )
