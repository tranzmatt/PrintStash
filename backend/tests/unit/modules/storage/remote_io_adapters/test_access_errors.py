"""Remote I/O preserves actionable authentication failures without retrying."""

from contextlib import contextmanager
from io import BytesIO
from types import SimpleNamespace

import pytest
from opendal.exceptions import Unexpected

from app.modules.storage.access_errors import StorageAccessError
from app.modules.storage.remote_io_adapters import remote_io_for
from app.modules.storage.storage_providers import TransportKind, TransportSpec


class RejectingOperator:
    def __init__(self, *, accept_upload=False):
        self.requests = []
        self.closed = False
        self.accept_upload = accept_upload
        self.published = b""

    def capability(self):
        return SimpleNamespace(write_with_if_not_exists=True)

    def reject(self, operation):
        self.requests.append(operation)
        raise Unexpected(
            'Unexpected => S3Error { code: "ExpiredToken", message: "SECRET key not found: 404" }'
        )

    def exists(self, key):
        return self.reject("exists")

    def stat(self, key):
        return self.reject("stat")

    def check(self):
        self.reject("check")

    def read(self, key):
        return self.reject("read")

    def list(self, directory):
        return self.reject("list")

    @contextmanager
    def open(self, key, mode, **kwargs):
        owner = self

        class Reader(BytesIO):
            def write(self, data):
                if not owner.accept_upload:
                    owner.reject("write")
                owner.requests.append("write")
                owner.published += bytes(data)
                return len(data)

            def read(self, size=-1):
                return owner.reject("stream")

            def read1(self, size=-1):
                return self.read(size)

        try:
            with Reader() as reader:
                yield reader
        finally:
            self.closed = True


class TestRemoteAccessFailures:
    @pytest.mark.parametrize(
        ("operation", "expected_request"),
        [
            pytest.param("exists", "exists", id="existence"),
            pytest.param("object_info", "exists", id="metadata"),
            pytest.param("stat_size", "stat", id="size"),
            pytest.param("read_bytes", "read", id="bytes"),
            pytest.param("check", "check", id="backup-check"),
            pytest.param("iter_directory", "list", id="library-list"),
            pytest.param("open_reader", "stream", id="stream"),
            pytest.param("publish_replica", "write", id="backup-upload"),
        ],
    )
    def test_reports_access_failure_from_remote_operation(
        self, operation, expected_request
    ):
        operator = RejectingOperator()
        remote = remote_io_for(
            TransportSpec(
                kind=TransportKind.S3,
                provider="s3",
                namespace="fixture-bucket",
                options={},
            ),
            operator=operator,
        )
        with pytest.raises(StorageAccessError, match="^storage_credentials_expired$"):
            if operation == "check":
                remote.check()
            elif operation == "iter_directory":
                with remote.iter_directory("") as entries:
                    list(entries)
            elif operation == "publish_replica":
                remote.publish_replica(
                    BytesIO(b"backup"), remote.source_key("archive.tar")
                )
            elif operation == "open_reader":
                with remote.open_reader(remote.source_key("model.stl")) as reader:
                    reader.read()
            else:
                getattr(remote, operation)(remote.source_key("model.stl"))
        assert operator.requests == [expected_request]
        if operation == "open_reader":
            assert operator.closed

    def test_reports_access_failure_after_replica_upload(self):
        operator = RejectingOperator(accept_upload=True)
        remote = remote_io_for(
            TransportSpec(
                kind=TransportKind.S3,
                provider="s3",
                namespace="fixture-bucket",
                options={},
            ),
            operator=operator,
        )
        with pytest.raises(StorageAccessError, match="^storage_credentials_expired$"):
            remote.publish_replica(BytesIO(b"backup"), remote.source_key("archive.tar"))
        assert operator.requests == ["write", "stat"]
        assert operator.published == b"backup"
        assert operator.closed
