"""Verified archive download staging and receipt checks."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from sqlmodel import select

import app.modules.backups.backup.archive_format as _archive_format_module
import app.modules.backups.backup.caches as _caches_module
import app.modules.backups.backup.contracts as _contracts_module
import app.modules.backups.backup.targets as _targets_module
import app.modules.backups.backup_destination as _backup_destination_module
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import (
    OwnedStorageObject,
    StorageObjectState,
)
from app.db.session import get_session_factory
from app.modules.storage.storage_backend.contracts import CreationReceipt
from app.modules.storage.storage_backend.local import LocalStorageBackend
from app.modules.storage.storage_ownership import (
    provider_ref_for_backend,
    publish_file,
    record_creation,
)

logger = get_logger(__name__)


def _require_backup_archive_owned(
    meta: _contracts_module.BackupMeta,
    *,
    target: _targets_module._BackupS3Target | None = None,
) -> OwnedStorageObject:
    """Require current proof for the archive selected by restore/delete."""
    with get_session_factory().session() as session:
        if meta.location == "local":
            backend = LocalStorageBackend()
            rows = session.exec(
                select(OwnedStorageObject).where(
                    OwnedStorageObject.backend == "local",
                    OwnedStorageObject.namespace == backend.namespace_for(meta.path),
                    OwnedStorageObject.key == meta.path,
                    OwnedStorageObject.provider_ref
                    == provider_ref_for_backend(
                        backend, namespace=backend.namespace_for(meta.path)
                    ),
                    OwnedStorageObject.object_kind.in_(  # type: ignore[union-attr]
                        ("backup", "backup-legacy")
                    ),
                    OwnedStorageObject.state == StorageObjectState.COMMITTED,
                )
            ).all()
            for row in rows:
                if row.token is None or row.size_bytes is None:
                    continue
                receipt = CreationReceipt(
                    key=row.key,
                    size=row.size_bytes,
                    token=row.token,
                    backend=row.backend,
                    namespace=row.namespace,
                    etag=row.etag,
                    version_id=row.version_id,
                    device=row.device,
                    inode=row.inode,
                    ctime_ns=row.ctime_ns,
                    provider_ref=row.provider_ref,
                )
                try:
                    if backend.creation_matches(receipt):
                        return row
                    if row.sha256 is None or row.device is None or row.inode is None:
                        continue
                    refreshed = backend.adopt_existing(
                        row.key,
                        expected_size=row.size_bytes,
                        expected_sha256=row.sha256,
                    )
                except Exception:
                    continue
                # A root-level metadata repair can change ctime, but it cannot
                # replace the directory entry. Require the original inode in
                # addition to exact bytes before refreshing the receipt.
                if (refreshed.device, refreshed.inode) != (row.device, row.inode):
                    continue
                owned = record_creation(
                    session,
                    refreshed,
                    object_kind=row.object_kind,
                    sha256=row.sha256,
                    provider_ref=row.provider_ref,
                )
                session.commit()
                session.refresh(owned)
                return owned
            raise _contracts_module.BackupOwnershipError(
                "backup_storage_ownership_unverified"
            )

        if meta.location.startswith("opendal:"):
            candidates = session.exec(
                select(OwnedStorageObject).where(
                    OwnedStorageObject.namespace == meta.namespace,
                    OwnedStorageObject.key == meta.path,
                    OwnedStorageObject.provider_ref == meta.provider_ref,
                    OwnedStorageObject.object_kind.in_(  # type: ignore[union-attr]
                        ("backup", "backup-legacy")
                    ),
                    OwnedStorageObject.state == StorageObjectState.COMMITTED,
                )
            ).all()
            for candidate in candidates:
                destination = _backup_destination_module.destination_for_ownership(
                    candidate
                )
                if destination is None:
                    continue
                try:
                    destination.require_owned(candidate)
                except _backup_destination_module.BackupDestinationError:
                    continue
                return candidate
            raise _contracts_module.BackupOwnershipError(
                "backup_storage_ownership_unverified"
            )

        target = target or _targets_module._get_backup_s3_target()
        if target is None:
            raise _contracts_module.BackupOwnershipError(
                "backup_storage_ownership_unverified"
            )
        if not target.bucket and meta.namespace:
            target = replace(target, bucket=meta.namespace.split("/", 1)[0])
        bucket = target.bucket
        prefix = _targets_module._s3_prefix_for_key(meta.path)
        if prefix is None:
            raise _contracts_module.BackupOwnershipError(
                "backup_storage_ownership_unverified"
            )
        expected_namespace = f"{bucket}/{prefix}"
        if meta.namespace is not None and meta.namespace != expected_namespace:
            raise _contracts_module.BackupOwnershipError(
                "backup_storage_target_changed"
            )
        candidates = session.exec(
            select(OwnedStorageObject).where(
                OwnedStorageObject.backend == "backup-s3",
                OwnedStorageObject.namespace == expected_namespace,
                OwnedStorageObject.key == meta.path,
                OwnedStorageObject.object_kind.in_(("backup", "backup-legacy")),
                OwnedStorageObject.state == StorageObjectState.COMMITTED,
            )
        ).all()
        for candidate in candidates:
            if candidate.provider_ref != target.provider_ref:
                continue
            if not candidate.version_id and not candidate.etag:
                continue
            try:
                response = _targets_module._s3_head_owned(target, candidate)
            except Exception:
                continue
            if (
                int(response.get("ContentLength", -1)) == candidate.size_bytes
                and (
                    not candidate.etag
                    or str(response.get("ETag", "")) == candidate.etag
                )
                and (
                    not candidate.version_id
                    or str(response.get("VersionId", "")) == candidate.version_id
                )
                and (
                    candidate.object_kind == "backup-legacy"
                    or response.get("Metadata", {}).get("printstash-create-token")
                    == candidate.token
                )
            ):
                return candidate
    raise _contracts_module.BackupOwnershipError("backup_storage_ownership_unverified")


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------


def _download_backup_to_local(
    meta: _contracts_module.BackupMeta,
    *,
    progress: Callable[[int], None] | None = None,
    fresh_remote: bool = False,
) -> Path:
    """Ensure a local copy of the backup exists, downloading from S3 if needed."""
    local_path = Path(meta.path) if meta.location == "local" else None

    if local_path and local_path.exists():
        return local_path

    if meta.location.startswith("opendal:"):
        owned = _require_backup_archive_owned(meta)
        destination = _backup_destination_module.destination_for_ownership(owned)
        if destination is None:
            raise _contracts_module.BackupOwnershipError(
                "backup_storage_ownership_unverified"
            )
        archive_name = meta.path.rsplit("/", 1)[-1]
        source_ref = meta.source_ref or _targets_module.source_reference(
            location=meta.location,
            namespace=meta.namespace,
            path=meta.path,
            provider_ref=owned.provider_ref,
        )
        remote_identity = owned.version_id or owned.etag or owned.sha256
        if not remote_identity:
            raise _contracts_module.BackupOwnershipError(
                "backup_remote_identity_unavailable"
            )
        cache_identity = hashlib.sha256(
            f"{source_ref}\x1f{remote_identity}".encode("utf-8")
        ).hexdigest()
        cache_dir = settings.backup_dir / ".cloud-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        local_path = cache_dir / f"{cache_identity}-{archive_name}"
        if fresh_remote and local_path.exists():
            _caches_module.cleanup_backup_cache(local_path)
        if local_path.exists():
            if (
                not owned.sha256
                or _archive_format_module._sha256_path(local_path) != owned.sha256
            ):
                raise _contracts_module.BackupOwnershipError(
                    "backup_local_destination_conflict"
                )
            cache_ownership = _caches_module._cache_ownership_for_path(local_path)
            if cache_ownership is None or cache_ownership.sha256 != owned.sha256:
                raise _contracts_module.BackupOwnershipError(
                    "backup_cache_ownership_unverified"
                )
            return local_path

        fd, raw_temp = tempfile.mkstemp(
            prefix=".printstash-backup-download-", dir=settings.backup_dir
        )
        os.close(fd)
        download_temp = Path(raw_temp)
        download_temp.unlink()
        try:
            if progress is None:
                destination.download_owned(owned, download_temp)
            else:
                destination.download_owned(owned, download_temp, progress=progress)
            with get_session_factory().session() as publish_session:
                publish_file(
                    publish_session,
                    LocalStorageBackend(),
                    str(local_path),
                    download_temp,
                    object_kind="backup-cloud-cache",
                    sha256=owned.sha256,
                    move=True,
                )
                publish_session.commit()
        except Exception:
            download_temp.unlink(missing_ok=True)
            raise
        return local_path

    if meta.location == "s3":
        # Download from S3 to a temp location
        target = _targets_module._get_backup_s3_target()
        if target is None:
            raise RuntimeError("backup is in S3 but no S3 client is available")
        owned = _require_backup_archive_owned(meta, target=target)
        if not target.bucket:
            target = replace(target, bucket=owned.namespace.split("/", 1)[0])
        archive_name = meta.path.rsplit("/", 1)[-1]
        source_ref = meta.source_ref or _targets_module.source_reference(
            location="s3",
            namespace=meta.namespace,
            path=meta.path,
            provider_ref=owned.provider_ref,
        )
        # A cloud source is not allowed to overwrite a same-named local or
        # another-source cache.  Keep the cache locator source-specific.
        cache_dir = settings.backup_dir / ".cloud-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Bind the rebuildable cache name to the exact remote content proof.
        # A provider may replace an unversioned object at the same key; a
        # source-only cache name would then turn that replacement into a
        # confusing local collision.
        remote_identity = owned.version_id or owned.etag or owned.sha256
        if not remote_identity:
            raise _contracts_module.BackupOwnershipError(
                "backup_remote_identity_unavailable"
            )
        cache_identity = hashlib.sha256(
            f"{source_ref}\x1f{remote_identity}".encode("utf-8")
        ).hexdigest()
        local_path = cache_dir / f"{cache_identity}-{archive_name}"
        settings.backup_dir.mkdir(parents=True, exist_ok=True)
        if fresh_remote and local_path.exists():
            _caches_module.cleanup_backup_cache(local_path)
        if local_path.exists():
            try:
                existing_hash = _archive_format_module._sha256_path(local_path)
            except OSError:
                existing_hash = None
            if not owned.sha256 or existing_hash != owned.sha256:
                raise _contracts_module.BackupOwnershipError(
                    "backup_local_destination_conflict"
                )
            cache_ownership = _caches_module._cache_ownership_for_path(local_path)
            if cache_ownership is None:
                # Never adopt a matching unowned file at a deterministic cache
                # locator: an operator or another process could have placed it
                # there.  A fresh download below reserves ownership first.
                raise _contracts_module.BackupOwnershipError(
                    "backup_cache_ownership_unverified"
                )
            LocalStorageBackend().adopt_existing(
                str(local_path),
                expected_size=owned.size_bytes or local_path.stat().st_size,
                expected_sha256=owned.sha256,
            )
            if cache_ownership.sha256 != owned.sha256:
                raise _contracts_module.BackupOwnershipError(
                    "backup_cache_identity_mismatch"
                )
            return local_path

        fd, raw_temp = tempfile.mkstemp(
            prefix=".printstash-backup-download-", dir=settings.backup_dir
        )
        os.close(fd)
        download_temp = Path(raw_temp)
        try:
            response = _targets_module._s3_get_owned(target, owned)
            body = response["Body"]
            try:
                with download_temp.open("wb") as destination:
                    while True:
                        if progress is not None:
                            progress(0)
                        chunk = body.read(1024 * 1024)
                        if not chunk:
                            break
                        if progress is not None:
                            progress(len(chunk))
                        destination.write(chunk)
            finally:
                body.close()
            _targets_module._assert_s3_identity(
                response,
                size_bytes=owned.size_bytes,
                etag=owned.etag,
                version_id=owned.version_id,
            )
            if download_temp.stat().st_size != owned.size_bytes:
                raise RuntimeError("backup_download_size_mismatch")
            if (
                owned.sha256
                and _archive_format_module._sha256_path(download_temp) != owned.sha256
            ):
                raise RuntimeError("backup_download_digest_mismatch")
            # Re-HEAD through the same immutable version/ETag proof after the
            # body is consumed.  An unversioned object may have been replaced
            # between the initial check and GET; never publish that body.
            confirmed = _targets_module._s3_head_owned(target, owned)
            _targets_module._assert_s3_identity(
                confirmed,
                size_bytes=owned.size_bytes,
                etag=owned.etag,
                version_id=owned.version_id,
            )
            with get_session_factory().session() as publish_session:
                publish_file(
                    publish_session,
                    LocalStorageBackend(),
                    str(local_path),
                    download_temp,
                    object_kind="backup-cloud-cache",
                    move=True,
                )
                publish_session.commit()
        except Exception:
            download_temp.unlink(missing_ok=True)
            raise
        logger.info("backup %s downloaded from S3 to %s", meta.id, local_path)
        return local_path

    raise FileNotFoundError(f"backup {meta.id} not found locally or in S3")
