"""A remote download cannot replace local bytes without current ownership proof."""

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from sqlmodel import select

from app.db.models import OwnedStorageObject
from app.modules.backups.backup import contracts, downloads, targets
from app.modules.storage.storage_backend.local import LocalStorageBackend
from tests.factories import store_owned_bytes


class TestArchiveOwnership:
    @pytest.mark.parametrize(
        "changes",
        [
            {"provider_ref": "another-provider"},
            {"etag": None},
        ],
        ids=["foreign-provider", "no-remote-identity"],
    )
    def test_rejects_unverifiable_receipts(self, remote_archive, changes):
        proof = remote_archive(**changes)
        with pytest.raises(
            contracts.BackupOwnershipError, match="ownership_unverified"
        ):
            downloads._require_backup_archive_owned(proof.meta)

    @pytest.mark.parametrize(
        "response",
        [
            {"ContentLength": 1},
            {"ETag": '"replaced"'},
            {"Metadata": {"printstash-create-token": "foreign-token"}},
        ],
        ids=["size", "etag", "token"],
    )
    def test_rejects_changed_remote_object(self, remote_archive, response):
        proof = remote_archive()
        proof.head(**response)
        with pytest.raises(
            contracts.BackupOwnershipError, match="ownership_unverified"
        ):
            downloads._require_backup_archive_owned(proof.meta)

    def test_remote_head_failure_does_not_authorize_download(self, remote_archive):
        proof = remote_archive()
        proof.stub.add_client_error(
            "head_object", service_error_code="NoSuchKey", expected_params=proof.locator
        )
        with pytest.raises(
            contracts.BackupOwnershipError, match="ownership_unverified"
        ):
            downloads._require_backup_archive_owned(proof.meta)

    @pytest.mark.parametrize(
        "case", ["no-target", "foreign-namespace", "outside-prefix"]
    )
    def test_rejects_a_changed_destination(self, remote_archive, monkeypatch, case):
        proof = remote_archive()
        if case == "no-target":
            monkeypatch.setattr(targets, "_get_backup_s3_target", lambda: None)
        elif case == "foreign-namespace":
            proof.meta.namespace = "other-bucket/printstash-backups/"
        else:
            proof.meta.path = "unrelated/archive.tar.gz"
        with pytest.raises(contracts.BackupOwnershipError):
            downloads._require_backup_archive_owned(proof.meta)

    def test_snapshot_without_bucket_uses_the_selected_namespace(
        self, remote_archive, monkeypatch
    ):
        proof = remote_archive()
        proof.head()
        monkeypatch.setattr(
            targets, "_get_backup_s3_target", lambda: replace(proof.target, bucket="")
        )
        assert downloads._require_backup_archive_owned(proof.meta).id == proof.row_id


class TestVerifiedDownload:
    @pytest.mark.parametrize(
        "corruption", ["truncated", "changed-digest", "changed-after-read"]
    )
    def test_partial_or_replaced_body_is_never_published(
        self, remote_archive, corruption
    ):
        proof = remote_archive()
        proof.head()
        body = proof.get(
            payload=b"x"
            if corruption == "truncated"
            else b"x" * len(proof.payload)
            if corruption == "changed-digest"
            else proof.payload
        )
        if corruption == "changed-after-read":
            proof.head(ETag='"replaced"')
        with pytest.raises(RuntimeError, match="backup_(download|remote)_"):
            downloads._download_backup_to_local(proof.meta)
        assert body.closed
        assert list(proof.env.backup_dir.glob(".printstash-backup-download-*")) == []
        assert list((proof.env.backup_dir / ".cloud-cache").iterdir()) == []
        with proof.env.new_session() as session:
            assert (
                session.exec(
                    select(OwnedStorageObject).where(
                        OwnedStorageObject.object_kind == "backup-cloud-cache"
                    )
                ).all()
                == []
            )

    def test_cache_reuse_requires_its_own_ownership(self, remote_archive):
        proof = remote_archive()
        proof.head()
        body = proof.get()
        proof.head()
        cached = downloads._download_backup_to_local(proof.meta)
        assert body.closed and cached.read_bytes() == proof.payload
        proof.head()
        assert downloads._download_backup_to_local(proof.meta) == cached

    @pytest.mark.parametrize(
        "cache_kind", ["foreign-bytes", "unowned", "wrong-ledger-hash"]
    )
    def test_an_existing_cache_cannot_be_adopted_implicitly(
        self, remote_archive, cache_kind
    ):
        proof = remote_archive()
        source_ref = targets.source_reference(
            location="s3",
            namespace=proof.meta.namespace,
            path=proof.meta.path,
            provider_ref=proof.target.provider_ref,
        )
        identity = hashlib.sha256(
            f'{source_ref}\x1f"archive-etag"'.encode()
        ).hexdigest()
        cached = (
            proof.env.backup_dir
            / ".cloud-cache"
            / f"{identity}-{Path(proof.meta.path).name}"
        )
        cached.parent.mkdir()
        payload = b"operator bytes" if cache_kind == "foreign-bytes" else proof.payload
        if cache_kind == "wrong-ledger-hash":
            with proof.env.new_session() as session:
                store_owned_bytes(
                    session,
                    LocalStorageBackend(),
                    str(cached),
                    payload,
                    object_kind="backup-cloud-cache",
                )
                row = session.exec(
                    select(OwnedStorageObject).where(
                        OwnedStorageObject.key == str(cached)
                    )
                ).one()
                row.sha256 = "0" * 64
                session.add(row)
                session.commit()
        else:
            cached.write_bytes(payload)
        proof.head()
        with pytest.raises(
            contracts.BackupOwnershipError,
            match="backup_(local_destination_conflict|cache_ownership_unverified|cache_identity_mismatch)",
        ):
            downloads._download_backup_to_local(proof.meta)
        assert cached.read_bytes() == payload

    def test_missing_local_archive_has_no_remote_fallback(self, remote_archive):
        proof = remote_archive()
        proof.meta.location = "local"
        proof.meta.path = str(proof.env.backup_dir / "missing.tar.gz")
        with pytest.raises(FileNotFoundError):
            downloads._download_backup_to_local(proof.meta)


class TestAuthoritativeAuditDownload:
    def test_detects_corruption_despite_a_valid_cache(self, remote_archive):
        proof = remote_archive()
        proof.head()
        proof.get()
        proof.head()
        cached = downloads._download_backup_to_local(proof.meta)
        assert cached.read_bytes() == proof.payload
        proof.head()
        corrupted_body = proof.get(payload=b"x" * len(proof.payload))
        with pytest.raises(RuntimeError, match="backup_download_digest_mismatch"):
            downloads._download_backup_to_local(proof.meta, fresh_remote=True)
        assert corrupted_body.closed
        assert not cached.exists()

    def test_stops_download_on_window_expiry(self, remote_archive):
        proof = remote_archive()
        proof.head()
        body = proof.get()

        def cancel(_size):
            raise RuntimeError("audit_window_expired")

        with pytest.raises(RuntimeError, match="audit_window_expired"):
            downloads._download_backup_to_local(proof.meta, progress=cancel)
        assert body.closed
        assert list(proof.env.backup_dir.glob(".printstash-backup-download-*")) == []
