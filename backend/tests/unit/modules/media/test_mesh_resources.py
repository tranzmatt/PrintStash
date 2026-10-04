"""Prepared geometry describes complete resources or an explicit source sample."""

import numpy as np
import pytest
import trimesh
from printstash_core.mesh.similarity.components import ExpandedScene

from app.modules.media.mesh_facts import (
    CompleteGeometry,
    FingerprintFailureCode,
    SampledGeometry,
)
from app.modules.media.mesh_resources import PreparedMesh, prepare_loaded_mesh


class TestPreparedMesh:
    def test_preserves_complete_resource_identity(self):
        mesh = trimesh.creation.box()
        prepared = prepare_loaded_mesh(mesh, file_type="stl")
        assert prepared.whole_mesh is mesh
        assert isinstance(prepared.geometry, CompleteGeometry)
        assert prepared.complete is True
        assert prepared.failure_code is None
        assert prepared.whole_resource_id == prepared.scene.resources[0].resource_id

    def test_retains_explicit_sampled_geometry(self):
        mesh = trimesh.creation.box()
        geometry = SampledGeometry(FingerprintFailureCode.SAMPLED_SOURCE)
        prepared = PreparedMesh(mesh, ExpandedScene((), ()), geometry=geometry)
        assert prepared.geometry is geometry
        assert prepared.complete is False
        assert prepared.failure_code is FingerprintFailureCode.SAMPLED_SOURCE

    def test_rejects_sample_with_resource_claims(self):
        mesh = trimesh.creation.box()
        scene = prepare_loaded_mesh(mesh, file_type="stl").scene
        with pytest.raises(ValueError, match="sampled_geometry"):
            PreparedMesh(
                mesh,
                scene,
                geometry=SampledGeometry(FingerprintFailureCode.SAMPLED_SOURCE),
            )

    def test_rejects_complete_geometry_without_resources(self):
        mesh = trimesh.creation.box()
        with pytest.raises(ValueError, match="complete_geometry"):
            PreparedMesh(mesh, ExpandedScene((), ()), geometry=CompleteGeometry())

    def test_rejects_unknown_whole_resource_identity(self):
        mesh = trimesh.creation.box()
        scene = prepare_loaded_mesh(mesh, file_type="stl").scene
        with pytest.raises(ValueError, match="whole_resource"):
            PreparedMesh(
                mesh,
                scene,
                geometry=CompleteGeometry(),
                whole_resource_id="missing",
            )

    def test_preserves_source_arrays(self):
        mesh = trimesh.creation.box()
        before_vertices = mesh.vertices.copy()
        before_faces = mesh.faces.copy()
        prepare_loaded_mesh(mesh, file_type="stl")
        np.testing.assert_array_equal(mesh.vertices, before_vertices)
        np.testing.assert_array_equal(mesh.faces, before_faces)
