"""Rhino 3DM and FBX sources as one placed mesh in millimetres with +Z up.

Both formats carry their own unit and axis conventions; each reader converts
them here so measurement, previews and fingerprints see the same frame as STL.
Parsers stay lazy imports, and a source that holds no readable mesh returns
None like every other format.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger

if TYPE_CHECKING:
    import numpy as np
    from trimesh import Trimesh

logger = get_logger(__name__)

# Millimetres per model unit. A file without units is taken as millimetres, the
# unit every slicer assumes; a unit outside physical lengths has no mesh frame.
_RHINO_MILLIMETRES = {
    "None": 1.0,
    "Unset": 1.0,
    "Microns": 0.001,
    "Millimeters": 1.0,
    "Centimeters": 10.0,
    "Decimeters": 100.0,
    "Meters": 1000.0,
    "Inches": 25.4,
    "Feet": 304.8,
    "Mils": 0.0254,
    "Microinches": 0.0000254,
    "Yards": 914.4,
}
# Block definitions may nest; a reference beyond this depth or count is a
# hostile or broken file, never a printable part.
_RHINO_MAX_DEPTH = 8
_RHINO_MAX_PLACEMENTS = 100_000


def load_3dm_mesh(path: Path) -> Trimesh | None:
    """Every visible Rhino mesh, render mesh and block placement, in millimetres.

    NURBS surfaces are read through the render meshes Rhino stores with them; a
    file saved without render meshes has nothing to measure or preview.
    """
    import numpy as np
    import rhino3dm
    import trimesh

    # The published rhino3dm stubs omit most table and geometry members.
    model: Any = rhino3dm.File3dm.Read(str(path))
    if model is None:
        return None
    unit = model.Settings.ModelUnitSystem.name
    if unit not in _RHINO_MILLIMETRES:
        logger.warning("mesh_processing: %s uses unsupported unit %s", path.name, unit)
        return None
    vertices: list[np.ndarray] = []
    faces: list[np.ndarray] = []
    offset = 0
    placements = 0

    def add(geometry: Any, transform: np.ndarray, depth: int) -> None:
        nonlocal offset, placements
        placements += 1
        if depth > _RHINO_MAX_DEPTH or placements > _RHINO_MAX_PLACEMENTS:
            raise ValueError("rhino_block_limit")
        if isinstance(geometry, rhino3dm.InstanceReference):
            reference: Any = geometry
            definition = model.InstanceDefinitions.FindId(reference.ParentIdefId)
            if definition is None:
                return
            placed = transform @ _rhino_matrix(reference.Xform)
            for member_id in definition.GetObjectIds():
                member = model.Objects.FindId(member_id)
                if member is not None:
                    add(member.Geometry, placed, depth + 1)
            return
        for mesh in _rhino_meshes(rhino3dm, geometry):
            points, triangles = _rhino_arrays(np, mesh)
            if not len(triangles):
                continue
            placed = points @ transform[:3, :3].T + transform[:3, 3]
            vertices.append(placed)
            faces.append(triangles + offset)
            offset += len(points)

    scale = np.diag([_RHINO_MILLIMETRES[unit]] * 3 + [1.0])
    try:
        for item in model.Objects:
            attributes = item.Attributes
            if attributes.IsInstanceDefinitionObject or not attributes.Visible:
                continue
            add(item.Geometry, scale, 0)
    except ValueError:
        logger.warning("mesh_processing: %s exceeds the block limit", path.name)
        return None
    if not faces:
        return None
    return trimesh.Trimesh(
        vertices=np.concatenate(vertices), faces=np.concatenate(faces), process=False
    )


def _rhino_meshes(rhino3dm: Any, geometry: Any) -> list[Any]:
    if isinstance(geometry, rhino3dm.Mesh):
        return [geometry]
    if isinstance(geometry, rhino3dm.Extrusion):
        mesh = geometry.GetMesh(rhino3dm.MeshType.Any)
        return [] if mesh is None else [mesh]
    if isinstance(geometry, rhino3dm.Brep):
        meshes = [face.GetMesh(rhino3dm.MeshType.Any) for face in geometry.Faces]
        return [mesh for mesh in meshes if mesh is not None]
    return []


def _rhino_arrays(np: Any, mesh: Any) -> tuple[np.ndarray, np.ndarray]:
    points = np.asarray(
        [(point.X, point.Y, point.Z) for point in mesh.Vertices.ToPoint3dArray()],
        dtype=np.float64,
    ).reshape(-1, 3)
    quads = np.asarray(
        [tuple(mesh.Faces[index]) for index in range(len(mesh.Faces))],
        dtype=np.int64,
    ).reshape(-1, 4)
    # Rhino stores a triangle as a quad whose last two corners repeat.
    split = quads[quads[:, 2] != quads[:, 3]]
    return points, np.concatenate([quads[:, :3], split[:, [0, 2, 3]]])


def _rhino_matrix(transform: Any) -> np.ndarray:
    import numpy as np

    return np.asarray(
        [
            [getattr(transform, f"M{row}{column}") for column in range(4)]
            for row in range(4)
        ],
        dtype=np.float64,
    )


_FBX_BINARY_MAGIC = b"Kaydara FBX Binary  \x00\x1a\x00"
_FBX_SETTINGS = frozenset(
    {
        "UnitScaleFactor",
        "UpAxis",
        "UpAxisSign",
        "FrontAxis",
        "FrontAxisSign",
        "CoordAxis",
        "CoordAxisSign",
    }
)
_FBX_SCALARS = {
    b"Y": "<h",
    b"C": "<?",
    b"I": "<i",
    b"F": "<f",
    b"D": "<d",
    b"L": "<q",
}
_FBX_ASCII_SETTING = re.compile(
    rb'P:\s*"(\w+)"\s*,\s*"[^"]*"\s*,\s*"[^"]*"\s*,\s*"[^"]*"\s*,\s*([-+0-9.eE]+)'
)
# The FBX defaults: centimetres, +Y up, +Z towards the viewer, +X right.
_FBX_DEFAULTS = {
    "UnitScaleFactor": 1.0,
    "UpAxis": 1,
    "UpAxisSign": 1,
    "FrontAxis": 2,
    "FrontAxisSign": 1,
    "CoordAxis": 0,
    "CoordAxisSign": 1,
}


class FBXSettingsError(ValueError):
    """The FBX GlobalSettings cannot describe a physical frame."""


def fbx_print_frame(data: bytes) -> np.ndarray:
    """The 4x4 transform from an FBX scene's frame to millimetres with +Z up.

    FBX states its unit as centimetres per unit and names which file axis is
    right, up and towards the viewer. On the print bed those are +X, +Z and -Y.
    """
    import numpy as np

    found = (
        _fbx_binary_settings(data)
        if data.startswith(_FBX_BINARY_MAGIC)
        else _fbx_ascii_settings(data)
    )
    settings = {**_FBX_DEFAULTS, **found}
    roles = (
        (int(settings["CoordAxis"]), int(settings["CoordAxisSign"]), (1, 0, 0)),
        (int(settings["UpAxis"]), int(settings["UpAxisSign"]), (0, 0, 1)),
        (int(settings["FrontAxis"]), int(settings["FrontAxisSign"]), (0, -1, 0)),
    )
    if sorted(axis for axis, _, _ in roles) != [0, 1, 2] or any(
        sign not in (-1, 1) for _, sign, _ in roles
    ):
        raise FBXSettingsError("fbx_axes")
    scale = float(settings["UnitScaleFactor"]) * 10.0
    if not np.isfinite(scale) or scale <= 0:
        raise FBXSettingsError("fbx_unit")
    frame = np.eye(4)
    frame[:3, :3] = 0.0
    for axis, sign, target in roles:
        frame[:3, axis] = np.asarray(target, dtype=np.float64) * sign * scale
    return frame


def load_fbx_mesh(path: Path) -> Trimesh | None:
    """Every FBX mesh with its node placements baked, in millimetres with +Z up."""
    import assimp_py
    import numpy as np
    import trimesh

    try:
        frame = fbx_print_frame(path.read_bytes())
    except FBXSettingsError, struct.error, IndexError, UnicodeDecodeError:
        logger.warning("mesh_processing: %s has no usable FBX frame", path.name)
        return None
    scene = assimp_py.import_file(
        str(path),
        assimp_py.Process_Triangulate
        | assimp_py.Process_PreTransformVertices
        | assimp_py.Process_SortByPType,
    )
    vertices: list[np.ndarray] = []
    faces: list[np.ndarray] = []
    offset = 0
    for mesh in scene.meshes:
        indices = np.asarray(mesh.indices, dtype=np.int64)
        if not len(indices) or len(indices) % 3:
            # Points and lines sort into their own meshes; they own no faces.
            continue
        points = np.asarray(mesh.vertices, dtype=np.float64).reshape(-1, 3)
        vertices.append(points)
        faces.append(indices.reshape(-1, 3) + offset)
        offset += len(points)
    if not faces:
        return None
    loaded = trimesh.Trimesh(
        vertices=np.concatenate(vertices), faces=np.concatenate(faces), process=False
    )
    loaded.apply_transform(frame)
    return loaded


def _fbx_ascii_settings(data: bytes) -> dict[str, float]:
    found: dict[str, float] = {}
    for key, value in _FBX_ASCII_SETTING.findall(data):
        name = key.decode("ascii")
        if name in _FBX_SETTINGS:
            found[name] = float(value)
    return found


def _fbx_binary_settings(data: bytes) -> dict[str, float]:
    """Read only GlobalSettings/Properties70 from a binary FBX node tree."""
    version = struct.unpack_from("<I", data, 23)[0]
    header = struct.Struct("<QQQB" if version >= 7500 else "<IIIB")
    found: dict[str, float] = {}
    position = 27
    # Top-level records are skipped whole by their end offset; only the
    # GlobalSettings subtree is decoded.
    stack: list[tuple[int, tuple[str, ...]]] = [(len(data), ())]
    while stack:
        end, path = stack[-1]
        if position >= end:
            stack.pop()
            continue
        record_end, count, length, name_length = header.unpack_from(data, position)
        if record_end == 0:
            # A null record closes the current list of children.
            stack.pop()
            position = end if stack else len(data)
            continue
        if record_end <= position or record_end > end:
            raise FBXSettingsError("fbx_record")
        name_start = position + header.size
        name = data[name_start : name_start + name_length].decode("ascii")
        properties = name_start + name_length
        if path == ("GlobalSettings", "Properties70") and name == "P":
            values = _fbx_properties(data, properties, count)
            key = values[0]
            if isinstance(key, bytes) and key.decode("ascii") in _FBX_SETTINGS:
                found[key.decode("ascii")] = float(values[-1])
        elif (path, name) in (
            ((), "GlobalSettings"),
            (("GlobalSettings",), "Properties70"),
        ):
            stack.append((record_end, (*path, name)))
            position = properties + length
            continue
        position = record_end
    return found


def _fbx_properties(data: bytes, position: int, count: int) -> list[Any]:
    values: list[Any] = []
    for _ in range(count):
        code = data[position : position + 1]
        position += 1
        if code in _FBX_SCALARS:
            layout = _FBX_SCALARS[code]
            values.append(struct.unpack_from(layout, data, position)[0])
            position += struct.calcsize(layout)
        elif code in (b"S", b"R"):
            (length,) = struct.unpack_from("<I", data, position)
            values.append(data[position + 4 : position + 4 + length])
            position += 4 + length
        else:
            raise FBXSettingsError("fbx_property")
    return values
