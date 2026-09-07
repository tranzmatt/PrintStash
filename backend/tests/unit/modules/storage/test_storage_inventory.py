"""Forecasts require independent daily evidence and positive stable growth."""

from datetime import datetime, timedelta, timezone

import pytest

from app.modules.storage.storage_inventory import growth_forecast

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
        }

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
