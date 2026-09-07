"""Durable capacity claims and bounded storage evidence."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Column, Text
from sqlmodel import Field

from app.core.time import utcnow

from .base import SQLModel


class CapacityLock(SQLModel, table=True):
    __tablename__ = "capacity_locks"
    id: int = Field(default=1, primary_key=True)
    revision: int = Field(default=0)


class CapacityReservation(SQLModel, table=True):
    __tablename__ = "capacity_reservations"
    operation_id: str = Field(primary_key=True, max_length=200)
    resources_json: str = Field(sa_column=Column(Text, nullable=False))
    expires_at: datetime = Field(index=True)
    created_at: datetime = Field(default_factory=utcnow)


class StorageInventorySample(SQLModel, table=True):
    __tablename__ = "storage_inventory_samples"
    __table_args__ = (
        CheckConstraint("owned_bytes >= 0", name="nonnegative_owned_bytes"),
    )
    id: int | None = Field(default=None, primary_key=True)
    sampled_at: datetime = Field(default_factory=utcnow, index=True)
    target_ref: str = Field(max_length=128, index=True)
    owned_bytes: int = Field(sa_column=Column(BigInteger, nullable=False))
    evidence_json: str = Field(sa_column=Column(Text, nullable=False))
