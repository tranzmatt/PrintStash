"""Forecasts require independent daily evidence and positive stable growth."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest

from app.modules.storage.storage_backend.contracts import (
    CapacityReliability,
    StorageCapacity,
)
from app.modules.storage.storage_inventory import (
    ProviderCapacityEvidence,
    _measure_provider_capacity,
    growth_forecast,
)

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


class TestGrowthForecast:
    @pytest.mark.parametrize(
        "days", [0, 1, 6, 7], ids=["empty", "single", "few-days", "short-span"]
    )
    def test_withholds_insufficient_history(self, days):
        result = growth_forecast(
            [(BASE + timedelta(days=i), i * 100) for i in range(days)], 1000
        )
        assert result["status"] == "insufficient_data"
        assert result["days_remaining"] is None

    def test_estimates_positive_growth(self):
        result = growth_forecast(
            [(BASE + timedelta(days=i), i * 100) for i in range(8)], 1000
        )
        assert result == {
            "status": "estimated",
            "days_remaining": 10,
            "bytes_per_day": 100,
            "sample_count": 8,
            "window_days": 7,
            "confidence": "medium",
            "threshold_at": (BASE + timedelta(days=17)).isoformat(),
        }

    def test_reports_high_confidence_window(self):
        result = growth_forecast(
            [(BASE + timedelta(days=i), i * 100) for i in range(15)], 1000
        )

        assert result["confidence"] == "high"
        assert result["sample_count"] == 15
        assert result["window_days"] == 14

    def test_withholds_flat_growth(self):
        result = growth_forecast(
            [(BASE + timedelta(days=i), 100) for i in range(8)], 1000
        )
        assert result["status"] == "no_positive_growth"

    def test_withholds_unknown_capacity(self):
        result = growth_forecast(
            [(BASE + timedelta(days=i), i * 100) for i in range(8)], None
        )
        assert result["status"] == "capacity_unknown"
        assert result["days_remaining"] is None

    def test_withholds_outlier_growth(self):
        samples = [(BASE + timedelta(days=i), i * 100) for i in range(8)]
        samples.append((BASE + timedelta(days=8), 100000))
        assert growth_forecast(samples, 1000)["status"] == "unstable_growth"


def test_provider_capacity_refresh_is_single_flight():
    class Backend:
        calls = 0

        def capacity(self):
            self.calls += 1
            time.sleep(0.05)
            return StorageCapacity(
                total_bytes=100,
                used_bytes=40,
                available_bytes=60,
                quota_bytes=None,
                measured_at=BASE,
                method="contract_fake",
                reliability=CapacityReliability.EXACT,
            )

    backend = Backend()
    barrier = Barrier(2)

    def refresh():
        barrier.wait()
        return _measure_provider_capacity(
            backend, "single-flight-unit-target", ProviderCapacityEvidence()
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: refresh(), range(2)))

    assert backend.calls == 1
    assert [result.available_bytes for result in results] == [60, 60]
