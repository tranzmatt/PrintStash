"""Collision preflight preserves all destination bytes and recovery evidence."""

import hashlib

import pytest

from app.modules.backups.backup import contracts, restore_blobs
from app.modules.storage.storage_backend.runtime import get_backend
from app.runtime.maintenance import RestoreConflictError


class TestCollisionPreflight:
    @pytest.mark.parametrize("case", ["duplicate", "changed-bytes", "wrong-intent"])
    def test_rejects_conflicts_before_publication(self, backup_env, tmp_path, case):
        backend = get_backend()
        key = str(backup_env.data_dir / "part.stl")
        staged = tmp_path / "part.stl"
        staged.write_bytes(b"restored")
        blob = contracts._StagedBlob(
            key=key,
            path=staged,
            size=8,
            sha256=hashlib.sha256(b"restored").hexdigest(),
            namespace=backend.namespace_for(key),
        )
        journal = None
        blobs = [blob, blob] if case == "duplicate" else [blob]
        if case != "duplicate":
            backend.write_bytes(b"operator bytes", key)
        if case == "wrong-intent":
            journal = contracts._RestoreJournalState(
                started={},
                intents={key: {"sha256": "wrong"}},
                published={},
                generations={},
            )
        with pytest.raises(RestoreConflictError):
            restore_blobs._apply_staged_blobs(
                blobs, tmp_path / "rollback", journal_state=journal
            )
        assert staged.read_bytes() == b"restored"
        assert backend.exists(key) is (case != "duplicate")
        if case != "duplicate":
            assert b"".join(backend.stream_chunks(key)) == b"operator bytes"
