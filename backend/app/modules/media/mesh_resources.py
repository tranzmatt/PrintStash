"""Materialized mesh preparation with explicit ownership of its source scene."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from printstash_core.mesh.similarity import GeometryError
from printstash_core.mesh.similarity.budgets import MAX_ANALYSIS_FACES
from printstash_core.mesh.similarity.components import (
    ExpandedScene,
    Instance,
    compose_scene,
    split_components,
)

from app.modules.media.three_mf_scene import read_scene

from .mesh_facts import (
    CompleteGeometry,
    FingerprintFailureCode,
    PreparedGeometry,
    SampledGeometry,
)

if TYPE_CHECKING:
    from trimesh import Trimesh


@dataclass(frozen=True)
class PreparedMesh:
    whole_mesh: Trimesh
    scene: ExpandedScene
    geometry: PreparedGeometry
    brep: dict[str, Any] | None = None
    whole_resource_id: str | None = None

    def __post_init__(self) -> None:
        import numpy as np
        from trimesh import Trimesh

        if not isinstance(self.whole_mesh, Trimesh):
            raise TypeError("invalid_prepared_mesh")
        if not isinstance(self.scene, ExpandedScene):
            raise TypeError("invalid_prepared_scene")
        if isinstance(self.geometry, SampledGeometry):
            if (
                self.scene.resources
                or self.scene.instances
                or self.whole_resource_id is not None
                or self.brep is not None
            ):
                raise ValueError("invalid_sampled_geometry_resource_claim")
        elif isinstance(self.geometry, CompleteGeometry):
            resources = self.scene.resources
            instances = self.scene.instances
            if not resources or not instances:
                raise ValueError("invalid_complete_geometry_resources")
            identifiers = {resource.resource_id for resource in resources}
            if len(identifiers) != len(resources) or any(
                instance.resource_id not in identifiers for instance in instances
            ):
                raise ValueError("invalid_complete_geometry_resource_identity")
            if self.whole_resource_id is not None and (
                self.whole_resource_id not in identifiers
                or len(resources) != 1
                or len(instances) != 1
                or not np.array_equal(instances[0].transform, np.eye(4))
            ):
                raise ValueError("invalid_whole_resource_identity")
        else:
            raise TypeError("invalid_prepared_geometry")

    @property
    def complete(self) -> bool:
        """Prepared-only bridge for verify_paths/_component/embedding consumers.

        These readers migrate to geometry variants during their owner extraction;
        source scan and preview completeness never use this property.
        """
        return isinstance(self.geometry, CompleteGeometry)

    @property
    def failure_code(self) -> FingerprintFailureCode | None:
        return (
            self.geometry.reason if isinstance(self.geometry, SampledGeometry) else None
        )


def prepare_loaded_mesh(mesh: Trimesh, *, file_type: str) -> PreparedMesh:
    import numpy as np

    resources = split_components(np.asarray(mesh.vertices), np.asarray(mesh.faces))
    scene = ExpandedScene(
        resources,
        tuple(Instance(resource.resource_id, np.eye(4)) for resource in resources),
    )
    return PreparedMesh(
        mesh,
        scene,
        geometry=CompleteGeometry(),
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
            geometry=CompleteGeometry(),
            whole_resource_id=(
                scene.resources[0].resource_id if same_resource else None
            ),
        )
    except GeometryError:
        raise
    except (OSError, ValueError, KeyError, OverflowError) as exc:
        raise GeometryError("invalid_3mf") from exc
