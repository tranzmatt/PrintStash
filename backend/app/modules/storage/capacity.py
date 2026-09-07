"""Serialized durable reservations for peak operation allocations.

Reservations are budget claims, never ownership receipts. Expiry does not free
budget until the workflow owner proves that an operation has stopped writing.
A caller must renew before increasing its peak allocation and release after its
last allocation. Actual free space is re-probed under the admission lock.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
from typing import Callable, Iterator, Sequence

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from app.core.config import settings
from app.core.errors import ErrorKind, OperationError
from app.core.time import ensure_utc, utcnow
from app.db.models import CapacityLock, CapacityReservation
from app.db.session import SessionFactory


@dataclass(frozen=True)
class CapacityResource:
    domain_id: str
    required_bytes: int
    available_bytes: int | None
    role: str
    path: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.domain_id
            or self.required_bytes < 0
            or (self.available_bytes is not None and self.available_bytes < 0)
        ):
            raise ValueError("invalid capacity resource")

    @classmethod
    def for_path(
        cls, path: Path, required_bytes: int, *, role: str
    ) -> CapacityResource:
        candidate = path.expanduser().resolve(strict=False)
        while not candidate.exists() and candidate != candidate.parent:
            candidate = candidate.parent
        try:
            info = candidate.stat()
        except OSError as exc:
            raise OperationError(
                "storage_capacity_unavailable", kind=ErrorKind.CAPACITY
            ) from exc
        return cls(
            f"volume:{info.st_dev}",
            required_bytes,
            None,
            role,
            str(path.expanduser().absolute()),
        )

    @classmethod
    def for_quota(
        cls,
        domain_id: str,
        required_bytes: int,
        available_bytes: int | None,
        *,
        role: str,
    ) -> CapacityResource:
        return cls(f"quota:{domain_id}", required_bytes, available_bytes, role)

    def probe(self) -> int | None:
        if self.path is None:
            return self.available_bytes
        import os

        candidate = Path(self.path).resolve(strict=False)
        while not candidate.exists() and candidate != candidate.parent:
            candidate = candidate.parent
        try:
            if f"volume:{candidate.stat().st_dev}" != self.domain_id:
                raise OperationError(
                    "storage_capacity_volume_changed", kind=ErrorKind.CAPACITY
                )
            stats = os.statvfs(candidate)
            return stats.f_bavail * stats.f_frsize
        except OSError as exc:
            raise OperationError(
                "storage_capacity_unavailable", kind=ErrorKind.CAPACITY
            ) from exc


def _decode(payload: str) -> list[CapacityResource]:
    return [CapacityResource(**item) for item in json.loads(payload)]


@dataclass
class CapacityReservationHandle:
    manager: CapacityManager
    operation_id: str
    resources: Sequence[CapacityResource]
    warnings: tuple[str, ...]

    def renew(
        self,
        resources: Sequence[CapacityResource] | None = None,
        *,
        ttl_seconds: int = 900,
    ) -> None:
        replacement = self.resources if resources is None else resources
        renewed = self.manager._reserve(
            self.operation_id, replacement, ttl_seconds=ttl_seconds, renew=True
        )
        self.resources, self.warnings = renewed.resources, renewed.warnings

    def release(self) -> None:
        self.manager.release(self.operation_id)


class CapacityManager:
    def __init__(
        self, session_factory: SessionFactory, *, headroom_bytes: int | None = None
    ) -> None:
        self.session_factory = session_factory
        self.headroom_bytes = (
            settings.storage_min_free_bytes
            if headroom_bytes is None
            else headroom_bytes
        )
        if self.headroom_bytes < 0:
            raise ValueError("negative headroom")

    @staticmethod
    def _lock(session: Session) -> None:
        # INSERT conflict handling also serializes the first concurrent callers;
        # UPDATE keeps the lock through commit on SQLite and PostgreSQL alike.
        table = CapacityLock.__table__
        insert = (
            sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
        )
        session.execute(
            insert(table)
            .values(id=1, revision=0)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        session.execute(
            update(CapacityLock)
            .where(CapacityLock.id == 1)
            .values(revision=CapacityLock.revision + 1)
        )

    def reserve(
        self,
        operation_id: str,
        resources: Sequence[CapacityResource],
        *,
        ttl_seconds: int = 900,
    ) -> CapacityReservationHandle:
        return self._reserve(
            operation_id, resources, ttl_seconds=ttl_seconds, renew=False
        )

    def _reserve(
        self,
        operation_id: str,
        resources: Sequence[CapacityResource],
        *,
        ttl_seconds: int,
        renew: bool,
    ) -> CapacityReservationHandle:
        if (
            not operation_id
            or len(operation_id) > 200
            or ttl_seconds <= 0
            or not resources
        ):
            raise ValueError("invalid capacity reservation")
        payload = json.dumps([asdict(item) for item in resources], sort_keys=True)
        with self.session_factory.scoped_session() as session:
            self._lock(session)
            existing = session.get(CapacityReservation, operation_id)
            if renew and existing is None:
                raise OperationError(
                    "capacity_reservation_lost", kind=ErrorKind.CONFLICT
                )
            if (
                existing is not None
                and not renew
                and existing.resources_json != payload
            ):
                raise OperationError(
                    "capacity_operation_conflict", kind=ErrorKind.CONFLICT
                )
            totals: dict[str, int] = {}
            for row in session.exec(
                select(CapacityReservation).where(
                    CapacityReservation.operation_id != operation_id
                )
            ):
                for item in _decode(row.resources_json):
                    totals[item.domain_id] = (
                        totals.get(item.domain_id, 0) + item.required_bytes
                    )
            free: dict[str, int | None] = {}
            for item in resources:
                totals[item.domain_id] = (
                    totals.get(item.domain_id, 0) + item.required_bytes
                )
                measured = item.probe()
                previous = free.get(item.domain_id)
                free[item.domain_id] = (
                    measured
                    if previous is None
                    else previous
                    if measured is None
                    else min(previous, measured)
                )
            warnings = []
            for domain, available in free.items():
                if available is None:
                    warnings.append(f"capacity_unknown:{domain}")
                elif totals[domain] + self.headroom_bytes > available:
                    raise OperationError(
                        "storage_capacity_exceeded", kind=ErrorKind.CAPACITY
                    )
            row = existing or CapacityReservation(
                operation_id=operation_id, resources_json=payload, expires_at=utcnow()
            )
            row.resources_json = payload
            row.expires_at = utcnow() + timedelta(seconds=ttl_seconds)
            session.add(row)
            session.commit()
        return CapacityReservationHandle(
            self, operation_id, tuple(resources), tuple(warnings)
        )

    @contextmanager
    def hold(
        self,
        operation_id: str,
        resources: Sequence[CapacityResource],
        *,
        ttl_seconds: int = 900,
    ) -> Iterator[CapacityReservationHandle]:
        handle = self.reserve(operation_id, resources, ttl_seconds=ttl_seconds)
        try:
            yield handle
        finally:
            handle.release()

    def release(self, operation_id: str) -> None:
        with self.session_factory.scoped_session() as session:
            self._lock(session)
            row = session.get(CapacityReservation, operation_id)
            if row is not None:
                session.delete(row)
            session.commit()

    def reserved_bytes(self) -> dict[str, int]:
        with self.session_factory.scoped_session() as session:
            totals: dict[str, int] = {}
            for row in session.exec(select(CapacityReservation)):
                for item in _decode(row.resources_json):
                    totals[item.domain_id] = (
                        totals.get(item.domain_id, 0) + item.required_bytes
                    )
            return totals

    def reconcile(self, is_operation_active: Callable[[str], bool]) -> int:
        """Release only expired claims whose owner proves no further writes."""
        released = 0
        with self.session_factory.scoped_session() as session:
            self._lock(session)
            for row in session.exec(select(CapacityReservation)):
                if ensure_utc(row.expires_at) <= utcnow() and not is_operation_active(
                    row.operation_id
                ):
                    session.delete(row)
                    released += 1
            session.commit()
        return released
