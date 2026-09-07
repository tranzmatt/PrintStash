"""Administrative inventory is safe to read; cleanup is explicit and audited."""

from sqlmodel import select

from app.core.config import _overlay
from app.db.models import AuditLog


class TestStorageInventory:
    def test_reports_current_capacity(self, client, auth_headers):
        response = client.get("/api/v1/storage/inventory", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["inventory"]["volumes"]
        assert response.json()["forecast"]["status"] == "insufficient_data"

    def test_denies_non_admin_inventory(self, client, user_headers):
        response = client.get("/api/v1/storage/inventory", headers=user_headers())
        assert response.status_code == 403

    def test_persists_explicit_measurement(self, client, auth_headers):
        assert (
            client.post(
                "/api/v1/storage/inventory/sample", headers=auth_headers
            ).status_code
            == 200
        )
        assert (
            len(
                client.get("/api/v1/storage/inventory", headers=auth_headers).json()[
                    "history"
                ]
            )
            == 1
        )

    def test_audits_explicit_cleanup(self, client, auth_headers, db_session):
        response = client.post(
            "/api/v1/storage/inventory/cleanup-staging", headers=auth_headers
        )
        assert response.status_code == 200
        assert response.json()["files_removed"] == 0
        assert (
            db_session.exec(
                select(AuditLog).where(
                    AuditLog.action == "storage.cleanup_expired_staging"
                )
            ).first()
            is not None
        )

    def test_denies_non_admin_cleanup(self, client, user_headers):
        assert (
            client.post(
                "/api/v1/storage/inventory/cleanup-staging", headers=user_headers()
            ).status_code
            == 403
        )

    def test_bounds_drilldown_page_size(self, client, auth_headers):
        assert (
            client.get(
                "/api/v1/storage/inventory/models?limit=101", headers=auth_headers
            ).status_code
            == 422
        )

    def test_denies_upload_when_headroom_unavailable(
        self, client, auth_headers, monkeypatch
    ):
        monkeypatch.setitem(_overlay, "storage_min_free_bytes", 10**18)
        response = client.post(
            "/api/v1/ingest/model",
            headers=auth_headers,
            files={"file": ("model.stl", b"solid x\nendsolid x")},
        )
        assert response.status_code == 507
        assert response.json()["detail"] == "storage_capacity_exceeded"
        assert response.json()["capacity"]["headroom_bytes"] == 10**18
        assert response.json()["capacity"]["required_bytes"] > 0
        assert response.headers["retry-after"] == "60"

    def test_resets_headroom_to_environment_default(self, client, auth_headers):
        original = client.get("/api/v1/config", headers=auth_headers).json()[
            "storage_min_free_bytes"
        ]
        updated = client.put(
            "/api/v1/config",
            headers=auth_headers,
            json={"storage_min_free_bytes": 1234},
        )
        assert updated.status_code == 200
        assert (
            client.get("/api/v1/config", headers=auth_headers).json()[
                "storage_min_free_bytes"
            ]
            == 1234
        )
        assert (
            client.put(
                "/api/v1/config",
                headers=auth_headers,
                json={"storage_min_free_bytes": -1},
            ).status_code
            == 200
        )
        assert (
            client.get("/api/v1/config", headers=auth_headers).json()[
                "storage_min_free_bytes"
            ]
            == original
        )
