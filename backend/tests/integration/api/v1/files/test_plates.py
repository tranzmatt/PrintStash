"""A slicer project's plates, and each plate's preview, over HTTP.

The model page lists a multi-plate 3MF's plates and shows one plate at a time,
so the layout it reads must be the derivative's, never one parsed inside the
request: until the ``plates`` derivative is ready the list is empty and its
state says why. A plate's preview is the image the slicer saved in the package,
and only a reader of the Model's collection may see either.
"""

from __future__ import annotations

import hashlib

import pytest

from app.db.models import CollectionRole, FileType
from app.modules.derivatives import producers
from app.modules.storage.storage_backend.runtime import get_backend
from tests.factories.content import png
from tests.fixtures.three_mf_projects import (
    build_3d_builder_component_project,
    build_multi_plate_project,
)


@pytest.fixture
def project(make_model, make_file):
    def build(data: bytes, *, slug: str = "rack", **fields):
        key = f"plates/{hashlib.sha256(data).hexdigest()}.3mf"
        get_backend().write_bytes(data, key)
        return make_file(
            make_model(slug, **fields),
            filename="rack.3mf",
            ftype=FileType.THREE_MF.value,
            path=key,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )

    return build


class TestFilePlates:
    def test_lists_the_plates_of_a_derived_project(self, client, auth_headers, project):
        artifact = project(build_multi_plate_project())
        producers.derive_plates(artifact.id)

        response = client.get(
            f"/api/v1/files/{artifact.id}/plates", headers=auth_headers
        )

        assert response.status_code == 200, response.text
        assert response.json() == {
            "state": "ready",
            "plates": [
                {
                    "number": 1,
                    "name": "Main parts",
                    "object_count": 1,
                    "image_url": f"/api/v1/files/{artifact.id}/plates/1/image",
                    "region": {
                        "min_x": 0.0,
                        "min_y": 0.0,
                        "max_x": 256.0,
                        "max_y": 256.0,
                    },
                },
                {
                    "number": 2,
                    "name": "Wall mount",
                    "object_count": 1,
                    "image_url": f"/api/v1/files/{artifact.id}/plates/2/image",
                    "region": {
                        "min_x": 307.2,
                        "min_y": 0.0,
                        "max_x": 563.2,
                        "max_y": 256.0,
                    },
                },
            ],
        }

    def test_reports_a_pending_layout_before_derivation(
        self, client, auth_headers, project
    ):
        artifact = project(build_multi_plate_project())

        response = client.get(
            f"/api/v1/files/{artifact.id}/plates", headers=auth_headers
        )

        assert response.json() == {"state": "pending", "plates": []}

    def test_reports_a_package_that_is_not_a_project_as_skipped(
        self, client, auth_headers, project
    ):
        artifact = project(build_3d_builder_component_project())
        producers.derive_plates(artifact.id)

        response = client.get(
            f"/api/v1/files/{artifact.id}/plates", headers=auth_headers
        )

        assert response.json() == {"state": "skipped", "plates": []}

    def test_omits_the_preview_of_a_plate_the_slicer_saved_none_for(
        self, client, auth_headers, project
    ):
        artifact = project(build_multi_plate_project(images=False))
        producers.derive_plates(artifact.id)

        response = client.get(
            f"/api/v1/files/{artifact.id}/plates", headers=auth_headers
        )

        assert [plate["image_url"] for plate in response.json()["plates"]] == [
            None,
            None,
        ]

    def test_refuses_an_artifact_that_is_not_a_3mf(
        self, client, auth_headers, make_model, make_file
    ):
        artifact = make_file(make_model("cube"), filename="cube.stl")

        response = client.get(
            f"/api/v1/files/{artifact.id}/plates", headers=auth_headers
        )

        assert (response.status_code, response.json()["detail"]) == (
            404,
            "plates_not_supported",
        )

    def test_requires_authentication(self, client, project):
        artifact = project(build_multi_plate_project())

        response = client.get(f"/api/v1/files/{artifact.id}/plates")

        assert response.status_code == 401, response.text

    def test_denies_a_user_without_the_collection(
        self, client, project, make_collection, make_user, headers_for
    ):
        artifact = project(
            build_multi_plate_project(), collection=make_collection("Private plates")
        )

        response = client.get(
            f"/api/v1/files/{artifact.id}/plates",
            headers=headers_for(make_user("plates-outsider")),
        )

        assert response.status_code == 403, response.text


class TestFilePlateImage:
    def test_serves_the_preview_the_slicer_saved(self, client, auth_headers, project):
        artifact = project(build_multi_plate_project())
        producers.derive_plates(artifact.id)

        response = client.get(
            f"/api/v1/files/{artifact.id}/plates/2/image", headers=auth_headers
        )

        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "image/png"
        assert response.content == png(width=5, height=4)

    def test_allows_a_reader_of_the_parent_collection(
        self, client, project, make_collection, make_user, headers_for, grant_role
    ):
        collection = make_collection("Shared plates")
        artifact = project(build_multi_plate_project(), collection=collection)
        producers.derive_plates(artifact.id)
        reader = make_user("plates-reader")
        grant_role(reader, collection, CollectionRole.VIEW)

        response = client.get(
            f"/api/v1/files/{artifact.id}/plates/1/image", headers=headers_for(reader)
        )

        assert response.status_code == 200, response.text

    def test_answers_a_matching_validator_without_the_image(
        self, client, auth_headers, project
    ):
        artifact = project(build_multi_plate_project())
        producers.derive_plates(artifact.id)
        url = f"/api/v1/files/{artifact.id}/plates/1/image"
        etag = client.get(url, headers=auth_headers).headers["etag"]

        response = client.get(url, headers={**auth_headers, "If-None-Match": etag})

        assert (response.status_code, response.content) == (304, b"")

    @pytest.mark.parametrize("number", [3, 0], ids=["beyond-the-layout", "zero"])
    def test_refuses_a_plate_the_layout_does_not_have(
        self, client, auth_headers, project, number
    ):
        artifact = project(build_multi_plate_project())
        producers.derive_plates(artifact.id)

        response = client.get(
            f"/api/v1/files/{artifact.id}/plates/{number}/image", headers=auth_headers
        )

        assert (response.status_code, response.json()["detail"]) == (
            404,
            "plate_image_not_found",
        )

    def test_refuses_a_plate_without_a_saved_preview(
        self, client, auth_headers, project
    ):
        artifact = project(build_multi_plate_project(images=False))
        producers.derive_plates(artifact.id)

        response = client.get(
            f"/api/v1/files/{artifact.id}/plates/1/image", headers=auth_headers
        )

        assert response.status_code == 404, response.text

    def test_refuses_a_layout_that_is_not_derived_yet(
        self, client, auth_headers, project
    ):
        artifact = project(build_multi_plate_project())

        response = client.get(
            f"/api/v1/files/{artifact.id}/plates/1/image", headers=auth_headers
        )

        assert response.status_code == 404, response.text

    def test_reports_a_blob_missing_from_storage(
        self, client, auth_headers, project, remove_blob
    ):
        artifact = project(build_multi_plate_project())
        producers.derive_plates(artifact.id)
        remove_blob(artifact.path)

        response = client.get(
            f"/api/v1/files/{artifact.id}/plates/1/image", headers=auth_headers
        )

        assert (response.status_code, response.json()["detail"]) == (
            410,
            "file_blob_missing",
        )

    def test_requires_authentication(self, client, project):
        artifact = project(build_multi_plate_project())
        producers.derive_plates(artifact.id)

        response = client.get(f"/api/v1/files/{artifact.id}/plates/1/image")

        assert response.status_code == 401, response.text

    def test_denies_a_user_without_the_collection(
        self, client, project, make_collection, make_user, headers_for
    ):
        artifact = project(
            build_multi_plate_project(), collection=make_collection("Private previews")
        )
        producers.derive_plates(artifact.id)

        response = client.get(
            f"/api/v1/files/{artifact.id}/plates/1/image",
            headers=headers_for(make_user("preview-outsider")),
        )

        assert response.status_code == 403, response.text
