"""Cached paths stay verified and available until their last consumer closes."""
from __future__ import annotations

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest

from app.modules.storage.artifact_materializer import (
    ArtifactMaterializer, CachePolicy, CacheUnavailable, Representation, RepresentationChanged,
)


@pytest.fixture
def cache(tmp_path):
    return ArtifactMaterializer(tmp_path / "cache", lambda: CachePolicy(enabled=True, headroom_bytes=0))


@pytest.fixture
def representation():
    payload = b"verified bytes"
    return Representation("artifact", 1, hashlib.sha256(payload).hexdigest(), len(payload))


class TestArtifactMaterializer:
    def test_reuses_verified_materialization(self, cache, representation):
        transferred = bytearray()
        def source():
            transferred.extend(b"verified bytes")
            yield b"verified bytes"
        with cache.materialize(representation, source) as path:
            assert path.read_bytes() == b"verified bytes"
        with cache.materialize(representation, source) as path:
            assert path.read_bytes() == b"verified bytes"
        assert transferred == b"verified bytes"

    def test_preserves_selection_before_open(self, cache, representation):
        with cache.materialize(representation, lambda: iter([b"verified bytes"])):
            pass
        lease = cache.acquire(representation)
        cache.clear()
        assert lease.path.read_bytes() == b"verified bytes"
        lease.close()
        assert not lease.path.exists()

    def test_accounts_for_bytes_until_lease_release(self, cache, representation):
        with cache.materialize(representation, lambda: iter([b"verified bytes"])):
            assert cache.clear()["bytes"] == representation.size
        assert cache.status()["bytes"] == 0

    @pytest.mark.parametrize("payload", [pytest.param(b"short", id="short"), pytest.param(b"incorrect byte", id="digest"), pytest.param(b"way too many unexpected bytes", id="oversize")])
    def test_rejects_corrupt_fill(self, cache, representation, payload):
        with pytest.raises(RepresentationChanged, match="representation"):
            with cache.materialize(representation, lambda: iter([payload])):
                pytest.fail("exposed corrupt content")
        assert cache.status()["entries"] == 0
        assert list(cache.root.glob("*.tmp")) == []

    def test_discards_interrupted_fill(self, cache, representation):
        fill = cache.begin_fill(representation)
        fill.write(b"verified")
        fill.close()
        assert cache.acquire(representation) is None
        assert cache.status()["reserved_bytes"] == 0

    def test_rejects_corrupt_hit(self, cache, representation):
        with cache.materialize(representation, lambda: iter([b"verified bytes"])) as path:
            pass
        path.write_bytes(b"incorrect byte")
        assert cache.acquire(representation) is None
        assert cache.status()["errors"] == 1

    def test_separates_representation_versions(self, cache, representation):
        with cache.materialize(representation, lambda: iter([b"verified bytes"])):
            pass
        assert cache.acquire(replace(representation, version=2)) is None

    def test_clear_revokes_active_fill(self, cache, representation):
        fill = cache.begin_fill(representation)
        fill.write(b"verified bytes")
        cache.clear()
        assert fill.complete() is None
        fill.close()
        assert cache.status()["entries"] == 0

    def test_disable_preserves_existing_lease(self, cache, representation):
        with cache.materialize(representation, lambda: iter([b"verified bytes"])) as path:
            cache.policy = lambda: CachePolicy(enabled=False)
            assert path.read_bytes() == b"verified bytes"
            assert cache.begin_fill(replace(representation, version=2)) is None
        assert cache.status()["leases"] == 0

    def test_bounds_bytes_while_leased(self, cache, representation):
        cache.policy = lambda: CachePolicy(enabled=True, max_bytes=representation.size, headroom_bytes=0)
        with cache.materialize(representation, lambda: iter([b"verified bytes"])):
            assert cache.begin_fill(replace(representation, version=2)) is None
        assert cache.status()["bytes"] <= representation.size

    def test_bounds_concurrent_fill_count(self, cache, representation):
        cache.policy = lambda: CachePolicy(enabled=True, max_fills=1, headroom_bytes=0)
        fill = cache.begin_fill(representation)
        assert cache.begin_fill(replace(representation, version=2)) is None
        fill.close()

    def test_recovers_abandoned_claim(self, cache, representation):
        fill = cache.begin_fill(representation)
        fill.write(b"verified")
        fill.output.close()
        fill.output = None
        with sqlite3.connect(cache.root / "index.sqlite3") as db:
            db.execute("UPDATE claims SET incarnation='previous-process'")
        cache.reconcile()
        assert cache.status()["reserved_bytes"] == 0
        assert not fill.path.exists()

    def test_recovers_abandoned_lease(self, cache, representation):
        with cache.materialize(representation, lambda: iter([b"verified bytes"])):
            lease = cache.acquire(representation)
        with sqlite3.connect(cache.root / "index.sqlite3") as db:
            db.execute("UPDATE leases SET incarnation='previous-process'")
        cache.reconcile()
        assert cache.clear()["bytes"] == 0
        assert not lease.path.exists()

    def test_recovers_unindexed_publication(self, cache, representation):
        orphan = cache.root / f"{representation.key}.blob"
        orphan.write_bytes(b"verified bytes")
        cache.reconcile()
        assert not orphan.exists()

    def test_coalesces_concurrent_materialization(self, cache, representation):
        entered = Event()
        release = Event()
        transferred = bytearray()
        def source():
            transferred.extend(b"verified bytes")
            entered.set()
            assert release.wait(5)
            yield b"verified bytes"
        def read():
            with cache.materialize(representation, source) as path:
                return path.read_bytes()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(read)
            assert entered.wait(5)
            second = pool.submit(read)
            release.set()
            assert first.result() == second.result() == b"verified bytes"
        assert transferred == b"verified bytes"

    def test_disabled_cache_refuses_materialization(self, cache, representation):
        cache.policy = lambda: CachePolicy(enabled=False)
        with pytest.raises(CacheUnavailable, match="admission refused"):
            with cache.materialize(representation, lambda: iter([b"verified bytes"])):
                pytest.fail("disabled cache exposed a path")
