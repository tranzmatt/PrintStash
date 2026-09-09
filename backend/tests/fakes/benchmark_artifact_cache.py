"""Repeatable filesystem-cache measurements; run as a module, not a CI timing gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock

from app.modules.storage.artifact_materializer import (
    ArtifactMaterializer,
    CachePolicy,
    Representation,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mib", type=int, default=64)
    parser.add_argument("--callers", type=int, default=8)
    parser.add_argument("--entries", type=int, default=1000)
    args = parser.parse_args()
    chunk = b"x" * (1024 * 1024)
    digest = hashlib.sha256()
    for _ in range(args.mib):
        digest.update(chunk)
    size = len(chunk) * args.mib
    representation = Representation("artifact", 1, digest.hexdigest(), size)
    transferred = 0
    counter_lock = Lock()

    def source():
        nonlocal transferred
        for _ in range(args.mib):
            with counter_lock:
                transferred += len(chunk)
            yield chunk

    with tempfile.TemporaryDirectory(prefix="printstash-cache-benchmark-") as directory:
        policy = CachePolicy(
            enabled=True,
            max_bytes=3 * size,
            max_entries=args.entries + 10,
            headroom_bytes=0,
        )
        cache = ArtifactMaterializer(Path(directory), lambda: policy)
        tracemalloc.start()
        started = time.perf_counter()
        with cache.materialize(representation, source) as path:
            assert path.stat().st_size == size
        cold_seconds = time.perf_counter() - started
        started = time.perf_counter()
        before = transferred
        with cache.materialize(representation, source) as path:
            assert path.stat().st_size == size
        hot_seconds = time.perf_counter() - started
        hot_provider_bytes = transferred - before
        concurrent = Representation("artifact", 2, representation.sha256, size)
        barrier = Barrier(args.callers)

        def reader(_):
            barrier.wait()
            with cache.materialize(concurrent, source) as path:
                assert path.stat().st_size == size

        before = transferred
        started = time.perf_counter()
        with ThreadPoolExecutor(args.callers) as pool:
            list(pool.map(reader, range(args.callers)))
        stampede_seconds = time.perf_counter() - started
        stampede_provider_bytes = transferred - before
        _, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        started = time.perf_counter()
        for index in range(args.entries):
            payload = str(index).encode()
            entry = Representation(
                "derived", 1, hashlib.sha256(payload).hexdigest(), len(payload)
            )
            with cache.materialize(entry, lambda payload=payload: iter([payload])):
                pass
        population_seconds = time.perf_counter() - started
        index_bytes = sum(
            path.stat().st_size for path in cache.root.glob("index.sqlite3*")
        )
        policy = CachePolicy(enabled=True, max_bytes=0, max_entries=0, headroom_bytes=0)
        started = time.perf_counter()
        cache.trim()
        eviction_seconds = time.perf_counter() - started
        assert cache.status()["bytes"] == 0
        assert hot_provider_bytes == 0
        assert stampede_provider_bytes == size
        print(
            json.dumps(
                {
                    "representation_bytes": size,
                    "cold_seconds": round(cold_seconds, 4),
                    "hot_seconds": round(hot_seconds, 4),
                    "hot_provider_bytes": hot_provider_bytes,
                    "callers": args.callers,
                    "stampede_seconds": round(stampede_seconds, 4),
                    "stampede_provider_bytes": stampede_provider_bytes,
                    "peak_traced_bytes": peak_memory,
                    "entry_count": args.entries + 2,
                    "population_seconds": round(population_seconds, 4),
                    "index_bytes": index_bytes,
                    "eviction_seconds": round(eviction_seconds, 4),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
