"""Stable mesh derivative data and tagged geometry outcomes.

Workers, supervisors and publishers share these contracts without importing the
thumbnail strategy owner. Geometry tags preserve refusal independently from a
usable preview; transport framing remains with the supervisor.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, Literal, Optional, Protocol

from printstash_core.mesh.measurements import (
    VolumeLegacyUnassessed,
    VolumeMeasurement,
    VolumeNotCalculated,
    VolumeNotCalculatedCause,
    validate_geometry_extents,
    volume_value,
)
from printstash_core.mesh.similarity.budgets import MAX_ANALYSIS_FACES

from app.modules.media.mesh_telemetry import PhaseStats, SupervisionStats

if TYPE_CHECKING:
    from app.modules.media.fingerprints import FingerprintResult

Geometry = Dict[str, Optional[float]]
ProgressReporter = Callable[[str], None]


class ThumbnailStrategy(str, Enum):
    NONE = "none"
    EMBEDDED = "embedded"
    FULL = "full"
    STREAMING = "streaming"
    FALLBACK = "fallback"


class ThumbnailFailureReason(str, Enum):
    INVALID_SOURCE = "invalid_source"
    UNSUPPORTED_FORMAT = "unsupported_format"
    NO_GEOMETRY = "no_geometry"
    RESOURCE_LIMIT = "resource_limit"
    TIMEOUT = "timeout"
    RENDERER_NO_OUTPUT = "renderer_no_output"
    WORKER_FAILED = "worker_failed"
    STORAGE = "storage"


@dataclass(frozen=True)
class GeometryReady:
    """Measurements were obtained; individual unknown measurements are legitimate."""


@dataclass(frozen=True)
class GeometryRefused:
    reason: ThumbnailFailureReason


@dataclass(frozen=True)
class GeometryNotRequested:
    pass


GeometryOutcome = GeometryReady | GeometryRefused | GeometryNotRequested


@dataclass(frozen=True)
class MeshMeasurements:
    geometry: Geometry
    volume: VolumeMeasurement

    def __post_init__(self) -> None:
        validate_geometry_extents(self.geometry)
        scalar = self.geometry["volume_mm3"]
        if isinstance(scalar, bool) or scalar != volume_value(self.volume):
            raise ValueError("volume scalar disagrees with measurement evidence")


@dataclass(frozen=True)
class ThumbnailRequest:
    path: Path
    file_type: str | None = None
    width: int | None = None
    height: int | None = None
    include_geometry: bool = True
    reason: str = "ingestion"
    report: ProgressReporter | None = None
    output_format: Literal["PNG", "WEBP"] = "PNG"
    include_fingerprint: bool = False
    triangle_cap: int = MAX_ANALYSIS_FACES
    include_thumbnail: bool = True


@dataclass(frozen=True)
class ThumbnailResult:
    image: bytes | None
    geometry: Geometry
    geometry_outcome: GeometryOutcome
    volume: VolumeMeasurement
    strategy: ThumbnailStrategy
    complete: bool
    failure_reason: ThumbnailFailureReason | None
    duration_ms: int
    peak_rss_bytes: int | None
    fingerprint_result: FingerprintResult | None = None
    phase_stats: tuple[PhaseStats, ...] = ()
    supervision: SupervisionStats | None = None

    def __post_init__(self) -> None:
        if isinstance(
            self.geometry_outcome, GeometryNotRequested
        ) and self.volume != VolumeNotCalculated(
            VolumeNotCalculatedCause.NOT_REQUESTED
        ):
            raise ValueError("volume was not requested")
        if isinstance(
            self.geometry_outcome, GeometryRefused
        ) and self.volume != VolumeNotCalculated(
            VolumeNotCalculatedCause.GEOMETRY_UNAVAILABLE
        ):
            raise ValueError("refused geometry cannot carry assessed volume")
        if isinstance(self.volume, VolumeNotCalculated) and self.volume.cause in (
            VolumeNotCalculatedCause.ENRICHMENT_PENDING,
            VolumeNotCalculatedCause.NOT_APPLICABLE,
        ):
            raise ValueError("native output cannot carry durable row volume causes")
        if isinstance(self.volume, VolumeLegacyUnassessed):
            raise ValueError("native output cannot be legacy unassessed")
        MeshMeasurements(self.geometry, self.volume)


class ThumbnailMetricsSink(Protocol):
    def increment(self, name: str, *, labels: dict[str, str]) -> None: ...

    def observe(self, name: str, value: float, *, labels: dict[str, str]) -> None: ...


def encode_geometry(outcome: GeometryOutcome) -> dict[str, str]:
    if isinstance(outcome, GeometryReady):
        return {"state": "ready"}
    if isinstance(outcome, GeometryRefused):
        return {"state": "refused", "reason": outcome.reason.value}
    if isinstance(outcome, GeometryNotRequested):
        return {"state": "not_requested"}
    raise TypeError("invalid geometry outcome")


def decode_geometry(raw: dict[str, str]) -> GeometryOutcome:
    if raw == {"state": "ready"}:
        return GeometryReady()
    if raw == {"state": "not_requested"}:
        return GeometryNotRequested()
    if set(raw) == {"state", "reason"} and raw["state"] == "refused":
        return GeometryRefused(ThumbnailFailureReason(raw["reason"]))
    raise ValueError("invalid geometry outcome")
