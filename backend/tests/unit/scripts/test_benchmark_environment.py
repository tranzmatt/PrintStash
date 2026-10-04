"""Benchmark evidence distinguishes measured constraints from unknown values."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import benchmark_environment


class TestCgroupLimits:
    def test_reads_effective_ancestor_limits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "cgroup"
        group = root / "worker"
        group.mkdir(parents=True)
        (root / "cpu.max").write_text("100000 100000")
        (root / "memory.max").write_text("1048576")
        (group / "cpu.max").write_text("max 100000")
        (group / "memory.max").write_text("2097152")
        proc = tmp_path / "self-cgroup"
        proc.write_text("0::/worker\n")
        monkeypatch.setattr(benchmark_environment, "CGROUP_ROOT", root)
        monkeypatch.setattr(benchmark_environment, "SELF_CGROUP", proc)

        result = benchmark_environment.cgroup_limits()

        assert result.cpu_quota_cores == 1.0
        assert result.memory_limit_bytes == 1048576
        assert result.cpu_limit_read is True
        assert result.memory_limit_read is True

    def test_preserves_unavailable_constraints(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(benchmark_environment, "CGROUP_ROOT", tmp_path / "absent")
        monkeypatch.setattr(benchmark_environment, "SELF_CGROUP", tmp_path / "missing")

        result = benchmark_environment.cgroup_limits()

        assert result.cpu_quota_cores is None
        assert result.memory_limit_bytes is None
        assert result.cpu_limit_read is False
        assert result.memory_limit_read is False

    def test_distinguishes_unlimited_constraints(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "cpu.max").write_text("max 100000")
        (tmp_path / "memory.max").write_text("max")
        monkeypatch.setattr(benchmark_environment, "CGROUP_ROOT", tmp_path)
        monkeypatch.setattr(benchmark_environment, "SELF_CGROUP", tmp_path / "missing")

        result = benchmark_environment.cgroup_limits()

        assert result.cpu_quota_cores is None
        assert result.memory_limit_bytes is None
        assert result.cpu_limit_read is True
        assert result.memory_limit_read is True

    def test_reads_conventional_v1_limits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "cpu").mkdir()
        (tmp_path / "memory").mkdir()
        (tmp_path / "cpu/cpu.cfs_quota_us").write_text("50000")
        (tmp_path / "cpu/cpu.cfs_period_us").write_text("100000")
        (tmp_path / "memory/memory.limit_in_bytes").write_text("1048576")
        monkeypatch.setattr(benchmark_environment, "CGROUP_ROOT", tmp_path)
        monkeypatch.setattr(benchmark_environment, "SELF_CGROUP", tmp_path / "missing")

        result = benchmark_environment.cgroup_limits()

        assert result.cpu_quota_cores == 0.5
        assert result.memory_limit_bytes == 1048576

    def test_preserves_malformed_constraints_as_unknown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "cpu.max").write_text("malformed 0")
        (tmp_path / "memory.max").write_text("malformed")
        monkeypatch.setattr(benchmark_environment, "CGROUP_ROOT", tmp_path)
        monkeypatch.setattr(benchmark_environment, "SELF_CGROUP", tmp_path / "missing")

        result = benchmark_environment.cgroup_limits()

        assert result.cpu_limit_read is False
        assert result.memory_limit_read is False


class TestCollectEnvironment:
    def test_records_versions_without_claiming_performance_qualification(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENBLAS_NUM_THREADS", "1")

        result = benchmark_environment.collect_environment()

        assert result.python_version
        assert result.versions["numpy"]
        assert result.versions["trimesh"]
        assert result.thread_environment["OPENBLAS_NUM_THREADS"] == "1"
        assert result.performance_gate_qualified is False
        assert len(result.commit) == 40

    def test_preserves_unavailable_git_identity(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def missing_git(*args, **kwargs):
            raise FileNotFoundError("git unavailable")

        monkeypatch.setattr(benchmark_environment.subprocess, "run", missing_git)
        result = benchmark_environment.collect_environment()

        assert result.commit is None
        assert result.working_tree_dirty is None
