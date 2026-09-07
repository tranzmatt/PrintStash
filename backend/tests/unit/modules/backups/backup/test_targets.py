"""Remote identity and configuration snapshots fail closed on disagreement."""

import pytest

from app.modules.backups.backup import contracts, targets


class TestRemoteIdentity:
    @pytest.mark.parametrize(
        ("response", "error"),
        [
            (
                {"ContentLength": 2, "ETag": '"one"', "VersionId": "v1"},
                "backup_remote_size_changed",
            ),
            (
                {"ContentLength": 1, "ETag": '"two"', "VersionId": "v1"},
                "backup_remote_etag_changed",
            ),
            (
                {"ContentLength": 1, "ETag": '"one"', "VersionId": "v2"},
                "backup_remote_version_changed",
            ),
        ],
    )
    def test_response_must_match_every_selected_identity_component(
        self, response, error
    ):
        with pytest.raises(contracts.BackupOwnershipError, match=error):
            targets._assert_s3_identity(
                response, size_bytes=1, etag='"one"', version_id="v1"
            )

    def test_version_does_not_hide_an_etag_change(self):
        with pytest.raises(
            contracts.BackupOwnershipError, match="backup_remote_etag_changed"
        ):
            targets._assert_same_s3_identity(
                {"VersionId": "v1", "ETag": "changed"},
                {"VersionId": "v1", "ETag": "selected"},
            )

    def test_config_changing_through_every_retry_cannot_build_a_target(
        self, monkeypatch
    ):
        snapshots = iter(
            [(str(i), "endpoint", "region", "access", "secret") for i in range(4)]
        )
        monkeypatch.setattr(targets, "_backup_s3_config", lambda: next(snapshots))
        with pytest.raises(
            contracts._BackupConfigUnstableError, match="backup_s3_config_changed"
        ):
            targets._stable_backup_s3_config()

    def test_config_settling_after_an_update_uses_the_whole_new_snapshot(
        self, monkeypatch
    ):
        old = ("old", "endpoint", "region", "access", "secret")
        new = ("new", "endpoint2", "region2", "access2", "secret2")
        snapshots = iter([old, new, new])
        monkeypatch.setattr(targets, "_backup_s3_config", lambda: next(snapshots))
        assert targets._stable_backup_s3_config() == new
