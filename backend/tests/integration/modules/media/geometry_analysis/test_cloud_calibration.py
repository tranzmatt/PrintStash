"""The surface-cloud gate never rejects a labelled derivative before verification.

A rejected pair is never verified, so a gate that rejected a real derivative
would silently lose its evidence. Every labelled positive in the frozen corpus,
fingerprinted through the production extraction path, must pass the gate.
"""

import pytest
from printstash_core.mesh.similarity import cloud

from app.modules.media.fingerprints import extract
from app.modules.media.mesh_resources import prepare_loaded_mesh
from tests.factories.similarity_corpus import cases, mesh_for

POSITIVES = [row for row in cases() if row["expected"] != "not_exact"]


def whole_cloud(base, variant):
    prepared = prepare_loaded_mesh(mesh_for(base, variant), file_type="stl")
    (record,) = (r for r in extract(prepared).records if r.component_index == 0)
    return cloud.SurfaceCloud.decode(record.values["cloud_blob"])


class TestCloudGate:
    @pytest.mark.parametrize(
        "row", POSITIVES, ids=[row["case_id"] for row in POSITIVES]
    )
    def test_keeps_every_labelled_derivative(self, row):
        assert not cloud.rejects(
            whole_cloud(row["base"], row["left_variant"]),
            whole_cloud(row["base"], row["right_variant"]),
        )

    def test_rejects_an_unrelated_design(self):
        assert cloud.rejects(
            whole_cloud("thingi10k-45169.stl", "original"),
            whole_cloud("thingi10k-117647.stl", "original"),
        )
