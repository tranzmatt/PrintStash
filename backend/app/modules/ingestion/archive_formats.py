"""TAR, 7z and RAR archives become a ZIP the existing review flow already owns.

Archive review, selection and extraction are ZIP-only: entry ids come from the
ZIP directory and each selected entry is opened by name. Rather than teach that
flow a second random-access reader, a non-ZIP archive is read once, in its own
order, into an uncompressed ZIP under the same entry, size and path limits. The
output is deterministic, so a review and its later selection see the same ids.
"""

from __future__ import annotations

import tarfile
import unicodedata
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import IO, Protocol

from printstash_core.files.archives import (
    ArchiveLimits,
    ArchivePolicyError,
    safe_entry_name,
)

# Members are written with one fixed timestamp: the transcoded bytes, and so
# every entry id derived from them, depend only on the source archive.
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)
_CHUNK = 1024 * 1024
# A stored ZIP64 member costs a local header, data descriptor and central
# record around its bytes, each repeating the name; 256 bytes covers the rest.
_MEMBER_OVERHEAD = 256
_DIRECTORY_OVERHEAD = 1024
_SEVEN_ZIP_MAGIC = b"7z\xbc\xaf\x27\x1c"
_RAR_MAGICS = (b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00")


class ArchiveFormat(StrEnum):
    ZIP = "zip"
    TAR = "tar"
    SEVEN_ZIP = "7z"
    RAR = "rar"


# Longest first: ``.tar.gz`` must not be read as a ``.gz`` file.
ARCHIVE_SUFFIXES: tuple[tuple[str, ArchiveFormat], ...] = (
    (".tar.gz", ArchiveFormat.TAR),
    (".tar.bz2", ArchiveFormat.TAR),
    (".tar.xz", ArchiveFormat.TAR),
    (".tgz", ArchiveFormat.TAR),
    (".tar", ArchiveFormat.TAR),
    (".zip", ArchiveFormat.ZIP),
    (".7z", ArchiveFormat.SEVEN_ZIP),
    (".rar", ArchiveFormat.RAR),
)


def archive_suffix(filename: str) -> str | None:
    """The archive suffix *filename* ends with, compound suffixes included."""
    lower = filename.lower()
    return next(
        (suffix for suffix, _ in ARCHIVE_SUFFIXES if lower.endswith(suffix)), None
    )


def named_format(filename: str) -> ArchiveFormat | None:
    """The archive format *filename* names, without reading any bytes."""
    lower = filename.lower()
    return next(
        (archive for suffix, archive in ARCHIVE_SUFFIXES if lower.endswith(suffix)),
        None,
    )


def sniff_format(path: Path) -> ArchiveFormat | None:
    """The archive format *path*'s bytes hold, for links that name no suffix."""
    with path.open("rb") as source:
        head = source.read(8)
    if head.startswith(_SEVEN_ZIP_MAGIC):
        return ArchiveFormat.SEVEN_ZIP
    if head.startswith(_RAR_MAGICS):
        return ArchiveFormat.RAR
    if zipfile.is_zipfile(path):
        return ArchiveFormat.ZIP
    try:
        if tarfile.is_tarfile(path):
            return ArchiveFormat.TAR
    except OSError, EOFError, tarfile.TarError:
        return None
    return None


class _Readable(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...


@dataclass(frozen=True)
class _Member:
    name: str
    size: int


class _Writer:
    """Copy kept members into a stored ZIP while enforcing archive limits."""

    def __init__(
        self,
        archive: zipfile.ZipFile | None,
        *,
        limits: ArchiveLimits,
        keep: Callable[[str], bool],
        on_chunk: Callable[[], None],
    ) -> None:
        # Without an output ZIP the writer only plans: it admits every member
        # under the same limits and sums the bytes the ZIP will need.
        self._archive = archive
        self.planned_bytes = _DIRECTORY_OVERHEAD
        self._limits = limits
        self._keep = keep
        self._on_chunk = on_chunk
        self._entries = 0
        self._total = 0
        self._names: set[str] = set()
        self._handle: IO[bytes] | None = None

    def admit(self, member: _Member) -> bool:
        """Check one regular file; True when its bytes belong in the output."""
        self._entries += 1
        if self._entries > self._limits.max_entries:
            raise ArchivePolicyError("archive_too_many_entries")
        normalized = unicodedata.normalize("NFC", member.name.replace("\\", "/"))
        if len(normalized.encode("utf-8")) > self._limits.max_path_bytes or (
            len(PurePosixPath(normalized).parts) > self._limits.max_depth + 1
        ):
            raise ArchivePolicyError("archive_path_too_deep")
        if not safe_entry_name(member.name):
            raise ArchivePolicyError("archive_unsafe_entry")
        folded = normalized.casefold()
        if folded in self._names:
            raise ArchivePolicyError("archive_duplicate_entry")
        self._names.add(folded)
        if member.size > self._limits.max_entry_bytes:
            raise ArchivePolicyError("archive_entry_too_large")
        if not self._keep(member.name):
            return False
        self._total += member.size
        if self._total > self._limits.max_total_bytes:
            raise ArchivePolicyError("archive_too_large")
        self.planned_bytes += (
            member.size + _MEMBER_OVERHEAD + 2 * len(member.name.encode("utf-8"))
        )
        return self._archive is not None

    @contextmanager
    def member(self, member: _Member) -> Iterator[_BoundedTarget]:
        assert self._archive is not None
        info = zipfile.ZipInfo(member.name, date_time=_FIXED_TIME)
        info.compress_type = zipfile.ZIP_STORED
        info.external_attr = 0o644 << 16
        with self._archive.open(info, "w", force_zip64=True) as target:
            self._handle = target
            yield _BoundedTarget(target, member, self._on_chunk)
        self._handle = None

    def abort(self) -> None:
        """Release a member a failed reader left open, so the failure surfaces."""
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def copy(self, member: _Member, source: _Readable) -> None:
        with self.member(member) as target:
            while chunk := source.read(_CHUNK):
                target.write(chunk)
            target.close()


class _BoundedTarget:
    """A ZIP member that refuses more bytes than its archive declared."""

    def __init__(
        self, target: IO[bytes], member: _Member, on_chunk: Callable[[], None]
    ):
        self._target = target
        self._member = member
        self._on_chunk = on_chunk
        self._written = 0

    def write(self, chunk: bytes) -> int:
        self._on_chunk()
        self._written += len(chunk)
        if self._written > self._member.size:
            raise ArchivePolicyError("archive_entry_too_large")
        return self._target.write(chunk)

    def close(self) -> None:
        if self._written != self._member.size:
            raise ArchivePolicyError("archive_invalid")


def planned_zip_bytes(
    source: Path,
    archive: ArchiveFormat,
    *,
    limits: ArchiveLimits,
    keep: Callable[[str], bool],
) -> int:
    """Bytes the stored ZIP of *source* will take, refusing it as transcoding would.

    The plan reads only the archive's own directory, except for TAR, whose
    member headers are spread through the (possibly compressed) stream.
    """
    writer = _Writer(None, limits=limits, keep=keep, on_chunk=lambda: None)
    _READERS[archive](source, writer)
    return writer.planned_bytes


def transcode_to_zip(
    source: Path,
    archive: ArchiveFormat,
    destination: Path,
    *,
    limits: ArchiveLimits,
    keep: Callable[[str], bool],
    on_chunk: Callable[[], None],
) -> None:
    """Write *source*'s kept regular files to *destination* as a stored ZIP.

    Directories, links and device entries are dropped: they carry no model and
    a link could only point at something outside the archive. Every other entry
    counts toward the entry limit and must have a safe, unique path.
    """
    with zipfile.ZipFile(destination, "w", allowZip64=True) as output:
        writer = _Writer(output, limits=limits, keep=keep, on_chunk=on_chunk)
        try:
            _READERS[archive](source, writer)
        except BaseException:
            writer.abort()
            raise


def _copy_tar(source: Path, writer: _Writer) -> None:
    try:
        # Stream mode reads members in order without seeking back; it is the
        # only mode that never revisits a compressed member.
        with tarfile.open(source, mode="r|*") as archive:
            for info in archive:
                if not info.isreg():
                    continue
                member = _Member(info.name, info.size)
                if not writer.admit(member):
                    continue
                extracted = archive.extractfile(info)
                if extracted is None:
                    raise ArchivePolicyError("archive_invalid")
                writer.copy(member, extracted)
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise ArchivePolicyError("archive_invalid") from exc


def _copy_seven_zip(source: Path, writer: _Writer) -> None:
    import py7zr
    from py7zr.exceptions import ArchiveError
    from py7zr.io import Py7zIO, WriterFactory

    class Member(Py7zIO):
        """Stream one decompressed member into its open ZIP entry."""

        def __init__(self, member: _Member) -> None:
            self._context = writer.member(member)
            self._target = self._context.__enter__()

        def write(self, s: bytes | bytearray) -> int:
            return self._target.write(bytes(s))

        def read(self, size: int | None = None) -> bytes:
            raise ArchivePolicyError("archive_invalid")

        def seek(self, offset: int, whence: int = 0) -> int:
            raise ArchivePolicyError("archive_invalid")

        def seekable(self) -> bool:
            # py7zr rewinds seekable products to read them back; a ZIP entry
            # being written cannot be.
            return False

        def flush(self) -> None:
            return None

        def size(self) -> int:
            raise ArchivePolicyError("archive_invalid")

        def close(self) -> None:
            self._target.close()
            self._context.__exit__(None, None, None)

    class Factory(WriterFactory):
        def __init__(self, sizes: dict[str, int]) -> None:
            self._sizes = sizes

        def create(self, filename: str) -> Py7zIO:
            return Member(_Member(filename, self._sizes[filename]))

    try:
        with py7zr.SevenZipFile(source, mode="r") as archive:
            if archive.needs_password():
                raise ArchivePolicyError("archive_invalid")
            sizes: dict[str, int] = {}
            for info in archive.list():
                if info.is_directory or info.is_symlink:
                    continue
                member = _Member(info.filename, int(info.uncompressed))
                if writer.admit(member):
                    sizes[info.filename] = member.size
            if sizes:
                archive.extract(targets=list(sizes), factory=Factory(sizes))
    except ArchivePolicyError:
        raise
    except (ArchiveError, py7zr.Bad7zFile, OSError, ValueError, KeyError) as exc:
        raise ArchivePolicyError("archive_invalid") from exc


def _copy_rar(source: Path, writer: _Writer) -> None:
    import rarfile

    try:
        # Strict parsing: a damaged header is a broken archive, not its end.
        with rarfile.RarFile(source, errors="strict") as archive:
            if archive.needs_password():
                raise ArchivePolicyError("archive_invalid")
            for info in archive.infolist():
                if info.is_dir() or info.is_symlink():
                    continue
                member = _Member(info.filename, int(info.file_size))
                if not writer.admit(member):
                    continue
                with archive.open(info) as extracted:
                    writer.copy(member, extracted)
    except rarfile.RarCannotExec as exc:
        raise ArchivePolicyError("archive_format_unavailable") from exc
    except (rarfile.Error, OSError) as exc:
        raise ArchivePolicyError("archive_invalid") from exc


_READERS: dict[ArchiveFormat, Callable[[Path, _Writer], None]] = {
    ArchiveFormat.TAR: _copy_tar,
    ArchiveFormat.SEVEN_ZIP: _copy_seven_zip,
    ArchiveFormat.RAR: _copy_rar,
}
