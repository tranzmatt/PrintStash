"""Bounded-label capacity and inventory telemetry.

No operation id, Collection, Model, user, path, key, or provider credential is
ever accepted as a label value.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

from app.core.metrics import registry

_OPERATION_KINDS = frozenset(
    {
        "archive-export",
        "archive-extract",
        "archive-import",
        "artifact",
        "artifact-materialization",
        "artifact-stream",
        "artifact-upload",
        "backup",
        "backup-download",
        "backup-adoption",
        "backup-upload",
        "browser-upload",
        "media-repair",
        "media-conversion",
        "postgres-restore",
        "printer-capture",
        "restore",
        "thumbnail",
        "upload",
        "url-download",
        "vault-migration",
    }
)
_OUTCOMES = frozenset({"allow", "warn", "deny"})
_REASONS = frozenset(
    {
        "capacity_available",
        "capacity_unknown",
        "capacity_total_unknown",
        "storage_capacity_exceeded",
    }
)
_PROVIDERS = frozenset({"local", "s3", "webdav", "sftp", "unknown"})
_CATEGORIES = frozenset(
    {
        "stl",
        "3mf",
        "obj",
        "step",
        "gcode",
        "other",
        "thumbnail",
        "legacy_thumbnail",
        "derived_stl",
        "document",
        "document_image",
        "collection_image",
        "staging",
        "cache",
        "backups",
        "unknown",
    }
)
_LIFECYCLES = frozenset(
    {"live", "trash", "external", "owned", "temporary", "replica", "unknown"}
)

capacity_decisions = Counter(
    "printstash_storage_capacity_decisions_total",
    "Capacity admission decisions with bounded operation labels.",
    labelnames=("operation", "outcome", "reason"),
    registry=registry,
)
active_capacity_reservations = Gauge(
    "printstash_storage_capacity_active_reservations",
    "Process-observed active capacity reservations by operation kind.",
    labelnames=("operation",),
    registry=registry,
)
inventory_duration = Histogram(
    "printstash_storage_inventory_duration_seconds",
    "Time spent producing bounded inventory evidence.",
    labelnames=("outcome", "mode"),
    registry=registry,
)
inventory_bytes = Gauge(
    "printstash_storage_inventory_bytes",
    "Latest known inventory bytes by bounded category and lifecycle.",
    labelnames=("category", "lifecycle"),
    registry=registry,
)
provider_available_bytes = Gauge(
    "printstash_storage_provider_available_bytes",
    "Latest measured provider available bytes when known.",
    labelnames=("provider",),
    registry=registry,
)
cleanup_outcomes = Counter(
    "printstash_storage_cleanup_total",
    "Explicit owner-routed storage cleanup outcomes.",
    labelnames=("owner", "outcome"),
    registry=registry,
)
forecast_prediction_error = Histogram(
    "printstash_storage_forecast_prediction_error_ratio",
    "Absolute forecast error divided by current owned bytes.",
    registry=registry,
)


def operation_kind(operation_id: str) -> str:
    candidate = operation_id.partition(":")[0]
    return candidate if candidate in _OPERATION_KINDS else "unknown"


def record_decision(operation_id: str, outcome: str, reason: str) -> None:
    try:
        safe_outcome = outcome if outcome in _OUTCOMES else "deny"
        safe_reason = reason if reason in _REASONS else "unknown"
        capacity_decisions.labels(
            operation_kind(operation_id), safe_outcome, safe_reason
        ).inc()
    except Exception:  # metrics never alter admission
        return


def change_reservations(operation_id: str, delta: int) -> None:
    try:
        active_capacity_reservations.labels(operation_kind(operation_id)).inc(delta)
    except Exception:
        return


def observe_inventory(current, *, provider: str) -> None:
    try:
        for bucket in current.buckets:
            category = bucket.category if bucket.category in _CATEGORIES else "unknown"
            lifecycle = (
                bucket.lifecycle if bucket.lifecycle in _LIFECYCLES else "unknown"
            )
            inventory_bytes.labels(category, lifecycle).set(bucket.logical_bytes)
        available = current.provider_capacity.available_bytes
        if available is not None:
            safe_provider = provider if provider in _PROVIDERS else "unknown"
            provider_available_bytes.labels(safe_provider).set(available)
    except Exception:
        return


def record_cleanup(owner: str, outcome: str) -> None:
    try:
        safe_owner = (
            owner if owner in {"staging", "trash", "backups", "cache"} else "unknown"
        )
        safe_outcome = outcome if outcome in {"success", "error"} else "error"
        cleanup_outcomes.labels(safe_owner, safe_outcome).inc()
    except Exception:
        return


def record_prediction_error(ratio: float) -> None:
    try:
        if ratio >= 0:
            forecast_prediction_error.observe(ratio)
    except Exception:
        return
