import json
from datetime import timedelta

import pytest
from sqlmodel import select

from app.core.time import utcnow
from app.db.models import NotificationDelivery, NotificationEventType, VaultAuditEvent, VaultAuditFindingState, VaultAuditMode, VaultAuditRunState
from app.modules.administration.vault_audit_results import record_success, repair_safe_findings


def test_deduplicates_events(db_session, make_user, make_audit_run, make_audit_finding):
    run = make_audit_run(make_user(), finished_at=utcnow())
    make_audit_finding(run)
    record_success(db_session, run)
    db_session.commit()
    record_success(db_session, run)
    db_session.commit()
    assert len(db_session.exec(select(VaultAuditEvent)).all()) == 1


@pytest.mark.parametrize("state", [VaultAuditRunState.FAILED, VaultAuditRunState.CANCELLED])
def test_preserves_baseline_after_failure(db_session, make_user, make_audit_run, make_audit_finding, state):
    user = make_user()
    baseline = make_audit_run(user, finished_at=utcnow() - timedelta(hours=1))
    make_audit_finding(baseline)
    record_success(db_session, baseline)
    db_session.commit()
    failed = make_audit_run(user, state=state, finished_at=utcnow())
    record_success(db_session, failed)
    db_session.commit()
    next_run = make_audit_run(user, finished_at=utcnow())
    record_success(db_session, next_run)
    db_session.commit()
    assert next_run.baseline_run_id == baseline.id
    assert json.loads(next_run.regression_json)["summary"]["resolved"] == 1


@pytest.mark.parametrize("overrides", [{"mode": VaultAuditMode.FULL}, {"scope": "other"}, {"storage_generation": "other"}])
def test_excludes_incomparable_baseline(db_session, make_user, make_audit_run, overrides):
    user = make_user()
    baseline = make_audit_run(user, finished_at=utcnow(), **overrides)
    record_success(db_session, baseline)
    db_session.commit()
    run = make_audit_run(user, finished_at=utcnow())
    record_success(db_session, run)
    assert run.baseline_run_id is None


def test_records_recovery(db_session, make_user, make_audit_run, make_audit_finding):
    user = make_user()
    baseline = make_audit_run(user, finished_at=utcnow() - timedelta(hours=1))
    make_audit_finding(baseline)
    record_success(db_session, baseline)
    db_session.commit()
    run = make_audit_run(user, finished_at=utcnow())
    record_success(db_session, run)
    db_session.commit()
    events = db_session.exec(select(VaultAuditEvent).where(VaultAuditEvent.run_id == run.id)).all()
    assert [row.event_type for row in events] == ["storage_recovery"]


def test_rejects_unsafe_automatic_repair(db_session, make_user, make_audit_run, make_audit_finding):
    run = make_audit_run(make_user(), repair_actions_json='["restore_recommended_revision"]')
    finding = make_audit_finding(run, repair_action="restore_recommended_revision")
    repair_safe_findings(db_session, run)
    db_session.refresh(finding)
    assert finding.state == VaultAuditFindingState.OPEN


def test_does_not_change_source_with_invalid_hash(db_session, local_storage, make_user, make_model, make_stored_file, make_audit_run, make_audit_finding):
    model = make_model()
    file = make_stored_file(model, content=b"invalid source")
    file.sha256 = "0" * 64
    db_session.add(file)
    db_session.commit()
    run = make_audit_run(make_user(), repair_actions_json='["reparse_metadata"]')
    finding = make_audit_finding(run, code="metadata_missing", repair_action="reparse_metadata", details_json=json.dumps({"file_id": file.id}))
    repair_safe_findings(db_session, run)
    db_session.refresh(finding)
    assert finding.state == VaultAuditFindingState.OPEN


@pytest.mark.parametrize("enabled,events", [(False, '["storage_regression"]'), (True, '["print_failed"]')])
def test_respects_notification_preferences(db_session, make_user, make_system_config, make_notification_channel, make_audit_run, make_audit_finding, enabled, events):
    make_system_config(notifications_enabled=enabled)
    make_notification_channel(events_json=events)
    run = make_audit_run(make_user(), finished_at=utcnow())
    make_audit_finding(run)
    record_success(db_session, run)
    db_session.commit()
    assert db_session.exec(select(NotificationDelivery)).all() == []


def test_queues_safe_storage_context(db_session, make_user, make_system_config, make_notification_channel, make_audit_run, make_audit_finding):
    make_system_config(notifications_enabled=True)
    make_notification_channel(events_json='["storage_regression"]')
    run = make_audit_run(make_user(), finished_at=utcnow())
    make_audit_finding(run, resource_identifier="private-model-name", details_json='{"path":"/private/storage/key"}')
    record_success(db_session, run)
    db_session.commit()
    delivery = db_session.exec(select(NotificationDelivery)).one()
    assert delivery.event_type == NotificationEventType.STORAGE_REGRESSION
    assert "private" not in delivery.context_json
    assert delivery.printer_id is None
    assert delivery.print_job_id is None
    assert json.loads(delivery.context_json)["summary"]["new"] == 1
