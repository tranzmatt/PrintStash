"""Catalogue discovery and projections for owned backup archives."""

from __future__ import annotations

from pathlib import Path

from sqlmodel import select

import app.modules.backups.backup.archive_format as _archive_format_module
import app.modules.backups.backup.contracts as _contracts_module
import app.modules.backups.backup.downloads as _downloads_module
import app.modules.backups.backup.publications as _publications_module
import app.modules.backups.backup.targets as _targets_module
import app.modules.backups.backup_catalogue as _backup_catalogue_module
import app.modules.backups.backup_destination as _backup_destination_module
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import (
    OwnedStorageObject,
    StorageObjectState,
)
from app.db.session import get_session_factory
from app.modules.storage.storage_backend.local import LocalStorageBackend
from app.modules.storage.storage_ownership import provider_ref_for_backend

logger = get_logger(__name__)


def _committed_backup_keys(
    backend: str,
    namespace: str | None = None,
    provider_ref: str | None = None,
) -> set[str]:
    """Return only archives whose publication reached COMMITTED in the ledger."""
    with get_session_factory().session() as session:
        statement = select(OwnedStorageObject.key).where(
            OwnedStorageObject.backend == backend,
            OwnedStorageObject.object_kind.in_(("backup", "backup-legacy")),
            OwnedStorageObject.state == StorageObjectState.COMMITTED,
        )
        if namespace is not None:
            statement = statement.where(OwnedStorageObject.namespace == namespace)
        if provider_ref is not None:
            statement = statement.where(OwnedStorageObject.provider_ref == provider_ref)
        return {str(key) for key in session.exec(statement).all()}


def _backup_ownership_rows(
    *, key: str | None = None, bucket: str | None = None
) -> list[OwnedStorageObject]:
    """Load committed/incomplete S3 backup evidence for exact locators."""
    with get_session_factory().session() as session:
        statement = select(OwnedStorageObject).where(
            OwnedStorageObject.backend == "backup-s3",
            OwnedStorageObject.object_kind.in_(("backup", "backup-legacy")),
            OwnedStorageObject.state.in_(
                (StorageObjectState.COMMITTED, StorageObjectState.BLOCKED)
            ),
        )
        if key is not None:
            statement = statement.where(OwnedStorageObject.key == key)
        if bucket is not None:
            statement = statement.where(
                OwnedStorageObject.namespace.startswith(f"{bucket}/")
            )
        return list(session.exec(statement).all())


def _list_local_backups() -> list[_contracts_module.BackupMeta]:
    results: list[_contracts_module.BackupMeta] = []
    if not settings.backup_dir.exists():
        return results
    local = LocalStorageBackend()
    local_namespace = f"backup:{settings.backup_dir.expanduser().resolve(strict=False)}"
    committed = _committed_backup_keys(
        "local",
        provider_ref=provider_ref_for_backend(local, namespace=local_namespace),
    )

    for archive in sorted(
        [
            *settings.backup_dir.glob(
                f"{_contracts_module._BACKUP_NAME_PREFIX}*.tar.gz"
            ),
            *settings.backup_dir.glob(
                f"{_contracts_module._LEGACY_BACKUP_NAME_PREFIX}*.tar.gz"
            ),
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ):
        if str(archive) not in committed:
            # A visible archive can be left by a crash between publication and
            # its ownership commit; it is not a listable backup yet.
            continue
        try:
            meta = _archive_format_module._read_manifest(archive)
            if meta is not None:
                meta.location = "local"
                meta.path = str(archive)
                meta.archive_sha256 = _archive_format_module._sha256_path(archive)
                meta.namespace = LocalStorageBackend().namespace_for(str(archive))
                meta.provider_ref = provider_ref_for_backend(
                    LocalStorageBackend(), namespace=meta.namespace
                )
                meta.source_ref = _targets_module.source_reference(
                    location="local",
                    namespace=meta.namespace,
                    path=meta.path,
                    provider_ref=meta.provider_ref,
                )
                results.append(meta)
        except Exception:
            logger.warning("backup: cannot read manifest from %s", archive.name)

    return results


def _list_s3_backups() -> list[_contracts_module.BackupMeta]:
    target = _targets_module._get_backup_s3_target()
    if target is None:
        return []
    results: list[_contracts_module.BackupMeta] = []
    s3, bucket = target.client, target.bucket
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for prefix in (
            _contracts_module._BACKUP_S3_PREFIX,
            _contracts_module._LEGACY_BACKUP_S3_PREFIX,
        ):
            for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = str(obj.get("Key", ""))
                    archive_name = key.rsplit("/", 1)[-1]
                    if not archive_name.startswith(
                        (
                            _contracts_module._BACKUP_NAME_PREFIX,
                            _contracts_module._LEGACY_BACKUP_NAME_PREFIX,
                        )
                    ):
                        continue
                    try:
                        namespace = f"{bucket}/{prefix}"
                        ownership = next(
                            (
                                row
                                for row in _backup_ownership_rows(
                                    key=key, bucket=bucket
                                )
                                if row.namespace == namespace
                                and row.state == StorageObjectState.COMMITTED
                                and row.provider_ref == target.provider_ref
                            ),
                            None,
                        )
                        # Unowned/legacy objects remain in the explicit admin
                        # discovery view. Listing is ownership-only.
                        # A content hash alone does not bind an operation to a
                        # stable remote object. Historical rows lacking both a
                        # version id and an ETag are therefore fail-closed and
                        # must be re-adopted after an operator can prove the
                        # exact object identity.
                        if (
                            ownership is None
                            or not ownership.sha256
                            or (not ownership.version_id and not ownership.etag)
                        ):
                            continue
                        head = _targets_module._s3_head_owned(target, ownership)
                        if (
                            int(head.get("ContentLength", -1)) != ownership.size_bytes
                            or (
                                ownership.etag
                                and str(head.get("ETag", "")) != ownership.etag
                            )
                            or (
                                ownership.version_id
                                and str(head.get("VersionId", ""))
                                != ownership.version_id
                            )
                            or (
                                ownership.object_kind == "backup"
                                and head.get("Metadata", {}).get(
                                    "printstash-create-token"
                                )
                                != ownership.token
                            )
                        ):
                            continue
                        # Listing is a metadata operation. The durable ledger
                        # already carries the archive's content hash and exact
                        # remote identity; do not download and fully validate
                        # every historical archive whenever the UI refreshes.
                        # The GET is conditional and consumes only the first
                        # manifest member (created archives put it first).
                        downloaded = _targets_module._s3_get_owned(target, ownership)
                        body = downloaded.get("Body")
                        try:
                            _targets_module._assert_s3_identity(
                                downloaded,
                                size_bytes=ownership.size_bytes,
                                etag=ownership.etag,
                                version_id=ownership.version_id,
                            )
                            if body is None or not hasattr(body, "read"):
                                continue
                            meta = _archive_format_module._read_manifest_from_stream(
                                body
                            )
                        finally:
                            if body is not None and hasattr(body, "close"):
                                body.close()
                        confirmed = _targets_module._s3_head_owned(target, ownership)
                        _targets_module._assert_s3_identity(
                            confirmed,
                            size_bytes=ownership.size_bytes,
                            etag=ownership.etag,
                            version_id=ownership.version_id,
                        )
                        if meta is None:
                            continue
                        meta.id = _targets_module._backup_id_from_archive_name(
                            archive_name
                        )
                        meta.path = key
                        meta.location = "s3"
                        meta.size_bytes = int(ownership.size_bytes)
                        meta.archive_sha256 = ownership.sha256
                        meta.provider_ref = ownership.provider_ref
                        meta.namespace = namespace
                        meta.source_ref = _targets_module.source_reference(
                            location="s3",
                            namespace=namespace,
                            path=key,
                            provider_ref=ownership.provider_ref,
                        )
                        results.append(meta)
                    except Exception:
                        logger.warning("backup: cannot read S3 manifest for %s", key)
                        continue
    except Exception:
        logger.warning("backup: failed to list S3 backups", exc_info=True)

    return results


def _list_opendal_backups() -> list[_contracts_module.BackupMeta]:
    """List owned replicas for the currently configured OpenDAL destinations."""
    results: list[_contracts_module.BackupMeta] = []
    for destination in _backup_destination_module.configured_destinations():
        try:
            with get_session_factory().scoped_session() as session:
                rows = session.exec(
                    select(OwnedStorageObject).where(
                        OwnedStorageObject.backend == destination.backend.backend_name,
                        OwnedStorageObject.namespace == destination.namespace,
                        OwnedStorageObject.provider_ref == destination.provider_ref,
                        OwnedStorageObject.object_kind.in_(("backup", "backup-legacy")),
                        OwnedStorageObject.state == StorageObjectState.COMMITTED,
                    )
                ).all()
                for row in rows:
                    try:
                        with destination.open_owned(row) as body:
                            meta = _archive_format_module._read_manifest_from_stream(
                                body
                            )
                        if meta is None:
                            continue
                        archive_name = row.key.rsplit("/", 1)[-1]
                        meta.id = _targets_module._backup_id_from_archive_name(
                            archive_name
                        )
                        meta.path = row.key
                        meta.location = destination.location
                        meta.size_bytes = int(row.size_bytes or 0)
                        meta.archive_sha256 = row.sha256
                        meta.provider_ref = row.provider_ref
                        meta.namespace = row.namespace
                        meta.source_ref = _targets_module.source_reference(
                            location=destination.location,
                            namespace=row.namespace,
                            path=row.key,
                            provider_ref=row.provider_ref,
                        )
                        results.append(meta)
                    except Exception:
                        logger.warning(
                            "backup: cannot read OpenDAL manifest for %s", row.key
                        )
        except Exception:
            logger.warning(
                "backup: failed to list OpenDAL destination %s",
                destination.name,
                exc_info=True,
            )
    return results


def list_backups() -> list[_contracts_module.BackupMeta]:
    """List logical archives, retaining visibility of ambiguous identities."""
    return _backup_catalogue_module.BackupCatalogue(list_backup_sources()).backups()


def list_backup_sources(
    *, reconcile: bool = True
) -> list[_contracts_module.BackupMeta]:
    """Return every owned source; canonical display never authorizes a target."""
    if reconcile:
        _publications_module.reconcile_backup_publications()
    return _backup_catalogue_module.BackupCatalogue(
        [*_list_local_backups(), *_list_s3_backups(), *_list_opendal_backups()]
    ).sources()


def get_backup(
    backup_id: str, *, source_ref: str | None = None
) -> _contracts_module.BackupMeta | None:
    return _backup_catalogue_module.BackupCatalogue(list_backup_sources()).select(
        backup_id, source_ref=source_ref
    )


def get_backup_archive_path(backup_id: str, *, source_ref: str | None = None) -> Path:
    """Return a local archive path, downloading cloud-only backups first."""
    meta = get_backup(backup_id, source_ref=source_ref)
    if meta is None:
        raise FileNotFoundError(f"backup {backup_id} not found")
    return _downloads_module._download_backup_to_local(meta)
