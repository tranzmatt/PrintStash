"""Business examples exercised by every product's real Revision adapter.

The fixture contains no persistence or authorization implementation. Products
create their own authorized records, invoke the shared command, and compare the
persisted result with these expectations.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RevisionExample:
    name: str
    # version, format, recommended, trashed; the first entry is deleted.
    files: tuple[tuple[int, str, bool, bool], ...]
    thumbnail_index: int | None
    recommended_version: int | None
    thumbnail_survives: bool
    error: str | None = None


REVISION_EXAMPLES = (
    RevisionExample(
        "promote_highest_version",
        (
            (1, "gcode", True, False),
            (3, "gcode", False, False),
            (2, "gcode", False, False),
        ),
        None,
        3,
        False,
    ),
    RevisionExample(
        "preserve_other_recommendation",
        ((2, "gcode", False, False), (1, "gcode", True, False)),
        None,
        1,
        False,
    ),
    RevisionExample(
        "ignore_trashed_successor",
        (
            (1, "gcode", True, False),
            (3, "gcode", False, True),
            (2, "gcode", False, False),
        ),
        None,
        2,
        False,
    ),
    RevisionExample(
        "ignore_mesh_successor",
        (
            (1, "gcode", True, False),
            (3, "stl", False, False),
            (2, "gcode", False, False),
        ),
        None,
        2,
        False,
    ),
    RevisionExample(
        "clear_deleted_thumbnail",
        ((1, "gcode", True, False),),
        0,
        None,
        False,
    ),
    RevisionExample(
        "preserve_other_thumbnail",
        ((1, "gcode", False, False), (2, "gcode", True, False)),
        1,
        2,
        True,
    ),
    RevisionExample(
        "reject_mesh",
        ((1, "stl", False, False),),
        None,
        None,
        False,
        "revision_not_supported",
    ),
    RevisionExample(
        "reject_trashed_revision",
        ((1, "gcode", False, True),),
        None,
        None,
        False,
        "file_not_found",
    ),
)
