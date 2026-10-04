"""The research harness compares explicit expectations and freezes its inputs."""

import io
import zipfile

import pytest

from scripts.pilot_lib3mf import check_expectations
from tests.factories.three_mf_pilot import corpus, load_mesh


class TestCorpus:
    def test_archive_generation_is_deterministic(self):
        first = {case.name: case.payload for case in corpus()}
        second = {case.name: case.payload for case in corpus()}

        assert first == second
        assert len(first) == len(corpus())

    def test_generated_archive_has_required_opc_parts(self):
        case = load_mesh(12)

        with zipfile.ZipFile(io.BytesIO(case.payload)) as archive:
            assert "[Content_Types].xml" in archive.namelist()
            assert b"/3D/3dmodel.model" in archive.read("_rels/.rels")
            assert all(
                entry.date_time == (2020, 1, 1, 0, 0, 0) for entry in archive.infolist()
            )

    @pytest.mark.parametrize("faces, instances", [(0, 1), (6, 1), (4, 0)])
    def test_refuses_invalid_load_dimensions(self, faces, instances):
        with pytest.raises(ValueError, match="invalid_pilot_load"):
            load_mesh(faces, instances)


class TestExpectations:
    def test_accepts_matching_evidence(self):
        observed = {
            "outcome": "ready",
            "bbox": [10 + 1e-8, 20, 30],
            "volume": 1000.0,
            "faces": 4,
        }

        assert (
            check_expectations(
                observed,
                {
                    "outcome": "ready",
                    "bbox": [10, 20, 30],
                    "volume": 1000.0,
                    "faces": 4,
                },
            )
            == []
        )

    @pytest.mark.parametrize(
        "actual",
        [None, "bad", [], [10, 20], [10, 20, 31], ["bad", 20, 30], [True, 20, 30]],
    )
    def test_reports_mismatched_evidence(self, actual):
        assert check_expectations({"bbox": actual}, {"bbox": [10, 20, 30]}) == ["bbox"]
