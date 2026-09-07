"""Adoption needs an explicit, current source and cannot steal pending work."""

from pathlib import Path

import pytest

from app.db.models import OwnedStorageObject, StorageObjectState
from app.modules.backups.backup import adoption, creation, targets


class TestS3Adoption:
    @pytest.mark.parametrize(
        "state", [StorageObjectState.COMMITTED, StorageObjectState.PENDING]
    )
    def test_existing_receipt_cannot_be_adopted_again(self, remote_archive, state):
        proof = remote_archive(state=state)
        with pytest.raises(ValueError, match="backup_already_adopted"):
            adoption.adopt_s3_backup(
                proof.meta.path, source_ref="selected", expected_archive_sha256="a" * 64
            )
        with proof.env.new_session() as session:
            assert session.get(OwnedStorageObject, proof.row_id).state == state

    def test_stale_selection_does_not_update_legacy_receipt(self, remote_archive):
        proof = remote_archive(sha256=None)
        proof.stub.add_response(
            "head_object",
            proof.response(),
            {"Bucket": proof.target.bucket, "Key": proof.meta.path},
        )
        with pytest.raises(ValueError, match="backup_source_ref_mismatch"):
            adoption.adopt_s3_backup(
                proof.meta.path,
                source_ref="another-source",
                expected_archive_sha256="a" * 64,
            )
        with proof.env.new_session() as session:
            assert session.get(OwnedStorageObject, proof.row_id).sha256 is None

    @pytest.mark.parametrize(
        "key",
        [
            "",
            "outside/backup.tar.gz",
            "printstash-backups/",
            "printstash-backups/unrelated.tar.gz",
        ],
    )
    def test_refuses_non_archive_locators(self, remote_archive, key):
        remote_archive()
        with pytest.raises(ValueError, match="backup_key_invalid"):
            adoption.adopt_s3_backup(
                key, source_ref="selected", expected_archive_sha256="a" * 64
            )

    def test_missing_target_is_explicit(self, remote_archive, monkeypatch):
        proof = remote_archive()
        monkeypatch.setattr(targets, "_get_backup_s3_target", lambda: None)
        with pytest.raises(RuntimeError, match="backup_s3_unavailable"):
            adoption.adopt_s3_backup(
                proof.meta.path, source_ref="selected", expected_archive_sha256="a" * 64
            )

    def test_operator_digest_must_match_the_download(self, backup_env, remote_archive):
        archive = creation.create_backup()
        proof = remote_archive(Path(archive.path).read_bytes(), sha256=None)
        source_ref = targets.source_reference(
            location="s3",
            namespace=proof.meta.namespace,
            path=proof.meta.path,
            provider_ref=proof.target.provider_ref,
        )
        proof.stub.add_response(
            "head_object",
            proof.response(),
            {"Bucket": proof.target.bucket, "Key": proof.meta.path},
        )
        body = proof.get()
        with pytest.raises(RuntimeError, match="backup_archive_digest_mismatch"):
            adoption.adopt_s3_backup(
                proof.meta.path, source_ref=source_ref, expected_archive_sha256="0" * 64
            )
        assert body.closed
        with proof.env.new_session() as session:
            assert session.get(OwnedStorageObject, proof.row_id).sha256 is None
        assert list(backup_env.backup_dir.glob(".printstash-s3-adopt-*")) == []


class TestLocalAdoption:
    @pytest.mark.parametrize(
        "filename", ["", "../printstash-backup-x.tar.gz", "unrelated.tar.gz"]
    )
    def test_rejects_ambiguous_or_outside_names(self, backup_env, filename):
        with pytest.raises(ValueError, match="backup_filename_invalid"):
            adoption.adopt_local_backup(filename)

    def test_missing_selected_archive_is_not_adopted(self, backup_env):
        with pytest.raises(FileNotFoundError):
            adoption.adopt_local_backup("printstash-backup-missing.tar.gz")
