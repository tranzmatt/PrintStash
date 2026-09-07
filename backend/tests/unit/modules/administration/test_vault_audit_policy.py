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
