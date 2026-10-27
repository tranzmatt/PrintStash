"""A real uploaded print exposes its captured settings through Profiles."""

import pytest

from tests.e2e._jobs import completed_job
from tests.paths import FIXTURES_DIR


@pytest.mark.asyncio
async def test_uploaded_orca_print_exposes_captured_settings(api, superuser_headers):
    source = FIXTURES_DIR / "real_orca_ender3_benchy.gcode"
    accepted = await api.post(
        "/api/v1/ingest/orca",
        files={"file": (source.name, source.read_bytes(), "text/plain")},
        data={"model_name": "Captured Benchy"},
        headers=superuser_headers,
    )
    job = await completed_job(api, accepted, superuser_headers)

    response = await api.get("/api/v1/slicer-profiles", headers=superuser_headers)

    assert response.status_code == 200, response.text
    profile = response.json()["items"][0]
    assert profile["model_id"] == job["model_id"]
    assert profile["settings"]["printer"]["nozzle_diameter"] == "0.4"
    assert profile["settings"]["filament"]["filament_flow_ratio"] == "0.98"
    assert profile["settings"]["process"]["layer_height"] == "0.2"
