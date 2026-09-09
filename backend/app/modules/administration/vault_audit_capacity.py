"""Audit-specific peak estimates using the shared capacity reservation contract."""

from __future__ import annotations

import tempfile
from pathlib import Path

from sqlmodel import Session, col, select

from app.core.config import settings
from app.db.models import File, OwnedStorageObject, VaultAuditMode, VaultAuditRun
from app.modules.storage.capacity import CapacityResource


def estimate_resources(session: Session, run: VaultAuditRun) -> list[CapacityResource]:
    # The sequential executor materializes at most one source/backup at once.
    largest_file = (
        session.exec(
            select(col(File.size_bytes)).order_by(col(File.size_bytes).desc()).limit(1)
        ).first()
        or 0
    )
    resources = [
        CapacityResource.for_path(
            Path(tempfile.gettempdir()), largest_file, role="audit-source"
        )
    ]
    if run.mode == VaultAuditMode.FULL:
        largest_backup = (
            session.exec(
                select(col(OwnedStorageObject.size_bytes))
                .where(
                    col(OwnedStorageObject.object_kind).in_(("backup", "backup-legacy"))
                )
                .order_by(col(OwnedStorageObject.size_bytes).desc())
                .limit(1)
            ).first()
            or 0
        )
        resources.append(
            CapacityResource.for_path(
                settings.backup_dir, largest_backup * 2, role="audit-backup"
            )
        )
    return resources
