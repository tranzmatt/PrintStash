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
