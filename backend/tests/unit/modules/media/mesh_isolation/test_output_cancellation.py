"""A decoded output cannot publish after cancellation, even within one pipe read."""

from dataclasses import replace

import pytest
from printstash_core.mesh.measurements import VolumeMeasured

from app.core.cancellation import OperationCancelled, cancellation_scope
from app.modules.media import mesh_isolation
from app.modules.media.mesh_contracts import (
    GeometryReady,
    MeshCoverage,
    PreviewCoverage,
    SourceScanState,
    ThumbnailRequest,
    ThumbnailStrategy,
)
from app.modules.media.mesh_facts import CompleteGeometry
from app.modules.media.mesh_protocol import (
    FingerprintFinal,
    GeometryOutput,
    ThumbnailOutput,
    encode_frame,
)
from app.modules.media.mesh_telemetry import (
    SupervisedReply,
    SupervisionStats,
    WorkerExitCause,
)


@pytest.fixture
def framed_worker(tmp_path, monkeypatch):
    coverage = MeshCoverage(
        SourceScanState.COMPLETE, CompleteGeometry(), PreviewCoverage.NOT_PRODUCED
    )
    geometry = GeometryOutput(
        {
            "bbox_x_mm": 1.0,
            "bbox_y_mm": 2.0,
            "bbox_z_mm": 3.0,
            "triangle_count": 12,
            "volume_mm3": 6.0,
        },
        GeometryReady(),
        VolumeMeasured(6.0),
        coverage,
        1,
        None,
    )
    rendered = replace(coverage, preview=PreviewCoverage.COMPLETE)
    thumbnail = ThumbnailOutput(
        b"image", ThumbnailStrategy.FULL, rendered, None, 2, None
    )
    payload = (
        encode_frame(geometry, sequence=0)
        + encode_frame(thumbnail, sequence=1)
        + encode_frame(FingerprintFinal(None, (), 3, None, rendered), sequence=2)
    )

    def run(_module, _spec, *, on_chunk, **_options):
        on_chunk(payload)
        return SupervisedReply(
            payload,
            SupervisionStats(
                "a" * 32, 1, None, len(payload), WorkerExitCause.EXITED_ZERO
            ),
        )

    monkeypatch.setattr(mesh_isolation, "_run_worker", run)
    return ThumbnailRequest(tmp_path / "source.stl"), geometry


class TestGenerate:
    def test_refuses_a_second_output_after_cancellation(self, framed_worker):
        request, geometry = framed_worker
        published = []

        with (
            cancellation_scope(lambda: bool(published)),
            pytest.raises(OperationCancelled),
        ):
            mesh_isolation.generate(request, on_output=published.append)

        assert published == [geometry]

    def test_refuses_the_first_output_after_cancellation(self, framed_worker):
        request, _geometry = framed_worker
        published = []

        with cancellation_scope(lambda: True), pytest.raises(OperationCancelled):
            mesh_isolation.generate(request, on_output=published.append)

        assert published == []
