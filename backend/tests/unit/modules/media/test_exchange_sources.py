"""Rhino and FBX sources land in the print frame: millimetres with +Z up.

Each format names its own unit and axes. A reader that ignored them would
measure an FBX from Blender 1,000 times too small and preview a Maya part lying
on its back, so every row here asserts the frame, not merely that a mesh loaded.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.modules.media import exchange_sources, mesh_loading
from tests.factories.geometry import fbx_binary_settings, fbx_cube_ascii, rhino_cube


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


class TestRhino:
    @pytest.mark.parametrize(
        ("unit", "edge"),
        [
            ("Millimeters", 1.0),
            ("Centimeters", 10.0),
            ("Meters", 1000.0),
            ("Inches", 25.4),
        ],
    )
    def test_scales_model_units_to_millimetres(self, tmp_path, unit, edge) -> None:
        path = _write(tmp_path, "cube.3dm", rhino_cube(unit=unit))

        mesh = mesh_loading.load_mesh(path)

        assert mesh is not None
        np.testing.assert_allclose(mesh.extents, [edge] * 3)

    def test_takes_a_unitless_model_as_millimetres(self, tmp_path) -> None:
        path = _write(tmp_path, "cube.3dm", rhino_cube(unit="None"))

        mesh = mesh_loading.load_mesh(path)

        assert mesh is not None
        np.testing.assert_allclose(mesh.extents, [1.0] * 3)

    def test_splits_quads_into_outward_triangles(self, tmp_path) -> None:
        path = _write(tmp_path, "cube.3dm", rhino_cube())

        mesh = mesh_loading.load_mesh(path)

        assert mesh is not None
        assert len(mesh.faces) == 12
        assert mesh.volume == pytest.approx(1.0)

    def test_places_every_block_reference(self, tmp_path) -> None:
        path = _write(
            tmp_path,
            "blocks.3dm",
            rhino_cube(unit="Centimeters", block_offsets=((0, 0, 0), (5, 0, 0))),
        )

        mesh = mesh_loading.load_mesh(path)

        assert mesh is not None
        assert len(mesh.faces) == 24
        np.testing.assert_allclose(mesh.bounds, [[0, 0, 0], [60, 10, 10]])

    def test_declines_an_astronomical_unit(self, tmp_path) -> None:
        path = _write(tmp_path, "far.3dm", rhino_cube(unit="Parsecs"))

        assert mesh_loading.load_mesh(path) is None

    def test_declines_a_model_without_meshes(self, tmp_path) -> None:
        import rhino3dm

        model = rhino3dm.File3dm()
        model.Objects.AddPoint(rhino3dm.Point3d(1, 2, 3))
        path = tmp_path / "point.3dm"
        model.Write(str(path), 8)

        assert mesh_loading.load_mesh(path) is None

    def test_skips_surfaces_saved_without_render_meshes(self, tmp_path) -> None:
        import rhino3dm

        model = rhino3dm.File3dm()
        box = rhino3dm.Box(
            rhino3dm.BoundingBox(rhino3dm.Point3d(0, 0, 0), rhino3dm.Point3d(1, 1, 1))
        )
        model.Objects.AddBrep(rhino3dm.Brep.CreateFromBox(box))
        circle = rhino3dm.Circle(rhino3dm.Point3d(0, 0, 0), 5).ToNurbsCurve()
        model.Objects.AddExtrusion(rhino3dm.Extrusion.Create(circle, 10, True))
        path = tmp_path / "surfaces.3dm"
        model.Write(str(path), 8)

        assert mesh_loading.load_mesh(path) is None

    def test_skips_a_mesh_without_faces(self, tmp_path) -> None:
        import rhino3dm

        model = rhino3dm.File3dm()
        empty = rhino3dm.Mesh()
        empty.Vertices.Add(0.0, 0.0, 0.0)
        model.Objects.AddMesh(empty)
        path = tmp_path / "empty.3dm"
        model.Write(str(path), 8)

        assert mesh_loading.load_mesh(path) is None

    def test_declines_more_block_placements_than_the_limit(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setattr(exchange_sources, "_RHINO_MAX_PLACEMENTS", 2)
        path = _write(
            tmp_path, "many.3dm", rhino_cube(block_offsets=((0, 0, 0), (5, 0, 0)))
        )

        assert mesh_loading.load_mesh(path) is None

    def test_declines_bytes_that_are_not_a_3dm(self, tmp_path) -> None:
        path = _write(tmp_path, "renamed.3dm", b"solid not rhino")

        assert mesh_loading.load_mesh(path) is None


class TestFBXFrame:
    def test_reads_centimetres_with_y_up_by_default(self) -> None:
        frame = exchange_sources.fbx_print_frame(fbx_cube_ascii())

        np.testing.assert_allclose(
            frame[:3, :3], [[10, 0, 0], [0, 0, -10], [0, 10, 0]], atol=1e-12
        )

    @pytest.mark.parametrize("version", [7400, 7500], ids=["32-bit", "64-bit"])
    def test_reads_binary_global_settings(self, version) -> None:
        data = fbx_binary_settings(
            {
                "UnitScaleFactor": 100.0,
                "UpAxis": 2,
                "FrontAxis": 1,
                "FrontAxisSign": -1,
            },
            version=version,
        )

        frame = exchange_sources.fbx_print_frame(data)

        np.testing.assert_allclose(frame[:3, :3], np.eye(3) * 1000, atol=1e-12)

    def test_mirrors_a_left_handed_scene(self) -> None:
        data = fbx_cube_ascii(axes={"CoordAxisSign": -1})

        frame = exchange_sources.fbx_print_frame(data)

        assert np.linalg.det(frame[:3, :3]) < 0

    def test_ignores_other_ascii_settings(self) -> None:
        frame = exchange_sources.fbx_print_frame(
            fbx_cube_ascii(axes={"OriginalUpAxis": 2})
        )

        np.testing.assert_allclose(
            frame[:3, :3], [[10, 0, 0], [0, 0, -10], [0, 10, 0]], atol=1e-12
        )

    def test_ignores_other_binary_settings(self) -> None:
        data = fbx_binary_settings({"OriginalUpAxis": 2.0, "UnitScaleFactor": 100.0})

        frame = exchange_sources.fbx_print_frame(data)

        assert frame[0, 0] == pytest.approx(1000.0)

    def test_refuses_an_axis_named_twice(self) -> None:
        with pytest.raises(exchange_sources.FBXSettingsError):
            exchange_sources.fbx_print_frame(fbx_cube_ascii(axes={"UpAxis": 0}))

    def test_refuses_a_zero_unit(self) -> None:
        with pytest.raises(exchange_sources.FBXSettingsError):
            exchange_sources.fbx_print_frame(fbx_cube_ascii(unit_scale=0.0))

    def test_refuses_a_binary_record_past_its_parent(self) -> None:
        data = bytearray(fbx_binary_settings({"UnitScaleFactor": 1.0}))
        # The first record's end offset now points beyond the file.
        data[27:31] = (len(data) + 100).to_bytes(4, "little")

        with pytest.raises(exchange_sources.FBXSettingsError):
            exchange_sources.fbx_print_frame(bytes(data))


class TestFBXMesh:
    def test_converts_a_metre_scene_to_millimetres(self, tmp_path) -> None:
        path = _write(tmp_path, "cube.fbx", fbx_cube_ascii(unit_scale=100.0))

        mesh = mesh_loading.load_mesh(path)

        assert mesh is not None
        np.testing.assert_allclose(mesh.extents, [1000.0] * 3)

    def test_turns_the_up_axis_onto_z(self, tmp_path) -> None:
        path = _write(tmp_path, "raised.fbx", fbx_cube_ascii(translation=(0, 2, 0)))

        mesh = mesh_loading.load_mesh(path)

        assert mesh is not None
        np.testing.assert_allclose(mesh.bounds[:, 2], [20.0, 30.0])

    def test_keeps_faces_outward(self, tmp_path) -> None:
        path = _write(tmp_path, "cube.fbx", fbx_cube_ascii())

        mesh = mesh_loading.load_mesh(path)

        assert mesh is not None
        assert mesh.volume == pytest.approx(1000.0)

    def test_declines_a_scene_with_an_impossible_frame(self, tmp_path) -> None:
        path = _write(tmp_path, "bad.fbx", fbx_cube_ascii(axes={"FrontAxis": 1}))

        assert mesh_loading.load_mesh(path) is None

    def test_declines_a_scene_without_geometry(self, tmp_path) -> None:
        text = fbx_cube_ascii().decode()
        objects = text.index("Objects:")
        connections = text.index("Connections:")
        empty = text[:objects] + "Objects:  {\n}\n" + text[connections:]
        path = _write(tmp_path, "empty.fbx", empty.encode())

        assert mesh_loading.load_mesh(path) is None

    def test_declines_bytes_that_are_not_an_fbx(self, tmp_path) -> None:
        path = _write(tmp_path, "renamed.fbx", b"\x00\x01not an fbx")

        assert mesh_loading.load_mesh(path) is None
