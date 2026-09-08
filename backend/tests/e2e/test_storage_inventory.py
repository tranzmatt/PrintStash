"""Operators can measure storage and run an explicitly audited safe cleanup."""

import hashlib
from datetime import timedelta

import pytest
from sqlmodel import select

from app.core.time import utcnow
from app.db.models import AuditLog, User
from app.modules.ingestion.staging_leases import create_review_lease
from tests.factories import build_inbox_item


class TestStorageInventoryCleanup:
    @pytest.mark.asyncio
    async def test_explicit_cleanup_refreshes_insights(
        self, api, e2e_db, superuser_headers, tmp_path
    ):
        user = e2e_db.exec(select(User).where(User.username == "e2e-admin")).one()
        item = build_inbox_item(e2e_db, user)
        staged = tmp_path / "expired-staging.stl"
        staged.write_bytes(b"old staging")
        create_review_lease(
            e2e_db,
            inbox_item_id=item.id,
            owner_user_id=user.id,
            path=staged,
            size_bytes=11,
            sha256=hashlib.sha256(b"old staging").hexdigest(),
            now=utcnow() - timedelta(days=400),
        )
        e2e_db.commit()
        before = await api.get("/api/v1/storage/inventory", headers=superuser_headers)
        assert before.status_code == 200
        assert before.json()["inventory"]["temporary_bytes"] == 11
        measured = await api.post(
            "/api/v1/storage/inventory/sample", headers=superuser_headers
        )
        assert measured.status_code == 200
        result = await api.post(
            "/api/v1/storage/inventory/cleanup-staging", headers=superuser_headers
        )
        assert result.status_code == 200
        assert result.json()["files_removed"] == 1
        assert not staged.exists()
        after = await api.get("/api/v1/storage/inventory", headers=superuser_headers)
        assert len(after.json()["history"]) == 1
        assert after.json()["inventory"]["temporary_bytes"] == 0
        assert after.json()["inventory"]["measured_at"] is not None
        assert (
            e2e_db.exec(
                select(AuditLog).where(
                    AuditLog.action == "storage.cleanup_expired_staging"
                )
            ).first()
            is not None
        )
