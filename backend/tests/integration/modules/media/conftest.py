"""Observe real source I/O without replacing geometry parsing or rendering."""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def count_source_reads(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[int]]:
    def observe(source: Path, *, fail_after_bytes: int | None = None) -> list[int]:
        reads: list[int] = []
        original_open = Path.open

        class MeteredReader(io.BufferedReader):
            def __init__(self, raw: io.RawIOBase) -> None:
                super().__init__(raw)
                self.index = len(reads)
                reads.append(0)

            def _check_failure(self) -> None:
                if (
                    fail_after_bytes is not None
                    and reads[self.index] >= fail_after_bytes
                ):
                    raise OSError("injected source read failure")

            def read(self, size: int = -1) -> bytes:
                self._check_failure()
                data = super().read(size)
                reads[self.index] += len(data)
                return data

            def readline(self, size: int = -1) -> bytes:
                self._check_failure()
                data = super().readline(size)
                reads[self.index] += len(data)
                return data

        def open_source(path: Path, mode: str = "r", *args, **kwargs):
            stream = original_open(path, mode, *args, **kwargs)
            if path == source and mode == "rb":
                return MeteredReader(stream.detach())
            return stream

        monkeypatch.setattr(Path, "open", open_source)
        return reads

    return observe
