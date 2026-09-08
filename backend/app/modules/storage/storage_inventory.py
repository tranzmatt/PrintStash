"""Database-derived inventory; interactive reads never enumerate providers.

Logical bytes count references. Unique bytes count provider/namespace/key
identities with known size; unknown objects remain explicitly unmeasured.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

from pydantic import BaseModel, Field
from sqlalchemy import case, func
from sqlalchemy import select as sa_select
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.time import ensure_utc, utcnow
from app.db.models import (
    SENTINEL_FILE_HASH,
    Collection,
    File,
    Model,
    OwnedStorageObject,
    StagingLease,
    StorageInventorySample,
    User,
)
from app.db.scopes import live
from app.modules.library.model_views.access import accessible_live_model_ids_stmt
from app.modules.storage.capacity_policy import CapacityPolicy
from app.modules.storage.storage_backend.contracts import StorageCollisionError
from app.modules.storage.storage_backend.runtime import get_backend
from app.modules.storage.storage_ownership import provider_ref_for_backend
from app.modules.storage.storage_utils import ownership_snapshot


class InventoryBucket(BaseModel):
    category: str
    lifecycle: str
    count: int
    logical_bytes: int
    external_bytes: int = 0


class VolumeEvidence(BaseModel):
    domain_id: str
    roles: list[str]
    total_bytes: int | None = None
    free_bytes: int | None = None
    reserved_bytes: int = 0
    headroom_bytes: int = 0
    status: str = "unknown"
    method: str = "statvfs"


class StorageInventory(BaseModel):
    generated_at: datetime
    target_ref: str
    buckets: list[InventoryBucket]
    logical_bytes: int
    external_referenced_bytes: int
    unique_owned_bytes: int
    unknown_object_count: int
    temporary_bytes: int
    backup_bytes: int
    measured_provider_bytes: int | None = None
    measured_at: datetime | None = None
    method: str = "database ownership census"
    confidence: str = "known sizes only"
    volumes: list[VolumeEvidence] = Field(default_factory=list)


def _volumes(reserved: dict[str, int]) -> list[VolumeEvidence]:
    groups: dict[str, VolumeEvidence] = {}
    backend = get_backend()
    roots = [("staging", settings.staging_dir), ("backups", settings.backup_dir)]
    if backend.direct_path(backend.thumbnail_key(0)) is not None:
        roots.extend(
            [("vault", settings.data_dir), ("derivatives", settings.thumb_dir)]
        )
    else:
        groups["remote"] = VolumeEvidence(
            domain_id="remote", roles=["vault"], method="provider quota unavailable"
        )
    for role, root in roots:
        candidate = Path(root).resolve(strict=False)
        while not candidate.exists() and candidate != candidate.parent:
            candidate = candidate.parent
        try:
            info = candidate.stat()
            stats = os.statvfs(candidate)
            domain = f"volume:{info.st_dev}"
            if domain in groups:
                groups[domain].roles.append(role)
                continue
            remaining = stats.f_bavail * stats.f_frsize
            headroom = CapacityPolicy(
                settings.storage_min_free_bytes, settings.storage_min_free_percent
            ).headroom(stats.f_blocks * stats.f_frsize)
            claimed = reserved.get(domain, 0)
            groups[domain] = VolumeEvidence(
                domain_id=domain,
                roles=[role],
                total_bytes=stats.f_blocks * stats.f_frsize,
                free_bytes=remaining,
                reserved_bytes=claimed,
                headroom_bytes=headroom,
                status="blocked" if remaining - claimed < headroom else "available",
            )
        except OSError:
            groups[role] = VolumeEvidence(
                domain_id=role, roles=[role], status="unavailable"
            )
    return list(groups.values())


def inventory(
    session: Session, *, reserved: dict[str, int] | None = None
) -> StorageInventory:
    backend = get_backend()
    target = backend.storage_target
    target_ref = (
        target.target_ref if target else provider_ref_for_backend(backend) or "unknown"
    )
    lifecycle = case((live(File) & live(Model), "live"), else_="trash")
    aggregates = session.execute(
        sa_select(
            col(File.file_type),
            lifecycle,
            col(File.is_external),
            func.count(col(File.id)),
            func.coalesce(func.sum(col(File.size_bytes)), 0),
        )
        .join(Model, col(Model.id) == col(File.model_id))
        .where(col(File.sha256) != SENTINEL_FILE_HASH)
        .group_by(col(File.file_type), lifecycle, col(File.is_external))
    ).all()
    buckets = [
        InventoryBucket(
            category=kind.value,
            lifecycle=state,
            count=count,
            logical_bytes=size,
            external_bytes=size if external else 0,
        )
        for kind, state, external, count, size in aggregates
    ]
    snapshot = ownership_snapshot(session, discover=False)
    objects: dict[tuple[str, str, str], int | None] = {}
    current_provider = provider_ref_for_backend(backend)
    receipts = list(session.exec(select(OwnedStorageObject)))
    receipt_sizes = {
        (row.provider_ref or "legacy", row.namespace, row.key): row.size_bytes
        for row in receipts
    }
    for blob in snapshot.primary + snapshot.derived + snapshot.embedded:
        try:
            namespace = backend.namespace_for(blob.key)
        except StorageCollisionError:
            # A legacy invalid locator is evidence of an unknown object, not
            # authority to stat or claim bytes outside the managed roots.
            objects[(current_provider, "unresolved", blob.key)] = None
            continue
        identity = (
            provider_ref_for_backend(backend, namespace=namespace),
            namespace,
            blob.key,
        )
        known_size = blob.expected_size
        if known_size is None:
            known_size = receipt_sizes.get(identity)
        if identity not in objects or objects[identity] is None:
            objects[identity] = known_size
        if blob.resource_type != "file":
            buckets.append(
                InventoryBucket(
                    category=blob.resource_type,
                    lifecycle="owned",
                    count=1,
                    logical_bytes=known_size or 0,
                )
            )
    backup_bytes = 0
    backup_count = 0
    for row in receipts:
        identity = (row.provider_ref or "legacy", row.namespace, row.key)
        if row.size_bytes is not None:
            objects[identity] = row.size_bytes
        else:
            objects.setdefault(identity, None)
        if row.object_kind.startswith("backup"):
            backup_bytes += row.size_bytes or 0
            backup_count += 1
    temporary = int(
        session.exec(
            select(func.coalesce(func.sum(col(StagingLease.size_bytes)), 0))
        ).one()
    )
    buckets.extend(
        [
            InventoryBucket(
                category="staging",
                lifecycle="temporary",
                count=int(session.exec(select(func.count(col(StagingLease.id)))).one()),
                logical_bytes=temporary,
            ),
            InventoryBucket(
                category="backups",
                lifecycle="replica",
                count=backup_count,
                logical_bytes=backup_bytes,
            ),
        ]
    )
    # Keep the interactive payload bounded by categories, not library size.
    grouped: dict[tuple[str, str], InventoryBucket] = {}
    for bucket in buckets:
        key = (bucket.category, bucket.lifecycle)
        if key not in grouped:
            grouped[key] = bucket.model_copy()
        else:
            grouped[key].count += bucket.count
            grouped[key].logical_bytes += bucket.logical_bytes
            grouped[key].external_bytes += bucket.external_bytes
    buckets = list(grouped.values())
    latest = session.exec(
        select(StorageInventorySample)
        .where(col(StorageInventorySample.target_ref) == target_ref)
        .order_by(col(StorageInventorySample.sampled_at).desc())
        .limit(1)
    ).first()
    return StorageInventory(
        generated_at=utcnow(),
        target_ref=target_ref,
        buckets=buckets,
        logical_bytes=sum(
            bucket.logical_bytes
            for bucket in buckets
            if bucket.lifecycle not in {"temporary", "replica"}
        ),
        external_referenced_bytes=sum(bucket.external_bytes for bucket in buckets),
        unique_owned_bytes=sum(size for size in objects.values() if size is not None),
        unknown_object_count=sum(size is None for size in objects.values()),
        temporary_bytes=temporary,
        backup_bytes=backup_bytes,
        measured_at=ensure_utc(latest.sampled_at) if latest else None,
        volumes=_volumes(reserved or {}),
    )


def record_sample(session: Session, current: StorageInventory) -> None:
    """Keep one sample per UTC day per target and at most 366 daily samples."""
    day = current.generated_at.date()
    rows = list(
        session.exec(
            select(StorageInventorySample)
            .where(col(StorageInventorySample.target_ref) == current.target_ref)
            .order_by(col(StorageInventorySample.sampled_at).desc())
        )
    )
    existing = next((row for row in rows if row.sampled_at.date() == day), None)
    sample = existing or StorageInventorySample(
        target_ref=current.target_ref,
        owned_bytes=current.unique_owned_bytes,
        evidence_json="{}",
    )
    sample.sampled_at = current.generated_at
    sample.owned_bytes = current.unique_owned_bytes
    sample.evidence_json = current.model_dump_json()
    session.add(sample)
    cutoff = current.generated_at - timedelta(days=366)
    for index, row in enumerate(rows):
        if row is not existing and (
            ensure_utc(row.sampled_at) < cutoff or index >= 365
        ):
            session.delete(row)
    session.commit()


def growth_forecast(
    samples: list[tuple[datetime, int]], available_bytes: int | None
) -> dict:
    ordered = sorted(samples)
    daily = {
        ensure_utc(when).date(): (ensure_utc(when), size) for when, size in ordered
    }
    ordered = sorted(daily.values())
    if len(ordered) < 7 or (ordered[-1][0] - ordered[0][0]).total_seconds() < 7 * 86400:
        return {
            "status": "insufficient_data",
            "days_remaining": None,
            "bytes_per_day": None,
        }
    rates = [
        (right[1] - left[1]) / ((right[0] - left[0]).total_seconds() / 86400)
        for left, right in zip(ordered, ordered[1:], strict=False)
    ]
    rate = median(rates)
    if rate <= 0:
        return {
            "status": "no_positive_growth",
            "days_remaining": None,
            "bytes_per_day": rate,
        }
    if max(rates) > rate * 10 or min(rates) < -rate * 10:
        return {
            "status": "unstable_growth",
            "days_remaining": None,
            "bytes_per_day": rate,
        }
    return {
        "status": "estimated" if available_bytes is not None else "capacity_unknown",
        "days_remaining": max(0, available_bytes / rate)
        if available_bytes is not None
        else None,
        "bytes_per_day": rate,
    }


def history(session: Session, target_ref: str) -> list[dict]:
    return [
        {
            "sampled_at": ensure_utc(row.sampled_at).isoformat(),
            "owned_bytes": row.owned_bytes,
        }
        for row in session.exec(
            select(StorageInventorySample)
            .where(col(StorageInventorySample.target_ref) == target_ref)
            .order_by(col(StorageInventorySample.sampled_at).desc())
            .limit(366)
        )
    ]


def logical_drilldown(
    session: Session,
    user: User,
    *,
    offset: int = 0,
    limit: int = 50,
    collection_id: int | None = None,
) -> list[dict]:
    visible = accessible_live_model_ids_stmt(session, user)
    if collection_id is not None:
        visible = visible.where(
            col(Model.collection_id).is_(None)
            if collection_id == 0
            else col(Model.collection_id) == collection_id
        )
    rows = session.exec(
        select(
            col(Model.id),
            col(Model.name),
            func.coalesce(func.sum(col(File.size_bytes)), 0),
        )
        .join(File, col(File.model_id) == col(Model.id))
        .where(col(Model.id).in_(visible), live(File))
        .group_by(col(Model.id), col(Model.name))
        .order_by(func.sum(col(File.size_bytes)).desc(), col(Model.id))
        .offset(offset)
        .limit(limit)
    ).all()
    return [
        {"model_id": identity, "name": name, "logical_bytes": size}
        for identity, name, size in rows
    ]


def cleanup_expired_staging(session: Session, actor: User) -> dict:
    """Explicit cleanup delegates receipt validation to the existing owner."""
    from app.modules.administration import audit
    from app.modules.ingestion.staging_cleanup import prune_expired

    removed, unlinked = prune_expired(session, backend=get_backend())
    session.commit()
    audit.record(
        session,
        action="storage.cleanup_expired_staging",
        resource_type="storage",
        actor_id=actor.id,
        diff={"leases_removed": removed, "files_removed": unlinked},
    )
    current = inventory(session)
    record_sample(session, current)
    return {"leases_removed": removed, "files_removed": unlinked, "inventory": current}


def legacy_usage(session: Session) -> dict:
    """Legacy dashboard wire shape, sourced from recorded owned object sizes."""
    count, size = session.exec(
        select(
            func.count(col(OwnedStorageObject.id)),
            func.coalesce(func.sum(col(OwnedStorageObject.size_bytes)), 0),
        )
    ).one()
    return {
        "backend": settings.storage_backend,
        "object_count": count,
        "total_size_bytes": size,
        "ok": True,
    }


def refresh_inventory_sample(session_factory) -> None:
    """Hourly maintenance records one daily sample and reconciles dead owners."""
    from app.modules.storage.capacity import CapacityManager

    manager = CapacityManager(session_factory)
    manager.reconcile_stopped_processes()
    with session_factory.scoped_session() as session:
        record_sample(session, inventory(session, reserved=manager.reserved_bytes()))


class InventoryReport(BaseModel):
    inventory: StorageInventory
    history: list[dict]
    forecast: dict


def inventory_report(session: Session, manager) -> InventoryReport:
    current = inventory(session, reserved=manager.reserved_bytes())
    samples = history(session, current.target_ref)
    available = next(
        (
            max(0, volume.free_bytes - volume.reserved_bytes - volume.headroom_bytes)
            for volume in current.volumes
            if "vault" in volume.roles and volume.free_bytes is not None
        ),
        None,
    )
    return InventoryReport(
        inventory=current,
        history=samples,
        forecast=growth_forecast(
            [
                (datetime.fromisoformat(row["sampled_at"]), row["owned_bytes"])
                for row in samples
            ],
            available,
        ),
    )


def collection_drilldown(
    session: Session, user: User, *, offset: int = 0, limit: int = 50
) -> list[dict]:
    """Attribute logical references only within the caller's live Model scope."""
    visible = accessible_live_model_ids_stmt(session, user)
    rows = session.exec(
        select(
            col(Model.collection_id),
            col(Collection.name),
            func.coalesce(func.sum(col(File.size_bytes)), 0),
            func.coalesce(
                func.sum(case((col(File.is_external), col(File.size_bytes)), else_=0)),
                0,
            ),
            func.count(func.distinct(col(Model.id))),
        )
        .join(File, col(File.model_id) == col(Model.id))
        .outerjoin(Collection, col(Collection.id) == col(Model.collection_id))
        .where(
            col(Model.id).in_(visible),
            live(File),
            col(File.sha256) != SENTINEL_FILE_HASH,
        )
        .group_by(col(Model.collection_id), col(Collection.name))
        .order_by(func.sum(col(File.size_bytes)).desc(), col(Model.collection_id))
        .offset(offset)
        .limit(limit)
    ).all()
    return [
        {
            "collection_id": identity,
            "name": name or "Uncollected",
            "logical_bytes": size,
            "external_bytes": external,
            "model_count": count,
        }
        for identity, name, size, external, count in rows
    ]
