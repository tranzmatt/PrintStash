"""Fingerprint outcomes have a closed set of terminal states."""

import pytest

from app.modules.media.fingerprints import FingerprintResult, FingerprintResultState


class TestFingerprintResult:
    @pytest.mark.parametrize(
        "state",
        [
            "ready",
            "partial",
            "failed",
            "unsupported",
            "unknown",
            "pending",
            "",
            None,
            True,
            1,
            [],
            {},
        ],
    )
    def test_rejects_a_state_outside_the_enum(self, state):
        with pytest.raises(TypeError, match="fingerprint_state"):
            FingerprintResult(state=state)

    @pytest.mark.parametrize("state", list(FingerprintResultState))
    def test_accepts_each_terminal_outcome(self, state):
        result = FingerprintResult(state=state)

        assert result.state is state
