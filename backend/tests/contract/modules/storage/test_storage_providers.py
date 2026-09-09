"""Named presets exercise real transport services, without certifying appliances."""

import pytest

from app.modules.storage.storage_opendal import OpenDALStorageBackend
from app.modules.storage.storage_providers import (
    PRESETS,
    parse_provider_config,
    resolve_transport,
)
from tests.fixtures.storage_presets import real_preset_configuration

REMOTE_PRESETS = [
    pytest.param(
        provider,
        id=provider,
        marks=pytest.mark.s3
        if preset["transport"] == "s3"
        else pytest.mark.remote_storage,
    )
    for provider, preset in PRESETS.items()
    if preset["transport"] != "local"
]


@pytest.fixture
def preset_backend(provider):
    spec = resolve_transport(parse_provider_config(real_preset_configuration(provider)))
    backend = OpenDALStorageBackend(spec)
    if spec.kind.value == "sftp":
        backend.provision_root()
    backend.ensure_setup()
    return backend


class TestPresetTransports:
    @pytest.mark.parametrize("provider", REMOTE_PRESETS)
    def test_preserves_exact_source_bytes(self, provider, preset_backend):
        backend = preset_backend
        key = backend.source_key("nested/Unicode-✓.gcode")
        payload = b"G1 X20 Y30\n"
        backend.create_bytes(payload, key)

        result = b"".join(backend.stream_chunks(key))

        assert result == payload
        assert backend.stat_size(key) == len(payload)

    @pytest.mark.parametrize(
        "provider",
        [
            provider
            for provider, preset in PRESETS.items()
            if preset["transport"] == "local"
        ],
    )
    def test_mounted_presets_retain_local_bytes(
        self, provider, local_storage, db_session
    ):
        from app.modules.administration.runtime_config import update_storage_provider
        from app.modules.storage.storage_backend.local import LocalStorageBackend

        update_storage_provider(
            db_session,
            provider=provider,
            raw_config={
                "provider": provider,
                "data_dir": str(local_storage / "files"),
                "thumb_dir": str(local_storage / "thumbs"),
            },
        )
        backend = LocalStorageBackend()
        key = str(local_storage / "files" / "preset.gcode")
        backend.create_bytes(b"G1 X30\n", key)

        result = backend.read_bytes(key)

        assert result == b"G1 X30\n"
