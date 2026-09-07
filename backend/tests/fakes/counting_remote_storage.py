"""Remote Artifact read contract backed by a private test directory.

Only the stream interface exposes content; byte counts measure actual chunks
returned to consumers, and direct paths/native redirects are unavailable.
"""

from pathlib import Path

from app.modules.storage.storage_backend.local import LocalStorageBackend


class CountingRemoteStorage(LocalStorageBackend):
    backend_name = "counting-remote"

    def __init__(self):
        super().__init__()
        self.bytes_read = 0
        self.open_readers = 0

    def direct_path(self, key: str):
        return None

    def presigned_download_url(self, key: str, filename: str):
        return None

    def stream_chunks(self, key: str, chunk_size: int = 1024 * 1024):
        self.open_readers += 1
        try:
            with Path(key).open("rb") as source:
                while chunk := source.read(chunk_size):
                    self.bytes_read += len(chunk)
                    yield chunk
        finally:
            self.open_readers -= 1

    def download_to_path(self, key: str, dest: Path):
        with dest.open("wb") as output:
            for chunk in self.stream_chunks(key):
                output.write(chunk)
        return dest
