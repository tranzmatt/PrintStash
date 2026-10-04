"""Render only the surface referenced by faces, preserving source measurements."""

import io

import numpy as np
import pytest
import trimesh
from PIL import Image

from app.modules.media.thumbnail_engine import ThumbnailEngine, ThumbnailRequest
from tests.factories.geometry import three_mf


class TestUnreferencedVertices:
    def test_preserves_3mf_preview(self, tmp_path):
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        padded = trimesh.Trimesh(
            vertices=np.concatenate([mesh.vertices, [[1e6, -1e6, 1e6]]]),
            faces=mesh.faces.copy(),
            process=False,
        )
        original_path = tmp_path / "original.3mf"
        padded_path = tmp_path / "padded.3mf"
        original_path.write_bytes(three_mf(meshes={1: mesh}))
        padded_path.write_bytes(three_mf(meshes={1: padded}))

        original = ThumbnailEngine().generate(
            ThumbnailRequest(original_path, width=128, height=128)
        )
        result = ThumbnailEngine().generate(
            ThumbnailRequest(padded_path, width=128, height=128)
        )

        assert original.image is not None and result.image is not None
        expected = np.asarray(Image.open(io.BytesIO(original.image)))
        actual = np.asarray(Image.open(io.BytesIO(result.image)))
        assert np.count_nonzero(expected[..., 3]) > 0
        np.testing.assert_array_equal(actual, expected)

    def test_preserves_3mf_metadata(self, tmp_path):
        mesh = trimesh.creation.box(extents=[10, 10, 10])
        mesh.vertices = np.concatenate([mesh.vertices, [[1e6, -1e6, 1e6]]])
        path = tmp_path / "padded.3mf"
        path.write_bytes(three_mf(meshes={1: mesh}))

        result = ThumbnailEngine().generate(ThumbnailRequest(path, width=64, height=64))

        assert result.geometry == pytest.approx(
            {
                "bbox_x_mm": 10,
                "bbox_y_mm": 10,
                "bbox_z_mm": 10,
                "volume_mm3": 1000,
                "triangle_count": 12,
            }
        )
