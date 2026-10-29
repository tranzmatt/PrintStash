"""Reading a slicer project's plates out of its 3MF.

Bambu Studio and its forks save each plate's name, objects and preview in the
package, and lay the plates out side by side in one build space. The viewer
shows one plate by keeping only the geometry inside that plate's rectangle, so a
wrong rectangle shows the wrong parts, or none. These tests pin the rectangles
to the slicer's own layout, and every package whose plates cannot be placed
with certainty is refused rather than given a layout that would mislead.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.modules.media.three_mf_plates import (
    Plate,
    PlateLayoutError,
    PlateLayoutFailure,
    PlateRegion,
    read_image,
    read_layout,
)
from tests.factories.content import png
from tests.fixtures.three_mf_projects import (
    build_3d_builder_component_project,
    build_multi_plate_project,
)


def _write(tmp_path: Path, data: bytes) -> Path:
    path = tmp_path / "project.3mf"
    path.write_bytes(data)
    return path


def _replace_member(data: bytes, name: str, content: bytes) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(data))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for info in source.infolist():
            if info.filename != name:
                archive.writestr(info, source.read(info))
        archive.writestr(name, content)
    return output.getvalue()


class TestReadLayout:
    def test_reads_each_plates_metadata(self, tmp_path):
        path = _write(tmp_path, build_multi_plate_project())

        layout = read_layout(path)

        assert layout is not None
        assert layout.plates == (
            Plate(
                number=1,
                name="Main parts",
                object_count=1,
                image_member="Metadata/plate_1.png",
                region=PlateRegion(0.0, 0.0, 256.0, 256.0),
            ),
            Plate(
                number=2,
                name="Wall mount",
                object_count=1,
                image_member="Metadata/plate_2.png",
                region=PlateRegion(307.2, 0.0, 563.2, 256.0),
            ),
        )

    def test_lays_a_fifth_plate_out_on_a_second_row_below_the_first(self, tmp_path):
        # Five plates take ceil(sqrt(5)) = 3 columns; plate 4 starts row two at -Y.
        path = _write(
            tmp_path,
            build_multi_plate_project(
                names=("A", "B", "C", "D", "E"),
                placements=(
                    (128.0, 128.0),
                    (435.2, 128.0),
                    (742.4, 128.0),
                    (128.0, -179.2),
                    (435.2, -179.2),
                ),
            ),
        )

        layout = read_layout(path)

        assert layout is not None
        assert [vars(plate.region) for plate in layout.plates[2:4]] == [
            pytest.approx(vars(PlateRegion(614.4, 0.0, 870.4, 256.0))),
            pytest.approx(vars(PlateRegion(0.0, -307.2, 256.0, -51.2))),
        ]

    def test_offsets_each_region_by_a_bed_that_does_not_start_at_zero(self, tmp_path):
        path = _write(
            tmp_path,
            build_multi_plate_project(
                printable_area=("-10x-5", "190x-5", "190x195", "-10x195"),
                placements=((90.0, 90.0), (330.0, 90.0)),
            ),
        )

        layout = read_layout(path)

        assert layout is not None
        assert layout.plates[1].region == PlateRegion(230.0, -5.0, 430.0, 195.0)

    def test_accepts_a_placement_overhanging_its_plate_within_half_the_gap(
        self, tmp_path
    ):
        # The gap between 256 mm plates is 51.2 mm; 280 mm is 24 mm past plate 1.
        path = _write(
            tmp_path,
            build_multi_plate_project(placements=((280.0, 128.0), (435.2, 128.0))),
        )

        layout = read_layout(path)

        assert layout is not None
        assert len(layout.plates) == 2

    def test_leaves_an_unnamed_plate_without_a_name(self, tmp_path):
        path = _write(tmp_path, build_multi_plate_project(names=("", "Wall mount")))

        layout = read_layout(path)

        assert layout is not None
        assert layout.plates[0].name is None

    def test_leaves_a_plate_whose_preview_is_missing_without_an_image(self, tmp_path):
        path = _write(tmp_path, build_multi_plate_project(images=False))

        layout = read_layout(path)

        assert layout is not None
        assert [plate.image_member for plate in layout.plates] == [None, None]

    def test_counts_an_empty_plate_without_reading_the_build(self, tmp_path):
        settings = """<config><plate>
            <metadata key="plater_id" value="1"/>
            <metadata key="plater_name" value="Empty"/>
        </plate></config>"""
        path = _write(tmp_path, build_multi_plate_project(model_settings=settings))

        layout = read_layout(path)

        assert layout is not None
        assert layout.plates[0].object_count == 0

    def test_has_no_layout_without_plate_metadata(self, tmp_path):
        path = _write(tmp_path, build_3d_builder_component_project())

        assert read_layout(path) is None

    def test_has_no_layout_when_the_settings_declare_no_plates(self, tmp_path):
        path = _write(
            tmp_path, build_multi_plate_project(model_settings="<config></config>")
        )

        assert read_layout(path) is None

    @pytest.mark.parametrize(
        "printable_area",
        [None, ("0x0", "256x0"), ("0x0", "256x0", "wide"), ("0x0", "0x0", "0x0")],
        ids=["missing", "two-points", "unparsable", "zero-area"],
    )
    def test_refuses_a_project_without_a_usable_bed(self, tmp_path, printable_area):
        path = _write(
            tmp_path, build_multi_plate_project(printable_area=printable_area)
        )

        with pytest.raises(PlateLayoutError) as raised:
            read_layout(path)

        assert raised.value.failure is PlateLayoutFailure.BED_UNKNOWN

    def test_refuses_a_build_placing_an_object_outside_its_plate(self, tmp_path):
        path = _write(
            tmp_path,
            build_multi_plate_project(placements=((128.0, 128.0), (128.0, 128.0))),
        )

        with pytest.raises(PlateLayoutError) as raised:
            read_layout(path)

        assert raised.value.failure is PlateLayoutFailure.MISMATCH

    def test_refuses_a_plate_listing_an_object_the_build_does_not_place(self, tmp_path):
        settings = """<config><plate>
            <metadata key="plater_id" value="1"/>
            <model_instance>
              <metadata key="object_id" value="9"/>
              <metadata key="instance_id" value="0"/>
            </model_instance>
        </plate></config>"""
        path = _write(tmp_path, build_multi_plate_project(model_settings=settings))

        with pytest.raises(PlateLayoutError) as raised:
            read_layout(path)

        assert raised.value.failure is PlateLayoutFailure.MISMATCH

    @pytest.mark.parametrize(
        "settings",
        [
            "<config><plate>",
            '<!DOCTYPE config [<!ENTITY x "y">]><config/>',
            '<config><plate><metadata key="plater_id" value="2"/></plate></config>',
            '<config><plate><metadata key="plater_id" value="one"/></plate></config>',
            """<config><plate>
                <metadata key="plater_id" value="1"/>
                <metadata key="plater_id" value="2"/>
            </plate></config>""",
        ],
        ids=["truncated", "dtd", "numbering-gap", "non-numeric", "duplicate-key"],
    )
    def test_refuses_malformed_plate_metadata(self, tmp_path, settings):
        path = _write(tmp_path, build_multi_plate_project(model_settings=settings))

        with pytest.raises(PlateLayoutError) as raised:
            read_layout(path)

        assert raised.value.failure is PlateLayoutFailure.MALFORMED

    def test_refuses_a_plate_name_beyond_the_stored_length(self, tmp_path):
        path = _write(
            tmp_path, build_multi_plate_project(names=("x" * 1025, "Wall mount"))
        )

        with pytest.raises(PlateLayoutError) as raised:
            read_layout(path)

        assert raised.value.failure is PlateLayoutFailure.LIMITS

    def test_refuses_bytes_that_are_not_an_archive(self, tmp_path):
        path = _write(tmp_path, b"not a zip")

        with pytest.raises(PlateLayoutError) as raised:
            read_layout(path)

        assert raised.value.failure is PlateLayoutFailure.MALFORMED


class TestReadImage:
    def test_returns_the_plates_preview(self, tmp_path):
        path = _write(tmp_path, build_multi_plate_project())

        image = read_image(path, "Metadata/plate_2.png")

        assert image == png(width=5, height=4)

    @pytest.mark.parametrize(
        "member", ["3D/3dmodel.model", "Metadata/../plate_1.png", "Metadata/a/b.png"]
    )
    def test_refuses_a_member_outside_the_plate_previews(self, tmp_path, member):
        path = _write(tmp_path, build_multi_plate_project())

        with pytest.raises(PlateLayoutError):
            read_image(path, member)

    def test_refuses_a_preview_that_is_not_a_png(self, tmp_path):
        data = _replace_member(
            build_multi_plate_project(), "Metadata/plate_1.png", b"GIF89a"
        )
        path = _write(tmp_path, data)

        with pytest.raises(PlateLayoutError) as raised:
            read_image(path, "Metadata/plate_1.png")

        assert raised.value.failure is PlateLayoutFailure.MALFORMED

    def test_refuses_a_missing_preview(self, tmp_path):
        path = _write(tmp_path, build_multi_plate_project(images=False))

        with pytest.raises(PlateLayoutError) as raised:
            read_image(path, "Metadata/plate_1.png")

        assert raised.value.failure is PlateLayoutFailure.MALFORMED
