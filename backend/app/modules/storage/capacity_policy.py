"""Pure capacity decisions shared by admission, previews and diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, isfinite
from typing import Literal


@dataclass(frozen=True)
class CapacityDecision:
    outcome: Literal["allow", "warn", "deny"]
    required_bytes: int
    available_bytes: int | None
    reserved_bytes: int
    headroom_bytes: int
    reason: str
    confidence: Literal["measured", "unknown"]
    refresh_after_seconds: int = 60


@dataclass(frozen=True)
class CapacityPolicy:
    minimum_free_bytes: int = 0
    minimum_free_percent: float = 0

    def __post_init__(self) -> None:
        if (
            self.minimum_free_bytes < 0
            or not isfinite(self.minimum_free_percent)
            or not 0 <= self.minimum_free_percent <= 100
        ):
            raise ValueError("invalid capacity headroom")

    def headroom(self, total_bytes: int | None) -> int:
        return max(
            self.minimum_free_bytes,
            ceil((total_bytes or 0) * self.minimum_free_percent / 100),
        )

    def evaluate(
        self,
        required_bytes: int,
        *,
        available_bytes: int | None,
        reserved_bytes: int = 0,
        total_bytes: int | None = None,
    ) -> CapacityDecision:
        if (
            required_bytes < 0
            or reserved_bytes < 0
            or (available_bytes is not None and available_bytes < 0)
            or (total_bytes is not None and total_bytes < 0)
        ):
            raise ValueError("invalid capacity estimate")
        headroom = self.headroom(total_bytes)
        if available_bytes is None:
            return CapacityDecision(
                "warn",
                required_bytes,
                None,
                reserved_bytes,
                headroom,
                "capacity_unknown",
                "unknown",
            )
        if required_bytes + reserved_bytes + headroom > available_bytes:
            return CapacityDecision(
                "deny",
                required_bytes,
                available_bytes,
                reserved_bytes,
                headroom,
                "storage_capacity_exceeded",
                "measured",
            )
        if self.minimum_free_percent and total_bytes is None:
            return CapacityDecision(
                "warn",
                required_bytes,
                available_bytes,
                reserved_bytes,
                headroom,
                "capacity_total_unknown",
                "unknown",
            )
        return CapacityDecision(
            "allow",
            required_bytes,
            available_bytes,
            reserved_bytes,
            headroom,
            "capacity_available",
            "measured",
        )
