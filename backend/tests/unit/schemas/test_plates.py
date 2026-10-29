"""A plate layout is listed only once its derivative is ready.

Before then the layout is unknown, and after a skip there is none; a response
carrying plates in either state would show the model page a layout nobody
derived, and a ready one without plates would hide a project's plates.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.jobs import DerivativeStatus
from app.schemas.plates import FilePlateRead, FilePlatesRead, PlateRegionRead

PLATE = FilePlateRead(
    number=1,
    name="Main parts",
    object_count=1,
    image_url=None,
    region=PlateRegionRead(min_x=0.0, min_y=0.0, max_x=256.0, max_y=256.0),
)


class TestFilePlatesRead:
    def test_lists_the_plates_of_a_ready_layout(self) -> None:
        layout = FilePlatesRead(state=DerivativeStatus.READY, plates=[PLATE])

        assert layout.plates == [PLATE]

    @pytest.mark.parametrize(
        "state",
        [DerivativeStatus.PENDING, DerivativeStatus.SKIPPED, DerivativeStatus.FAILED],
    )
    def test_accepts_an_empty_layout_that_is_not_ready(self, state) -> None:
        assert FilePlatesRead(state=state, plates=[]).plates == []

    @pytest.mark.parametrize(
        "state",
        [DerivativeStatus.PENDING, DerivativeStatus.SKIPPED, DerivativeStatus.FAILED],
    )
    def test_refuses_plates_before_the_layout_is_ready(self, state) -> None:
        with pytest.raises(ValidationError, match="plates_require_a_ready_layout"):
            FilePlatesRead(state=state, plates=[PLATE])

    def test_refuses_a_ready_layout_without_plates(self) -> None:
        with pytest.raises(ValidationError, match="plates_require_a_ready_layout"):
            FilePlatesRead(state=DerivativeStatus.READY, plates=[])
