"""Receipt-backed archives with a contract-enforcing S3 SDK boundary."""

import hashlib
import io
from dataclasses import dataclass

import boto3
import pytest
from botocore.stub import Stubber

from app.modules.backups.backup import contracts, targets
from tests.factories import build_owned_storage_object


@dataclass
class RemoteArchive:
    env: object
    target: object
    stub: Stubber
    meta: contracts.BackupMeta
    row_id: int
    payload: bytes

    @property
    def locator(self):
        return {
            "Bucket": self.target.bucket,
            "Key": self.meta.path,
            "IfMatch": '"archive-etag"',
        }

    def response(self, **changes):
        return {
            "ContentLength": len(self.payload),
            "ETag": '"archive-etag"',
            "Metadata": {"printstash-create-token": "archive-token"},
            **changes,
        }

    def head(self, **changes):
        self.stub.add_response("head_object", self.response(**changes), self.locator)

    def get(self, payload=None, **changes):
        body = io.BytesIO(self.payload if payload is None else payload)
        self.stub.add_response(
            "get_object", self.response(Body=body, **changes), self.locator
        )
        return body


@pytest.fixture
def remote_archive(backup_env, monkeypatch):
    """Real SQL ownership; boto validates every conditional SDK request."""
    client = boto3.client(
        "s3",
        region_name="us-east-1",
        endpoint_url="https://storage.invalid",
        aws_access_key_id="test-access",
        aws_secret_access_key="test-secret",
    )
    target = targets._BackupS3Target(
        client, "archive-bucket", "signature", "provider-ref"
    )
    monkeypatch.setattr(targets, "_get_backup_s3_target", lambda: target)
    with Stubber(client) as stub:

        def create(payload=b"an archive body", **changes):
            key = "printstash-backups/printstash-backup-20240101-000000-abc123.tar.gz"
            values = dict(
                backend="backup-s3",
                namespace="archive-bucket/printstash-backups/",
                key=key,
                object_kind="backup",
                token="archive-token",
                size_bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                provider_ref=target.provider_ref,
                etag='"archive-etag"',
            )
            values.update(changes)
            with backup_env.new_session() as session:
                row = build_owned_storage_object(session, **values)
                row_id = row.id
            meta = contracts.BackupMeta(
                id="abc123",
                created_at="2024-01-01T00:00:00Z",
                size_bytes=len(payload),
                storage_backend="local",
                file_count=0,
                app_version="test",
                path=key,
                location="s3",
                namespace=values["namespace"],
                provider_ref=target.provider_ref,
            )
            return RemoteArchive(backup_env, target, stub, meta, row_id, payload)

        yield create
        stub.assert_no_pending_responses()
    client.close()
