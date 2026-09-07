"""Administrative cache policy and usage without exposing cached object paths."""
from __future__ import annotations

import sqlite3
from dataclasses import asdict
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.core.config import _overlay, settings
from app.db.models import SystemConfig
from app.modules.administration.config_repository import get_or_create
from app.modules.storage.artifact_materializer import CachePolicy
from app.modules.storage.materializer_runtime import get_materializer


class CacheSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    root: str = Field(min_length=1, max_length=1024)
    max_bytes: int = Field(ge=0)
    max_entries: int = Field(ge=0, le=1000000)
    max_fills: int = Field(ge=1, le=64)
    headroom_bytes: int = Field(ge=0)
    verify_every_hits: int = Field(ge=0)


class CacheSettingsRead(BaseModel):
    policy: CacheSettings
    effective_root: str
    restart_required: bool
    source: str
    available: bool
    usage: dict[str, int]


def live_policy() -> CachePolicy:
    return CachePolicy(**{name: getattr(settings, f"artifact_cache_{name}") for name in asdict(CachePolicy())})


def apply_cache_overlay(config: SystemConfig) -> None:
    if config.artifact_cache_policy_json:
        policy = CacheSettings.model_validate_json(config.artifact_cache_policy_json)
        for name, value in policy.model_dump().items():
            _overlay[f"artifact_cache_{name}"] = value


def read_settings(session: Session) -> CacheSettingsRead:
    config = session.get(SystemConfig, 1)
    policy = CacheSettings(**asdict(live_policy()), root=str(settings.artifact_cache_root))
    cache = get_materializer()
    available = cache is not None
    usage: dict[str, int] = {}
    if cache:
        try:
            usage = cache.status()
        except (OSError, sqlite3.Error):
            available = False
    effective_root = str(cache.root) if cache else str(settings.artifact_cache_root)
    return CacheSettingsRead(policy=policy, effective_root=effective_root, restart_required=Path(policy.root).absolute() != Path(effective_root).absolute(), source="database" if config and config.artifact_cache_policy_json else "environment", available=available, usage=usage)


def update_settings(session: Session, policy: CacheSettings | None) -> CacheSettingsRead:
    config = get_or_create(session)
    config.artifact_cache_policy_json = policy.model_dump_json() if policy else None
    session.add(config)
    session.commit()
    for name in CacheSettings.model_fields:
        _overlay.pop(f"artifact_cache_{name}", None)
    apply_cache_overlay(config)
    return read_settings(session)


def clear_cache(session: Session) -> CacheSettingsRead:
    cache = get_materializer()
    if cache:
        cache.clear()
    return read_settings(session)
