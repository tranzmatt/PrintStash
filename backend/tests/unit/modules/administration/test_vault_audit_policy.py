from datetime import UTC, date, datetime

import pytest

from app.modules.administration.vault_audit_policy import window_start
from app.modules.administration.vault_audit_results import compare


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 3, 8), datetime(2026, 3, 8, 7, tzinfo=UTC)),
        (date(2026, 11, 1), datetime(2026, 11, 1, 7, 30, tzinfo=UTC)),
    ],
)
def test_resolves_dst_wall_clock(day, expected):
    assert window_start(day, "02:30", "America/New_York") == expected


def test_chooses_first_fold_occurrence():
    assert window_start(date(2026, 11, 1), "01:30", "America/New_York") == datetime(
        2026, 11, 1, 5, 30, tzinfo=UTC
    )


def test_classifies_regressions():
    assert compare(
        {"worse": 1, "same": 2, "better": 3, "gone": 2},
        {"worse": 2, "same": 2, "better": 1, "new": 3},
    ) == {"new": 1, "worsened": 1, "unchanged": 1, "improved": 1, "resolved": 1}


def test_skipped_calendar_date_advances_to_valid_instant():
    assert window_start(date(2011, 12, 30), "02:30", "Pacific/Apia") == datetime(
        2011, 12, 30, 10, tzinfo=UTC
    )


def test_jitter_is_deterministic_and_bounded_by_window():
    from app.db.models import VaultAuditPolicy
    from app.modules.administration.vault_audit_policy import slot_jitter

    policy = VaultAuditPolicy(
        mode="full", revision=7, jitter_seconds=3600, window_minutes=2
    )
    assert slot_jitter(policy) == slot_jitter(policy)
    assert 0 <= slot_jitter(policy) <= 60
    policy.window_minutes = 1
    assert slot_jitter(policy) == 0


def test_backup_identity_uses_ownership_id_not_display_reference():
    from app.db.models import VaultAuditFinding, VaultAuditSeverity
    from app.modules.administration.vault_audit_results import finding_identity

    finding = VaultAuditFinding(
        run_id=1,
        code="backup_corrupt",
        severity=VaultAuditSeverity.CRITICAL,
        resource_type="backup",
        resource_identifier="old-display",
        details_json='{"ownership_id":42}',
    )
    identity = finding_identity(finding)
    finding.resource_identifier = "changed-display"
    assert finding_identity(finding) == identity
    finding.details_json = '{"ownership_id":43}'
    assert finding_identity(finding) != identity
