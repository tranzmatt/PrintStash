"""Canonical metadata belongs to the Artifact, even when response bytes are cached."""

from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest

from app.core.time import utcnow
from app.modules.storage.artifact_content import resolve
from app.modules.storage.artifact_delivery import DeliveryRequest, plan_artifact
from app.modules.storage.artifact_materializer import ArtifactMaterializer, CachePolicy
from app.modules.storage.delivery_contracts import BrowserDownload
from app.modules.storage.materializer_runtime import bind_materializer, get_materializer
from app.modules.storage.storage_backend.runtime import bind_backend, get_backend
from tests.fakes.counting_remote_storage import CountingRemoteStorage


@pytest.fixture
def cached_artifact(make_model, make_file, tmp_path):
    old_backend, old_cache = get_backend(), get_materializer()
    backend = CountingRemoteStorage()
    cache = ArtifactMaterializer(
        tmp_path / "cache", lambda: CachePolicy(enabled=True, headroom_bytes=0)
    )
    bind_backend(backend)
    bind_materializer(cache)
    source = tmp_path / "source.gcode"
    source.write_bytes(b"G28\nG1 X1\n")
    row = make_file(
        make_model("Cached delivery"),
        filename="source.gcode",
        path=str(source),
        size_bytes=source.stat().st_size,
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    )
    yield row, backend, cache
    bind_backend(old_backend)
    bind_materializer(old_cache)


class TestCacheDelivery:
    def test_retains_canonical_metadata_on_cache_hit(
        self, client, auth_headers, cached_artifact
    ):
        row, backend, _ = cached_artifact
        first = client.get(f"/api/v1/files/{row.id}/download", headers=auth_headers)
        second = client.get(f"/api/v1/files/{row.id}/download", headers=auth_headers)
        assert first.content == second.content
        assert first.headers["etag"] == second.headers["etag"] == f'"{row.sha256}"'
        assert first.headers["last-modified"] == second.headers["last-modified"]
        assert (
            first.headers["content-disposition"]
            == second.headers["content-disposition"]
        )
        assert backend.bytes_read == row.size_bytes

    def test_cold_range_does_not_publish_partial_representation(
        self, client, auth_headers, cached_artifact
    ):
        row, _, cache = cached_artifact
        response = client.get(
            f"/api/v1/files/{row.id}/download",
            headers={**auth_headers, "Range": "bytes=0-2"},
        )
        assert response.status_code == 206
        assert response.content == b"G28"
        assert cache.status()["entries"] == 0

    def test_selected_response_survives_clear_before_open(self, cached_artifact):
        row, _, cache = cached_artifact
        with resolve(row).materialize():
            pass
        plan = plan_artifact(row, DeliveryRequest(filename=row.original_filename))
        cache.clear()
        assert plan.path.read_bytes() == b"G28\nG1 X1\n"
        plan.close()
        assert cache.status()["bytes"] == 0

    def test_redirect_precedes_cache_selection(self, cached_artifact, monkeypatch):
        row, backend, cache = cached_artifact
        with resolve(row).materialize():
            pass
        target = BrowserDownload(
            url="https://provider.example.test/file",
            method="GET",
            required_headers=(),
            expires_at=utcnow() + timedelta(seconds=60),
            key=row.path,
            cors_origin=None,
        )
        monkeypatch.setattr(backend, "browser_download", lambda *args, **kwargs: target)
        plan = plan_artifact(row, DeliveryRequest(filename=row.original_filename))
        assert plan.status == 307
        assert plan.redirect == target.url
        assert cache.status()["leases"] == 0
