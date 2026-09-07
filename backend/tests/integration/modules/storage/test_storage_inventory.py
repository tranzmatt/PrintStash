"""Storage inventory distinguishes references, owned objects and unknown evidence."""

from datetime import timedelta

import pytest

from app.core.time import utcnow
from app.db.models import FileType
from app.modules.storage.storage_backend.runtime import get_backend
from app.modules.storage.storage_inventory import (
    history,
    inventory,
    logical_drilldown,
    record_sample,
)


class TestInventory:
    @pytest.mark.parametrize("kind", list(FileType), ids=lambda kind: kind.value)
    def test_classifies_artifact_types(self, db_session, make_model, make_file, kind):
        make_file(make_model(), file_type=kind, size_bytes=73)
        current = inventory(db_session)
        assert (
            next(
                bucket for bucket in current.buckets if bucket.category == kind.value
            ).logical_bytes
            == 73
        )

    def test_separates_trashed_artifacts(self, db_session, make_model, make_file):
        make_file(make_model(trashed=True), size_bytes=53)
        assert (
            next(
                bucket
                for bucket in inventory(db_session).buckets
                if bucket.category == "gcode"
            ).lifecycle
            == "trash"
        )

    def test_excludes_external_bytes_from_owned_total(
        self, db_session, make_model, make_file, make_external_library, tmp_path
    ):
        library = make_external_library(tmp_path / "external")
        make_file(
            make_model(), external=True, external_library_id=library.id, size_bytes=700
        )
        current = inventory(db_session)
        assert current.external_referenced_bytes == 700
        assert current.unique_owned_bytes == 0

    def test_counts_shared_key_once(self, db_session, make_model, make_file):
        backend = get_backend()
        key = backend.blob_key("same", 1, "model.stl")
        make_file(make_model(), path=key, size_bytes=23)
        make_file(make_model(), path=key, size_bytes=23)
        current = inventory(db_session)
        assert current.unique_owned_bytes == 23
        assert current.logical_bytes == 46

    def test_counts_distinct_copies(
        self, db_session, make_model, make_owned_storage_object
    ):
        make_owned_storage_object(
            key="copy-a", namespace="vault", size_bytes=23, sha256="a" * 64
        )
        make_owned_storage_object(
            key="copy-b", namespace="vault", size_bytes=23, sha256="a" * 64
        )
        assert inventory(db_session).unique_owned_bytes == 46

    def test_never_walks_provider_on_read(self, db_session, monkeypatch):
        backend = get_backend()

        def forbid(*args, **kwargs):
            pytest.fail("interactive inventory must not enumerate provider")

        monkeypatch.setattr(backend, "walk_keys", forbid)
        monkeypatch.setattr(backend, "usage", forbid)
        assert inventory(db_session).measured_provider_bytes is None

    def test_counts_documents(self, db_session, make_document):
        make_document(filename="guide.pdf", size_bytes=43)
        current = inventory(db_session)
        assert (
            next(
                bucket for bucket in current.buckets if bucket.category == "document"
            ).logical_bytes
            == 43
        )

    def test_collapses_roles_on_shared_volume(self, db_session):
        volumes = inventory(db_session).volumes
        assert len({volume.domain_id for volume in volumes}) == len(volumes)
        assert sum("staging" in volume.roles for volume in volumes) == 1

    def test_replaces_daily_sample(self, db_session):
        current = inventory(db_session)
        record_sample(db_session, current)
        record_sample(db_session, current)
        assert len(history(db_session, current.target_ref)) == 1

    def test_bounds_retention(self, db_session, make_storage_inventory_sample):
        current = inventory(db_session)
        make_storage_inventory_sample(
            target_ref=current.target_ref, sampled_at=utcnow() - timedelta(days=400)
        )
        record_sample(db_session, current)
        assert len(history(db_session, current.target_ref)) == 1

    def test_hides_inaccessible_model_drilldowns(
        self, db_session, make_user, make_model, make_file
    ):
        user = make_user(superuser=False)
        make_file(make_model(), size_bytes=400)
        assert logical_drilldown(db_session, user) == []

    def test_cleanup_reclaims_verified_expired_staging(
        self, db_session, make_user, make_inbox_item, tmp_path
    ):
        import hashlib

        from app.modules.ingestion.staging_leases import create_review_lease
        from app.modules.storage.storage_inventory import cleanup_expired_staging

        user = make_user(superuser=True)
        item = make_inbox_item(user)
        staged = tmp_path / "expired.stl"
        staged.write_bytes(b"old staging")
        create_review_lease(
            db_session,
            inbox_item_id=item.id,
            owner_user_id=user.id,
            path=staged,
            size_bytes=11,
            sha256=hashlib.sha256(b"old staging").hexdigest(),
            now=utcnow() - timedelta(days=400),
        )
        db_session.commit()
        assert inventory(db_session).temporary_bytes == 11
        result = cleanup_expired_staging(db_session, user)
        assert result["files_removed"] == 1
        assert result["inventory"].temporary_bytes == 0
        assert not staged.exists()

    def test_aggregates_document_buckets(self, db_session, make_document):
        make_document(filename="a.pdf", size_bytes=11)
        make_document(filename="b.pdf", size_bytes=13)
        documents = [
            b for b in inventory(db_session).buckets if b.category == "document"
        ]
        assert len(documents) == 1
        assert documents[0].count == 2
        assert documents[0].logical_bytes == 24

    def test_counts_backup_receipts(self, db_session, make_owned_storage_object):
        make_owned_storage_object(
            key="backup-one", object_kind="backup_archive", size_bytes=37
        )
        current = inventory(db_session)
        assert current.backup_bytes == 37
        assert next(b for b in current.buckets if b.category == "backups").count == 1

    def test_reports_probe_failure(self, db_session, monkeypatch):
        def unavailable(path):
            raise OSError("unavailable mount")

        monkeypatch.setattr(
            "app.modules.storage.storage_inventory.os.statvfs", unavailable
        )
        assert all(
            v.status == "unavailable" and v.free_bytes is None
            for v in inventory(db_session).volumes
        )

    def test_s3_capacity_is_unknown_without_remote_calls(self, db_session, monkeypatch):
        from app.core.config import _overlay
        from app.modules.storage.storage_backend import runtime
        from app.modules.storage.storage_backend.s3 import S3StorageBackend

        monkeypatch.setitem(_overlay, "s3_bucket", "inventory-test")
        monkeypatch.setitem(_overlay, "s3_access_key", "test-access")
        monkeypatch.setitem(_overlay, "s3_secret_key", "test-secret")
        backend = S3StorageBackend(check_bucket=False)
        monkeypatch.setattr(runtime, "_backend", backend)
        current = inventory(db_session)
        remote = next(v for v in current.volumes if v.domain_id == "remote")
        assert remote.free_bytes is None
        assert remote.status == "unknown"

    def test_uses_receipt_size_for_derivative_bucket(
        self, db_session, make_model, make_file, make_owned_storage_object
    ):
        from app.modules.storage.storage_ownership import provider_ref_for_backend

        file = make_file(make_model())
        backend = get_backend()
        key = backend.thumbnail_key(file.id)
        namespace = backend.namespace_for(key)
        make_owned_storage_object(
            key=key,
            namespace=namespace,
            provider_ref=provider_ref_for_backend(backend, namespace=namespace),
            object_kind="thumbnail",
            size_bytes=29,
        )
        thumbnail = next(
            b for b in inventory(db_session).buckets if b.category == "thumbnail"
        )
        assert thumbnail.logical_bytes == 29
