"""Small synthetic geometry with known topology and source transforms."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from tests.factories.content import zip_bytes

CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
CONTENT_TYPES = (
    b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    b'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    b'<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
    b'<Default Extension="png" ContentType="image/png"/>'
    b"</Types>"
)


def tetrahedron():
    import numpy as np
    import trimesh

    return trimesh.Trimesh(
        vertices=np.array([[0.0, 0, 0], [10, 0, 0], [1, 20, 0], [2, 3, 30]]),
        faces=np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]]),
        process=False,
    )


def three_mf(
    *,
    meshes: dict[int, object] | None = None,
    assemblies: dict[int, list[tuple[int, str | None]]] | None = None,
    build: tuple[tuple[int, str | None], ...] = ((1, None),),
    unit: str = "millimeter",
    extras: dict[str, bytes] | None = None,
    external_paths: dict[int, str] | None = None,
    model_part: str = "3D/3dmodel.model",
    relationship_target: str | None = None,
    opc: bool = True,
) -> bytes:
    """A 3MF package; ``opc=False`` leaves out the OPC entries every producer writes.

    Without ``[Content_Types].xml`` and ``_rels/.rels`` only the XML reader reads
    the package (it falls back to the conventional root part); lib3mf refuses it.
    """
    root = ET.Element("model", xmlns=CORE_NS, unit=unit)
    resources = ET.SubElement(root, "resources")
    for key, mesh in (meshes if meshes is not None else {1: tetrahedron()}).items():
        obj = ET.SubElement(resources, "object", id=str(key), type="model")
        element = ET.SubElement(obj, "mesh")
        vertices = ET.SubElement(element, "vertices")
        for point in mesh.vertices:
            ET.SubElement(
                vertices,
                "vertex",
                **dict(zip(("x", "y", "z"), map(str, point), strict=True)),
            )
        triangles = ET.SubElement(element, "triangles")
        for triangle in mesh.faces:
            ET.SubElement(
                triangles,
                "triangle",
                **dict(zip(("v1", "v2", "v3"), map(str, triangle), strict=True)),
            )
    for key, children in (assemblies or {}).items():
        obj = ET.SubElement(resources, "object", id=str(key), type="model")
        components = ET.SubElement(obj, "components")
        for child, transform in children:
            attributes = {"objectid": str(child)}
            if transform is not None:
                attributes["transform"] = transform
            if external_paths and child in external_paths:
                attributes[
                    "{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}path"
                ] = external_paths[child]
            ET.SubElement(components, "component", **attributes)
    items = ET.SubElement(root, "build")
    for key, transform in build:
        attributes = {"objectid": str(key)}
        if transform is not None:
            attributes["transform"] = transform
        ET.SubElement(items, "item", **attributes)
    entries = {model_part: ET.tostring(root), **(extras or {})}
    if opc:
        entries["[Content_Types].xml"] = CONTENT_TYPES
        if relationship_target is None:
            relationship_target = f"/{model_part}"
    if relationship_target is not None:
        relationships = ET.Element(
            "Relationships",
            xmlns="http://schemas.openxmlformats.org/package/2006/relationships",
        )
        ET.SubElement(
            relationships,
            "Relationship",
            Id="model",
            Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel",
            Target=relationship_target,
        )
        entries["_rels/.rels"] = ET.tostring(relationships)
    return zip_bytes(entries)


def expanding_three_mf(depth: int = 20) -> bytes:
    """Four base faces repeated exponentially without a large source archive."""
    if depth < 1:
        raise ValueError("depth must be positive")
    return three_mf(
        assemblies={
            index: [(index - 1, None), (index - 1, None)]
            for index in range(2, depth + 2)
        },
        build=((depth + 1, None),),
    )


# A unit cube as 8 corners and 6 outward-wound quads, shared by the exchange
# format builders below.
_CUBE_CORNERS = (
    (0, 0, 0),
    (1, 0, 0),
    (1, 1, 0),
    (0, 1, 0),
    (0, 0, 1),
    (1, 0, 1),
    (1, 1, 1),
    (0, 1, 1),
)
_CUBE_QUADS = (
    (0, 3, 2, 1),
    (4, 5, 6, 7),
    (0, 1, 5, 4),
    (1, 2, 6, 5),
    (2, 3, 7, 6),
    (3, 0, 4, 7),
)
_FBX_Y_UP = {
    "UpAxis": 1,
    "UpAxisSign": 1,
    "FrontAxis": 2,
    "FrontAxisSign": 1,
    "CoordAxis": 0,
    "CoordAxisSign": 1,
}


def fbx_cube_ascii(
    *,
    unit_scale: float = 1.0,
    axes: dict[str, int] | None = None,
    translation: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> bytes:
    """An ASCII FBX 7.4 unit cube in *unit_scale* centimetres per unit."""
    settings = {**_FBX_Y_UP, **(axes or {}), "UnitScaleFactor": unit_scale}
    properties = "\n".join(
        f'\t\tP: "{name}", "{"double" if name == "UnitScaleFactor" else "int"}", '
        f'"Number", "",{value}'
        for name, value in settings.items()
    )
    corners = ",".join(str(value) for corner in _CUBE_CORNERS for value in corner)
    # FBX closes each polygon by storing its last index as -(index + 1).
    polygons = ",".join(f"{a},{b},{c},{-(d + 1)}" for a, b, c, d in _CUBE_QUADS)
    x, y, z = translation
    return f"""; FBX 7.4.0 project file
FBXHeaderExtension:  {{
\tFBXHeaderVersion: 1003
\tFBXVersion: 7400
}}
GlobalSettings:  {{
\tVersion: 1000
\tProperties70:  {{
{properties}
\t}}
}}
Objects:  {{
\tGeometry: 1000, "Geometry::cube", "Mesh" {{
\t\tVertices: *24 {{
\t\t\ta: {corners}
\t\t}}
\t\tPolygonVertexIndex: *24 {{
\t\t\ta: {polygons}
\t\t}}
\t\tGeometryVersion: 124
\t}}
\tModel: 2000, "Model::cube", "Mesh" {{
\t\tVersion: 232
\t\tProperties70:  {{
\t\t\tP: "Lcl Translation", "Lcl Translation", "", "A",{x},{y},{z}
\t\t}}
\t}}
}}
Connections:  {{
\tC: "OO",2000,0
\tC: "OO",1000,2000
}}
""".encode()


def fbx_binary_settings(settings: dict[str, float], *, version: int = 7400) -> bytes:
    """A binary FBX holding only GlobalSettings/Properties70 and a later node."""
    import struct

    wide = version >= 7500
    head = struct.Struct("<QQQB" if wide else "<IIIB")
    null = b"\x00" * head.size

    def node(
        name: str, properties: bytes, count: int, children: list, start: int
    ) -> bytes:
        body_start = start + head.size + len(name) + len(properties)
        payload = b""
        for child in children:
            payload += child(body_start + len(payload))
        if children:
            payload += null
        end = body_start + len(payload)
        return (
            head.pack(end, count, len(properties), len(name))
            + name.encode()
            + properties
            + payload
        )

    def string(value: str) -> bytes:
        return b"S" + struct.pack("<I", len(value)) + value.encode()

    def p(name: str, value: float):
        typed = (
            b"D" + struct.pack("<d", value)
            if name == "UnitScaleFactor"
            else b"I" + struct.pack("<i", int(value))
        )
        properties = string(name) + string("t") + string("t") + string("") + typed
        return lambda start: node("P", properties, 5, [], start)

    entries = [p(name, value) for name, value in settings.items()]

    def properties70(start: int) -> bytes:
        return node("Properties70", b"", 0, entries, start)

    def version_node(start: int) -> bytes:
        return node("Version", b"I" + struct.pack("<i", 1000), 1, [], start)

    out = b"Kaydara FBX Binary  \x00\x1a\x00" + struct.pack("<I", version)
    out += node("FBXHeaderExtension", b"", 0, [version_node], len(out))
    out += node("GlobalSettings", b"", 0, [version_node, properties70], len(out))
    out += node("Objects", b"", 0, [], len(out))
    return out + null


def rhino_cube(*, unit: str = "Millimeters", block_offsets: tuple = ()) -> bytes:
    """A Rhino 3DM unit cube mesh, optionally also placed through a block."""
    import os
    import tempfile

    import rhino3dm

    mesh = rhino3dm.Mesh()
    for corner in _CUBE_CORNERS:
        mesh.Vertices.Add(*map(float, corner))
    for a, b, c, d in _CUBE_QUADS:
        mesh.Faces.AddFace(a, b, c, d)
    model: Any = rhino3dm.File3dm()
    model.Settings.ModelUnitSystem = getattr(rhino3dm.UnitSystem, unit)
    if block_offsets:
        index = model.InstanceDefinitions.Add(
            "cube",
            "",
            "",
            "",
            rhino3dm.Point3d(0, 0, 0),
            (mesh,),
            (rhino3dm.ObjectAttributes(),),
        )
        definition = model.InstanceDefinitions.FindIndex(index)
        for offset in block_offsets:
            placement = rhino3dm.Transform.Translation(*map(float, offset))
            model.Objects.AddInstanceObject(
                rhino3dm.InstanceReference(definition.Id, placement)
            )
    else:
        model.Objects.AddMesh(mesh)
    handle, name = tempfile.mkstemp(suffix=".3dm")
    os.close(handle)
    try:
        model.Write(name, 8)
        with open(name, "rb") as written:
            return written.read()
    finally:
        os.unlink(name)


def gltf_embedded(mesh, *, external_buffer: str | None = None) -> bytes:
    """A .gltf whose buffers are data URIs, or one naming *external_buffer*."""
    import base64
    import json

    files = mesh.export(file_type="gltf")
    document = json.loads(files["model.gltf"])
    for buffer in document["buffers"]:
        payload = files[buffer["uri"]]
        buffer["uri"] = (
            external_buffer
            if external_buffer is not None
            else "data:application/octet-stream;base64,"
            + base64.b64encode(payload).decode()
        )
    return json.dumps(document).encode()
