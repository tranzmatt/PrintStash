"""Geometry tags preserve refused measurements independently of usable previews.

These pure data contracts are shared by the native worker and its supervisor;
unknown tags or reasons must fail instead of turning unavailable geometry into
an apparently successful measurement.
"""

from __future__ import annotations

import pytest

from app.modules.media.mesh_contracts import (
    GeometryNotRequested,
    GeometryReady,
    GeometryRefused,
    ThumbnailFailureReason,
    decode_geometry,
    encode_geometry,
)


class TestEncodeGeometry:
    @pytest.mark.parametrize(
        ("outcome", "encoded"),
        [
            (GeometryReady(), {"state": "ready"}),
            (GeometryNotRequested(), {"state": "not_requested"}),
            (
                GeometryRefused(ThumbnailFailureReason.RESOURCE_LIMIT),
                {"state": "refused", "reason": "resource_limit"},
            ),
        ],
    )
    def test_preserves_the_geometry_wire_shape(self, outcome, encoded):
        assert encode_geometry(outcome) == encoded

    def test_rejects_an_unknown_geometry_outcome(self):
        with pytest.raises(TypeError, match="invalid geometry outcome"):
            encode_geometry(object())


class TestDecodeGeometry:
    @pytest.mark.parametrize(
        ("encoded", "outcome"),
        [
            ({"state": "ready"}, GeometryReady()),
            ({"state": "not_requested"}, GeometryNotRequested()),
            *[
                ({"state": "refused", "reason": reason.value}, GeometryRefused(reason))
                for reason in ThumbnailFailureReason
            ],
        ],
    )
    def test_decodes_each_geometry_outcome(self, encoded, outcome):
        assert decode_geometry(encoded) == outcome

    @pytest.mark.parametrize(
        "encoded",
        [
            {},
            {"state": "unknown"},
            {"state": "ready", "reason": "resource_limit"},
            {"state": "not_requested", "extra": "value"},
            {"state": "refused"},
            {"state": "refused", "reason": "resource_limit", "extra": "value"},
        ],
    )
    def test_rejects_an_unknown_geometry_tag(self, encoded):
        with pytest.raises(ValueError, match="invalid geometry outcome"):
            decode_geometry(encoded)

    @pytest.mark.parametrize("reason", ["unknown", "", None, 1])
    def test_rejects_an_unknown_refusal_reason(self, reason):
        with pytest.raises(ValueError, match="is not a valid ThumbnailFailureReason"):
            decode_geometry({"state": "refused", "reason": reason})
