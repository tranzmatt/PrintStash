"""Owned relative render positions with repeatable, bounded triangle chunks.

Scene preparation retains unique source geometry and affine placements. The
renderer still needs O(expanded referenced vertices) float32 positions for global
normal welding and projection; it never builds a placed float64 source mesh or
an entire placed triangle array. No parser or Trimesh dependency belongs here.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from .similarity.components import ExpandedScene, expand_scene
from .similarity.fingerprint import GeometryError

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    FloatArray = NDArray[np.float64]
    RenderPositions = NDArray[np.float32]
    IntArray = NDArray[np.int64]

_POINT_CHUNK_SIZE = 64_000


class RenderableMesh(Protocol):
    """Source arrays required by the existing structural mesh entry point."""

    @property
    def vertices(self) -> FloatArray: ...

    @property
    def faces(self) -> IntArray | None: ...


@dataclass(frozen=True)
class MeshRenderInput:
    mesh: RenderableMesh | None


@dataclass(frozen=True)
class SceneRenderInput:
    scene: ExpandedScene


@dataclass(frozen=True)
class PreparedRenderGeometry:
    vertices: RenderPositions
    face_count: int
    face_chunks: Callable[[int], Iterator[IntArray]]


def prepare_mesh(mesh: RenderableMesh | None) -> PreparedRenderGeometry | None:
    """Preserve the structural mesh API while framing referenced vertices only."""
    import numpy as np

    if (
        mesh is None
        or len(mesh.vertices) == 0
        or mesh.faces is None
        or len(mesh.faces) == 0
    ):
        return None
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces)
    if faces.ndim != 2 or faces.shape[1] != 3 or faces.dtype.kind not in "iu":
        raise ValueError("invalid triangle indices")
    if faces.min() < 0 or faces.max() >= len(vertices):
        raise ValueError("triangle index outside vertex array")
    faces = faces.astype(np.int64, copy=False)
    referenced = np.zeros(len(vertices), dtype=bool)
    referenced[faces] = True
    remap = None
    if not referenced.all():
        remap = np.cumsum(referenced, dtype=np.int64) - 1
        vertices = vertices[referenced]
    center = (vertices.max(axis=0) + vertices.min(axis=0)) * 0.5
    relative = (vertices - center).astype(np.float32)

    def chunks(size: int) -> Iterator[IntArray]:
        _validate_chunk(size)
        for start in range(0, len(faces), size):
            selected = faces[start : start + size]
            yield remap[selected] if remap is not None else selected

    return PreparedRenderGeometry(relative, len(faces), chunks)


def prepare_scene(scene: ExpandedScene) -> PreparedRenderGeometry:
    """Admit first, center in float64, then prepare render positions only."""
    import numpy as np

    scene = expand_scene(scene.resources, scene.instances)
    by_id = {resource.resource_id: resource for resource in scene.resources}
    points: dict[str, FloatArray] = {}
    remaps: dict[str, IntArray] = {}
    for resource in scene.resources:
        referenced = np.zeros(len(resource.vertices), dtype=bool)
        referenced[resource.faces] = True
        points[resource.resource_id] = resource.vertices[referenced]
        # Only referenced indices can appear in admitted faces. Unused entries
        # in this source-to-render index map are never read.
        remaps[resource.resource_id] = np.cumsum(referenced, dtype=np.int64) - 1

    minimum = np.full(3, np.inf)
    maximum = np.full(3, -np.inf)
    vertex_count = face_count = 0
    try:
        with np.errstate(over="raise", invalid="raise"):
            for instance in scene.instances:
                source = points[instance.resource_id]
                vertex_count += len(source)
                face_count += len(by_id[instance.resource_id].faces)
                for start in range(0, len(source), _POINT_CHUNK_SIZE):
                    placed = (
                        source[start : start + _POINT_CHUNK_SIZE]
                        @ instance.transform[:3, :3].T
                        + instance.transform[:3, 3]
                    )
                    minimum = np.minimum(minimum, placed.min(axis=0))
                    maximum = np.maximum(maximum, placed.max(axis=0))
            center = (minimum + maximum) * 0.5
            vertices = np.empty((vertex_count, 3), dtype=np.float32)
            layout: list[tuple[IntArray, IntArray, int]] = []
            offset = 0
            for instance in scene.instances:
                source = points[instance.resource_id]
                transform = instance.transform
                for start in range(0, len(source), _POINT_CHUNK_SIZE):
                    placed = (
                        source[start : start + _POINT_CHUNK_SIZE] @ transform[:3, :3].T
                        + transform[:3, 3]
                    )
                    vertices[offset + start : offset + start + len(placed)] = (
                        placed - center
                    ).astype(np.float32)
                resource = by_id[instance.resource_id]
                winding = (
                    resource.faces[:, ::-1]
                    if np.linalg.slogdet(transform[:3, :3])[0] < 0
                    else resource.faces
                )
                layout.append((winding, remaps[instance.resource_id], offset))
                offset += len(source)
            if not np.isfinite(vertices).all():
                raise GeometryError("numeric_range")
    except (FloatingPointError, np.linalg.LinAlgError) as exc:
        raise GeometryError("numeric_range") from exc

    def chunks(size: int) -> Iterator[IntArray]:
        _validate_chunk(size)
        placement = source_offset = emitted = 0
        while emitted < face_count:
            count = min(size, face_count - emitted)
            output = np.empty((count, 3), dtype=np.int64)
            target = 0
            while target < count:
                faces, remap, vertex_offset = layout[placement]
                take = min(count - target, len(faces) - source_offset)
                np.add(
                    remap[faces[source_offset : source_offset + take]],
                    vertex_offset,
                    out=output[target : target + take],
                )
                target += take
                source_offset += take
                if source_offset == len(faces):
                    placement += 1
                    source_offset = 0
            emitted += count
            yield output

    return PreparedRenderGeometry(vertices, face_count, chunks)


def _validate_chunk(size: int) -> None:
    if type(size) is not int or size < 1:
        raise ValueError("invalid_render_chunk")
