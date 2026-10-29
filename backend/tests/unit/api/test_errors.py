"""Unexpected failures must not be disguised as recoverable storage problems."""

import pytest
from starlette.requests import Request

from app.api.errors import storage_access_response


class TestStorageAccessResponse:
    @pytest.mark.asyncio
    async def test_propagates_unrelated_failure(self):
        failure = ValueError("unexpected adapter failure")

        with pytest.raises(ValueError, match="unexpected adapter failure") as raised:
            await storage_access_response(Request({"type": "http"}), failure)

        assert raised.value is failure
