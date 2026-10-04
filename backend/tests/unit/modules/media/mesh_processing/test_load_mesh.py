"""Getting a mesh object out of a file, in whatever shape the file arrives.

`_load_mesh` is the one place `trimesh` is called, and it exists to absorb the
variety of what that call returns. A `.glb` or `.obj` usually loads as a
*Scene* rather than a mesh — one geometry, or several, or none that are meshes at
all — and every caller above this function wants a single mesh or nothing. A
`None` here means "no thumbnail, no geometry", which is a fine outcome; an
unhandled type means a traceback in a background scan.

3MF is routed around trimesh entirely: trimesh expands repeated build/component
placements while it loads, so 3MF goes through the bounded resource loader (#259).

STEP is the exception and runs out-of-process. Tessellating a CAD file is
unbounded work on untrusted input: a modest STEP can expand into hundreds of
millions of triangles, and there is no way to know before trying. So the child
is watched and killed when its RSS passes the budget — which is a real kill of a
real process, not a raised exception, because an in-process tessellation that
went that far would already have taken the parent with it.

`_geometry_from_mesh` reads dimensions off a loaded mesh. Volume is the sharp
edge: `trimesh` raises for a non-watertight mesh, and most models people
download are not watertight, so the failure is the common case and has to leave
the other measurements intact.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh
from printstash_core.mesh.measurements import (
    VolumeMeasured,
    VolumeNotCalculated,
    VolumeNotCalculatedCause,
    VolumeUnavailable,
    VolumeUnavailableCause,
)

from app.modules.media import mesh_processing
from tests.fixtures.mesh_analysis import analyze
from tests.paths import FIXTURES_DIR

from .._meshes import _real_binary_stl_cube


class TestLoadMesh:
    def test_load_mesh_returns_trimesh_for_real_stl(self, tmp_path: Path) -> None:
        p = tmp_path / "cube.stl"
        _real_binary_stl_cube(p)
        mesh = mesh_processing._load_mesh(p)
        assert mesh is not None
        assert len(mesh.faces) > 0

    def test_load_mesh_renders_real_step_fixture(self) -> None:
        path = FIXTURES_DIR / "cascadio_material.stp"

        mesh = mesh_processing._load_mesh(path)
        result = analyze(path)
        geometry, thumbnail = result.geometry, result.image

        assert mesh is not None
        assert len(mesh.faces) > 0
        assert geometry["triangle_count"] == len(mesh.faces)
        assert thumbnail is not None
        assert thumbnail.startswith(mesh_processing._PNG_MAGIC)

    def test_load_mesh_returns_none_for_unrecognised_extension(
        self, tmp_path: Path
    ) -> None:
        # trimesh cannot even pick a loader for an unknown extension, so this raises
        # inside trimesh.load_scene — exercising _load_mesh's broad except-and-log path.
        p = tmp_path / "garbage.foobar"
        p.write_bytes(b"this is not a mesh at all \x00\x01\x02")
        assert mesh_processing._load_mesh(p) is None

    def test_load_mesh_flattens_scene_with_multiple_geometries(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # `_load_mesh` keeps the scene rather than asking trimesh for a mesh, because
        # `dump()` is what bakes each graph path's transforms in. A real Scene is
        # stubbed here so the flattening runs over real trimesh geometry: reading
        # `scene.geometry` instead would return each source mesh once, untransformed.
        # Exporting and reloading the scene would flatten it before we saw it.

        scene = trimesh.Scene()
        scene.add_geometry(trimesh.creation.box(extents=[5, 5, 5]), node_name="a")
        scene.add_geometry(
            trimesh.creation.box(extents=[3, 3, 3]).apply_translation([10, 0, 0]),
            node_name="b",
        )
        p = tmp_path / "scene.3mf"
        scene.export(p, file_type="3mf")

        monkeypatch.setattr(trimesh, "load_scene", lambda *a, **k: scene)
        mesh = mesh_processing._load_mesh(p)
        assert mesh is not None
        # Concatenated geometry from both boxes.
        assert len(mesh.faces) == 24

    def test_load_mesh_scene_with_no_trimesh_geometry_returns_none(
        self, tmp_path: Path, monkeypatch
    ) -> None:

        empty_scene = trimesh.Scene()  # no geometry at all
        p = tmp_path / "empty.obj"
        p.write_bytes(b"placeholder")
        monkeypatch.setattr(trimesh, "load_scene", lambda *a, **k: empty_scene)
        assert mesh_processing._load_mesh(p) is None

    def test_load_mesh_declines_a_scene_it_cannot_flatten(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """`dump()` is where the transforms are applied, and it can throw.

        A malformed component graph — a 3MF referencing a component that is not
        in the file — raises inside trimesh rather than returning an empty scene.
        Letting it escape turns a bad upload into a 500 on the preview route, so
        it becomes the same honest `None` as any other unloadable mesh.
        """

        class UnflattenableScene(trimesh.Scene):
            def dump(self, *_args: object, **_kwargs: object):
                raise ValueError("component graph references a missing object")

        p = tmp_path / "broken-graph.obj"
        p.write_bytes(b"placeholder")
        monkeypatch.setattr(trimesh, "load_scene", lambda *a, **k: UnflattenableScene())

        assert mesh_processing._load_mesh(p) is None

    def test_load_mesh_declines_a_scene_whose_parts_will_not_concatenate(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Two meshes that flatten fine can still refuse to join.

        Mismatched vertex attributes across instances make `concatenate` raise,
        and the geometry is by then already loaded — so this branch is the last
        one before the caller, and the only thing standing between a mixed-format
        3MF and a 500.
        """
        scene = trimesh.Scene()
        scene.add_geometry(trimesh.creation.box(extents=[5, 5, 5]), node_name="a")
        scene.add_geometry(trimesh.creation.box(extents=[3, 3, 3]), node_name="b")
        p = tmp_path / "unjoinable.obj"
        p.write_bytes(b"placeholder")
        monkeypatch.setattr(trimesh, "load_scene", lambda *a, **k: scene)

        def refuse(*_args: object, **_kwargs: object):
            raise ValueError("vertex attributes differ between instances")

        monkeypatch.setattr(trimesh.util, "concatenate", refuse)

        assert mesh_processing._load_mesh(p) is None

    def test_load_mesh_scene_with_single_geometry_returns_it_directly(
        self, tmp_path: Path, monkeypatch
    ) -> None:

        scene = trimesh.Scene()
        box = trimesh.creation.box(extents=[5, 5, 5])
        scene.add_geometry(box, node_name="a")
        p = tmp_path / "single.obj"
        p.write_bytes(b"placeholder")
        monkeypatch.setattr(trimesh, "load_scene", lambda *a, **k: scene)
        mesh = mesh_processing._load_mesh(p)
        assert mesh is not None
        assert len(mesh.faces) == 12

    def test_load_mesh_returns_none_for_unsupported_loaded_type(
        self, tmp_path: Path, monkeypatch
    ) -> None:

        p = tmp_path / "cloud.stl"
        p.write_bytes(b"placeholder")
        # A loader may return a PointCloud (or other non-mesh geometry) for some
        # inputs; _load_mesh must decline rather than mishandle it.
        monkeypatch.setattr(
            trimesh,
            "load_scene",
            lambda *a, **k: trimesh.points.PointCloud([[0, 0, 0]]),
        )
        assert mesh_processing._load_mesh(p) is None

    def test_load_mesh_uses_typed_loader_without_processing(
        self, tmp_path: Path, monkeypatch
    ) -> None:

        expected = trimesh.creation.box(extents=[1, 1, 1])
        calls: list[tuple[tuple, dict]] = []

        def typed_loader(*args, **kwargs):
            calls.append((args, kwargs))
            return expected

        monkeypatch.setattr(trimesh, "load_scene", typed_loader)
        path = tmp_path / "typed.stl"
        path.write_bytes(b"placeholder")

        assert mesh_processing._load_mesh(path) is expected
        assert calls == [((str(path),), {"process": False})]


class TestLoadStepMeshIsolated:
    def test_step_tessellation_is_killed_when_child_exceeds_rss_budget(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        path = tmp_path / "complex.step"
        path.write_text("ISO-10303-21;")

        class MemoryHungryProcess:
            pid = 4242
            returncode = None
            killed = False

            def poll(self):
                return -9 if self.killed else None

            def kill(self):
                self.killed = True
                self.returncode = -9

            def communicate(self):
                return b"", b""

        process = MemoryHungryProcess()
        monkeypatch.setattr(
            mesh_processing.subprocess, "Popen", lambda *a, **k: process
        )
        monkeypatch.setattr(mesh_processing, "_step_memory_budget_bytes", lambda: 1024)
        monkeypatch.setattr(mesh_processing, "_process_rss_bytes", lambda _pid: 2048)

        assert mesh_processing._load_step_mesh_isolated(path) is None
        assert process.killed is True


class TestGeometryFromMesh:
    @pytest.mark.parametrize("edge", [0.001, 0.123456789, 123.456789])
    def test_preserves_measurement_precision(self, edge):
        mesh = trimesh.creation.box(extents=[edge, edge, edge])

        geometry = mesh_processing._geometry_from_mesh(mesh).geometry

        for axis in ("x", "y", "z"):
            assert geometry[f"bbox_{axis}_mm"] == pytest.approx(edge, rel=1e-12, abs=0)
        assert geometry["volume_mm3"] == pytest.approx(edge**3, rel=1e-12, abs=0)

    @pytest.mark.parametrize(
        "volume", [float("inf"), float("nan")], ids=["infinite", "nan"]
    )
    def test_refuses_nonfinite_volume(self, monkeypatch, volume):
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        monkeypatch.setattr(
            trimesh.triangles,
            "mass_properties",
            lambda *a, **kw: SimpleNamespace(volume=volume),
        )

        geometry = mesh_processing._geometry_from_mesh(mesh).geometry

        assert geometry["volume_mm3"] is None

    def test_geometry_from_mesh_handles_non_watertight_volume_error(
        self, monkeypatch
    ) -> None:
        mesh = trimesh.creation.box(extents=[1, 1, 1])
        mesh.unmerge_vertices()
        monkeypatch.setattr(
            trimesh.triangles,
            "mass_properties",
            lambda *a, **kw: (_ for _ in ()).throw(ValueError("non-watertight")),
        )
        geometry = mesh_processing._geometry_from_mesh(mesh).geometry
        assert geometry["volume_mm3"] is None
        assert geometry["bbox_x_mm"] == 1.0

    def test_reports_inconsistent_winding_volume_evidence(self):
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        mesh.faces[0] = mesh.faces[0][::-1]

        result = mesh_processing._geometry_from_mesh(mesh)

        assert result.volume == VolumeUnavailable(
            VolumeUnavailableCause.INCONSISTENT_WINDING
        )

    def test_reports_open_surface_volume_evidence(self):
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        mesh.faces = mesh.faces[:-1]

        result = mesh_processing._geometry_from_mesh(mesh)

        assert result.volume == VolumeUnavailable(VolumeUnavailableCause.NOT_WATERTIGHT)

    def test_reports_negative_integral_volume_evidence(self):
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        mesh.invert()

        result = mesh_processing._geometry_from_mesh(mesh)

        assert result.volume == VolumeUnavailable(
            VolumeUnavailableCause.NON_POSITIVE_INTEGRAL
        )

    @pytest.mark.parametrize("volume", [float("inf"), float("nan")], ids=str)
    def test_reports_nonfinite_integral_volume_evidence(self, monkeypatch, volume):
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        monkeypatch.setattr(
            trimesh.triangles,
            "mass_properties",
            lambda *a, **kw: SimpleNamespace(volume=volume),
        )

        result = mesh_processing._geometry_from_mesh(mesh)

        assert result.volume == VolumeUnavailable(
            VolumeUnavailableCause.NONFINITE_INTEGRAL
        )

    def test_reports_zero_integral_volume_evidence(self, monkeypatch):
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        monkeypatch.setattr(
            trimesh.triangles,
            "mass_properties",
            lambda *a, **kw: SimpleNamespace(volume=0.0),
        )

        result = mesh_processing._geometry_from_mesh(mesh)

        assert result.volume == VolumeUnavailable(
            VolumeUnavailableCause.NON_POSITIVE_INTEGRAL
        )

    def test_reports_small_measured_volume_evidence(self):
        mesh = trimesh.creation.box(extents=[0.001, 0.001, 0.001])

        result = mesh_processing._geometry_from_mesh(mesh)

        assert isinstance(result.volume, VolumeMeasured)
        assert result.volume.value_mm3 == pytest.approx(1e-9, rel=1e-12, abs=0)

    def test_reports_missing_geometry_volume_evidence(self):
        result = mesh_processing._geometry_from_mesh(None)

        assert result.volume == VolumeNotCalculated(
            VolumeNotCalculatedCause.GEOMETRY_UNAVAILABLE
        )

    def test_unexpected_volume_failure_retains_independent_measurements(
        self, monkeypatch, caplog
    ):
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        vertices, faces = mesh.vertices.copy(), mesh.faces.copy()

        def fail_volume(*_args, **_kwargs):
            raise RuntimeError("integral kernel failed")

        monkeypatch.setattr(trimesh.triangles, "mass_properties", fail_volume)
        result = mesh_processing._geometry_from_mesh(mesh)
        assert result.volume == VolumeUnavailable(
            VolumeUnavailableCause.MEASUREMENT_FAILED
        )
        assert result.geometry == {
            "bbox_x_mm": 10.0,
            "bbox_y_mm": 10.0,
            "bbox_z_mm": 10.0,
            "volume_mm3": None,
            "triangle_count": 12,
        }
        record = next(
            record
            for record in caplog.records
            if record.getMessage() == "mesh volume measurement failed"
        )
        assert record.exc_info[0] is RuntimeError
        assert str(record.exc_info[1]) == "integral kernel failed"
        np.testing.assert_array_equal(mesh.vertices, vertices)
        np.testing.assert_array_equal(mesh.faces, faces)


@pytest.fixture
def oriented_tetrahedra():
    vertices = np.array([[0, 0, 0], [3, 0, 0], [0, 2, 0], [0, 0, 1]], dtype=np.float64)
    faces = np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]])
    offsets = np.zeros((64, 3))
    offsets[:, 0] = 1e15
    offsets[::2, 0] = -1e15
    offsets[:, 0] += np.arange(64) * 8
    all_vertices = (vertices[None, :, :] + offsets[:, None, :]).reshape(-1, 3)
    all_faces = (faces[None, :, :] + 4 * np.arange(64)[:, None, None]).reshape(-1, 3)
    all_faces[:40] = all_faces[:40, ::-1]
    return trimesh.Trimesh(vertices=all_vertices, faces=all_faces, process=False)


class TestVolumeIntegralBatching:
    @pytest.mark.parametrize("batch_faces", [5, 12, 17])
    def test_preserves_signed_integrals_across_facet_batch_boundaries(
        self, monkeypatch, oriented_tetrahedra, batch_faces
    ):
        monkeypatch.setattr(
            mesh_processing, "_VOLUME_INTEGRAL_BATCH_FACES", batch_faces
        )
        vertices, faces = (
            oriented_tetrahedra.vertices.copy(),
            oriented_tetrahedra.faces.copy(),
        )
        result = mesh_processing._geometry_from_mesh(oriented_tetrahedra)
        # Each tetrahedron has signed volume +/- (3 * 2 * 1 / 6).
        assert result.volume == VolumeMeasured(64 - 2 * 10)
        assert result.geometry["triangle_count"] == 256
        np.testing.assert_array_equal(oriented_tetrahedra.vertices, vertices)
        np.testing.assert_array_equal(oriented_tetrahedra.faces, faces)

    def test_measures_closed_source_without_whole_mesh_geometry_copies(
        self, monkeypatch, oriented_tetrahedra
    ):
        def forbid_allocation(*_args, **_kwargs):
            raise AssertionError("full source geometry allocation")

        monkeypatch.setattr(trimesh.Trimesh, "copy", forbid_allocation)
        monkeypatch.setattr(trimesh.Trimesh, "triangles", property(forbid_allocation))
        result = mesh_processing._geometry_from_mesh(oriented_tetrahedra)
        assert result.volume == VolumeMeasured(44.0)
