"""Descriptor-pinned external-root marker parsing, independent of scanning."""

import json
import os
import stat

ROOT_MARKER_FILENAME = ".printstash-external-root.json"


ROOT_MARKER_FORMAT = 1


ROOT_MARKER_ROLE = "external-library"


_ROOT_MARKER_KEYS = {
    "format",
    "installation",
    "role",
    "library_id",
    "root_identity",
}


_ROOT_MARKER_MAX_BYTES = 4096


def _validate_marker_payload(actual: object) -> dict[str, object]:
    if not isinstance(actual, dict) or set(actual) != _ROOT_MARKER_KEYS:
        raise ValueError("root_marker_invalid")
    if type(actual["format"]) is not int or actual["format"] != ROOT_MARKER_FORMAT:
        raise ValueError("root_marker_invalid")
    installation = actual["installation"]
    token = actual["root_identity"]
    if (
        not isinstance(installation, str)
        or len(installation) != 64
        or any(char not in "0123456789abcdefABCDEF" for char in installation)
        or actual["role"] != ROOT_MARKER_ROLE
        or type(actual["library_id"]) is not int
        or actual["library_id"] <= 0
        or not isinstance(token, str)
        or len(token) != 64
        or any(char not in "0123456789abcdefABCDEF" for char in token)
    ):
        raise ValueError("root_marker_invalid")
    return actual


def read_root_marker_fd(root_fd: int) -> dict[str, object]:
    """Parse a marker through a pinned root descriptor, fail-closed."""
    marker_fd = os.open(
        ROOT_MARKER_FILENAME,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=root_fd,
    )
    try:
        marker_stat = os.fstat(marker_fd)
        if (
            not stat.S_ISREG(marker_stat.st_mode)
            or marker_stat.st_size > _ROOT_MARKER_MAX_BYTES
        ):
            raise ValueError("root_marker_invalid")
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(marker_fd, 1024):
            total += len(chunk)
            if total > _ROOT_MARKER_MAX_BYTES:
                raise ValueError("root_marker_invalid")
            chunks.append(chunk)
        return _validate_marker_payload(json.loads(b"".join(chunks).decode("utf-8")))
    finally:
        os.close(marker_fd)
