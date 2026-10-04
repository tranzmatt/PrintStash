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


class TestValidTriangle:
    def test_renders_valid_oblique_facet(self, tmp_path: Path) -> None:
        import io

        from PIL import Image

        source = tmp_path / "oblique.stl"
        source.write_text(
            """solid oblique
facet normal -2 -2 4
outer loop
vertex 0 0 0
vertex 2 0 1
vertex 0 2 1
endloop
endfacet
endsolid oblique
""",
            encoding="ascii",
        )

        result = stl_streaming.render_stl_preview_isolated(
            source, width=128, height=128
        )

        assert result is not None
        assert result.parsed_triangles == 1
        assert result.raster_candidates > 0
        with Image.open(io.BytesIO(result.png)) as image:
            assert image.getchannel("A").getbbox() is not None
