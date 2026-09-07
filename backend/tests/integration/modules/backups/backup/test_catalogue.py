"""An unverifiable remote archive is never advertised as restorable."""

import io

import pytest

from app.modules.backups.backup import catalogue


class TestS3Catalogue:
    @pytest.mark.parametrize(
        "case",
        [
            "no-digest",
            "no-identity",
            "changed-size",
            "missing-body",
            "invalid-manifest",
            "get-failure",
        ],
    )
    def test_omits_unverifiable_archives(self, remote_archive, case):
        changes = (
            {"sha256": None}
            if case == "no-digest"
            else {"etag": None}
            if case == "no-identity"
            else {}
        )
        proof = remote_archive(**changes)
        proof.stub.add_response(
            "list_objects_v2",
            {"Contents": [{"Key": proof.meta.path}]},
            {"Bucket": proof.target.bucket, "Prefix": "printstash-backups/"},
        )
        body = None
        if case not in {"no-digest", "no-identity"}:
            proof.head(**({"ContentLength": 1} if case == "changed-size" else {}))
            if case == "missing-body":
                proof.stub.add_response("get_object", proof.response(), proof.locator)
            elif case == "invalid-manifest":
                # Valid gzip/tar without a manifest: the listing parser returns None.
                import tarfile

                output = io.BytesIO()
                with tarfile.open(fileobj=output, mode="w:gz"):
                    pass
                body = proof.get(payload=output.getvalue())
                proof.head()
            elif case == "get-failure":
                proof.stub.add_client_error(
                    "get_object",
                    service_error_code="AccessDenied",
                    expected_params=proof.locator,
                )
        proof.stub.add_response(
            "list_objects_v2",
            {},
            {"Bucket": proof.target.bucket, "Prefix": "nexus3d-backups/"},
        )
        assert catalogue._list_s3_backups() == []
        if body is not None:
            assert body.closed

    def test_listing_outage_does_not_invent_sources(self, remote_archive):
        proof = remote_archive()
        proof.stub.add_client_error(
            "list_objects_v2",
            service_error_code="ServiceUnavailable",
            expected_params={
                "Bucket": proof.target.bucket,
                "Prefix": "printstash-backups/",
            },
        )
        assert catalogue._list_s3_backups() == []
