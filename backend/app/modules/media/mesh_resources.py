"""Materialized mesh preparation with explicit ownership of its source scene."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from printstash_core.mesh.similarity import GeometryError
from printstash_core.mesh.similarity.budgets import MAX_ANALYSIS_FACES
from printstash_core.mesh.similarity.components import (
    ExpandedScene,
    Instance,
    compose_scene,
    split_components,
)

from app.modules.media.three_mf_scene import read_scene


@dataclass(frozen=True)
class PreparedMesh:
    whole_mesh: Any
    scene: ExpandedScene
    format: str
    complete: bool = True
    failure_code: str | None = None
    brep: dict[str, Any] | None = None
    whole_resource_id: str | None = None


def prepare_loaded_mesh(mesh: Any, *, file_type: str) -> PreparedMesh:
    import numpy as np

    resources = split_components(np.asarray(mesh.vertices), np.asarray(mesh.faces))
    scene = ExpandedScene(
        resources,
        tuple(Instance(resource.resource_id, np.eye(4)) for resource in resources),
    )
    return PreparedMesh(
        mesh,
        scene,
        file_type,
        brep=mesh.metadata.get("brep"),
        whole_resource_id=resources[0].resource_id if len(resources) == 1 else None,
    )


def load_3mf(path: Path, *, max_faces: int = MAX_ANALYSIS_FACES) -> PreparedMesh:
    """Read a bounded source scene, then explicitly materialize its placed mesh."""
    import numpy as np
    import trimesh

    scene = read_scene(path, max_faces=max_faces)
    try:
        vertices, faces = compose_scene(scene)
        if not np.isfinite(vertices).all():
            raise GeometryError("nonfinite_geometry")
        mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        same_resource = len(scene.resources) == len(
            scene.instances
        ) == 1 and np.array_equal(scene.instances[0].transform, np.eye(4))
        return PreparedMesh(
            mesh,
            scene,
            "3mf",
            whole_resource_id=(
                scene.resources[0].resource_id if same_resource else None
            ),
        )
    except GeometryError:
        raise
    except (OSError, ValueError, KeyError, OverflowError) as exc:
        raise GeometryError("invalid_3mf") from exc
