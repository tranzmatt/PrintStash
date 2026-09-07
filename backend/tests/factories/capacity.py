"""Factories for persisted capacity claims and inventory samples."""

from datetime import timedelta
from typing import Any

from sqlmodel import Session

from app.core.time import utcnow
from app.db.models import CapacityLock, CapacityReservation, StorageInventorySample
from tests.factories._support import nth, save


def build_capacity_lock(session: Session, **overrides: Any) -> CapacityLock:
    overrides.setdefault("id", 1)
    return save(session, CapacityLock(**overrides))


def build_capacity_reservation(
    session: Session, *, expired: bool = False, **overrides: Any
) -> CapacityReservation:
    overrides.setdefault("operation_id", f"operation-{nth('capacity')}")
    overrides.setdefault(
        "resources_json",
        '[{"domain_id":"quota:test","required_bytes":10,"available_bytes":100,"role":"test","path":null}]',
    )
    overrides.setdefault(
        "expires_at", utcnow() + timedelta(seconds=-60 if expired else 900)
    )
    return save(session, CapacityReservation(**overrides))


def build_storage_inventory_sample(
    session: Session, **overrides: Any
) -> StorageInventorySample:
    overrides.setdefault("target_ref", "test-target")
    overrides.setdefault("owned_bytes", 0)
    overrides.setdefault("evidence_json", "{}")
    return save(session, StorageInventorySample(**overrides))
