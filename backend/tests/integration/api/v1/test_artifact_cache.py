"""Only administrators can change disposable cache policy."""
from __future__ import annotations

from dataclasses import asdict

import pytest

from app.core.config import _overlay
from app.modules.storage.artifact_materializer import ArtifactMaterializer, CachePolicy
from app.modules.storage.materializer_runtime import bind_materializer, get_materializer


@pytest.fixture
def cache_settings_env(tmp_path):
    previous = dict(_overlay)
    original = get_materializer()
    cache = ArtifactMaterializer(tmp_path / "cache", lambda: CachePolicy())
    bind_materializer(cache)
    yield cache
    bind_materializer(original)
    _overlay.clear()
    _overlay.update(previous)


class TestArtifactCacheConfig:
    def test_persists_live_policy(self, client, auth_headers, cache_settings_env):
        policy = {**asdict(CachePolicy(enabled=True, max_bytes=500)), "root": str(cache_settings_env.root)}
        response = client.put("/api/v1/config/artifact-cache", json=policy, headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["policy"] == policy
        assert response.json()["source"] == "database"
        assert client.get("/api/v1/config/artifact-cache", headers=auth_headers).json()["policy"] == policy

    def test_reports_root_restart_requirement(self, client, auth_headers, cache_settings_env, tmp_path):
        response = client.put("/api/v1/config/artifact-cache", json={**asdict(CachePolicy()), "root": str(tmp_path / "replacement")}, headers=auth_headers)
        assert response.json()["restart_required"] is True
        assert response.json()["effective_root"] == str(cache_settings_env.root)
        assert not (tmp_path / "replacement").exists()

    def test_reset_restores_environment_defaults(self, client, auth_headers, cache_settings_env):
        initial = client.get("/api/v1/config/artifact-cache", headers=auth_headers).json()["policy"]
        client.put("/api/v1/config/artifact-cache", json={**initial, "max_bytes": 123}, headers=auth_headers)
        reset = client.delete("/api/v1/config/artifact-cache", headers=auth_headers)
        assert reset.json()["policy"] == initial
        assert reset.json()["source"] == "environment"

    def test_requires_authentication(self, client):
        assert client.get("/api/v1/config/artifact-cache").status_code == 401

    def test_validates_fill_limit(self, client, auth_headers, cache_settings_env):
        response = client.put("/api/v1/config/artifact-cache", json={**asdict(CachePolicy()), "root": str(cache_settings_env.root), "max_fills": 0}, headers=auth_headers)
        assert response.status_code == 422

    def test_clear_preserves_policy(self, client, auth_headers, cache_settings_env):
        initial = client.get("/api/v1/config/artifact-cache", headers=auth_headers).json()["policy"]
        cleared = client.post("/api/v1/config/artifact-cache/clear", headers=auth_headers)
        assert cleared.status_code == 200
        assert cleared.json()["policy"] == initial
        assert cleared.json()["usage"]["bytes"] == 0
