"""Reads of the plates derivative: a 3MF's layout and each plate's preview."""

from __future__ import annotations

from sqlmodel import Session, col, select

from app.db.models import DerivativeKind, File, FilePlate, FileType
from app.schemas.jobs import DerivativeStatus
from app.schemas.plates import FilePlateRead, FilePlatesRead, PlateRegionRead

from . import records


class NoPlates(Exception):
    """The Artifact has no such plate in a ready layout."""


def layout(session: Session, file: File) -> FilePlatesRead:
    """``file``'s plates at the current recipe; empty until the layout is ready."""
    if file.file_type != FileType.THREE_MF:
        raise NoPlates("not_a_3mf")
    (state,) = (
        read.state
        for read in records.read(session, file)
        if read.kind is DerivativeKind.PLATES
    )
    if state is not DerivativeStatus.READY:
        return FilePlatesRead(state=state, plates=[])
    assert file.id is not None
    rows = session.exec(
        select(FilePlate)
        .where(FilePlate.file_id == file.id)
        .order_by(col(FilePlate.number))
    ).all()
    return FilePlatesRead(
        state=state,
        plates=[
            FilePlateRead(
                number=row.number,
                name=row.name,
                object_count=row.object_count,
                image_url=f"/api/v1/files/{file.id}/plates/{row.number}/image"
                if row.image_member is not None
                else None,
                region=PlateRegionRead(
                    min_x=row.min_x, min_y=row.min_y, max_x=row.max_x, max_y=row.max_y
                ),
            )
            for row in rows
        ],
    )


def image_member(session: Session, file: File, number: int) -> str:
    """The archive member holding plate ``number``'s preview in a ready layout."""
    if layout(session, file).state is not DerivativeStatus.READY:
        raise NoPlates("plates_not_ready")
    assert file.id is not None
    row = session.exec(
        select(FilePlate).where(
            FilePlate.file_id == file.id, FilePlate.number == number
        )
    ).first()
    if row is None or row.image_member is None:
        raise NoPlates("plate_image_not_found")
    return row.image_member
