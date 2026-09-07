from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.time import utcnow
from app.db.models import SavedView
from app.schemas.saved_views import (
    SavedViewCreate,
    SavedViewFilters,
    SavedViewRead,
    SavedViewUpdate,
)


class SavedViewConflict(Exception):
    pass


def _read(row: SavedView) -> SavedViewRead:
    return SavedViewRead(
        id=row.id,
        name=row.name,
        filters=SavedViewFilters.model_validate_json(row.filters_json),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_for_user(session: Session, user_id: int) -> list[SavedViewRead]:
    rows = session.exec(
        select(SavedView)
        .where(SavedView.user_id == user_id)
        .order_by(SavedView.name.asc(), SavedView.id.asc())
    ).all()
    return [_read(row) for row in rows]


def get_for_user(session: Session, user_id: int, view_id: int) -> SavedViewRead | None:
    row = session.exec(
        select(SavedView).where(SavedView.id == view_id, SavedView.user_id == user_id)
    ).first()
    return _read(row) if row else None


def create(session: Session, user_id: int, payload: SavedViewCreate) -> SavedViewRead:
    row = SavedView(
        user_id=user_id,
        name=payload.name.strip(),
        filters_json=payload.filters.model_dump_json(exclude_none=True),
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise SavedViewConflict from exc
    session.refresh(row)
    return _read(row)


def update(
    session: Session, user_id: int, view_id: int, payload: SavedViewUpdate
) -> SavedViewRead | None:
    row = session.exec(
        select(SavedView).where(SavedView.id == view_id, SavedView.user_id == user_id)
    ).first()
    if row is None:
        return None
    if payload.name is not None:
        row.name = payload.name.strip()
    if payload.filters is not None:
        row.filters_json = payload.filters.model_dump_json(exclude_none=True)
    row.updated_at = utcnow()
    session.add(row)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise SavedViewConflict from exc
    session.refresh(row)
    return _read(row)


def delete(session: Session, user_id: int, view_id: int) -> bool:
    row = session.exec(
        select(SavedView).where(SavedView.id == view_id, SavedView.user_id == user_id)
    ).first()
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True
