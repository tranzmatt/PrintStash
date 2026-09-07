"""Object ownership, deletion intents, restore markers and storage connections."""

import secrets
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field

from app.core.time import utcnow
from app.db.encrypted import EncryptedText

from .base import SQLModel
from .types import LibrarySourceKind, StorageConnectionPurpose, StorageObjectState


class OwnedStorageObject(SQLModel, table=True):
    """Intent and proof for one key PrintStash means to own.

    ``PENDING`` is committed before storage publication. The transition to
    ``COMMITTED`` shares the domain transaction that makes the object live.
    """

    __tablename__ = "owned_storage_objects"
    __table_args__ = (
        UniqueConstraint(
            "backend",
            "provider_ref",
            "namespace",
            "key",
            name="uq_owned_storage_provider_locator",
        ),
        # Historical rows have no provider identity.  Keep those rows
        # collision-safe as well: SQLite/Postgres both allow multiple NULLs in
        # a normal UNIQUE constraint, so the partial index is the legacy
        # equivalent while new rows use the provider-aware constraint above.
        Index(
            "uq_owned_storage_legacy_locator",
            "backend",
            "namespace",
            "key",
            unique=True,
            sqlite_where=text("provider_ref IS NULL"),
            postgresql_where=text("provider_ref IS NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    backend: str = Field(max_length=32, index=True)
    namespace: str = Field(max_length=1024, index=True)
    key: str = Field(max_length=2048)
    # Credential-free identity of the provider destination.  This is a stable
    # digest of the normalized endpoint/region/bucket (or local namespace),
    # never of access credentials.  It lets recovery distinguish a receipt
    # written against an old target from one written against the current
    # target even when a bucket/key happens to be reused.
    provider_ref: Optional[str] = Field(default=None, max_length=64, index=True)
    object_kind: str = Field(max_length=64, index=True)
    state: StorageObjectState = Field(
        default=StorageObjectState.PENDING,
        sa_column=Column(
            SAEnum(
                StorageObjectState,
                values_callable=lambda members: [member.value for member in members],
                native_enum=False,
                length=16,
            ),
            nullable=False,
            index=True,
        ),
    )
    token: Optional[str] = Field(default=None, max_length=64)
    size_bytes: Optional[int] = None
    sha256: Optional[str] = Field(default=None, max_length=64, index=True)
    etag: Optional[str] = Field(default=None, max_length=255)
    version_id: Optional[str] = Field(default=None, max_length=1024)
    device: Optional[int] = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    inode: Optional[int] = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    ctime_ns: Optional[int] = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    created_at: datetime = Field(default_factory=utcnow, index=True)
    committed_at: Optional[datetime] = Field(default=None, index=True)
    last_error: Optional[str] = Field(default=None, max_length=255)


class StorageDeleteIntent(SQLModel, table=True):
    """Durable, immutable authorization to delete one exact owned object."""

    __tablename__ = "storage_delete_intents"
    __table_args__ = (
        UniqueConstraint(
            "backend",
            "provider_ref",
            "namespace",
            "key",
            "token",
            name="uq_storage_delete_intent_provider_receipt",
        ),
        Index(
            "uq_storage_delete_intent_legacy_receipt",
            "backend",
            "namespace",
            "key",
            "token",
            unique=True,
            sqlite_where=text("provider_ref IS NULL"),
            postgresql_where=text("provider_ref IS NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    backend: str = Field(max_length=32, index=True)
    namespace: str = Field(max_length=1024)
    key: str = Field(max_length=2048)
    # Credential-free identity of the configured destination. NULL is retained
    # for old outbox rows, but recovery must block those rows rather than
    # guessing which provider now owns their key.
    provider_ref: Optional[str] = Field(default=None, max_length=64, index=True)
    object_kind: str = Field(max_length=64, index=True)
    token: str = Field(max_length=64)
    size_bytes: int
    # Content evidence is revalidated immediately before a Guarded/manual
    # delete, preventing a replacement at the same key from being removed.
    sha256: Optional[str] = Field(default=None, max_length=64, index=True)
    etag: Optional[str] = Field(default=None, max_length=255)
    version_id: Optional[str] = Field(default=None, max_length=1024)
    device: Optional[int] = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    inode: Optional[int] = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    ctime_ns: Optional[int] = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    # The authorization decision is durable: a retry after process death must
    # not reinterpret a one-shot guarded confirmation as a verified delete (or
    # vice versa).
    authorization_mode: str = Field(default="verified", max_length=16, index=True)
    authorized_actor_id: Optional[int] = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    authorized_at: datetime = Field(default_factory=utcnow, index=True)
    quarantine_key: Optional[str] = Field(default=None, max_length=2048)
    quarantine_state: str = Field(default="none", max_length=16)
    resource_kind: Optional[str] = Field(default=None, max_length=64, index=True)
    resource_id: Optional[str] = Field(default=None, max_length=64, index=True)
    status: str = Field(default="pending", max_length=16, index=True)
    attempts: int = Field(default=0)
    next_attempt_at: Optional[datetime] = Field(default=None, index=True)
    last_error: Optional[str] = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)
    completed_at: Optional[datetime] = None


class RestoreMarker(SQLModel, table=True):
    """Durable point-of-no-return marker carried by a restored database."""

    __tablename__ = "restore_markers"
    __table_args__ = (
        UniqueConstraint("backup_id", name="uq_restore_marker_backup"),
        UniqueConstraint("operation_nonce", name="uq_restore_marker_nonce"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    backup_id: str = Field(max_length=255, index=True)
    operation_nonce: str = Field(
        default_factory=lambda: secrets.token_hex(32), max_length=64, index=True
    )
    archive_sha256: str = Field(default="", max_length=64, index=True)
    state: str = Field(default="database_active", max_length=32, index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)


class StorageFailureDomainDeclaration(SQLModel, table=True):
    """Administrator attestation bound to one versioned target identity."""

    __tablename__ = "storage_failure_domain_declarations"

    target_ref: str = Field(primary_key=True, max_length=64)
    target_identity: str = Field(sa_column=Column(Text, nullable=False))
    failure_domain: str = Field(max_length=128)
    revision: str = Field(max_length=32)
    declared_by: Optional[int] = Field(default=None, foreign_key="users.id")
    updated_at: datetime = Field(default_factory=utcnow)


class StorageConnection(SQLModel, table=True):
    """Reusable encrypted credentials for one bounded remote location."""

    __tablename__ = "storage_connections"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=128, unique=True, index=True)
    kind: LibrarySourceKind = Field(index=True)
    purpose: StorageConnectionPurpose = Field(
        default=StorageConnectionPurpose.LIBRARY,
        sa_column=Column(
            SAEnum(StorageConnectionPurpose, native_enum=False, length=16),
            nullable=False,
            index=True,
            server_default=StorageConnectionPurpose.LIBRARY.name,
        ),
    )
    config_json: str = Field(default="{}", sa_column=Column(Text, nullable=False))
    secret_json: str = Field(
        default="{}", sa_column=Column(EncryptedText(), nullable=False)
    )
    enabled: bool = Field(default=True, index=True)
    manual_backup_enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="1"),
    )
    automatic_backup_enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="1"),
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
