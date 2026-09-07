"""Pending restore evidence cannot authorize an unknown storage destination."""

import json

import pytest

from app.modules.backups.backup import restore
from app.modules.storage.storage_backend.contracts import UnavailableStorageBackend
from app.modules.storage.storage_backend.local import LocalStorageBackend
from app.modules.storage.storage_backend.runtime import bind_backend
from app.runtime.maintenance import (
    RestoreConflictError,
    hold_restore_maintenance,
    restore_in_progress,
)


class TestRecoveryDestination:
    @pytest.mark.parametrize("case", ["unknown-identity", "legacy-remote"])
    def test_refuses_recovery_without_current_destination_proof(self, backup_env, case):
        backup_id = "abc123"
        started = {
            "event": "started",
            "version": 2,
            "backup_id": backup_id,
            "operation_nonce": "a" * 64,
            "archive_sha256": "b" * 64,
            "provider_ref": "c" * 64,
        }
        if case == "unknown-identity":

            class UnknownIdentity(LocalStorageBackend):
                @property
                def endpoint_url(self):
                    raise OSError("provider configuration unavailable")

            bind_backend(UnknownIdentity())
            expected = "restore_storage_provider_unknown"
        else:
            started = {"event": "started", "version": 1, "backup_id": backup_id}
            bind_backend(UnavailableStorageBackend("remote provider unavailable"))
            expected = "restore_journal_mismatch"
        journal = backup_env.backup_dir / f".restore-{backup_id}.journal"
        content = json.dumps(started) + "\n"
        journal.write_text(content)
        database_before = backup_env.db_file.read_bytes()
        hold_restore_maintenance()

        with pytest.raises(RestoreConflictError, match=expected):
            restore.restore_backup(backup_id)

        assert journal.read_text() == content
        assert backup_env.db_file.read_bytes() == database_before
        assert restore_in_progress()
