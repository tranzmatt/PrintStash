"""The plates of a slicer project 3MF, read from its slicer metadata.

Bambu Studio and the slicers built on it (OrcaSlicer, Creality Print) save a
project's plates in ``Metadata/model_settings.config`` and the printer's bed
in ``Metadata/project_settings.config``. They lay plate *i* of *n* out on a
grid of ``ceil(sqrt(n))`` columns whose cells are the bed plus a fifth of it,
rows growing towards -Y, and place every object in the build in its plate's
cell. A plate is therefore a fixed rectangle of the package's build space, and
the build's own coordinates say which geometry belongs to which plate.

A package without that metadata is not a plate project and has no layout. One
whose metadata is present but cannot be read, or whose build places an object
outside the plate that lists it, raises :class:`PlateLayoutError`: a layout is
published only when every plate's rectangle is the slicer's own.
"""

from __future__ import annotations

import json
import math
import re
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from app.modules.media import three_mf_package as package

if TYPE_CHECKING:
    from lxml.etree import _Element

MODEL_SETTINGS = "Metadata/model_settings.config"
PROJECT_SETTINGS = "Metadata/project_settings.config"
# The slicers' logical gap between plates, as a share of the bed.
PLATE_GAP = 0.2
MAX_PLATES = 64
MAX_SETTINGS_BYTES = 16 * 1024 * 1024
MAX_NAME_CHARS = 1024
_IMAGE_MEMBER = re.compile(r"^Metadata/[A-Za-z0-9_.-]{1,128}\.png$")
_POINT = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*x\s*(-?\d+(?:\.\d+)?)\s*$")
_MODEL = re.compile(rb"<(?:[A-Za-z_][\w.-]*:)?model(?=[\s/>])([^>]*)>")
_ITEM = re.compile(rb"<(?:([A-Za-z_][\w.-]*):)?item(?=[\s/>])([^>]*)>")


class PlateLayoutFailure(StrEnum):
    """Why a package that declares plates has no readable layout."""

    MALFORMED = "plate_layout_malformed"
    BED_UNKNOWN = "plate_bed_unknown"
    MISMATCH = "plate_layout_mismatch"
    LIMITS = "plate_layout_limits"


class PlateLayoutError(Exception):
    def __init__(self, failure: PlateLayoutFailure):
        self.failure = failure
        super().__init__(failure.value)


@dataclass(frozen=True)
class PlateRegion:
    """A plate's rectangle of the build, in millimetres."""

    min_x: float
    min_y: float
    max_x: float
    max_y: float

    def contains(self, x: float, y: float, *, margin_x: float, margin_y: float) -> bool:
        return (
            self.min_x - margin_x <= x <= self.max_x + margin_x
            and self.min_y - margin_y <= y <= self.max_y + margin_y
        )


@dataclass(frozen=True)
class Plate:
    number: int
    # The slicer leaves a plate unnamed until the user names it.
    name: str | None
    object_count: int
    # The plate's rendered preview, when the slicer saved one.
    image_member: str | None
    region: PlateRegion


@dataclass(frozen=True)
class PlateLayout:
    plates: tuple[Plate, ...]

    def __post_init__(self) -> None:
        if [plate.number for plate in self.plates] != list(
            range(1, len(self.plates) + 1)
        ):
            raise ValueError("plates_not_numbered_in_order")


@dataclass(frozen=True)
class _DeclaredPlate:
    number: int
    name: str | None
    image_member: str | None
    instances: tuple[tuple[int, int], ...]


def read_layout(path: Path) -> PlateLayout | None:
    """The package's plates, or ``None`` when it is not a slicer project."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = {info.filename: info for info in archive.infolist()}
            if len(names) > package.MAX_ENTRIES:
                raise PlateLayoutError(PlateLayoutFailure.LIMITS)
            settings = names.get(MODEL_SETTINGS)
            if settings is None:
                return None
            declared = _declared_plates(_read(archive, settings), names)
            if not declared:
                return None
            project = names.get(PROJECT_SETTINGS)
            if project is None:
                raise PlateLayoutError(PlateLayoutFailure.BED_UNKNOWN)
            bed = _bed(_read(archive, project))
            regions = _regions(bed, len(declared))
            _require_placements(archive, names, declared, regions, bed)
    except zipfile.BadZipFile, package.Ambiguous, UnicodeDecodeError:
        raise PlateLayoutError(PlateLayoutFailure.MALFORMED) from None
    return PlateLayout(
        tuple(
            Plate(
                number=plate.number,
                name=plate.name,
                object_count=len(plate.instances),
                image_member=plate.image_member,
                region=region,
            )
            for plate, region in zip(declared, regions, strict=True)
        )
    )


def _read(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    if (
        info.file_size > MAX_SETTINGS_BYTES
        or info.file_size > max(info.compress_size, 1) * package.MAX_COMPRESSION_RATIO
    ):
        raise PlateLayoutError(PlateLayoutFailure.LIMITS)
    data = archive.read(info)
    if len(data) != info.file_size:
        raise PlateLayoutError(PlateLayoutFailure.MALFORMED)
    return data


def _declared_plates(
    data: bytes, names: dict[str, zipfile.ZipInfo]
) -> list[_DeclaredPlate]:
    import lxml.etree as etree

    if package.declares_dtd(data):
        raise PlateLayoutError(PlateLayoutFailure.MALFORMED)
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False
    )
    try:
        root = etree.fromstring(data, parser)
    except etree.XMLSyntaxError:
        raise PlateLayoutError(PlateLayoutFailure.MALFORMED) from None
    elements = root.findall("plate")
    if len(elements) > MAX_PLATES:
        raise PlateLayoutError(PlateLayoutFailure.LIMITS)
    plates = []
    for element in elements:
        values = _metadata(element)
        number = _positive_int(values.get("plater_id"))
        name = values.get("plater_name", "").strip()
        if len(name) > MAX_NAME_CHARS:
            raise PlateLayoutError(PlateLayoutFailure.LIMITS)
        image = values.get("thumbnail_file")
        instances = []
        for instance in element.findall("model_instance"):
            fields = _metadata(instance)
            instances.append(
                (
                    _positive_int(fields.get("object_id")),
                    _non_negative_int(fields.get("instance_id")),
                )
            )
        plates.append(
            _DeclaredPlate(
                number=number,
                name=name or None,
                image_member=image
                if image is not None
                and _IMAGE_MEMBER.fullmatch(image)
                and image in names
                and names[image].file_size > 0
                else None,
                instances=tuple(instances),
            )
        )
    plates.sort(key=lambda plate: plate.number)
    if [plate.number for plate in plates] != list(range(1, len(plates) + 1)):
        raise PlateLayoutError(PlateLayoutFailure.MALFORMED)
    return plates


def _metadata(element: _Element) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in element.findall("metadata"):
        key = item.get("key")
        value = item.get("value")
        if key is None or value is None:
            continue
        if key in values:
            raise PlateLayoutError(PlateLayoutFailure.MALFORMED)
        values[key] = value
    return values


def _positive_int(value: str | None) -> int:
    number = _non_negative_int(value)
    if number < 1:
        raise PlateLayoutError(PlateLayoutFailure.MALFORMED)
    return number


def _non_negative_int(value: str | None) -> int:
    if value is None or not value.isdecimal() or len(value) > 9:
        raise PlateLayoutError(PlateLayoutFailure.MALFORMED)
    return int(value)


def _bed(data: bytes) -> PlateRegion:
    """The bed's printable rectangle, relative to its plate's origin."""
    try:
        settings = json.loads(data)
    except ValueError:
        raise PlateLayoutError(PlateLayoutFailure.MALFORMED) from None
    area = settings.get("printable_area") if isinstance(settings, dict) else None
    if not isinstance(area, list) or not 3 <= len(area) <= 256:
        raise PlateLayoutError(PlateLayoutFailure.BED_UNKNOWN)
    points = []
    for point in area:
        match = _POINT.fullmatch(point) if isinstance(point, str) else None
        if match is None:
            raise PlateLayoutError(PlateLayoutFailure.BED_UNKNOWN)
        points.append((float(match.group(1)), float(match.group(2))))
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    bed = PlateRegion(min(xs), min(ys), max(xs), max(ys))
    if not (
        0 < bed.max_x - bed.min_x <= 10_000 and 0 < bed.max_y - bed.min_y <= 10_000
    ):
        raise PlateLayoutError(PlateLayoutFailure.BED_UNKNOWN)
    return bed


def _regions(bed: PlateRegion, count: int) -> list[PlateRegion]:
    """Each plate's rectangle, as the slicer arranges its plates."""
    columns = math.isqrt(count)
    if columns * columns < count:
        columns += 1
    stride_x = (bed.max_x - bed.min_x) * (1 + PLATE_GAP)
    stride_y = (bed.max_y - bed.min_y) * (1 + PLATE_GAP)
    regions = []
    for index in range(count):
        row, column = divmod(index, columns)
        origin_x = column * stride_x
        origin_y = -row * stride_y
        regions.append(
            PlateRegion(
                bed.min_x + origin_x,
                bed.min_y + origin_y,
                bed.max_x + origin_x,
                bed.max_y + origin_y,
            )
        )
    return regions


def _require_placements(
    archive: zipfile.ZipFile,
    names: dict[str, zipfile.ZipInfo],
    declared: list[_DeclaredPlate],
    regions: list[PlateRegion],
    bed: PlateRegion,
) -> None:
    """Refuse a layout whose build places an object outside its plate's cell.

    A placement may overhang its plate, but never reach past the half gap that
    separates it from the next one.
    """
    if not any(plate.instances for plate in declared):
        return
    placements = _build_placements(archive, names)
    margin_x = (bed.max_x - bed.min_x) * PLATE_GAP / 2
    margin_y = (bed.max_y - bed.min_y) * PLATE_GAP / 2
    for plate, region in zip(declared, regions, strict=True):
        for object_id, instance_id in plate.instances:
            items = placements.get(object_id, [])
            if instance_id >= len(items):
                raise PlateLayoutError(PlateLayoutFailure.MISMATCH)
            x, y = items[instance_id]
            if not region.contains(x, y, margin_x=margin_x, margin_y=margin_y):
                raise PlateLayoutError(PlateLayoutFailure.MISMATCH)


def _build_placements(
    archive: zipfile.ZipFile, names: dict[str, zipfile.ZipInfo]
) -> dict[int, list[tuple[float, float]]]:
    """Each root object's build placements, in build order, as XY in mm."""
    entries, models = package.model_parts(
        archive, max_model_bytes=package.MAX_ARCHIVE_BYTES
    )
    root = package.root_part(archive, entries, models)
    unit: float | None = None
    placements: dict[int, list[tuple[float, float]]] = {}
    count = 0
    for window in package.windows(archive, entries[root]):
        if package.declares_dtd(window):
            raise PlateLayoutError(PlateLayoutFailure.MALFORMED)
        if unit is None and (model := _MODEL.search(window)):
            declared_unit = package.attributes(model.group(1)).get((None, b"unit"))
            # The core specification's default unit.
            scale = package.UNITS.get(
                b"millimeter" if declared_unit is None else declared_unit
            )
            if scale is None:
                raise PlateLayoutError(PlateLayoutFailure.MALFORMED)
            unit = scale
        for match in _ITEM.finditer(window):
            count += 1
            if unit is None:
                raise PlateLayoutError(PlateLayoutFailure.MALFORMED)
            if count > package.MAX_ENTRIES:
                raise PlateLayoutError(PlateLayoutFailure.LIMITS)
            attrs = package.attributes(match.group(2))
            raw_id = attrs.get((None, b"objectid"))
            if raw_id is None:
                raise PlateLayoutError(PlateLayoutFailure.MALFORMED)
            object_id = _positive_int(raw_id.decode("ascii"))
            transform = attrs.get((None, b"transform"))
            x = y = 0.0
            if transform is not None:
                values = transform.split()
                if len(values) != 12:
                    raise PlateLayoutError(PlateLayoutFailure.MALFORMED)
                try:
                    x, y = float(values[9]), float(values[10])
                except ValueError:
                    raise PlateLayoutError(PlateLayoutFailure.MALFORMED) from None
                if not (math.isfinite(x) and math.isfinite(y)):
                    raise PlateLayoutError(PlateLayoutFailure.MALFORMED)
            placements.setdefault(object_id, []).append((x * unit, y * unit))
    return placements


MAX_IMAGE_BYTES = 8 * 1024 * 1024


def read_image(path: Path, member: str) -> bytes:
    """One plate's preview PNG, bounded, from the package that declared it."""
    if not _IMAGE_MEMBER.fullmatch(member):
        raise PlateLayoutError(PlateLayoutFailure.MALFORMED)
    try:
        with zipfile.ZipFile(path) as archive:
            try:
                info = archive.getinfo(member)
            except KeyError:
                raise PlateLayoutError(PlateLayoutFailure.MALFORMED) from None
            if (
                info.file_size > MAX_IMAGE_BYTES
                or info.file_size
                > max(info.compress_size, 1) * package.MAX_COMPRESSION_RATIO
            ):
                raise PlateLayoutError(PlateLayoutFailure.LIMITS)
            data = archive.read(info)
    except zipfile.BadZipFile:
        raise PlateLayoutError(PlateLayoutFailure.MALFORMED) from None
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise PlateLayoutError(PlateLayoutFailure.MALFORMED)
    return data
