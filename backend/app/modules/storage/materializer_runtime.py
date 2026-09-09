"""Bound cache adapter; construction belongs to application startup."""

from __future__ import annotations

from pathlib import Path

from app.modules.storage.artifact_materializer import ArtifactMaterializer

_materializer: ArtifactMaterializer | None = None
_root: Path | None = None


def bind_materializer(
    materializer: ArtifactMaterializer | None, *, configured_root: Path | None = None
) -> None:
    global _materializer, _root
    _materializer = materializer
    _root = materializer.root if materializer else configured_root


def get_materializer_root() -> Path | None:
    return _root


def get_materializer() -> ArtifactMaterializer | None:
    return _materializer


def cache_health() -> dict[str, bool | str]:
    from app.core.config import settings

    if not settings.artifact_cache_enabled:
        return {"ok": True, "state": "disabled"}
    if _materializer is None:
        return {"ok": False, "state": "unavailable"}
    return _materializer.health()
