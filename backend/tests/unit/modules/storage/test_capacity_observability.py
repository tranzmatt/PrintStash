"""Capacity metrics accept only bounded labels."""

from app.core.metrics import registry
from app.modules.storage.capacity_observability import (
    operation_kind,
    record_prediction_error,
)


class TestCapacityObservability:
    def test_operation_metric_never_uses_private_identifiers(self) -> None:
        assert operation_kind("artifact-upload:private-session") == "artifact-upload"
        assert operation_kind("private-user-value:secret") == "unknown"
        assert operation_kind("../../vault/key") == "unknown"

    def test_forecast_error_observation_has_no_private_labels(self) -> None:
        metric = "printstash_storage_forecast_prediction_error_ratio_count"
        before = registry.get_sample_value(metric) or 0

        record_prediction_error(0.25)

        assert registry.get_sample_value(metric) == before + 1
