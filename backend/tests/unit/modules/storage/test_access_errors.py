"""Provider evidence becomes a safe actionable code, never a credential leak."""

import pytest
from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError
from opendal.exceptions import NotFound, PermissionDenied, Unexpected

from app.modules.storage.access_errors import (
    StorageAccessError,
    StorageAccessProblem,
    raise_storage_access_error,
    storage_access_failure,
)


class TestStorageAccessFailure:
    @pytest.mark.parametrize(
        ("failure", "expected"),
        [
            pytest.param(
                ClientError(
                    {"Error": {"Code": "ExpiredToken", "Message": "SECRET"}},
                    "ListObjectsV2",
                ),
                "storage_credentials_expired",
                id="s3-expired",
            ),
            pytest.param(
                ClientError({"Error": {"Code": "InvalidAccessKeyId"}}, "HeadObject"),
                "storage_authentication_failed",
                id="s3-invalid-key",
            ),
            pytest.param(
                ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject"),
                "storage_access_denied",
                id="s3-permissions",
            ),
            pytest.param(
                ClientError({"Error": {"Code": "SignatureDoesNotMatch"}}, "GetObject"),
                "storage_signature_invalid",
                id="s3-signature",
            ),
            pytest.param(
                ClientError({"Error": {"Code": "RequestTimeTooSkewed"}}, "GetObject"),
                "storage_signature_invalid",
                id="s3-clock",
            ),
            pytest.param(
                ClientError({"ResponseMetadata": {"HTTPStatusCode": 401}}, "GetObject"),
                "storage_authentication_failed",
                id="s3-http401",
            ),
            pytest.param(
                NoCredentialsError(),
                "storage_authentication_failed",
                id="missing-key",
            ),
            pytest.param(
                PartialCredentialsError(provider="fixture", cred_var="secret"),
                "storage_authentication_failed",
                id="partial-key",
            ),
            pytest.param(
                Unexpected(
                    'Unexpected => S3Error { code: "ExpiredToken", message: "SECRET" }'
                ),
                "storage_credentials_expired",
                id="opendal-explicit-expiry",
            ),
            pytest.param(
                PermissionDenied(
                    'PermissionDenied => S3Error { code: "InvalidAccessKeyId", message: "SECRET" }'
                ),
                "storage_authentication_failed",
                id="opendal-invalid-key-over-403",
            ),
            pytest.param(
                PermissionDenied(
                    'PermissionDenied => S3Error { code: "SignatureDoesNotMatch", message: "SECRET" }'
                ),
                "storage_signature_invalid",
                id="opendal-signature-over-403",
            ),
            pytest.param(
                Unexpected(
                    "Unexpected at stat\n\nContext:\n   response: Parts { status: 401, headers: SECRET }"
                ),
                "storage_authentication_failed",
                id="r2-bare-401",
            ),
            pytest.param(
                Unexpected(
                    "Unexpected at stat\n\nContext:\n   response: Parts { status: 403, headers: SECRET }"
                ),
                "storage_access_denied",
                id="opendal-http403",
            ),
            pytest.param(
                PermissionDenied("SECRET"),
                "storage_access_denied",
                id="native-denied",
            ),
        ],
    )
    def test_classifies_provider_access_failures(self, failure, expected):
        result = storage_access_failure(failure)
        assert isinstance(result, StorageAccessError)
        assert str(result) == expected
        assert "SECRET" not in str(result)

    @pytest.mark.parametrize(
        "failure",
        [
            pytest.param(TimeoutError("401 ExpiredToken"), id="timeout"),
            pytest.param(FileNotFoundError("ExpiredToken.stl"), id="local-missing"),
            pytest.param(NotFound("ExpiredToken.stl"), id="remote-missing"),
            pytest.param(Unexpected("Temporary network failure"), id="network"),
            pytest.param(
                Unexpected(
                    'Unexpected\n\nContext:\n   path: S3Error { code: "ExpiredToken", }'
                ),
                id="code-in-filename",
            ),
            pytest.param(
                ClientError({"Error": {"Code": "NoSuchBucket"}}, "ListObjectsV2"),
                id="missing-bucket",
            ),
        ],
    )
    def test_ignores_unrelated_failures(self, failure):
        assert storage_access_failure(failure) is None

    @pytest.mark.parametrize(
        "chain", ["__cause__", "__context__"], ids=["cause", "context"]
    )
    @pytest.mark.parametrize("normalized", [False, True], ids=["native", "normalized"])
    def test_preserves_wrapped_access_failure(self, chain, normalized):
        wrapper = RuntimeError("read failed")
        inner = (
            StorageAccessError(StorageAccessProblem.DENIED)
            if normalized
            else PermissionDenied("SECRET")
        )
        setattr(wrapper, chain, inner)
        with pytest.raises(StorageAccessError) as raised:
            raise_storage_access_error(wrapper)
        assert str(raised.value) == "storage_access_denied"
        assert raised.value.__cause__ is wrapper
        assert raised.value is not inner

    @pytest.mark.parametrize("context", ["suppressed", "cycle"], ids=str)
    def test_respects_suppressed_context(self, context):
        failure = RuntimeError("independent failure")
        if context == "suppressed":
            failure.__context__ = PermissionDenied("SECRET")
            failure.__suppress_context__ = True
        else:
            failure.__cause__ = failure
        assert storage_access_failure(failure) is None

    def test_rethrows_normalized_error_without_self_cause(self):
        failure = StorageAccessError(StorageAccessProblem.EXPIRED)
        with pytest.raises(StorageAccessError) as raised:
            raise_storage_access_error(failure)
        assert raised.value is failure
        assert failure.__cause__ is None
