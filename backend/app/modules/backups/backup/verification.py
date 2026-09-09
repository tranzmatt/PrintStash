"""Archive integrity verification and verification metadata."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import tarfile
import tempfile
from collections.abc import Callable
from pathlib import Path

import app.modules.backups.backup.archive_format as _archive_format_module
import app.modules.backups.backup.caches as _caches_module
import app.modules.backups.backup.catalogue as _catalogue_module
import app.modules.backups.backup.contracts as _contracts_module
import app.modules.backups.backup.downloads as _downloads_module
import app.modules.backups.backup.snapshot as _snapshot_module
import app.modules.backups.backup.targets as _targets_module
import app.modules.backups.backup_destination as _backup_destination_module
from app.core.logging import get_logger
from app.db.models import (
    OwnedStorageObject,
    StorageObjectState,
)
from app.db.session import get_session_factory
from app.modules.administration import audit

logger = get_logger(__name__)


class _ProgressReader(io.BufferedReader):
    """Cooperative bounded read hook for scheduled verification."""

    def __init__(self, path: Path, progress: Callable[[int], None]) -> None:
        super().__init__(path.open("rb"))
        self.progress = progress

    def read(self, size: int = -1) -> bytes:
        self.progress(0)
        data = super().read(size)
        self.progress(len(data))
        return data


def verify_backup(
    backup_id: str,
    *,
    source_ref: str | None = None,
    archive_path: Path | None = None,
    record_audit: bool = True,
    progress: Callable[[int], None] | None = None,
    allocate: Callable[[int], None] | None = None,
) -> _contracts_module.BackupVerification:
    """Validate archive structure, manifest membership, sizes, and safe paths."""
    explicit_archive = archive_path is not None
    # Keep the narrow helper seam compatible with integrations that replace it
    # with a one-argument callable; source selection is only needed on the
    # collision path.
    archive = archive_path or (
        _catalogue_module.get_backup_archive_path(backup_id)
        if source_ref is None
        else _catalogue_module.get_backup_archive_path(backup_id, source_ref=source_ref)
    )
    findings: list[dict[str, str | int]] = []
    manifest: dict | None = None
    members: list[tarfile.TarInfo] = []
    try:
        with (
            (
                _ProgressReader(archive, progress) if progress else archive.open("rb")
            ) as archive_stream,
            tarfile.open(fileobj=archive_stream, mode="r:gz") as tar,
        ):
            members = tar.getmembers()
            for member in members:
                if (
                    _archive_format_module._unsafe_member_name(member.name)
                    or member.issym()
                    or member.islnk()
                ):
                    findings.append(
                        {"code": "backup_manifest_invalid", "member": member.name[:255]}
                    )
            manifests = [member for member in members if member.name == "manifest.json"]
            if len(manifests) != 1:
                findings.append(
                    {"code": "backup_manifest_invalid", "member": "manifest.json"}
                )
            else:
                stream = tar.extractfile(manifests[0])
                try:
                    parsed = (
                        json.loads(stream.read().decode("utf-8")) if stream else None
                    )
                except (ValueError, UnicodeDecodeError):
                    parsed = None
                if isinstance(parsed, dict):
                    manifest = parsed
                else:
                    findings.append(
                        {"code": "backup_manifest_invalid", "member": "manifest.json"}
                    )
            if sum(member.name == "db.sqlite3" for member in members) != 1:
                findings.append(
                    {"code": "backup_member_missing", "member": "db.sqlite3"}
                )
            else:
                db_member = next(
                    member for member in members if member.name == "db.sqlite3"
                )
                if not db_member.isfile():
                    findings.append(
                        {"code": "backup_manifest_invalid", "member": "db.sqlite3"}
                    )
                else:
                    if allocate is not None:
                        allocate(db_member.size)
                    fd, raw_db = tempfile.mkstemp(prefix=".printstash-verify-db-")
                    os.close(fd)
                    db_path = Path(raw_db)
                    try:
                        stream = tar.extractfile(db_member)
                        if stream is None:
                            raise RuntimeError("backup_member_missing:db.sqlite3")
                        with db_path.open("wb") as destination:
                            shutil.copyfileobj(stream, destination)
                        try:
                            _snapshot_module._validate_sqlite_snapshot(db_path)
                        except Exception:
                            findings.append(
                                {
                                    "code": "backup_manifest_invalid",
                                    "member": "db.sqlite3",
                                }
                            )
                    finally:
                        db_path.unlink(missing_ok=True)
            if manifest is not None:
                if manifest.get("version") == _contracts_module.MANIFEST_VERSION and (
                    not isinstance(manifest.get("provider_id"), str)
                    or not isinstance(manifest.get("transport"), str)
                    or not isinstance(manifest.get("namespace"), (str, type(None)))
                    or not isinstance(manifest.get("namespaces"), list)
                    or any(
                        not isinstance(value, str) for value in manifest["namespaces"]
                    )
                ):
                    findings.append(
                        {"code": "backup_manifest_invalid", "member": "manifest.json"}
                    )
                expected_entries = manifest.get("files")
                if not isinstance(expected_entries, list):
                    findings.append(
                        {"code": "backup_manifest_invalid", "member": "files"}
                    )
                else:
                    by_name: dict[str, list[tarfile.TarInfo]] = {}
                    for member in members:
                        by_name.setdefault(member.name, []).append(member)
                    declared_members: set[str] = set()
                    for entry in expected_entries:
                        if not isinstance(entry, dict):
                            findings.append(
                                {"code": "backup_manifest_invalid", "member": "files"}
                            )
                            continue
                        arc = entry.get("member", entry.get("arc"))
                        if not isinstance(arc, str):
                            findings.append(
                                {"code": "backup_manifest_invalid", "member": "files"}
                            )
                            continue
                        if arc in declared_members:
                            findings.append(
                                {"code": "backup_manifest_invalid", "member": arc[:255]}
                            )
                            continue
                        declared_members.add(arc)
                        matches = by_name.get(arc, [])
                        if len(matches) != 1 or not matches[0].isfile():
                            findings.append(
                                {"code": "backup_member_missing", "member": arc[:255]}
                            )
                            continue
                        expected_size = entry.get("size")
                        if (
                            isinstance(expected_size, int)
                            and matches[0].size != expected_size
                        ):
                            findings.append(
                                {
                                    "code": "backup_member_size_mismatch",
                                    "member": arc[:255],
                                    "expected_size": expected_size,
                                    "actual_size": matches[0].size,
                                }
                            )
                        expected_sha = entry.get("sha256")
                        if str(manifest.get("version")) in {
                            _contracts_module._LEGACY_MANIFEST_V2,
                            _contracts_module.MANIFEST_VERSION,
                        } and (
                            not isinstance(entry.get("key"), str)
                            or not isinstance(entry.get("namespace"), str)
                            or not isinstance(expected_size, int)
                            or not isinstance(expected_sha, str)
                            or (
                                str(manifest.get("version"))
                                == _contracts_module._LEGACY_MANIFEST_V2
                                and not isinstance(entry.get("provider"), str)
                            )
                            or (
                                str(manifest.get("version"))
                                == _contracts_module.MANIFEST_VERSION
                                and (
                                    not isinstance(entry.get("provider"), str)
                                    or not isinstance(entry.get("provider_id"), str)
                                    or not isinstance(entry.get("transport"), str)
                                )
                            )
                        ):
                            findings.append(
                                {"code": "backup_manifest_invalid", "member": arc[:255]}
                            )
                            continue
                        if isinstance(expected_sha, str) and len(expected_sha) == 64:
                            stream = tar.extractfile(matches[0])
                            digest = hashlib.sha256()
                            if stream is not None:
                                while chunk := stream.read(1024 * 1024):
                                    digest.update(chunk)
                            if digest.hexdigest() != expected_sha.lower():
                                findings.append(
                                    {
                                        "code": "backup_member_hash_mismatch",
                                        "member": arc[:255],
                                    }
                                )
                    if str(manifest.get("version")) in {
                        _contracts_module._LEGACY_MANIFEST_V2,
                        _contracts_module.MANIFEST_VERSION,
                    }:
                        archived_regular_files = {
                            member.name
                            for member in members
                            if member.isfile() and member.name.startswith("files/")
                        }
                        if archived_regular_files != declared_members:
                            findings.append(
                                {
                                    "code": "backup_manifest_invalid",
                                    "member": "files",
                                }
                            )
                        if manifest.get("file_count") != len(expected_entries):
                            findings.append(
                                {
                                    "code": "backup_manifest_invalid",
                                    "member": "file_count",
                                }
                            )
    except (tarfile.TarError, OSError, EOFError):
        findings.append({"code": "backup_manifest_invalid", "member": "archive"})

    manifest_version = str(manifest.get("version")) if manifest else None
    app_compatible = manifest_version in _contracts_module._SUPPORTED_MANIFEST_VERSIONS
    if manifest is not None and not app_compatible:
        findings.append({"code": "backup_manifest_invalid", "member": "version"})
    result = _contracts_module.BackupVerification(
        backup_id=backup_id,
        valid=not findings,
        app_compatible=app_compatible,
        manifest_version=manifest_version,
        checked_members=len(members),
        findings=findings,
    )
    if not explicit_archive:
        if result.valid and result.app_compatible:
            from app.modules.backups.backup_runs import record_verification

            record_verification(
                backup_id=backup_id,
                source_ref=source_ref,
                archive_path=archive,
                digest=_archive_format_module._sha256_path(archive),
            )
        _caches_module.cleanup_backup_cache(archive)
    if record_audit:
        with get_session_factory().session() as session:
            audit.record(
                session,
                action="backup.verify",
                resource_type="backup",
                diff={
                    "backup_id": backup_id,
                    "valid": result.valid,
                    "findings": len(findings),
                },
            )
    return result


def verify_backup_ownership(
    ownership_id: int,
    *,
    progress: Callable[[int], None] | None = None,
    allocate: Callable[[int], None] | None = None,
    fresh_remote: bool = False,
) -> _contracts_module.BackupOwnershipVerification:
    """Verify one exact committed backup receipt without discovery/listing.

    Audits must be able to report a missing or inaccessible replica.  Resolving
    a logical backup id through the discovery APIs can hide that replica (and
    can collapse same-id sources), so this seam starts from the durable ledger
    primary key and carries its exact locator through download and validation.
    """
    with get_session_factory().session() as session:
        row = session.get(OwnedStorageObject, ownership_id)
        if row is None or row.object_kind not in {"backup", "backup-legacy"}:
            return _contracts_module.BackupOwnershipVerification(
                ownership_id=ownership_id,
                status="missing",
                error="backup_ownership_not_found",
            )
        row = OwnedStorageObject.model_validate(row.model_dump())

    if row.state == StorageObjectState.BLOCKED:
        return _contracts_module.BackupOwnershipVerification(
            ownership_id=ownership_id,
            status="identity",
            error=row.last_error or "backup_ownership_blocked",
        )
    if row.state != StorageObjectState.COMMITTED:
        return _contracts_module.BackupOwnershipVerification(
            ownership_id=ownership_id,
            status="missing",
            error="backup_ownership_not_committed",
        )

    if row.backend == "local":
        location = "local"
    elif row.backend.startswith("backup-opendal-"):
        destination = _backup_destination_module.destination_for_ownership(row)
        if destination is None:
            return _contracts_module.BackupOwnershipVerification(
                ownership_id=ownership_id,
                status="identity",
                error="backup_storage_ownership_unverified",
            )
        location = destination.location
    else:
        location = "s3"
    try:
        backup_id = _targets_module._backup_id_from_archive_name(Path(row.key).name)
    except ValueError:
        backup_id = str(ownership_id)
    source_ref = _targets_module.source_reference(
        location=location,
        namespace=row.namespace,
        path=row.key,
        provider_ref=row.provider_ref,
    )
    meta = _contracts_module.BackupMeta(
        id=backup_id,
        created_at=row.created_at.isoformat(),
        size_bytes=row.size_bytes or 0,
        storage_backend=row.backend,
        file_count=0,
        app_version="unknown",
        path=row.key,
        location=location,
        archive_sha256=row.sha256,
        provider_ref=row.provider_ref,
        namespace=row.namespace,
        source_ref=source_ref,
    )
    cache_path: Path | None = None
    try:
        if location == "local":
            archive = Path(row.key)
        else:
            download_options = {}
            if progress is not None:
                download_options["progress"] = progress
            if fresh_remote:
                download_options["fresh_remote"] = True
            archive = _downloads_module._download_backup_to_local(
                meta, **download_options
            )
        if location != "local":
            cache_path = archive
        verify_options = {"archive_path": archive, "record_audit": False}
        if progress is not None:
            verify_options["progress"] = progress
        if allocate is not None:
            verify_options["allocate"] = allocate
        result = verify_backup(backup_id, **verify_options)
    except FileNotFoundError as exc:
        return _contracts_module.BackupOwnershipVerification(
            ownership_id=ownership_id,
            status="missing",
            error=type(exc).__name__,
        )
    except _contracts_module.BackupOwnershipError as exc:
        message = str(exc)
        status: _contracts_module.BackupOwnershipVerificationStatus = (
            "digest" if "digest" in message or "hash" in message else "identity"
        )
        return _contracts_module.BackupOwnershipVerification(
            ownership_id=ownership_id,
            status=status,
            error=message,
        )
    except OSError as exc:
        return _contracts_module.BackupOwnershipVerification(
            ownership_id=ownership_id,
            status="inaccessible",
            error=type(exc).__name__,
        )
    finally:
        if cache_path is not None:
            _caches_module.cleanup_backup_cache(cache_path)

    status = "valid" if result.valid else "corrupt"
    return _contracts_module.BackupOwnershipVerification(
        ownership_id=ownership_id,
        status=status,
        verification=result,
    )
