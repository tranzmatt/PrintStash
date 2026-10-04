"""Mesh admission, resource budgets and reclamation shared by native consumers.

This owner holds the one mutable admission gate and cached detected ceiling.
It does not parse geometry or select thumbnail strategies.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import gc
import struct
import threading
import zipfile
from pathlib import Path, PurePosixPath
from typing import Literal, Optional

from printstash_core.mesh.similarity.budgets import MAX_ANALYSIS_FACES

from app.core.cancellation import checkpoint
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)
_LIBC: ctypes.CDLL | Literal[False] | None = None
_RENDER_SEMAPHORE: RenderAdmission | None = None
_RENDER_SEMAPHORE_LOCK = threading.Lock()
_PEAK_BYTES_PER_TRIANGLE: dict[str, int] = {".3mf": 3600}
_DEFAULT_PEAK_BYTES_PER_TRIANGLE = 2200
_MEMORY_LIMIT_BYTES: int | Literal[False] | None = None


def reclaim_memory() -> None:
    """Force Python + the allocator to give a just-freed mesh back to the OS.

    Loading and rasterising a mesh churns hundreds of MB of NumPy/trimesh arrays.
    Dropping the references frees them on the Python heap, but glibc keeps the
    emptied arenas mapped, so across a long library scan RSS only ever climbs and
    never recedes — which presents exactly as a memory leak (#29). A
    ``gc.collect()`` breaks any reference cycles the mesh held, and
    ``malloc_trim(0)`` returns the freed arenas to the kernel so the high-water
    mark resets between files. Best-effort: a no-op where malloc_trim is absent.
    """
    gc.collect()
    global _LIBC
    try:
        if _LIBC is None:
            libc_name = ctypes.util.find_library("c")
            _LIBC = ctypes.CDLL(libc_name) if libc_name else False
        if _LIBC and hasattr(_LIBC, "malloc_trim"):
            _LIBC.malloc_trim(0)
    except (OSError, AttributeError):  # pragma: no cover - platform dependent
        _LIBC = False


class RenderAdmission:
    """One admission controller, including while administrators change its limit.

    A new allocation split becomes effective after old admissions drain. Mixing
    old large shares with new small ones could otherwise exceed the total budget.
    Nested work in the same thread consumes the existing admission.
    """

    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.active = 0
        self.limit = 1
        self.requested = 1
        self.local = threading.local()

    def configure(self, limit: int) -> None:
        with self.condition:
            self.requested = limit
            self.condition.notify_all()

    def __enter__(self) -> RenderAdmission:
        depth = getattr(self.local, "depth", 0)
        if depth:
            self.local.depth = depth + 1
            return self
        while True:
            # A checkpoint may consult durable job state. Never hold the
            # admission lock while that external operation blocks.
            checkpoint()
            with self.condition:
                if self.active == 0:
                    self.limit = self.requested
                if self.limit == self.requested and self.active < self.limit:
                    self.active += 1
                    self.local.depth = 1
                    self.local.limit = self.limit
                    return self
                self.condition.wait(0.1)

    def __exit__(self, *_args: object) -> None:
        self.local.depth -= 1
        if self.local.depth:
            return
        with self.condition:
            self.active -= 1
            self.condition.notify_all()


def _configured_render_jobs() -> int:
    try:
        return max(int(settings.max_render_jobs), 1)
    except (TypeError, ValueError):
        return 1


def render_jobs_limit() -> int:
    """The allocation split belonging to this thread's admission."""
    gate = _RENDER_SEMAPHORE
    if gate is not None and getattr(gate.local, "depth", 0):
        return gate.local.limit
    return _configured_render_jobs()


def render_admission() -> RenderAdmission:
    global _RENDER_SEMAPHORE
    with _RENDER_SEMAPHORE_LOCK:
        if _RENDER_SEMAPHORE is None:
            _RENDER_SEMAPHORE = RenderAdmission()
        _RENDER_SEMAPHORE.configure(_configured_render_jobs())
        return _RENDER_SEMAPHORE


def canonical_suffix(path: Path, file_type: str | None = None) -> str:
    """Return the source suffix even when *path* is an FD-backed alias.

    External-library scans deliberately read through ``/proc/self/fd`` so a
    mount replacement cannot change the bytes being processed.  Those aliases
    have no filename suffix, so callers that know the catalogued type pass it
    explicitly here.
    """
    if file_type is None:
        return path.suffix.lower()
    suffix = str(file_type).lower()
    return suffix if suffix.startswith(".") else f".{suffix}"


def estimate_triangle_count(
    path: Path, *, file_type: str | None = None
) -> Optional[int]:
    """Best-effort triangle count *without* loading the mesh into memory.

    Loading is itself the memory blow-up (trimesh.load_mesh of a 5M-triangle mesh
    peaks at ~3.5 GB), so the only way to keep a dense lattice/gyroid model from
    OOM-killing the process is to estimate before we load and bail out (#24).

    Exact for binary STL (the triangle count is a uint32 in the header) and for
    PLY (the face count is declared in the ASCII header); a face-directive count
    for OBJ; a size-based estimate for ASCII STL and 3MF (uncompressed mesh XML).
    For an STL that fails the exact binary size check we distinguish ASCII from a
    binary file with trailing bytes and pick the *conservative* density, so we
    never underestimate a binary mesh into an unsafe load. Returns None for
    formats we can't cheaply size up (incl. STEP, which trimesh can't mesh
    without optional CAD deps anyway) — the caller then relies on the post-load
    cap, which still skips the render.
    """
    suffix = canonical_suffix(path, file_type)
    try:
        if suffix == ".stl":
            size = path.stat().st_size
            with path.open("rb") as fh:
                sample = fh.read(1024)
            if len(sample) >= 84:
                count = struct.unpack("<I", sample[80:84])[0]
                # Binary STL is exactly 84 + 50 bytes per triangle; if the math
                # checks out we trust the header count exactly.
                if size == 84 + count * 50:
                    return count
            # The exact binary check failed. Now disambiguate a true ASCII STL
            # from a binary STL with trailing bytes (which also fails the check).
            # Guessing wrong toward ASCII is dangerous: ASCII is ~250 B/triangle
            # but binary is only ~50 B/triangle, so an ASCII estimate of a binary
            # file underestimates 5x and can let an over-cap mesh slip through to
            # the exact OOM load #24 set out to prevent. An ASCII STL starts with
            # the text "solid" and contains no NUL bytes; binary headers do.
            looks_ascii = (
                sample[:6].lower().startswith(b"solid") and b"\x00" not in sample
            )
            if looks_ascii:
                # ASCII STL: ~7 lines / ~250 bytes per triangle.
                return size // 250
            # Binary STL body is exactly 50 bytes per facet after the 84-byte
            # header; this stays a safe upper bound even with trailing bytes.
            return max(size - 84, 0) // 50
        if suffix == ".ply":
            # The PLY header is ASCII even when the body is binary, and it
            # declares the face count up front ("element face N"), so we can size
            # the mesh without parsing the (possibly huge) body.
            with path.open("rb") as fh:
                for _ in range(256):  # headers are short; bound the scan
                    line = fh.readline()
                    if not line:
                        break
                    parts = line.split()
                    if (
                        len(parts) >= 3
                        and parts[0].lower() == b"element"
                        and parts[1].lower() == b"face"
                    ):
                        try:
                            return int(parts[2])
                        except ValueError:
                            return None
                    if parts and parts[0].lower() == b"end_header":
                        break
            return None
        if suffix == ".obj":
            # OBJ is plain text; each "f " line is one face. trimesh triangulates
            # an n-gon face into (n - 2) triangles, so summing that keeps the
            # estimate a conservative upper bound (tris/quads dominate real files,
            # where it's already exact). A full text scan is cheap — no float
            # parsing, no mesh build — versus the trimesh.load_mesh it guards against.
            faces = 0
            with path.open("rb") as fh:
                for line in fh:
                    if not line.startswith(b"f ") and not line.startswith(b"f\t"):
                        continue
                    # vertex refs on the line, minus 2 = triangles after fan
                    # triangulation; clamp at 1 so a malformed face never
                    # subtracts from the count.
                    verts = len(line.split()) - 1
                    faces += max(verts - 2, 1)
            return faces or None
        if suffix == ".3mf":
            with zipfile.ZipFile(path) as zf:
                infos = zf.infolist()
                xml_bytes = sum(
                    info.file_size
                    for info in infos
                    if info.filename.lower().endswith(".model")
                )
                if not xml_bytes:
                    # Some 3MF variants keep the mesh outside a ".model" part (or
                    # name it unusually). Rather than return None and let the
                    # caller load a possibly-huge archive blind (#29), fall back to
                    # the total uncompressed payload as a conservative upper bound.
                    xml_bytes = sum(info.file_size for info in infos)
            # 3MF mesh XML runs ~70 bytes per <triangle> (verts are shared).
            return xml_bytes // 70 if xml_bytes else None
    except (OSError, zipfile.BadZipFile, struct.error):
        return None
    return None


def detect_memory_limit_bytes() -> int | None:
    """Best-effort bytes of RAM the process may use before being OOM-killed.

    Container-aware: a Docker/NAS deployment is usually capped well below host
    RAM by its cgroup, and that limit — not the host's total — is what the kernel
    enforces. Takes the smallest of the cgroup limit (v2 then v1) and host
    ``MemTotal`` so the RAM-aware cap reflects the real ceiling. Returns None when
    nothing can be read (non-Linux, locked-down /proc), disabling the RAM cap.
    """
    limits: list[int] = []
    try:  # cgroup v2
        raw = Path("/sys/fs/cgroup/memory.max").read_text().strip()
        if raw != "max":
            limits.append(int(raw))
    except (OSError, ValueError):
        pass
    # On a host service the cgroup filesystem is mounted above this process's
    # group. Reading only its root misses MemoryMax on the service or a parent
    # slice. Containers with a cgroup namespace already expose their group at /.
    try:
        root = Path("/sys/fs/cgroup")
        for line in Path("/proc/self/cgroup").read_text().splitlines():
            if not line.startswith("0::/"):
                continue
            parts = PurePosixPath(line[3:]).parts[1:]
            if len(parts) > 128 or any(part in (".", "..") for part in parts):
                continue
            group = root.joinpath(*parts)
            while group != root:
                try:
                    value = int((group / "memory.max").read_text().strip())
                    if value > 0:
                        limits.append(value)
                except (OSError, ValueError):
                    pass
                group = group.parent
    except OSError:
        pass
    try:  # cgroup v1
        v1 = int(
            Path("/sys/fs/cgroup/memory/memory.limit_in_bytes").read_text().strip()
        )
        if 0 < v1 < (1 << 62):  # v1 uses a huge sentinel for "unlimited"
            limits.append(v1)
    except (OSError, ValueError):
        pass
    try:  # host total
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                limits.append(int(line.split()[1]) * 1024)
                break
    except (OSError, ValueError, IndexError):
        pass
    return min(limits) if limits else None


def ram_triangle_cap(suffix: str) -> Optional[int]:
    """RAM-derived triangle ceiling for *suffix*, or None when RAM capping is off.

    Turns the ``mesh_memory_budget_fraction`` of detected memory into a triangle
    count using the format's measured per-triangle peak cost, so the same config
    auto-skips a mesh on a 4 GB box that a 32 GB box renders fine. The budget is
    divided by ``max_render_jobs`` so concurrent renders share the RAM ceiling
    rather than each claiming the whole of it (#29)."""
    fraction = settings.mesh_memory_budget_fraction
    if fraction <= 0:
        return None
    global _MEMORY_LIMIT_BYTES
    if _MEMORY_LIMIT_BYTES is None:
        _MEMORY_LIMIT_BYTES = detect_memory_limit_bytes() or False
    if not _MEMORY_LIMIT_BYTES:
        return None
    budget = _MEMORY_LIMIT_BYTES * fraction / render_jobs_limit()
    per_tri = _PEAK_BYTES_PER_TRIANGLE.get(suffix, _DEFAULT_PEAK_BYTES_PER_TRIANGLE)
    return max(int(budget / per_tri), 1)


def load_face_budget(suffix: str) -> int:
    """Faces a loader may admit for *suffix*: the static, analysis and RAM ceilings.

    The single answer for every path that parses a mesh into memory, so a caller
    cannot pick a looser bound than the one the thumbnail engine enforces.
    """
    budget = min(int(settings.mesh_max_render_triangles), MAX_ANALYSIS_FACES)
    ram_cap = ram_triangle_cap(suffix)
    return budget if ram_cap is None else min(budget, ram_cap)


def exceeds_cap(path: Path, *, file_type: str | None = None) -> bool:
    """True when *path* is too expensive to hand to trimesh (#24, #29).

    Centralises the "bail out before loading" guard so every entry point
    (analyze/geometry/thumbnail/export) skips the same monster meshes and logs
    consistently. Two independent ceilings, because each covers the other's blind
    spot:

    * A raw on-disk **size** cap (``mesh_max_load_mb``). Format-blind, so it
      catches the files the triangle estimate can't size up — a 3MF whose mesh
      the estimator doesn't sum returns ``None`` below, and the old code then
      loaded the whole archive and OOM-killed the scan inside trimesh (#29).
    * The **triangle** estimate vs. ``mesh_max_render_triangles`` (#24), which
      catches a dense lattice/gyroid that is small on disk but explodes on load.

    Returns True if either ceiling is exceeded; the file is still indexed and a
    3MF still falls back to its embedded preview.
    """
    size_cap_mb = settings.mesh_max_load_mb
    size_known = False
    if size_cap_mb > 0:
        try:
            size_mb = path.stat().st_size / (1024 * 1024)
            size_known = True
        except OSError:
            size_mb = 0.0
        if size_mb > size_cap_mb:
            logger.warning(
                "mesh_processing: %s is %.0f MB (> cap %d MB); skipping mesh load "
                "to avoid OOM",
                path.name,
                size_mb,
                size_cap_mb,
            )
            return True

    suffix = canonical_suffix(path, file_type)
    if file_type is None:
        estimate = estimate_triangle_count(path)
    else:
        estimate = estimate_triangle_count(path, file_type=suffix)
    if estimate is None:
        # An unknown estimate may use the full loader only when a successful
        # stat has already proved that the source is inside the byte budget.
        # A disabled byte cap or unreadable stat is not permission for an
        # unbounded allocation; STL can continue through the isolated streamer.
        return not size_known
    # Effective cap = the smaller of the static ceiling and the RAM-derived cap,
    # so a small host auto-skips meshes a large host would render (#29).
    cap = settings.mesh_max_render_triangles
    ram_cap = ram_triangle_cap(suffix)
    if ram_cap is not None and ram_cap < cap:
        cap = ram_cap
        limiter = "RAM budget"
    else:
        limiter = "static cap"
    if estimate > cap:
        logger.warning(
            "mesh_processing: %s is ~%d triangles (> %s %d); skipping mesh load "
            "to avoid OOM",
            path.name,
            estimate,
            limiter,
            cap,
        )
        return True
    return False


def process_rss_bytes(pid: int) -> int | None:
    """Read one Linux process's resident set; unavailable platforms return None."""

    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def step_memory_budget_bytes() -> int | None:
    limit = detect_memory_limit_bytes()
    fraction = settings.mesh_memory_budget_fraction
    if limit is None:
        return None
    # Zero disables triangle estimation, never containment.
    safety_fraction = fraction if fraction > 0 else 0.5
    return max(int(limit * safety_fraction / render_jobs_limit()), 1)


def process_tree_rss_bytes(pid: int) -> int | None:
    """Resident memory of an admitted worker including its descendants."""
    pending = [pid]
    seen: set[int] = set()
    total = 0
    found = False
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        rss = process_rss_bytes(current)
        if rss is not None:
            total += rss
            found = True
        try:
            pending.extend(
                int(value)
                for value in Path(f"/proc/{current}/task/{current}/children")
                .read_text()
                .split()
            )
        except (OSError, ValueError):
            # A process can exit between the two reads.
            continue
    return total if found else None


def native_memory_budget_bytes() -> int:
    """The render-step RSS policy, applied to one native worker process.

    Bounded even when automatic geometry RAM caps are disabled on a platform
    where cgroup or host memory cannot be detected. Embedding and search-view
    workers are killed past it.
    """
    return min(
        step_memory_budget_bytes() or 1024**3 // render_jobs_limit(), 2 * 1024**3
    )
