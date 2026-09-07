"""Real HTTP downloads reuse verified materializations without another transfer."""

from __future__ import annotations

import hashlib

import pytest

from app.modules.storage.artifact_content import resolve
from app.modules.storage.artifact_materializer import ArtifactMaterializer, CachePolicy
from app.modules.storage.materializer_runtime import bind_materializer, get_materializer
from app.modules.storage.storage_backend.runtime import bind_backend, get_backend
from tests.factories import build_file, build_model
from tests.fakes.counting_remote_storage import CountingRemoteStorage


@pytest.fixture
def remote_cache(e2e_db, superuser_headers, tmp_path):
    old_backend, old_cache = get_backend(), get_materializer()
    backend = CountingRemoteStorage()
    cache = ArtifactMaterializer(
        tmp_path / "cache", lambda: CachePolicy(enabled=True, headroom_bytes=0)
    )
    bind_backend(backend)
    bind_materializer(cache)
    yield backend, cache
    bind_backend(old_backend)
    bind_materializer(old_cache)


@pytest.mark.asyncio
async def test_repeat_proxy_download_transfers_provider_bytes_once(
    api, e2e_db, superuser_headers, remote_cache, tmp_path
):
    source = tmp_path / "source.gcode"
    source.write_bytes(b"G28\nG1 X1\n")
    model = build_model(e2e_db, "Cached model")
    artifact = build_file(
        e2e_db,
        model,
        filename="source.gcode",
        path=str(source),
        size_bytes=source.stat().st_size,
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    )
    first = await api.get(
        f"/api/v1/files/{artifact.id}/download", headers=superuser_headers
    )
    second = await api.get(
        f"/api/v1/files/{artifact.id}/download", headers=superuser_headers
    )
    assert first.status_code == second.status_code == 200
    assert first.content == second.content == source.read_bytes()
    assert remote_cache[0].bytes_read == source.stat().st_size
    assert remote_cache[1].status()["leases"] == 0


@pytest.mark.asyncio
async def test_materialization_reuses_http_verified_content(
    api, e2e_db, superuser_headers, remote_cache, tmp_path
):
    source = tmp_path / "source.gcode"
    source.write_bytes(b"G28\nG1 X2\n")
    model = build_model(e2e_db, "Materialized model")
    artifact = build_file(
        e2e_db,
        model,
        filename="source.gcode",
        path=str(source),
        size_bytes=source.stat().st_size,
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    )
    response = await api.get(
        f"/api/v1/files/{artifact.id}/download", headers=superuser_headers
    )
    assert response.status_code == 200
    with resolve(artifact).materialize() as first:
        assert first.read_bytes() == source.read_bytes()
    with resolve(artifact).materialize() as second:
        assert second.read_bytes() == source.read_bytes()
    assert remote_cache[0].bytes_read == source.stat().st_size


@pytest.mark.asyncio
async def test_full_audit_detects_authoritative_corruption_behind_cache(
    api, e2e_db, superuser_headers, remote_cache, tmp_path
):
    from sqlmodel import select

    from app.db.models import User, VaultAuditFinding, VaultAuditMode
    from app.modules.administration import vault_audit

    source = tmp_path / "source.gcode"
    source.write_bytes(b"G28\nG1 X3\n")
    model = build_model(e2e_db, "Audited model")
    artifact = build_file(
        e2e_db,
        model,
        filename="source.gcode",
        path=str(source),
        size_bytes=source.stat().st_size,
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
    )
    response = await api.get(
        f"/api/v1/files/{artifact.id}/download", headers=superuser_headers
    )
    assert response.status_code == 200
    source.write_bytes(b"G28\nG1 X4\n")
    user = e2e_db.exec(select(User)).first()
    run, created = vault_audit.create_run(e2e_db, user.id, VaultAuditMode.FULL)
    assert created
    vault_audit.execute_run(run.id)
    findings = e2e_db.exec(
        select(VaultAuditFinding).where(VaultAuditFinding.run_id == run.id)
    ).all()
    assert "owned_blob_hash_mismatch" in {finding.code for finding in findings}
    assert remote_cache[0].bytes_read >= source.stat().st_size * 2
