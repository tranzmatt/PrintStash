"""Captured settings belong to visible live Artifacts, with bounded pagination."""

import json

import pytest

from app.db.models import CollectionRole, DerivativeKind, DerivativeState, FileType
from app.modules.derivatives.kinds import GCODE_METADATA_RECIPE

CAPTURE = {
    "printer": {"nozzle_diameter": "0.4"},
    "filament": {"filament_flow_ratio": "0.98;1.02"},
    "process": {"layer_height": "0.2"},
}
OUTPUT = json.dumps({"slicer_settings": CAPTURE})


@pytest.fixture
def captured_file(make_model, make_file, make_derivative):
    artifact = make_file(
        make_model(),
        filename="bracket.gcode",
        metadata={"slicer_name": "OrcaSlicer", "slicer_version": "2.3.2"},
    )
    make_derivative(artifact, DerivativeKind.METADATA, output_json=OUTPUT)
    return artifact


class TestListSlicerProfiles:
    def test_lists_one_capture_after_reprocessing(
        self,
        client,
        auth_headers,
        captured_file,
        make_derivative,
    ):
        make_derivative(
            captured_file,
            DerivativeKind.METADATA,
            recipe_version=GCODE_METADATA_RECIPE - 1,
            output_json="{}",
        )

        result = client.get(
            "/api/v1/slicer-profiles?limit=1", headers=auth_headers
        ).json()

        assert result["next_before_id"] is None
        assert [item["file_id"] for item in result["items"]] == [captured_file.id]

    def test_keeps_the_ready_capture_during_reprocessing(
        self,
        client,
        auth_headers,
        captured_file,
        make_derivative,
    ):
        make_derivative(
            captured_file,
            DerivativeKind.METADATA,
            recipe_version=GCODE_METADATA_RECIPE + 1,
            state=DerivativeState.RUNNING,
        )

        result = client.get("/api/v1/slicer-profiles", headers=auth_headers).json()

        assert [item["settings"] for item in result["items"]] == [CAPTURE]

    def test_lists_settings_for_a_granted_viewer(
        self,
        client,
        make_user,
        headers_for,
        make_collection,
        grant_role,
        make_model,
        make_file,
        make_derivative,
    ):
        viewer = make_user()
        collection = make_collection("Shared")
        grant_role(viewer, collection, CollectionRole.VIEW)
        artifact = make_file(
            make_model(collection=collection), filename="shared.gcode", metadata={}
        )
        make_derivative(artifact, DerivativeKind.METADATA, output_json=OUTPUT)

        response = client.get(
            "/api/v1/slicer-profiles", headers=headers_for(viewer, scope="read")
        )

        assert response.status_code == 200, response.text
        assert [item["file_id"] for item in response.json()["items"]] == [artifact.id]

    def test_returns_the_captured_values(self, client, auth_headers, captured_file):
        response = client.get("/api/v1/slicer-profiles", headers=auth_headers)

        assert response.status_code == 200, response.text
        assert response.json()["items"][0]["settings"] == CAPTURE

    def test_identifies_the_source_artifact(self, client, auth_headers, captured_file):
        result = client.get("/api/v1/slicer-profiles", headers=auth_headers).json()[
            "items"
        ][0]

        assert (
            result["file_id"],
            result["model_id"],
            result["filename"],
            result["slicer_version"],
        ) == (captured_file.id, captured_file.model_id, "bracket.gcode", "2.3.2")

    def test_paginates_without_repeating_files(
        self,
        client,
        auth_headers,
        captured_file,
        make_model,
        make_file,
        make_derivative,
    ):
        newer = make_file(make_model(), filename="newer.gcode", metadata={})
        make_derivative(newer, DerivativeKind.METADATA, output_json=OUTPUT)

        first = client.get(
            "/api/v1/slicer-profiles?limit=1", headers=auth_headers
        ).json()
        second = client.get(
            f"/api/v1/slicer-profiles?limit=1&before_id={first['next_before_id']}",
            headers=auth_headers,
        ).json()

        assert (
            [row["file_id"] for row in first["items"]],
            [row["file_id"] for row in second["items"]],
            second["next_before_id"],
        ) == ([newer.id], [captured_file.id], None)

    def test_keeps_a_cursor_across_legacy_rows(
        self,
        client,
        auth_headers,
        captured_file,
        make_model,
        make_file,
        make_derivative,
    ):
        legacy = make_file(make_model(), filename="legacy.gcode", metadata={})
        make_derivative(legacy, DerivativeKind.METADATA, output_json="{}")

        result = client.get(
            "/api/v1/slicer-profiles?limit=1", headers=auth_headers
        ).json()

        assert result == {"items": [], "next_before_id": legacy.id}

    @pytest.mark.parametrize(
        "state",
        [
            DerivativeState.QUEUED,
            DerivativeState.RUNNING,
            DerivativeState.FAILED,
            DerivativeState.SKIPPED,
        ],
    )
    def test_excludes_unready_derivatives(
        self, client, auth_headers, make_model, make_file, make_derivative, state
    ):
        artifact = make_file(make_model(), filename="pending.gcode", metadata={})
        make_derivative(
            artifact, DerivativeKind.METADATA, state=state, output_json=OUTPUT
        )

        assert (
            client.get("/api/v1/slicer-profiles", headers=auth_headers).json()["items"]
            == []
        )

    def test_excludes_trashed_files(
        self, client, auth_headers, make_model, make_file, make_derivative
    ):
        artifact = make_file(
            make_model(), filename="trashed.gcode", trashed=True, metadata={}
        )
        make_derivative(artifact, DerivativeKind.METADATA, output_json=OUTPUT)

        assert (
            client.get("/api/v1/slicer-profiles", headers=auth_headers).json()["items"]
            == []
        )

    def test_excludes_trashed_models(
        self, client, auth_headers, make_model, make_file, make_derivative
    ):
        artifact = make_file(
            make_model(trashed=True), filename="trashed.gcode", metadata={}
        )
        make_derivative(artifact, DerivativeKind.METADATA, output_json=OUTPUT)

        assert (
            client.get("/api/v1/slicer-profiles", headers=auth_headers).json()["items"]
            == []
        )

    def test_excludes_inaccessible_models(self, client, captured_file, user_headers):
        result = client.get(
            "/api/v1/slicer-profiles", headers=user_headers(scope="read")
        )

        assert result.status_code == 200, result.text
        assert result.json()["items"] == []

    def test_excludes_empty_captures(
        self, client, auth_headers, make_model, make_file, make_derivative
    ):
        artifact = make_file(make_model(), filename="plain.gcode", metadata={})
        make_derivative(
            artifact,
            DerivativeKind.METADATA,
            output_json=json.dumps(
                {"slicer_settings": {"printer": {}, "filament": {}, "process": {}}}
            ),
        )

        assert (
            client.get("/api/v1/slicer-profiles", headers=auth_headers).json()["items"]
            == []
        )

    def test_excludes_non_gcode_sources(
        self, client, auth_headers, make_model, make_file, make_derivative
    ):
        artifact = make_file(make_model(), file_type=FileType.STL, metadata={})
        make_derivative(artifact, DerivativeKind.METADATA, output_json=OUTPUT)

        assert (
            client.get("/api/v1/slicer-profiles", headers=auth_headers).json()["items"]
            == []
        )

    @pytest.mark.parametrize(
        "query", ["limit=0", "limit=51", "before_id=0", "before_id=-1"]
    )
    def test_rejects_invalid_page_bounds(self, client, auth_headers, query):
        assert (
            client.get(
                f"/api/v1/slicer-profiles?{query}", headers=auth_headers
            ).status_code
            == 422
        )

    def test_requires_authentication(self, client):
        assert client.get("/api/v1/slicer-profiles").status_code == 401


@pytest.fixture(params=["filament", "printer"])
def scoped_profile(request, make_filament_profile, make_printer_profile):
    if request.param == "filament":
        profile = make_filament_profile(material=" PLA ", material_brand=" Acme ")
    else:
        profile = make_printer_profile(printer_model=" Machine A ")
    return request.param, profile


@pytest.fixture
def matching_capture(make_model, make_file, make_derivative):
    artifact = make_file(
        make_model(),
        filename="profile.gcode",
        metadata={
            "material_type": "pla",
            "material_brand": "acme",
            "printer_model": "machine a",
        },
    )
    make_derivative(artifact, DerivativeKind.METADATA, output_json=OUTPUT)
    return artifact


class TestListProfileSettings:
    def test_matches_explicit_attributes(
        self, client, auth_headers, scoped_profile, matching_capture
    ):
        kind, profile = scoped_profile
        response = client.get(
            f"/api/v1/slicer-profiles/{kind}/{profile.id}", headers=auth_headers
        )
        assert response.status_code == 200, response.text
        assert [item["file_id"] for item in response.json()["items"]] == [
            matching_capture.id
        ]

    def test_excludes_other_profiles(
        self,
        client,
        auth_headers,
        scoped_profile,
        matching_capture,
        make_model,
        make_file,
        make_derivative,
    ):
        kind, profile = scoped_profile
        other = make_file(
            make_model(),
            filename="other.gcode",
            metadata={
                "material_type": "PETG",
                "material_brand": "other",
                "printer_model": "machine b",
            },
        )
        make_derivative(other, DerivativeKind.METADATA, output_json=OUTPUT)
        result = client.get(
            f"/api/v1/slicer-profiles/{kind}/{profile.id}", headers=auth_headers
        ).json()
        assert [item["file_id"] for item in result["items"]] == [matching_capture.id]

    def test_requires_material_brand_match(
        self, client, auth_headers, matching_capture, make_filament_profile
    ):
        profile = make_filament_profile(material="PLA", material_brand="Different")
        result = client.get(
            f"/api/v1/slicer-profiles/filament/{profile.id}", headers=auth_headers
        ).json()
        assert result["items"] == []

    def test_matches_unbranded_filament(
        self,
        client,
        auth_headers,
        make_filament_profile,
        make_model,
        make_file,
        make_derivative,
    ):
        profile = make_filament_profile(material="PLA", material_brand=None)
        artifact = make_file(make_model(), metadata={"material_type": "PLA"})
        make_derivative(artifact, DerivativeKind.METADATA, output_json=OUTPUT)
        result = client.get(
            f"/api/v1/slicer-profiles/filament/{profile.id}", headers=auth_headers
        ).json()
        assert [item["file_id"] for item in result["items"]] == [artifact.id]

    def test_does_not_match_names_alone(
        self,
        client,
        auth_headers,
        matching_capture,
        make_filament_profile,
        make_printer_profile,
    ):
        profiles = [
            ("filament", make_filament_profile(name="acme", material="")),
            ("printer", make_printer_profile(name="machine a", printer_model=None)),
        ]
        for kind, profile in profiles:
            response = client.get(
                f"/api/v1/slicer-profiles/{kind}/{profile.id}", headers=auth_headers
            )
            assert response.json() == {"items": [], "next_before_id": None}

    def test_paginates_matching_files(
        self,
        client,
        auth_headers,
        scoped_profile,
        matching_capture,
        make_model,
        make_file,
        make_derivative,
    ):
        kind, profile = scoped_profile
        newer = make_file(
            make_model(),
            metadata={
                "material_type": "PLA",
                "material_brand": "Acme",
                "printer_model": "Machine A",
            },
        )
        make_derivative(newer, DerivativeKind.METADATA, output_json=OUTPUT)
        url = f"/api/v1/slicer-profiles/{kind}/{profile.id}"
        first = client.get(url, params={"limit": 1}, headers=auth_headers).json()
        second = client.get(
            url,
            params={"limit": 1, "before_id": first["next_before_id"]},
            headers=auth_headers,
        ).json()
        assert [row["file_id"] for row in first["items"] + second["items"]] == [
            newer.id,
            matching_capture.id,
        ]
        assert second["next_before_id"] is None

    @pytest.mark.parametrize("hidden", ["private", "trashed-file", "trashed-model"])
    def test_excludes_invisible_sources(
        self,
        client,
        headers_for,
        scoped_profile,
        make_user,
        make_model,
        make_file,
        make_collection,
        make_derivative,
        grant_role,
        hidden,
    ):
        kind, profile = scoped_profile
        user = make_user()
        collection = make_collection()
        if hidden != "private":
            grant_role(user, collection, CollectionRole.VIEW)
        artifact = make_file(
            make_model(collection=collection, trashed=hidden == "trashed-model"),
            trashed=hidden == "trashed-file",
            metadata={
                "material_type": "PLA",
                "material_brand": "Acme",
                "printer_model": "Machine A",
            },
        )
        make_derivative(artifact, DerivativeKind.METADATA, output_json=OUTPUT)
        response = client.get(
            f"/api/v1/slicer-profiles/{kind}/{profile.id}",
            headers=headers_for(user, scope="read"),
        )
        assert response.status_code == 200
        assert response.json()["items"] == []

    def test_omits_other_settings_kinds(
        self,
        client,
        auth_headers,
        scoped_profile,
        make_model,
        make_file,
        make_derivative,
    ):
        kind, profile = scoped_profile
        artifact = make_file(
            make_model(),
            metadata={
                "material_type": "PLA",
                "material_brand": "Acme",
                "printer_model": "Machine A",
            },
        )
        capture = {**CAPTURE, kind: {}}
        make_derivative(
            artifact,
            DerivativeKind.METADATA,
            output_json=json.dumps({"slicer_settings": capture}),
        )
        result = client.get(
            f"/api/v1/slicer-profiles/{kind}/{profile.id}", headers=auth_headers
        ).json()
        assert result["items"] == []

    @pytest.mark.parametrize("kind", ["filament", "printer"])
    def test_rejects_missing_profile(self, client, auth_headers, kind):
        response = client.get(
            f"/api/v1/slicer-profiles/{kind}/999999", headers=auth_headers
        )
        assert response.status_code == 404

    @pytest.mark.parametrize(
        "suffix",
        ["filament/0", "process/1", "printer/1?limit=51", "filament/1?before_id=0"],
    )
    def test_rejects_invalid_scope(self, client, auth_headers, suffix):
        response = client.get("/api/v1/slicer-profiles/" + suffix, headers=auth_headers)
        assert response.status_code == 422

    def test_requires_authentication(self, client, scoped_profile):
        kind, profile = scoped_profile
        assert (
            client.get(f"/api/v1/slicer-profiles/{kind}/{profile.id}").status_code
            == 401
        )

    def test_includes_granted_sources(
        self,
        client,
        headers_for,
        scoped_profile,
        make_user,
        make_model,
        make_file,
        make_collection,
        make_derivative,
        grant_role,
    ):
        kind, profile = scoped_profile
        user = make_user()
        collection = make_collection()
        grant_role(user, collection, CollectionRole.VIEW)
        artifact = make_file(
            make_model(collection=collection),
            metadata={
                "material_type": "PLA",
                "material_brand": "Acme",
                "printer_model": "Machine A",
            },
        )
        make_derivative(artifact, DerivativeKind.METADATA, output_json=OUTPUT)
        response = client.get(
            f"/api/v1/slicer-profiles/{kind}/{profile.id}",
            headers=headers_for(user, scope="read"),
        )
        assert response.status_code == 200
        assert [item["file_id"] for item in response.json()["items"]] == [artifact.id]
