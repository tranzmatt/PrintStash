"""Surface clouds reject clearly different shapes and keep every transformed copy."""

import numpy as np
import pytest

from printstash_core.mesh.similarity import cloud
from printstash_core.mesh.similarity.fingerprint import GeometryError
from printstash_core.mesh.similarity.geometry import prepare_surface


def surface_of(vertices, faces):
    return cloud.surface_cloud(prepare_surface(vertices, faces))


def rotation(angle, axis):
    axis = np.asarray(axis, dtype=float) / np.linalg.norm(axis)
    k = np.array(
        [[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]]
    )
    return np.eye(3) + np.sin(angle) * k + (1 - np.cos(angle)) * k @ k


@pytest.fixture
def box():
    def make(x, y, z):
        corners = np.array(
            [[i * x, j * y, k * z] for i in (0, 1) for j in (0, 1) for k in (0, 1)],
            dtype=float,
        )
        faces = np.array(
            [
                [0, 1, 3],
                [0, 3, 2],
                [4, 6, 7],
                [4, 7, 5],
                [0, 4, 5],
                [0, 5, 1],
                [2, 3, 7],
                [2, 7, 6],
                [0, 2, 6],
                [0, 6, 4],
                [1, 5, 7],
                [1, 7, 3],
            ],
            dtype=np.int64,
        )
        return corners, faces

    return make


class TestSurfaceCloud:
    def test_round_trips_through_storage(self, tetra):
        original = surface_of(*tetra)

        decoded = cloud.SurfaceCloud.decode(original.encode())

        assert (
            np.array_equal(decoded.points, original.points),
            np.array_equal(decoded.frame, original.frame),
            decoded.spacing == pytest.approx(original.spacing, rel=1e-6),
        ) == (True, True, True)

    def test_encodes_a_fixed_size(self, tetra):
        assert len(surface_of(*tetra).encode()) == cloud.CLOUD_BYTES

    @pytest.mark.parametrize(
        "blob",
        [b"", b"\0" * (cloud.CLOUD_BYTES - 4)],
        ids=["empty", "short"],
    )
    def test_refuses_a_blob_of_another_size(self, blob):
        with pytest.raises(GeometryError, match="invalid_surface_cloud"):
            cloud.SurfaceCloud.decode(blob)

    @pytest.mark.parametrize(
        "spacing", [0.0, -1.0, np.nan], ids=["zero", "negative", "nan"]
    )
    def test_refuses_an_invalid_spacing(self, tetra, spacing):
        valid = surface_of(*tetra)
        blob = cloud.SurfaceCloud(valid.points, valid.frame, spacing).encode()

        with pytest.raises(GeometryError, match="invalid_surface_cloud"):
            cloud.SurfaceCloud.decode(blob)

    def test_refuses_non_finite_points(self, tetra):
        valid = surface_of(*tetra)
        points = valid.points.copy()
        points[0, 0] = np.inf

        with pytest.raises(GeometryError, match="invalid_surface_cloud"):
            cloud.SurfaceCloud.decode(
                cloud.SurfaceCloud(points, valid.frame, valid.spacing).encode()
            )

    def test_is_reproducible(self, tetra):
        assert surface_of(*tetra).encode() == surface_of(*tetra).encode()


class TestRejection:
    @pytest.mark.parametrize(
        "transform",
        [
            lambda v: v,
            lambda v: v @ rotation(0.7, [0.2, 0.3, 1]).T + [13, -4, 2],
            lambda v: v * 25.4,
            lambda v: v * [-1, 1, 1],
            lambda v: (v * [-2, 2, 2]) @ rotation(1.9, [1, 0, 0.4]).T,
        ],
        ids=["same", "rigid", "rescaled", "mirrored", "rescaled-mirrored-rotated"],
    )
    def test_keeps_a_transformed_copy(self, subdivide, tetra, transform):
        vertices, faces = subdivide(*tetra, levels=2)

        assert not cloud.rejects(
            surface_of(vertices, faces), surface_of(transform(vertices), faces)
        )

    def test_keeps_a_remeshed_copy(self, subdivide, cube):
        coarse = surface_of(*cube)
        fine = surface_of(*subdivide(*cube, levels=3))

        assert not cloud.rejects(coarse, fine)

    def test_rejects_a_different_shape(self, subdivide, box, tetra):
        assert cloud.rejects(
            surface_of(*subdivide(*tetra, levels=2)), surface_of(*box(10, 20, 2))
        )

    def test_rejects_different_proportions(self, box):
        assert cloud.rejects(surface_of(*box(10, 10, 10)), surface_of(*box(10, 10, 1)))

    def test_scores_a_cloud_against_itself_as_zero(self, subdivide, tetra):
        surface = surface_of(*subdivide(*tetra, levels=2))

        assert cloud.alignment_score(surface, surface) == pytest.approx(0, abs=1e-9)
