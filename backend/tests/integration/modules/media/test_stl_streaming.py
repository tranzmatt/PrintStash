"""Legacy streaming cancellation follows the same worker-tree cleanup contract."""

import json
from pathlib import Path

import pytest

from app.core.cancellation import OperationCancelled, cancellation_scope
from app.modules.media import stl_streaming
from app.modules.media.worker_bootstrap import command
from tests.factories import content


class TestStreamingCancellation:
    def test_cancellation_reaps_owned_workers(self, tmp_path, monkeypatch):
        source = tmp_path / "part.stl"
        source.write_bytes(content.binary_stl())
        pids = tmp_path / "pids"
        original = stl_streaming.subprocess.Popen
        processes = []

        def waiting(_argv, **kwargs):
            process = original(
                command(
                    "tests.fakes.mesh_bootstrap_probe",
                    ["tree_wait", str(pids)],
                    256 * 1024**2,
                ),
                **kwargs,
            )
            processes.append(process)
            return process

        monkeypatch.setattr(stl_streaming.subprocess, "Popen", waiting)
        with cancellation_scope(pids.exists), pytest.raises(OperationCancelled):
            stl_streaming.render_stl_preview_isolated(source)
        assert processes[0].poll() is not None
        for pid in json.loads(pids.read_text()):
            assert not Path(f"/proc/{pid}").exists()
        assert set(tmp_path.iterdir()) == {source, pids}


class TestPreviewCoverage:
    def test_represents_remote_small_component(self, tmp_path: Path) -> None:
        import io

        import numpy as np
        import trimesh
        from PIL import Image

        sphere = trimesh.creation.icosphere(subdivisions=4, radius=1.0)
        cube = trimesh.creation.box(extents=(2.0, 2.0, 2.0))
        cube.apply_translation((100.0, 0.0, 0.0))
        source = tmp_path / "disconnected.stl"
        source.write_bytes(
            trimesh.util.concatenate([sphere, cube]).export(file_type="stl")
        )

        result = stl_streaming.render_stl_preview_isolated(
            source, width=512, height=512
        )

        assert result is not None
        assert result.triangle_count == 5132
        assert result.bounds_max[0] == pytest.approx(101.0)
        with Image.open(io.BytesIO(result.png)) as image:
            alpha = np.asarray(image.getchannel("A"))
        assert np.any(alpha[:, :128])
        assert np.any(alpha[:, -128:])
        assert not np.any(alpha[:, 192:320])

    def test_preserves_ascii_render_after_translation(self, tmp_path: Path) -> None:
        import trimesh

        cube = trimesh.creation.box(extents=(10.0, 10.0, 10.0))
        origin = tmp_path / "origin.stl"
        origin.write_text(trimesh.exchange.stl.export_stl_ascii(cube), encoding="ascii")
        cube.apply_translation((1e9, 1e9, 1e9))
        translated = tmp_path / "translated.stl"
        translated.write_text(
            trimesh.exchange.stl.export_stl_ascii(cube), encoding="ascii"
        )

        first = stl_streaming.render_stl_preview_isolated(origin, width=128, height=128)
        second = stl_streaming.render_stl_preview_isolated(
            translated, width=128, height=128
        )

        assert first is not None
        assert second is not None
        assert second.bounds_max[0] - second.bounds_min[0] == 10.0
        assert second.png == first.png

    @pytest.mark.parametrize("encoding", ["binary", "ascii"], ids=str)
    def test_keeps_output_independent_of_chunk(
        self, tmp_path: Path, encoding: str
    ) -> None:
        source = tmp_path / "chunked.stl"
        source.write_bytes(
            content.binary_stl(triangles=120)
            if encoding == "binary"
            else content.ascii_stl(triangles=120)
        )

        small = stl_streaming.render_stl_preview_isolated(
            source,
            width=128,
            height=128,
            limits=stl_streaming.STLStreamingLimits(chunk_triangles=1),
        )
        large = stl_streaming.render_stl_preview_isolated(
            source,
            width=128,
            height=128,
            limits=stl_streaming.STLStreamingLimits(chunk_triangles=8192),
        )

        assert small is not None
        assert large is not None
        assert small.png == large.png
        assert small.bounds_min == large.bounds_min
        assert small.bounds_max == large.bounds_max
