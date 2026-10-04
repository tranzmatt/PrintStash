"""STL consumers share exact source interpretation and explicit coverage."""

from pathlib import Path

import numpy as np
import pytest

from app.modules.media import mesh_processing, stl_fallback, stl_streaming
from app.modules.media.stl_reader import InvalidSTL, scan_stl
from tests.factories import content

FACETS = [
    ((0.0, 0.0, 0.0), (2.0, 0.0, 1.0), (0.0, 2.0, 1.0)),
    ((100.0, 3.0, 4.0), (101.0, 3.0, 4.0), (100.0, 4.0, 5.0)),
]


class TestSTLConsumers:
    @pytest.mark.parametrize("encoding", ["binary", "solid-binary", "ascii"])
    def test_parses_stl_variants_consistently(self, tmp_path: Path, encoding: str):
        source = tmp_path / "mesh.stl"
        body = (
            content.ascii_stl_facets(FACETS)
            if encoding == "ascii"
            else content.binary_stl_facets(FACETS)
        )
        if encoding == "solid-binary":
            body = b"solid" + body[5:]
        source.write_bytes(body)

        measured = scan_stl(source)
        sampled = stl_fallback.sample_stl_geometry(source, max_triangles=2)
        loaded = mesh_processing._load_mesh(source)
        streamed = stl_streaming.render_stl_preview_isolated(
            source, width=96, height=72
        )

        assert sampled is not None
        assert loaded is not None
        assert streamed is not None
        assert (
            measured.triangle_count
            == sampled.triangle_count
            == len(loaded.faces)
            == streamed.triangle_count
            == 2
        )
        for lower, upper in (
            (sampled.bounds_min, sampled.bounds_max),
            (loaded.bounds[0], loaded.bounds[1]),
            (streamed.bounds_min, streamed.bounds_max),
        ):
            np.testing.assert_array_equal(lower, measured.bounds_min)
            np.testing.assert_array_equal(upper, measured.bounds_max)

    @pytest.mark.parametrize(
        "normal",
        [(float("nan"), 0.0, 0.0), (float("inf"), 0.0, 0.0), (17.0, -23.0, 99.0)],
    )
    def test_binary_stored_normals_do_not_change_geometry_or_preview(
        self, tmp_path: Path, normal: tuple[float, float, float]
    ):
        import struct

        facets = [
            ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            ((0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (0.0, 1.0, 1.0)),
        ]
        source = tmp_path / "stored-normal.stl"
        body = bytearray(content.binary_stl_facets(facets))
        for offset in (84, 134):
            struct.pack_into("<3f", body, offset, 0.0, 0.0, 0.0)
        source.write_bytes(body)
        baseline = stl_streaming.render_stl_preview_isolated(
            source, width=96, height=72
        )
        assert baseline is not None
        altered = bytearray(body)
        for offset in (84, 134):
            struct.pack_into("<3f", altered, offset, *normal)
        source.write_bytes(altered)

        measured = scan_stl(source)
        sampled = stl_fallback.read_stl_sample(source, max_triangles=2)
        loaded = mesh_processing._load_mesh(source)
        streamed = stl_streaming.render_stl_preview_isolated(
            source, width=96, height=72
        )

        assert loaded is not None and streamed is not None
        assert sampled.source_complete and sampled.complete
        assert (
            measured.triangle_count == sampled.triangle_count == len(loaded.faces) == 2
        )
        np.testing.assert_array_equal(
            np.asarray(sampled.coordinates).reshape(-1, 3, 3), facets
        )
        np.testing.assert_array_equal(loaded.triangles, facets)
        assert streamed.png == baseline.png
        assert streamed.bounds_min == baseline.bounds_min
        assert streamed.bounds_max == baseline.bounds_max

    @pytest.mark.parametrize("value", [float("nan"), float("inf")])
    def test_nonfinite_binary_positions_are_refused(self, tmp_path: Path, value: float):
        import struct

        source = tmp_path / "bad-position.stl"
        body = bytearray(content.binary_stl(triangles=2))
        struct.pack_into("<f", body, 146, value)
        source.write_bytes(body)

        with pytest.raises(InvalidSTL):
            scan_stl(source)
        assert stl_fallback.sample_stl_geometry(source, max_triangles=1) is None
        assert mesh_processing._load_mesh(source) is None
        assert (
            stl_streaming.render_stl_preview_isolated(source, width=96, height=72)
            is None
        )

    @pytest.mark.parametrize("normal", [b"nan", b"inf"])
    def test_ascii_stored_normals_remain_finite_syntax(
        self, tmp_path: Path, normal: bytes
    ):
        source = tmp_path / "bad-ascii-normal.stl"
        source.write_bytes(
            content.ascii_stl_facets(FACETS).replace(
                b"normal 0 0 1", b"normal " + normal + b" 0 1"
            )
        )

        with pytest.raises(InvalidSTL):
            scan_stl(source)
        assert stl_fallback.sample_stl_geometry(source, max_triangles=1) is None
        assert mesh_processing._load_mesh(source) is None

    @pytest.mark.parametrize("consumer", ["sample", "full-loader"])
    @pytest.mark.parametrize(
        "damage",
        [
            "truncated",
            "count-mismatch",
            "trailing",
            "unsampled-nonfinite",
            "incomplete-ascii",
            "malformed-ascii",
            "nonascii",
        ],
    )
    def test_rejects_malformed_stl_consistently(
        self, tmp_path: Path, damage: str, consumer: str
    ):
        source = tmp_path / "damaged.stl"
        body = content.binary_stl_facets(FACETS)
        if damage == "truncated":
            body = body[:-1]
        elif damage == "count-mismatch":
            body = body[:80] + (3).to_bytes(4, "little") + body[84:]
        elif damage == "trailing":
            body += b"trailing"
        elif damage == "unsampled-nonfinite":
            body = body[:146] + b"\x00\x00\xc0\x7f" + body[150:]
        elif damage == "incomplete-ascii":
            body = content.ascii_stl_facets(FACETS).replace(b"endfacet", b"", 1)
        elif damage == "malformed-ascii":
            body = content.ascii_stl_facets(FACETS).replace(
                b"outer loop", b"outer wrong", 1
            )
        else:
            body = content.ascii_stl_facets(FACETS).replace(b"solid", b"sol\xffid", 1)
        source.write_bytes(body)
        with pytest.raises(InvalidSTL):
            scan_stl(source)

        if consumer == "sample":
            assert stl_fallback.sample_stl_geometry(source, max_triangles=1) is None
        else:
            assert mesh_processing._load_mesh(source) is None

    @pytest.mark.parametrize("encoding", ["binary", "ascii"])
    def test_certifies_source_completion_for_partial_samples(
        self, tmp_path: Path, encoding: str
    ):
        source = tmp_path / "partial.stl"
        source.write_bytes(
            content.binary_stl_facets(FACETS)
            if encoding == "binary"
            else content.ascii_stl_facets(FACETS)
        )

        sampled = stl_fallback.sample_stl_geometry(source, max_triangles=1)

        assert sampled is not None
        assert sampled.source_complete is True
        assert sampled.complete is False
        assert sampled.sampled_triangles == 1
        assert sampled.parsed_triangles == sampled.triangle_count == 2
        assert sampled.scanned_bytes == source.stat().st_size
        assert sampled.bounds_max == (101.0, 4.0, 5.0)

    def test_preserves_ascii_materialization_precision(self, tmp_path: Path):
        facets = [
            tuple(tuple(1e9 + value / 16 for value in vertex) for vertex in facet)
            for facet in FACETS
        ]
        source = tmp_path / "precise.stl"
        source.write_bytes(content.ascii_stl_facets(facets))

        sampled = stl_fallback.sample_stl_geometry(source, max_triangles=2)
        loaded = mesh_processing._load_mesh(source)

        assert sampled is not None
        assert loaded is not None
        expected = np.asarray(facets, dtype=np.float64)
        np.testing.assert_array_equal(
            np.asarray(sampled.coordinates).reshape(-1, 3, 3), expected
        )
        np.testing.assert_array_equal(loaded.triangles, expected)


class TestSTLBudgets:
    def test_accepts_stl_ascii_at_limit(self, tmp_path: Path):
        from app.modules.media.stl_reader import STLReadLimits

        body = content.ascii_stl_facets(FACETS)
        source = tmp_path / "exact-limit.stl"
        source.write_bytes(body)
        limits = STLReadLimits(
            max_triangles=2,
            max_source_bytes=len(body),
            max_lines=len(body.splitlines()),
            max_line_bytes=max(len(line) for line in body.splitlines(keepends=True)),
            chunk_triangles=1,
        )

        measured = scan_stl(source, limits=limits)
        sampled = stl_fallback.sample_stl_geometry(
            source, max_triangles=2, limits=limits
        )

        assert sampled is not None and sampled.source_complete and sampled.complete
        assert sampled.scanned_bytes == measured.scanned_bytes == len(body)
        assert sampled.triangle_count == measured.triangle_count == 2

    @pytest.mark.parametrize(
        "budget", ["max_triangles", "max_source_bytes", "max_lines", "max_line_bytes"]
    )
    def test_rejects_stl_ascii_above_limit(self, tmp_path: Path, budget: str):
        from app.modules.media.stl_reader import STLBudgetExceeded, STLReadLimits

        body = content.ascii_stl_facets(FACETS)
        source = tmp_path / "over-limit.stl"
        source.write_bytes(body)
        limits = {
            "max_triangles": 2,
            "max_source_bytes": len(body),
            "max_lines": len(body.splitlines()),
            "max_line_bytes": max(len(line) for line in body.splitlines(keepends=True)),
            "chunk_triangles": 1,
        }
        limits[budget] -= 1
        bounded = STLReadLimits(**limits)

        with pytest.raises(STLBudgetExceeded):
            scan_stl(source, limits=bounded)
        assert (
            stl_fallback.sample_stl_geometry(source, max_triangles=2, limits=bounded)
            is None
        )

    def test_reads_every_binary_source_byte_even_with_small_sample(
        self, tmp_path: Path, count_source_reads
    ):
        source = tmp_path / "read-cost.stl"
        source.write_bytes(content.binary_stl(triangles=120))
        reads = count_source_reads(source)

        sampled = stl_fallback.sample_stl_geometry(source, max_triangles=2)

        assert sampled is not None
        assert sampled.parsed_triangles == 120
        assert sampled.sampled_triangles == 2
        assert reads == [source.stat().st_size]

    @pytest.mark.parametrize("encoding", ["binary", "ascii"])
    def test_materializes_with_bounded_complete_read_passes(
        self, tmp_path: Path, count_source_reads, encoding: str
    ):
        import numpy as np

        from app.modules.media.stl_reader import STLReadLimits, materialize_stl

        body = (
            content.binary_stl_facets(FACETS)
            if encoding == "binary"
            else content.ascii_stl_facets(FACETS)
        )
        source = tmp_path / "materialize-cost.stl"
        source.write_bytes(body)
        reads = count_source_reads(source)

        materialized = materialize_stl(source, limits=STLReadLimits(chunk_triangles=1))

        np.testing.assert_array_equal(materialized.triangles, FACETS)
        assert materialized.triangles.dtype == np.float64
        assert materialized.measurements.scanned_bytes == len(body)
        assert materialized.measurements.triangle_count == 2
        # Binary count admits exact allocation directly; ASCII scans before its
        # allocation. Each parser probes84 bytes before ASCII rewind/read.
        expected = (
            [84, len(body)]
            if encoding == "binary"
            else [84, len(body) + 84, len(body) + 84]
        )
        assert reads == expected

    @pytest.mark.parametrize("encoding", ["binary", "ascii"])
    def test_keeps_sample_independent_of_chunk(self, tmp_path: Path, encoding: str):
        from app.modules.media.stl_reader import STLReadLimits

        source = tmp_path / "chunk-sample.stl"
        source.write_bytes(
            content.binary_stl(triangles=120)
            if encoding == "binary"
            else content.ascii_stl(triangles=120)
        )

        small = stl_fallback.sample_stl_geometry(
            source, max_triangles=17, limits=STLReadLimits(chunk_triangles=1)
        )
        large = stl_fallback.sample_stl_geometry(
            source, max_triangles=17, limits=STLReadLimits(chunk_triangles=8192)
        )

        assert small is not None and large is not None
        assert small == large
        assert small.sampled_triangles == 17
        assert small.parsed_triangles == 120


class TestSTLSourceSnapshots:
    @pytest.mark.parametrize("encoding", ["binary", "ascii"])
    def test_holds_source_snapshot_across_passes(self, tmp_path: Path, encoding: str):
        import os

        from app.modules.media.stl_reader import (
            STLReadLimits,
            STLSourceChanged,
            iter_stl_blocks,
        )

        source = tmp_path / "snapshot.stl"
        source.write_bytes(
            content.binary_stl_facets(FACETS)
            if encoding == "binary"
            else content.ascii_stl_facets(FACETS)
        )
        measured = scan_stl(source)
        before = source.stat()
        replacement = tmp_path / "replacement.stl"
        replacement.write_bytes(source.read_bytes())
        replacement.replace(source)
        os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))

        assert source.stat().st_size == measured.scanned_bytes
        assert source.stat().st_mtime_ns == before.st_mtime_ns
        with pytest.raises(STLSourceChanged):
            list(iter_stl_blocks(source, STLReadLimits(), snapshot=measured.snapshot))


class TestSTLCompletionSnapshots:
    @pytest.mark.parametrize("consumer", ["sample", "materialize"])
    def test_refuses_change_after_validated_eof_before_completion(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, consumer: str
    ):
        from app.modules.media.stl_reader import (
            STLReadLimits,
            STLSourceChanged,
            materialize_stl,
        )

        source = tmp_path / "completion-snapshot.stl"
        source.write_bytes(content.binary_stl_facets(FACETS))
        real_stat = Path.stat
        source_stats = 0

        def replace_after_eof_stat(path, *args, **kwargs):
            nonlocal source_stats
            current = real_stat(path, *args, **kwargs)
            if path == source:
                source_stats += 1
                if source_stats == 3:
                    replacement = path.with_suffix(".replacement")
                    replacement.write_bytes(path.read_bytes())
                    replacement.replace(path)
            return current

        monkeypatch.setattr(Path, "stat", replace_after_eof_stat)

        with pytest.raises(STLSourceChanged):
            if consumer == "sample":
                stl_fallback.read_stl_sample(source, max_triangles=2)
            else:
                materialize_stl(source, limits=STLReadLimits())
        assert source_stats >= 4


class TestSTLReadFailures:
    @pytest.mark.parametrize("encoding", ["binary", "ascii"])
    @pytest.mark.parametrize("consumer", ["scan", "sample", "full-loader"])
    def test_preserves_scan_bytes_on_read_failure(
        self, tmp_path: Path, count_source_reads, encoding: str, consumer: str
    ):
        from app.modules.media.stl_reader import STLReadLimits

        source = tmp_path / "interrupted.stl"
        source.write_bytes(
            content.binary_stl(triangles=120)
            if encoding == "binary"
            else content.ascii_stl(triangles=120)
        )
        before = source.read_bytes()
        reads = count_source_reads(source, fail_after_bytes=134)
        limits = STLReadLimits(chunk_triangles=1)

        if consumer == "scan":
            with pytest.raises(OSError, match="injected source read failure"):
                scan_stl(source, limits=limits)
        elif consumer == "sample":
            assert (
                stl_fallback.sample_stl_geometry(source, max_triangles=1, limits=limits)
                is None
            )
        else:
            assert mesh_processing._load_mesh(source) is None

        assert sum(reads) >= 134
        assert source.stat().st_size == len(before)


class TestCanonicalSTLRefusals:
    @pytest.mark.parametrize("consumer", ["sample", "materialize"])
    @pytest.mark.parametrize("failure", ["invalid", "budget", "changed"])
    def test_retains_canonical_refusal_category(
        self, tmp_path: Path, monkeypatch, consumer: str, failure: str
    ):
        from app.modules.media import stl_reader

        source = tmp_path / "canonical-refusal.stl"
        body = content.binary_stl_facets(FACETS)
        source.write_bytes(body + b"trailing" if failure == "invalid" else body)
        limits = stl_reader.STLReadLimits(max_triangles=1 if failure == "budget" else 2)
        expected = {
            "invalid": stl_reader.STLReadFailure.INVALID_SOURCE,
            "budget": stl_reader.STLReadFailure.RESOURCE_LIMIT,
            "changed": stl_reader.STLReadFailure.SOURCE_CHANGED,
        }[failure]
        if failure == "changed":
            real_snapshot = stl_reader.snapshot_stl

            def replace_after_snapshot(path):
                snapshot = real_snapshot(path)
                replacement = tmp_path / "replacement.stl"
                replacement.write_bytes(body)
                replacement.replace(path)
                return snapshot

            owner = stl_fallback if consumer == "sample" else stl_reader
            monkeypatch.setattr(owner, "snapshot_stl", replace_after_snapshot)

        with pytest.raises(stl_reader.InvalidSTL) as caught:
            if consumer == "sample":
                stl_fallback.read_stl_sample(source, max_triangles=1, limits=limits)
            else:
                stl_reader.materialize_stl(source, limits=limits)
        assert caught.value.reason is expected
