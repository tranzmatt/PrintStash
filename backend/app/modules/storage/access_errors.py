"""Display-safe credential failures at remote storage boundaries.

Transport details can contain signed URLs and credentials. Only recognized
provider evidence becomes a public code; unknown failures keep their existing
classification. No extra request is made to diagnose a failed operation.
"""

from __future__ import annotations

import re
from enum import StrEnum

from app.modules.storage.storage_backend.contracts import StorageConfigurationError


class StorageAccessProblem(StrEnum):
    EXPIRED = "storage_credentials_expired"
    REJECTED = "storage_authentication_failed"
    DENIED = "storage_access_denied"
    SIGNATURE = "storage_signature_invalid"


class StorageAccessError(StorageConfigurationError):
    def __init__(self, problem: StorageAccessProblem) -> None:
        super().__init__(problem.value)
        self.problem = problem


_S3_CODES = {
    "ExpiredToken": StorageAccessProblem.EXPIRED,
    "ExpiredTokenException": StorageAccessProblem.EXPIRED,
    "InvalidAccessKeyId": StorageAccessProblem.REJECTED,
    "InvalidSecurity": StorageAccessProblem.REJECTED,
    "InvalidToken": StorageAccessProblem.REJECTED,
    "TokenRefreshRequired": StorageAccessProblem.REJECTED,
    "AccessDenied": StorageAccessProblem.DENIED,
    "AllAccessDisabled": StorageAccessProblem.DENIED,
    "SignatureDoesNotMatch": StorageAccessProblem.SIGNATURE,
    "InvalidSignature": StorageAccessProblem.SIGNATURE,
    "RequestTimeTooSkewed": StorageAccessProblem.SIGNATURE,
    "RequestExpired": StorageAccessProblem.SIGNATURE,
}
# OpenDAL's Python binding exposes exception classes and display text, not the
# Rust response fields. Match its S3Error and HTTP Parts structures, never an
# arbitrary occurrence of a status/token name in an object key or URL.
_S3_ERROR = re.compile(r'\bS3Error \{ code: "([A-Za-z][A-Za-z0-9]*)",')
_HTTP_STATUS = re.compile(r"(?m)^[ \t]*response: Parts \{ status: (401|403),")


def _http_problem(status: int | None) -> StorageAccessProblem | None:
    if status == 401:
        return StorageAccessProblem.REJECTED
    if status == 403:
        return StorageAccessProblem.DENIED
    return None


def _provider_problem(exc: BaseException) -> StorageAccessProblem | None:
    try:
        from botocore.exceptions import (
            ClientError,
            NoCredentialsError,
            PartialCredentialsError,
        )
    except ImportError:
        pass
    else:
        if isinstance(exc, (NoCredentialsError, PartialCredentialsError)):
            return StorageAccessProblem.REJECTED
        if isinstance(exc, ClientError):
            code = exc.response.get("Error", {}).get("Code")
            problem = _S3_CODES.get(code)
            if problem is not None:
                return problem
            return _http_problem(
                exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            )

    try:
        from opendal.exceptions import ConfigInvalid, PermissionDenied, Unexpected
    except ImportError:
        return None
    if not isinstance(exc, (ConfigInvalid, PermissionDenied, Unexpected)):
        return None
    message = str(exc)
    provider_message = message.split("\n\nContext:", 1)[0]
    code = _S3_ERROR.search(provider_message)
    if code is not None:
        problem = _S3_CODES.get(code[1])
        if problem is not None:
            return problem
    status = _HTTP_STATUS.search(message)
    if status is not None:
        return _http_problem(int(status[1]))
    if isinstance(exc, PermissionDenied):
        return StorageAccessProblem.DENIED
    return None


def storage_access_failure(exc: BaseException) -> StorageAccessError | None:
    """Find provider evidence through wrappers without exposing provider text."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, StorageAccessError):
            return current if current is exc else StorageAccessError(current.problem)
        problem = _provider_problem(current)
        if problem is not None:
            return StorageAccessError(problem)
        current = (
            current.__cause__
            if current.__cause__ is not None
            else None
            if current.__suppress_context__
            else current.__context__
        )
    return None


def raise_storage_access_error(exc: BaseException) -> None:
    """Normalize only recognized access failures; callers own other errors."""
    error = storage_access_failure(exc)
    if error is not None:
        if error is exc:
            raise error
        raise error from exc
