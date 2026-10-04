"""Bounded STL blocks with a single binary/ASCII interpretation policy.

Binary sources must contain exactly their declared records, including headers
beginning with ``solid``. ASCII accepts complete facets without ``endsolid``,
ignores blank/comment lines, and rejects content after ``endsolid``. A complete
scan certifies source coverage, never closed topology or enclosed volume.
"""

from __future__ import annotations

import math
import os
import struct
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Iterator

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

_BINARY_HEADER_BYTES = 84
_BINARY_RECORD_BYTES = 50
_FLOAT32_MAX = 3.4028234663852886e38


class STLReadFailure(str, Enum):
    INVALID_SOURCE = "invalid_source"
    RESOURCE_LIMIT = "resource_limit"
    SOURCE_CHANGED = "source_changed"


class InvalidSTL(Exception):
    reason = STLReadFailure.INVALID_SOURCE


class STLBudgetExceeded(InvalidSTL):
    reason = STLReadFailure.RESOURCE_LIMIT


class STLSourceChanged(InvalidSTL):
    reason = STLReadFailure.SOURCE_CHANGED


class _FacetState(str, Enum):
    OUTSIDE = "outside"
    FACET = "facet"
    LOOP = "loop"
    END_LOOP = "endloop"
    END_FACET = "endfacet"


class STLFormat(str, Enum):
    BINARY = "binary"
    ASCII = "ascii"


@dataclass(frozen=True)
class STLReadLimits:
    max_triangles: int = 20_000_000
    max_source_bytes: int = 1 << 30
    chunk_triangles: int = 8192
    max_lines: int = 10_000_000
    max_line_bytes: int = 64 * 1024
    deadline: float = field(default_factory=lambda: time.monotonic() + 45)

    def __post_init__(self) -> None:
        for name in (
            "max_triangles",
            "max_source_bytes",
            "chunk_triangles",
            "max_lines",
            "max_line_bytes",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.chunk_triangles > 8192:
            raise ValueError("chunk_triangles exceeds hard cap")
        if not math.isfinite(self.deadline):
            raise ValueError("deadline must be finite")


@dataclass(frozen=True)
class STLMeasurements:
    triangle_count: int
    scanned_bytes: int
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]


def check_deadline(limits: STLReadLimits) -> None:
    if time.monotonic() >= limits.deadline:
        raise STLBudgetExceeded("deadline")


def _identity(stat: os.stat_result) -> tuple[int, int, int, int, int]:
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def binary_stl_info(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as stream:
            size = os.fstat(stream.fileno()).st_size
            header = stream.read(_BINARY_HEADER_BYTES)
        if len(header) != _BINARY_HEADER_BYTES:
            return None
        count = struct.unpack_from("<I", header, 80)[0]
        if (
            not 0 < count <= 20_000_000
            or size != _BINARY_HEADER_BYTES + count * _BINARY_RECORD_BYTES
        ):
            return None
        return count, size
    except (OSError, struct.error):
        return None


def valid_stl_value(value: float) -> bool:
    return math.isfinite(value) and abs(value) <= _FLOAT32_MAX


def parse_stl_float(token: str) -> float:
    try:
        value = float(token)
    except ValueError as exc:
        raise InvalidSTL("invalid number") from exc
    if not valid_stl_value(value):
        raise InvalidSTL("non-finite coordinate")
    return value


def _iter_ascii_facets(
    stream: BinaryIO, limits: STLReadLimits
) -> Iterator[tuple[tuple[float, float, float], ...]]:
    state = _FacetState.OUTSIDE
    vertices: list[tuple[float, float, float]] = []
    lines = 0
    scanned = 0
    saw_facet = False
    ended = False
    while True:
        check_deadline(limits)
        raw = stream.readline(limits.max_line_bytes + 1)
        if not raw:
            break
        scanned += len(raw)
        lines += 1
        if lines > limits.max_lines:
            raise STLBudgetExceeded("line budget")
        if scanned > limits.max_source_bytes:
            raise STLBudgetExceeded("source budget")
        if len(raw) > limits.max_line_bytes:
            raise STLBudgetExceeded("line too long")
        try:
            text = raw.decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise InvalidSTL("non-ascii input") from exc
        if not text or text.startswith("#") or text.startswith("//"):
            continue
        parts = text.split()
        keyword = parts[0].lower()
        if state is _FacetState.OUTSIDE:
            if ended:
                raise InvalidSTL("content after endsolid")
            if keyword == "solid":
                continue
            if keyword == "facet":
                if len(parts) != 5 or parts[1].lower() != "normal":
                    raise InvalidSTL("invalid facet normal")
                for token in parts[2:]:
                    parse_stl_float(token)
                state = _FacetState.FACET
                saw_facet = True
                continue
            if keyword == "endsolid":
                ended = True
                continue
            raise InvalidSTL("unexpected ASCII STL token")
        if state is _FacetState.FACET:
            if keyword != "outer" or len(parts) != 2 or parts[1].lower() != "loop":
                raise InvalidSTL("missing outer loop")
            vertices = []
            state = _FacetState.LOOP
            continue
        if state is _FacetState.LOOP:
            if keyword != "vertex" or len(parts) != 4:
                raise InvalidSTL("invalid vertex")
            vertices.append(
                (
                    parse_stl_float(parts[1]),
                    parse_stl_float(parts[2]),
                    parse_stl_float(parts[3]),
                )
            )
            if len(vertices) > 3:
                raise InvalidSTL("too many vertices")
            if len(vertices) == 3:
                state = _FacetState.END_LOOP
            continue
        if state is _FacetState.END_LOOP:
            if keyword != "endloop" or len(parts) != 1:
                raise InvalidSTL("missing endloop")
            state = _FacetState.END_FACET
            continue
        if state is _FacetState.END_FACET:
            if keyword != "endfacet" or len(parts) != 1:
                raise InvalidSTL("missing endfacet")
            yield (vertices[0], vertices[1], vertices[2])
            vertices = []
            state = _FacetState.OUTSIDE
            continue
    # ``endsolid`` is required by the formal grammar but a number of slicers
    # omit it while still emitting complete facets. EOF at a facet boundary is
    # unambiguous and safe to accept; an unfinished loop/facet remains invalid.
    if state is not _FacetState.OUTSIDE or not saw_facet:
        raise InvalidSTL("truncated ASCII STL")


def iter_stl_blocks(
    path: Path,
    limits: STLReadLimits,
    *,
    source_format: STLFormat | None = None,
) -> Iterator[NDArray[np.float64]]:
    """Yield bounded float64 source facets; certify the snapshot only at EOF."""
    import numpy as np

    with path.open("rb") as stream:
        before = _identity(os.fstat(stream.fileno()))
        if before != _identity(path.stat()):
            raise STLSourceChanged("source changed while opening")
        size = before[2]
        if size > limits.max_source_bytes:
            raise STLBudgetExceeded("source budget")
        header = stream.read(_BINARY_HEADER_BYTES)
        count = (
            struct.unpack_from("<I", header, 80)[0]
            if len(header) == _BINARY_HEADER_BYTES
            else 0
        )
        binary = (
            count > 0 and size == _BINARY_HEADER_BYTES + count * _BINARY_RECORD_BYTES
        )
        if source_format is STLFormat.BINARY and not binary:
            raise InvalidSTL("not an exact binary STL")
        if source_format is STLFormat.ASCII:
            binary = False
        if binary:
            if count > limits.max_triangles:
                raise STLBudgetExceeded("triangle budget")
            dtype = np.dtype(
                [
                    ("normal", "<f4", (3,)),
                    ("vertices", "<f4", (3, 3)),
                    ("attribute", "<u2"),
                ]
            )
            parsed = 0
            while parsed < count:
                check_deadline(limits)
                chunk_count = min(limits.chunk_triangles, count - parsed)
                raw = stream.read(chunk_count * _BINARY_RECORD_BYTES)
                if len(raw) != chunk_count * _BINARY_RECORD_BYTES:
                    raise InvalidSTL("truncated record")
                vertices = np.frombuffer(raw, dtype=dtype)["vertices"].astype(
                    np.float64
                )
                if not np.isfinite(vertices).all():
                    raise InvalidSTL("non-finite coordinate")
                parsed += chunk_count
                yield vertices
            if stream.read(1):
                raise InvalidSTL("content after binary records")
        else:
            stream.seek(0)
            batch: list[tuple[tuple[float, float, float], ...]] = []
            parsed = 0
            for facet in _iter_ascii_facets(stream, limits):
                parsed += 1
                if parsed > limits.max_triangles:
                    raise STLBudgetExceeded("triangle budget")
                batch.append(facet)
                if len(batch) == limits.chunk_triangles:
                    yield np.asarray(batch, dtype=np.float64)
                    batch.clear()
            if batch:
                yield np.asarray(batch, dtype=np.float64)
        if before != _identity(os.fstat(stream.fileno())) or before != _identity(
            path.stat()
        ):
            raise STLSourceChanged("source changed while reading")


def scan_stl(
    path: Path,
    *,
    limits: STLReadLimits | None = None,
    source_format: STLFormat | None = None,
) -> STLMeasurements:
    """Return exact source bounds/count after a complete, stable bounded read."""
    import numpy as np

    source = _identity(path.stat())
    lower = np.full(3, np.inf, dtype=np.float64)
    upper = np.full(3, -np.inf, dtype=np.float64)
    parsed = 0
    for vertices in iter_stl_blocks(
        path,
        limits if limits is not None else STLReadLimits(),
        source_format=source_format,
    ):
        lower = np.minimum(lower, vertices.min(axis=(0, 1)))
        upper = np.maximum(upper, vertices.max(axis=(0, 1)))
        parsed += len(vertices)
    if source != _identity(path.stat()):
        raise STLSourceChanged("source changed before completing scan")
    return STLMeasurements(
        triangle_count=parsed,
        scanned_bytes=source[2],
        bounds_min=(float(lower[0]), float(lower[1]), float(lower[2])),
        bounds_max=(float(upper[0]), float(upper[1]), float(upper[2])),
    )
