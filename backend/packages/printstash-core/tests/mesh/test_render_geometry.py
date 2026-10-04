"""Render preparation preserves relative coordinates without flattening scene faces.

Output chunk order must reproduce materialized geometry across placement edges.
Limits are applied before render buffers, and source arrays remain unchanged.
"""

import numpy as np
import pytest

from printstash_core.mesh.render_geometry import prepare_scene
from printstash_core.mesh.similarity import GeometryError
from printstash_core.mesh.similarity.components import (
    ExpandedScene,
    Instance,
    MeshResource,
)


class TestPrepareScene:
    @pytest.mark.parametrize("size", [1, 5, 20])
    def test_yields_repeatable_chunks_in_placement_order(self, size):
        vertices = np.array([[0.0, 0, 0], [10, 0, 0], [1, 20, 0], [2, 3, 30]])
        faces = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
        reflected = np.diag([-2.0, 2, 2, 1])
        reflected[:3, 3] = [100, 0, 0]
        scene = ExpandedScene(
            (MeshResource("part", vertices, faces),),
            (Instance("part", np.eye(4)), Instance("part", reflected)),
        )
        expected_points = np.concatenate(
            (vertices, vertices * [-2, 2, 2] + [100, 0, 0])
        )
        expected_relative = (expected_points - [50, 20, 30]).astype(np.float32)
        expected_faces = np.concatenate((faces, faces[:, ::-1] + 4))
        originals = vertices.tobytes(), faces.tobytes(), reflected.tobytes()

        prepared = prepare_scene(scene)
        first = tuple(prepared.face_chunks(size))
        repeated = tuple(prepared.face_chunks(size))

        np.testing.assert_array_equal(prepared.vertices, expected_relative)
        assert prepared.vertices.dtype == np.float32
        assert prepared.face_count == 8
        assert all(0 < len(chunk) <= size for chunk in first)
        np.testing.assert_array_equal(np.concatenate(first), expected_faces)
        np.testing.assert_array_equal(np.concatenate(repeated), expected_faces)
        assert (vertices.tobytes(), faces.tobytes(), reflected.tobytes()) == originals

    @pytest.mark.parametrize("size", [0, -1, True, 1.0])
    def test_rejects_invalid_chunk_size(self, size):
        scene = ExpandedScene(
            (MeshResource("part", np.eye(3), np.array([[0, 1, 2]])),),
            (Instance("part", np.eye(4)),),
        )
        prepared = prepare_scene(scene)

        with pytest.raises(ValueError, match="invalid_render_chunk"):
            tuple(prepared.face_chunks(size))

    @pytest.mark.parametrize(
        "vertex_count,face_count,instances",
        [(3, 1_000_001, 2), (3_000_001, 1, 2), (3, 1, 2049)],
    )
    def test_rejects_source_limits_before_render_allocation(
        self, monkeypatch, vertex_count, face_count, instances
    ):
        scene = ExpandedScene(
            (
                MeshResource(
                    "part",
                    np.broadcast_to(np.array([[0.0, 0, 0]]), (vertex_count, 3)),
                    np.broadcast_to(np.array([[0, 1, 2]]), (face_count, 3)),
                ),
            ),
            (Instance("part", np.eye(4)),) * instances,
        )

        def allocate(*_args, **_kwargs):
            raise AssertionError("refused scene allocated render output")

        monkeypatch.setattr(np, "empty", allocate)
        with pytest.raises(GeometryError, match="scene_resource_limit"):
            prepare_scene(scene)

    def test_rejects_relative_render_numeric_overflow(self):
        scene = ExpandedScene(
            (MeshResource("part", np.eye(3), np.array([[0, 1, 2]])),),
            (Instance("part", np.diag([1e300, 1e300, 1e300, 1])),),
        )

        with pytest.raises(GeometryError, match="numeric_range"):
            prepare_scene(scene)
