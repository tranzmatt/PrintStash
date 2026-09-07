"""Malformed restore manifests are rejected before any destination is written."""

import io
import json
import tarfile

import pytest

from app.modules.backups.backup import archive_format


def _archive(tmp_path, manifest):
    path = tmp_path / "input.tar"
    with tarfile.open(path, "w") as archive:
        if manifest != "missing":
            member = tarfile.TarInfo("manifest.json")
            if manifest == "directory":
                member.type = tarfile.DIRTYPE
                archive.addfile(member)
            else:
                body = (
                    manifest
                    if isinstance(manifest, bytes)
                    else json.dumps(manifest).encode()
                )
                member.size = len(body)
                archive.addfile(member, io.BytesIO(body))
    return path


class TestRestoreManifest:
    @pytest.mark.parametrize(
        "manifest",
        [
            "missing",
            "directory",
            b"{bad",
            {"version": "1", "files": {}},
            {
                "version": "3",
                "files": [],
                "provider_id": "local",
                "transport": "local",
                "namespaces": [42],
            },
            {"version": "1", "files": [{"member": 42, "key": "files/part.stl"}]},
        ],
        ids=[
            "missing",
            "directory",
            "invalid-json",
            "files-not-list",
            "namespace-not-text",
            "member-not-text",
        ],
    )
    def test_refuses_invalid_structure(self, backup_env, tmp_path, manifest):
        with tarfile.open(_archive(tmp_path, manifest)) as archive:
            with pytest.raises(RuntimeError, match="backup_manifest_invalid"):
                archive_format._restore_manifest_entries(archive)
        assert list(backup_env.data_dir.glob("*.stl")) == []

    def test_archive_identity_must_match_current_storage(self, backup_env, tmp_path):
        manifest = {
            "version": "3",
            "files": [],
            "file_count": 0,
            "provider_id": "another-provider",
            "transport": "local",
            "namespace": None,
            "namespaces": [],
        }
        with tarfile.open(_archive(tmp_path, manifest)) as archive:
            with pytest.raises(RuntimeError, match="backup_storage_namespace_mismatch"):
                archive_format._restore_manifest_entries(archive)

    def test_legacy_key_map_ignores_non_entries(self, tmp_path):
        manifest = {
            "files": [
                "invalid",
                {"member": 42, "key": "wrong"},
                {"arc": "files/part.stl", "key": "original-key"},
            ]
        }
        with tarfile.open(_archive(tmp_path, manifest)) as archive:
            assert archive_format._restore_key_map(archive) == {
                "files/part.stl": "original-key"
            }
