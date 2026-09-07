"""Credential-free backup catalogue projections."""

from app.modules.backups.backup import targets as backup_targets
from app.modules.backups.backup.contracts import BackupMeta
from app.modules.backups.backup_capabilities import backup_operations


def source_view(m: BackupMeta) -> dict:
    return {
        "backup_id": m.id,
        "created_at": m.created_at,
        "size_bytes": m.size_bytes,
        "file_count": m.file_count,
        "storage_backend": m.storage_backend,
        "app_version": m.app_version,
        "location": m.location,
        "archive_sha256": m.archive_sha256,
        "source_ref": m.source_ref,
        "provider_ref": m.provider_ref,
        "namespace": m.namespace,
        "key": m.path,
        "prefix": backup_targets._s3_prefix_for_key(m.path),
        "canonical": m.canonical,
        "precedence": m.precedence,
        "operations": backup_operations(m),
    }
