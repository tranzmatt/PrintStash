"""Bound cache adapter; construction belongs to application startup."""
from __future__ import annotations

from app.modules.storage.artifact_materializer import ArtifactMaterializer

_materializer: ArtifactMaterializer | None = None


def bind_materializer(materializer: ArtifactMaterializer | None) -> None:
    global _materializer
    _materializer = materializer


def get_materializer() -> ArtifactMaterializer | None:
    return _materializer
