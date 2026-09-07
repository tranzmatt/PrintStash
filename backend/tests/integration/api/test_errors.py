"""Business failures retain the public HTTP contract at the inbound adapter."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.errors import operation_error_response
from app.core.errors import ErrorKind, OperationError


@pytest.fixture
def error_client():
    app = FastAPI()
    app.add_exception_handler(OperationError, operation_error_response)

    @app.get("/failure/{kind}")
    def fail(kind: str, retry_after_seconds: int | None = None):
        raise OperationError(
            "operation_rejected",
            kind=ErrorKind(kind),
            retry_after_seconds=retry_after_seconds,
        )

    with TestClient(app) as client:
        yield client


class TestOperationErrorResponse:
    @pytest.mark.parametrize(
        ("kind", "status"),
        [
            (ErrorKind.INVALID, 400),
            (ErrorKind.FORBIDDEN, 403),
            (ErrorKind.NOT_FOUND, 404),
            (ErrorKind.CONFLICT, 409),
            (ErrorKind.GONE, 410),
            (ErrorKind.TOO_LARGE, 413),
            (ErrorKind.UNPROCESSABLE, 422),
            (ErrorKind.BUSY, 429),
            (ErrorKind.UPSTREAM, 502),
            (ErrorKind.UNAVAILABLE, 503),
            (ErrorKind.TIMEOUT, 504),
        ],
        ids=lambda value: value.value if isinstance(value, ErrorKind) else str(value),
    )
    def test_preserves_the_error_response(self, error_client, kind, status):
        response = error_client.get(f"/failure/{kind.value}")

        assert response.status_code == status
        assert response.json() == {"detail": "operation_rejected"}
        assert "Retry-After" not in response.headers

    def test_exposes_the_retry_delay(self, error_client):
        response = error_client.get("/failure/busy?retry_after_seconds=2")

        assert response.status_code == 429
        assert response.headers["Retry-After"] == "2"
