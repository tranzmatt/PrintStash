from __future__ import annotations

import json
from datetime import datetime, time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import VaultAuditPolicy


class AuditPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    paused: bool = False
    cadence: Literal["weekly", "monthly"] = "weekly"
    timezone: str = "UTC"
    weekday: int = Field(default=6, ge=0, le=6)
    month_day: int = Field(default=1, ge=1, le=31)
    start_time: str = "02:00"
    window_minutes: int = Field(default=120, ge=1, le=1440)
    bytes_per_second: int = Field(default=10485760, ge=1024, le=1073741824)
    read_concurrency: int = Field(default=1, ge=1, le=1)
    auto_repair: bool = False
    repair_actions: list[Literal["reparse_metadata", "regenerate_thumbnail"]] = Field(
        default_factory=list
    )
    full_cost_acknowledged: bool = False

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("audit_timezone_invalid") from exc
        return value

    @field_validator("start_time")
    @classmethod
    def valid_time(cls, value: str) -> str:
        parsed = time.fromisoformat(value)
        if (
            len(value) != 5
            or parsed.tzinfo is not None
            or parsed.second
            or parsed.microsecond
        ):
            raise ValueError("audit_time_invalid")
        return value


class AuditPolicyRead(AuditPolicyUpdate):
    mode: str
    revision: int
    next_due_at: datetime | None
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    deferred_reason: str | None


def policy_read(row: VaultAuditPolicy) -> AuditPolicyRead:
    values = row.model_dump(
        exclude={"repair_actions_json", "requested_by", "updated_at"}
    )
    return AuditPolicyRead(**values, repair_actions=json.loads(row.repair_actions_json))
