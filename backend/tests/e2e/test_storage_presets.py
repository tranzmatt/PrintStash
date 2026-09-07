"""Mounted NAS presets persist through the public setup and file-read boundary."""

import pytest

from app.modules.storage.storage_backend.runtime import init_backend
from app.modules.storage.storage_providers import PRESETS
from tests.factories import build_file, build_model


class TestMountedPresets:
    @pytest.mark.parametrize(
        "provider",
        [
            provider
            for provider, preset in PRESETS.items()
            if preset["transport"] == "local"
        ],
    )
    @pytest.mark.asyncio
    async def test_reads_bytes_after_preset_setup(
        self, api, e2e_db, tmp_path, provider
    ):
        data_dir = tmp_path / "nas" / "models"
        setup = await api.post(
            "/api/v1/setup",
            json={
                "username": "owner",
                "password": "Password123",
                "storage_provider": provider,
                "storage_provider_config": {
                    "provider": provider,
                    "data_dir": str(data_dir),
                    "thumb_dir": str(tmp_path / "thumbs"),
                },
            },
        )
        assert setup.status_code == 201, setup.text
        headers = {"Authorization": f"Bearer {setup.json()['access_token']}"}
        backend = init_backend()
        key = str(data_dir / "preset.gcode")
        backend.create_bytes(b"G1 X20\n", key)
        model = build_model(e2e_db)
        file = build_file(e2e_db, model, path=key)

        response = await api.get(f"/api/v1/files/{file.id}/download", headers=headers)

        assert response.status_code == 200, response.text
        assert response.content == b"G1 X20\n"
        config = await api.get("/api/v1/config", headers=headers)
        assert config.json()["storage_provider"] == provider
