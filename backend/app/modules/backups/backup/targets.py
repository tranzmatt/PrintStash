"""Backup target identity, configuration and storage location discovery."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import app.modules.backups.backup.contracts as _contracts_module
from app.core.config import _overlay, settings
from app.core.logging import get_logger
from app.db.models import (
    OwnedStorageObject,
)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# S3 client for backup operations (independent from vault S3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _BackupS3Target:
    client: Any
    bucket: str
    signature: str
    provider_ref: str = ""
    endpoint: str | None = None

    @property
    def storage_target(self):
        from app.modules.storage.storage_identity import s3_target

        if self.endpoint is None:
            return None
        return s3_target(endpoint=self.endpoint, bucket=self.bucket)


_backup_s3: Any = None  # compatibility seam used by existing tests

_backup_s3_target: _BackupS3Target | None = None

_backup_s3_lock = threading.RLock()

_backup_s3_last_signature: str | None = None


def _backup_s3_config() -> tuple[str, str, str, str, str]:
    # Runtime configuration is applied to ``_overlay`` in one ``dict.update``
    # operation.  Snapshot that mapping once, rather than resolving five
    # attributes independently: a concurrent admin update must yield either
    # the old complete target or the new complete target, never a bucket from
    # one credential set combined with a secret from another.
    snapshot = dict(_overlay)
    frozen = settings._frozen  # type: ignore[attr-defined]

    def value(name: str, default: str) -> str:
        configured = snapshot.get(name)
        if configured is None:
            configured = getattr(frozen, name)
        return str(configured or default)

    return (
        value("backup_s3_bucket", ""),
        value("backup_s3_endpoint_url", ""),
        value("backup_s3_region", "auto"),
        value("backup_s3_access_key", ""),
        value("backup_s3_secret_key", ""),
    )


def _stable_backup_s3_config() -> tuple[str, str, str, str, str]:
    """Read the complete target tuple atomically enough for env/admin flips.

    Runtime settings are ordinary attributes and an admin update changes more
    than one of them.  Never construct a client from a mixed bucket/credential
    tuple: retry until two consecutive snapshots agree.
    """
    previous = _backup_s3_config()
    for _ in range(3):
        current = _backup_s3_config()
        if current == previous:
            return current
        previous = current
    raise _contracts_module._BackupConfigUnstableError("backup_s3_config_changed")


def _backup_s3_signature(
    config: tuple[str, str, str, str, str] | None = None,
) -> str:
    """Return a non-secret fingerprint of the effective S3 target."""
    values = config or _backup_s3_config()
    return hashlib.sha256("\x1f".join(values).encode()).hexdigest()


def _normalize_provider_endpoint(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        raise ValueError("backup_s3_endpoint_invalid") from None
    if not parsed.scheme or not parsed.hostname:
        raise ValueError("backup_s3_endpoint_invalid")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("backup_s3_endpoint_invalid")
    host = parsed.hostname.lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("backup_s3_endpoint_invalid") from None
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if port in {None, 80} and parsed.scheme.lower() == "http":
        netloc = host
    elif port in {None, 443} and parsed.scheme.lower() == "https":
        netloc = host
    else:
        netloc = host if port is None else f"{host}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path.rstrip("/"), "", ""))


def _backup_provider_ref(config: tuple[str, str, str, str, str]) -> str:
    _, endpoint, region, _, _ = config
    payload = {
        "backend": "backup-s3",
        "provider": "backup-s3",
        "transport": "s3",
        "endpoint": _normalize_provider_endpoint(endpoint),
        "region": str(region or "").strip().lower(),
        "addressing_style": "path",
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _get_backup_s3() -> Any:
    """Return a boto3 S3 client for the backup bucket, or None if not configured."""
    global _backup_s3, _backup_s3_target, _backup_s3_last_signature
    with _backup_s3_lock:
        try:
            config = _stable_backup_s3_config()
        except _contracts_module._BackupConfigUnstableError:
            # Fail closed rather than constructing a client from a mixed
            # bucket/endpoint/credential tuple. A later operation retries.
            _backup_s3 = False
            _backup_s3_target = None
            _backup_s3_last_signature = None
            return None
        bucket, endpoint, region, access_key, secret_key = config
        signature = _backup_s3_signature(config)
        # A disabled or failed target must not poison the cache after an admin
        # fixes credentials/endpoint.  The signature is intentionally hashed so
        # secrets never enter logs or reprs.
        if signature == _backup_s3_last_signature:
            return None if _backup_s3 is False else _backup_s3
        _backup_s3_last_signature = signature
        _backup_s3_target = None
        _backup_s3 = None
        if not bucket:
            _backup_s3 = False
            return None
        try:
            import boto3
            from botocore.config import Config as BotoConfig

            kwargs: dict = {
                "service_name": "s3",
                "region_name": region,
                "aws_access_key_id": access_key or None,
                "aws_secret_access_key": secret_key or None,
                "config": BotoConfig(
                    signature_version="s3v4", s3={"addressing_style": "path"}
                ),
            }
            if endpoint:
                kwargs["endpoint_url"] = endpoint
            _backup_s3 = boto3.client(**kwargs)
            _backup_s3_target = _BackupS3Target(
                client=_backup_s3,
                bucket=bucket,
                signature=signature,
                provider_ref=_backup_provider_ref(config),
                endpoint=endpoint,
            )
            logger.info("backup: S3 client initialised for configured target")
            return _backup_s3
        except Exception:
            logger.warning("backup: failed to initialise S3 client", exc_info=True)
            _backup_s3 = False
            # Do not memoize an outage forever; the next operation retries so
            # an endpoint becoming reachable does not require a process
            # restart.
            _backup_s3_last_signature = None
            return None


def _get_backup_s3_target() -> _BackupS3Target | None:
    """Capture client and bucket atomically for one backup operation."""
    with _backup_s3_lock:
        client = _get_backup_s3()
        if not client:
            return None
        target = _backup_s3_target
        if target is not None and target.client is client:
            return target
        # Tests and integrations replace _get_backup_s3 with a fake. Keep that
        # seam safe while still snapshotting the bucket for the operation.
        try:
            config = _stable_backup_s3_config()
        except _contracts_module._BackupConfigUnstableError:
            return None
        return _BackupS3Target(
            client,
            config[0],
            _backup_s3_signature(config),
            _backup_provider_ref(config),
            config[1],
        )


def _backup_s3_key(archive_name: str) -> str:
    return f"{_contracts_module._BACKUP_S3_PREFIX}{archive_name}"


def source_reference(
    *, location: str, namespace: str | None, path: str, provider_ref: str | None = None
) -> str:
    """Opaque, stable locator identity (never contains credentials)."""
    raw = f"{provider_ref or ''}\x1f{location}\x1f{namespace or ''}\x1f{path}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _s3_prefix_for_key(key: str) -> str | None:
    for prefix in (
        _contracts_module._BACKUP_S3_PREFIX,
        _contracts_module._LEGACY_BACKUP_S3_PREFIX,
    ):
        if key.startswith(prefix):
            return prefix
    return None


def _backup_id_from_archive_name(name: str) -> str:
    if not name.endswith(".tar.gz"):
        raise ValueError("backup_key_invalid")
    stem = name.removesuffix(".tar.gz")
    backup_id = stem.rsplit("-", 1)[-1]
    if not backup_id:
        raise ValueError("backup_key_invalid")
    return backup_id


def _is_direct_remote_backup_key(key: str, prefix: str) -> bool:
    """Accept only a portable archive name directly under the reserved prefix."""
    if not key or "\\" in key:
        return False
    path = PurePosixPath(key)
    root = PurePosixPath(prefix.rstrip("/"))
    return not path.is_absolute() and ".." not in path.parts and path.parent == root


def _s3_object_kwargs(
    *, bucket: str, key: str, row: OwnedStorageObject, delete: bool = False
) -> dict[str, str]:
    """Build an immutable S3 locator proof for HEAD/GET/DELETE.

    Version ids are stronger than ETags and must be used whenever present. An
    unversioned object is only safe when the provider gave us an ETag that can
    be sent as a conditional request.  In particular, never perform an
    unconditional delete after a check-then-delete race.
    """
    kwargs: dict[str, str] = {"Bucket": bucket, "Key": key}
    if row.version_id and row.version_id != "null":
        kwargs["VersionId"] = row.version_id
    elif row.etag:
        kwargs["IfMatch"] = row.etag
    else:
        # Reads are destructive in practice too: downloading an object that
        # cannot be bound to an immutable locator can restore the wrong bytes.
        # Require a VersionId or conditional ETag for every remote operation,
        # not only DELETE.
        raise _contracts_module.BackupOwnershipError(
            "backup_remote_identity_unavailable"
        )
    return kwargs


def _s3_head_owned(target: _BackupS3Target, row: OwnedStorageObject) -> dict:
    return target.client.head_object(
        **_s3_object_kwargs(bucket=target.bucket, key=row.key, row=row)
    )


def _s3_get_owned(target: _BackupS3Target, row: OwnedStorageObject) -> dict:
    return target.client.get_object(
        **_s3_object_kwargs(bucket=target.bucket, key=row.key, row=row)
    )


def _assert_s3_identity(
    response: dict, *, size_bytes: int | None, etag: str | None, version_id: str | None
) -> None:
    """Require a response to describe the exact object selected by the ledger."""
    if size_bytes is not None and int(response.get("ContentLength", -1)) != size_bytes:
        raise _contracts_module.BackupOwnershipError("backup_remote_size_changed")
    if etag is not None and str(response.get("ETag", "")) != etag:
        raise _contracts_module.BackupOwnershipError("backup_remote_etag_changed")
    if version_id is not None and str(response.get("VersionId", "")) != version_id:
        raise _contracts_module.BackupOwnershipError("backup_remote_version_changed")


def _s3_identity_kwargs(*, bucket: str, key: str, response: dict) -> dict[str, str]:
    """Build a conditional locator from a just-captured S3 identity."""
    version_id = response.get("VersionId")
    etag = response.get("ETag")
    if version_id and version_id != "null":
        return {"Bucket": bucket, "Key": key, "VersionId": str(version_id)}
    if etag:
        return {"Bucket": bucket, "Key": key, "IfMatch": str(etag)}
    raise _contracts_module.BackupOwnershipError("backup_remote_identity_unavailable")


def _assert_same_s3_identity(actual: dict, expected: dict) -> None:
    """Require both identity components returned by a proof to be preserved."""
    _require_remote_identity(expected)
    _require_remote_identity(actual)
    if actual.get("VersionId") != expected.get("VersionId"):
        raise _contracts_module.BackupOwnershipError("backup_remote_version_changed")
    if actual.get("ETag") != expected.get("ETag"):
        raise _contracts_module.BackupOwnershipError("backup_remote_etag_changed")


def _require_remote_identity(response: dict) -> None:
    if not response.get("VersionId") and not response.get("ETag"):
        raise RuntimeError("backup_remote_identity_unavailable")


def configured_backup_storage_targets():
    """Describe configured backup destinations without exposing clients or secrets."""
    from app.modules.backups.backup_destination import configured_destinations

    targets = []
    legacy = _get_backup_s3_target()
    if legacy is not None:
        targets.append(("backup", "S3 backup", legacy.storage_target))
    targets.extend(
        ("backup", destination.name, destination.backend.storage_target)
        for destination in configured_destinations()
    )
    return targets
