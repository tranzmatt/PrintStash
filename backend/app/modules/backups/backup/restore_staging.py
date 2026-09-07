"""Validated restoration staging before database replacement."""

from __future__ import annotations

import shutil
import tarfile
from pathlib import Path

import app.modules.backups.backup.archive_format as _archive_format_module
import app.modules.backups.backup.contracts as _contracts_module
import app.modules.backups.backup.snapshot as _snapshot_module
from app.core.logging import get_logger
from app.modules.storage.storage_backend.runtime import get_backend

logger = get_logger(__name__)


def _stage_restore_archive(
    archive_path: Path, staging_dir: Path
) -> tuple[Path, list[_contracts_module._StagedBlob]]:
    """Extract a validated database and blobs into private staging files."""
    database_path = staging_dir / "db.sqlite3"
    staged_blobs: list[_contracts_module._StagedBlob] = []
    with tarfile.open(archive_path, mode="r:gz") as tar:
        members = tar.getmembers()
        for member in members:
            if (
                _archive_format_module._unsafe_member_name(member.name)
                or member.issym()
                or member.islnk()
            ):
                raise RuntimeError("backup_manifest_invalid")

        manifest, manifest_entries = _archive_format_module._restore_manifest_entries(
            tar
        )
        version = str(manifest["version"])
        if version in {
            _contracts_module._LEGACY_MANIFEST_V2,
            _contracts_module.MANIFEST_VERSION,
        }:
            regular_by_name: dict[str, list[tarfile.TarInfo]] = {}
            for member in members:
                if member.isfile():
                    regular_by_name.setdefault(member.name, []).append(member)
            if len(regular_by_name.get("manifest.json", [])) != 1:
                raise RuntimeError("backup_manifest_invalid")
            if len(regular_by_name.get("db.sqlite3", [])) != 1:
                raise RuntimeError("backup_manifest_invalid")
            archived_files = {
                name for name in regular_by_name if name.startswith("files/")
            }
            if archived_files != set(manifest_entries):
                raise RuntimeError("backup_manifest_invalid")
            if any(len(regular_by_name[name]) != 1 for name in archived_files):
                raise RuntimeError("backup_manifest_invalid")
            if set(regular_by_name) != {
                "manifest.json",
                "db.sqlite3",
                *manifest_entries,
            }:
                raise RuntimeError("backup_manifest_invalid")
        arc_to_key = _archive_format_module._restore_key_map(tar)
        db_member = (
            tar.extractfile("db.sqlite3")
            if _archive_format_module._has_member(tar, "db.sqlite3")
            else None
        )
        if db_member is None:
            raise RuntimeError("backup_member_missing:db.sqlite3")
        with database_path.open("wb") as destination:
            shutil.copyfileobj(db_member, destination)
        _snapshot_module._validate_sqlite_snapshot(database_path)

        for member in members:
            if not member.name.startswith("files/") or member.name == "files/":
                continue
            source = tar.extractfile(member)
            if source is None:
                continue
            key = arc_to_key.get(member.name, member.name[len("files/") :])
            staged_path = staging_dir / f"blob-{len(staged_blobs):08d}"
            with staged_path.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            if staged_path.stat().st_size != member.size:
                raise RuntimeError("backup_member_size_mismatch")
            entry = manifest_entries.get(member.name)
            digest = _archive_format_module._sha256_path(staged_path)
            if entry is not None and isinstance(entry.get("size"), int):
                if member.size != int(entry["size"]):
                    raise RuntimeError("backup_member_size_mismatch")
                expected_sha = entry.get("sha256")
                if isinstance(expected_sha, str):
                    if digest != expected_sha:
                        raise RuntimeError("backup_member_hash_mismatch")
            staged_blobs.append(
                _contracts_module._StagedBlob(
                    key=key,
                    path=staged_path,
                    size=member.size,
                    sha256=digest,
                    namespace=get_backend().namespace_for(key),
                )
            )
    return database_path, staged_blobs
