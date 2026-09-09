"""Defend cancellation, scratch reservations, and progress during backup audits."""

import pytest

from app.modules.backups.backup.creation import create_backup
from app.modules.backups.backup.verification import verify_backup


class TestVerifyBackupBudget:
    def test_verification_obeys_read_cancellation(self, backup_env):
        meta = create_backup()

        def cancel(_size):
            raise RuntimeError("audit_window_expired")

        with pytest.raises(RuntimeError, match="audit_window_expired"):
            verify_backup(meta.id, progress=cancel)

    def test_verification_reserves_database_scratch(self, backup_env):
        meta = create_backup()
        allocations = []
        result = verify_backup(meta.id, allocate=allocations.append)
        assert result.valid
        assert len(allocations) == 1
        assert allocations[0] > 0

    def test_verification_preserves_read_progress(self, backup_env):
        meta = create_backup()
        reads = []
        result = verify_backup(meta.id, progress=reads.append)
        assert result.valid
        assert sum(reads) > 0
