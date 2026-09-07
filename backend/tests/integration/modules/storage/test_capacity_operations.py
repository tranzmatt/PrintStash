"""Heavy workflows deny before allocating when headroom cannot be retained."""

import pytest

from app.core.config import _overlay
from app.core.errors import OperationError
from app.db.models import FileType
from app.modules.ingestion.library_transfer import create_archive, import_archive
from app.modules.media.thumbnail_repair import regenerate_model_thumbnail_result


class TestOperationAdmission:
    def test_denies_archive_export_before_allocation(
        self, db_session, make_user, monkeypatch
    ):
        monkeypatch.setitem(_overlay, "storage_min_free_bytes", 10**18)
        with pytest.raises(OperationError, match="storage_capacity_exceeded"):
            create_archive(db_session, make_user(superuser=True))

    def test_denies_archive_import_before_allocation(
        self, db_session, make_user, monkeypatch
    ):
        user = make_user(superuser=True)
        archive = create_archive(db_session, user)
        monkeypatch.setitem(_overlay, "storage_min_free_bytes", 10**18)
        try:
            with pytest.raises(OperationError, match="storage_capacity_exceeded"):
                import_archive(db_session, archive, user)
        finally:
            archive.unlink()

    def test_denies_media_repair_before_materialization(
        self, db_session, make_model, make_file, monkeypatch
    ):
        model = make_model()
        make_file(model, file_type=FileType.STL)
        monkeypatch.setitem(_overlay, "storage_min_free_bytes", 10**18)
        with pytest.raises(OperationError, match="storage_capacity_exceeded"):
            regenerate_model_thumbnail_result(db_session, model.id)

    def test_denies_backup_before_archive_allocation(self, backup_env, monkeypatch):
        from app.modules.backups.backup.creation import create_backup

        monkeypatch.setitem(_overlay, "storage_min_free_bytes", 10**18)
        with pytest.raises(OperationError, match="storage_capacity_exceeded"):
            create_backup()

    def test_denies_restore_before_download(self, backup_env, monkeypatch):
        from app.modules.backups.backup.creation import create_backup
        from app.modules.backups.backup.restore import restore_backup

        meta = create_backup()
        monkeypatch.setitem(_overlay, "storage_min_free_bytes", 10**18)
        with pytest.raises(OperationError, match="storage_capacity_exceeded"):
            restore_backup(meta.id)

    def test_denies_browser_upload_before_staging(
        self, db_session, make_user, monkeypatch
    ):
        from io import BytesIO

        from app.modules.ingestion.inbox import create_browser_upload

        monkeypatch.setitem(_overlay, "storage_min_free_bytes", 10**18)
        with pytest.raises(OperationError, match="storage_capacity_exceeded"):
            create_browser_upload(
                db_session,
                make_user(superuser=True),
                source_url="https://makerworld.com/en/models/42",
                title=None,
                capture_source=None,
                filename="model.stl",
                stream=BytesIO(b"solid"),
            )
