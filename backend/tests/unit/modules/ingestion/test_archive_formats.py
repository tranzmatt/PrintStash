"""TAR, 7z and RAR archives become the stored ZIP the review flow reads.

The review lists entry ids from that ZIP and the later selection rewrites the
archive again, so the output must be byte-identical every time. The rewrite is
also the only place these formats meet the archive limits: every refusal the
ZIP inspector makes for a ZIP has to be made here for the other formats.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest
from printstash_core.files.archives import ArchiveLimits, ArchivePolicyError

from app.modules.ingestion import archive_formats
from app.modules.ingestion.archive_formats import ArchiveFormat
from tests.factories.content import rar_bytes, seven_zip_bytes, tar_bytes, zip_bytes

LIMITS = ArchiveLimits(
    max_entries=10,
    max_entry_bytes=1000,
    max_total_bytes=1500,
    max_central_directory_bytes=1 << 20,
    max_path_bytes=64,
    max_depth=3,
)
ENTRIES = {"pack/a.stl": b"solid a", "pack/deep/b.3mf": b"PK-3mf", "notes.txt": b"n"}


def _keep(name: str) -> bool:
    return not name.endswith(".txt")


def _build(archive: ArchiveFormat, entries: dict[str, bytes]) -> bytes:
    if archive is ArchiveFormat.TAR:
        return tar_bytes(entries)
    if archive is ArchiveFormat.SEVEN_ZIP:
        return seven_zip_bytes(entries)
    return rar_bytes(entries)


def _transcode(tmp_path: Path, archive: ArchiveFormat, data: bytes, name="out.zip"):
    source = tmp_path / f"source.{archive.value}"
    source.write_bytes(data)
    target = tmp_path / name
    archive_formats.transcode_to_zip(
        source, archive, target, limits=LIMITS, keep=_keep, on_chunk=lambda: None
    )
    return target


FORMATS = [ArchiveFormat.TAR, ArchiveFormat.SEVEN_ZIP, ArchiveFormat.RAR]


class TestFormatNames:
    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("pack.zip", ArchiveFormat.ZIP),
            ("Pack.TAR.GZ", ArchiveFormat.TAR),
            ("pack.tgz", ArchiveFormat.TAR),
            ("pack.tar.xz", ArchiveFormat.TAR),
            ("pack.tar.bz2", ArchiveFormat.TAR),
            ("pack.tar", ArchiveFormat.TAR),
            ("pack.7z", ArchiveFormat.SEVEN_ZIP),
            ("pack.rar", ArchiveFormat.RAR),
            ("part.stl", None),
            ("part.stl.gz", None),
        ],
    )
    def test_names_the_archive_its_suffix_names(self, filename, expected) -> None:
        assert archive_formats.named_format(filename) is expected

    def test_keeps_the_whole_compound_suffix(self) -> None:
        assert archive_formats.archive_suffix("pack.tar.gz") == ".tar.gz"


class TestSniffing:
    @pytest.mark.parametrize(
        ("data", "expected"),
        [
            (zip_bytes({"a.stl": b"x"}), ArchiveFormat.ZIP),
            (tar_bytes({"a.stl": b"x"}), ArchiveFormat.TAR),
            (tar_bytes({"a.stl": b"x"}, compression=""), ArchiveFormat.TAR),
            (seven_zip_bytes({"a.stl": b"x"}), ArchiveFormat.SEVEN_ZIP),
            (rar_bytes({"a.stl": b"x"}), ArchiveFormat.RAR),
            (b"solid part\nendsolid\n", None),
        ],
        ids=["zip", "tar.gz", "tar", "7z", "rar", "stl"],
    )
    def test_recognizes_an_archive_by_its_bytes(self, tmp_path, data, expected) -> None:
        path = tmp_path / "download"
        path.write_bytes(data)

        assert archive_formats.sniff_format(path) is expected


@pytest.mark.parametrize("archive", FORMATS, ids=lambda archive: archive.value)
class TestTranscoding:
    def test_keeps_models_with_their_paths(self, tmp_path, archive) -> None:
        target = _transcode(tmp_path, archive, _build(archive, ENTRIES))

        with zipfile.ZipFile(target) as output:
            assert {info.filename: output.read(info) for info in output.infolist()} == {
                "pack/a.stl": b"solid a",
                "pack/deep/b.3mf": b"PK-3mf",
            }

    def test_stores_members_uncompressed(self, tmp_path, archive) -> None:
        target = _transcode(tmp_path, archive, _build(archive, ENTRIES))

        with zipfile.ZipFile(target) as output:
            assert {info.compress_type for info in output.infolist()} == {
                zipfile.ZIP_STORED
            }

    def test_writes_identical_bytes_on_every_run(self, tmp_path, archive) -> None:
        data = _build(archive, ENTRIES)
        first = _transcode(tmp_path, archive, data, "first.zip")
        second = _transcode(tmp_path, archive, data, "second.zip")

        assert (
            hashlib.sha256(first.read_bytes()).digest()
            == hashlib.sha256(second.read_bytes()).digest()
        )

    def test_plans_at_least_the_bytes_it_writes(self, tmp_path, archive) -> None:
        source = tmp_path / "source"
        source.write_bytes(_build(archive, ENTRIES))
        planned = archive_formats.planned_zip_bytes(
            source, archive, limits=LIMITS, keep=_keep
        )

        target = _transcode(tmp_path, archive, source.read_bytes())

        assert target.stat().st_size <= planned

    def test_refuses_an_entry_over_the_entry_limit(self, tmp_path, archive) -> None:
        data = _build(archive, {"big.stl": b"x" * 1001})

        with pytest.raises(ArchivePolicyError, match="archive_entry_too_large"):
            _transcode(tmp_path, archive, data)

    def test_refuses_kept_bytes_over_the_total_limit(self, tmp_path, archive) -> None:
        data = _build(archive, {"a.stl": b"x" * 800, "b.stl": b"y" * 800})

        with pytest.raises(ArchivePolicyError, match="archive_too_large"):
            _transcode(tmp_path, archive, data)

    def test_refuses_more_entries_than_the_limit(self, tmp_path, archive) -> None:
        data = _build(archive, {f"{index}.txt": b"" for index in range(11)})

        with pytest.raises(ArchivePolicyError, match="archive_too_many_entries"):
            _transcode(tmp_path, archive, data)

    def test_refuses_a_path_deeper_than_the_limit(self, tmp_path, archive) -> None:
        data = _build(archive, {"a/b/c/d/e.stl": b"x"})

        with pytest.raises(ArchivePolicyError, match="archive_path_too_deep"):
            _transcode(tmp_path, archive, data)

    def test_refuses_names_equal_after_case_folding(self, tmp_path, archive) -> None:
        data = _build(archive, {"Part.stl": b"x", "part.STL": b"y"})

        with pytest.raises(ArchivePolicyError, match="archive_duplicate_entry"):
            _transcode(tmp_path, archive, data)


class TestTranscodingPaths:
    # py7zr refuses to write a traversing name, so no 7z fixture can hold one.
    @pytest.mark.parametrize(
        "archive",
        [ArchiveFormat.TAR, ArchiveFormat.RAR],
        ids=lambda archive: archive.value,
    )
    def test_refuses_a_traversing_path(self, tmp_path, archive) -> None:
        data = _build(archive, {"../escape.stl": b"x"})

        with pytest.raises(ArchivePolicyError, match="archive_unsafe_entry"):
            _transcode(tmp_path, archive, data)


class TestTarMembers:
    def test_drops_symbolic_links(self, tmp_path) -> None:
        data = tar_bytes({"a.stl": b"x"}, links={"escape.stl": "/etc/passwd"})

        target = _transcode(tmp_path, ArchiveFormat.TAR, data)

        with zipfile.ZipFile(target) as output:
            assert output.namelist() == ["a.stl"]

    def test_refuses_a_truncated_archive(self, tmp_path) -> None:
        data = tar_bytes({"a.stl": b"x" * 600}, compression="")[:700]

        with pytest.raises(ArchivePolicyError, match="archive_invalid"):
            _transcode(tmp_path, ArchiveFormat.TAR, data)


class TestSevenZipMembers:
    def test_refuses_an_encrypted_archive(self, tmp_path) -> None:
        data = seven_zip_bytes({"a.stl": b"x"}, password="secret")

        with pytest.raises(ArchivePolicyError, match="archive_invalid"):
            _transcode(tmp_path, ArchiveFormat.SEVEN_ZIP, data)

    def test_refuses_bytes_that_are_not_a_7z(self, tmp_path) -> None:
        with pytest.raises(ArchivePolicyError, match="archive_invalid"):
            _transcode(tmp_path, ArchiveFormat.SEVEN_ZIP, b"7z\xbc\xaf\x27\x1cbroken")


class TestRarMembers:
    def test_refuses_bytes_that_are_not_a_rar(self, tmp_path) -> None:
        with pytest.raises(ArchivePolicyError, match="archive_invalid"):
            _transcode(tmp_path, ArchiveFormat.RAR, b"Rar!\x1a\x07\x00broken")
