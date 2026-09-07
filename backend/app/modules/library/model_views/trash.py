"""Authorized trash listings and their projections."""

from __future__ import annotations

from typing import List

from sqlalchemy import func
from sqlmodel import Session, select

from app.db.models import (
    File,
    Model,
    User,
)
from app.db.scopes import trashed
from app.modules.library.trash import trash_expires_at
from app.schemas.models import (
    TrashedModelRead,
)

from .access import _apply_model_access
from .projections import collection_name_for, thumb_url

# ---------------------------------------------------------------------------
# Trash listing
# ---------------------------------------------------------------------------


def list_trashed(
    session: Session,
    user: User,
    *,
    limit: int = 50,
    offset: int = 0,
    retention_days: int,
) -> List[TrashedModelRead]:
    stmt = (
        select(Model)
        .where(trashed(Model))
        # Stable tiebreaker on id: a bulk trash gives many rows the same
        # deleted_at, which would otherwise paginate non-deterministically.
        .order_by(Model.deleted_at.desc(), Model.id.desc())  # type: ignore[attr-defined]
        .offset(offset)
        .limit(limit)
    )
    stmt = _apply_model_access(stmt, session, user)
    rows = session.exec(stmt).all()
    model_ids = [m.id for m in rows if m.id is not None]
    file_stats: dict[int, tuple[int, int]] = {}
    if model_ids:
        for model_id, count, size in session.exec(
            select(
                File.model_id,
                func.count(File.id),
                func.coalesce(func.sum(File.size_bytes), 0),
            )
            .where(File.model_id.in_(model_ids))  # type: ignore[union-attr]
            .group_by(File.model_id)
        ).all():
            file_stats[int(model_id)] = (int(count or 0), int(size or 0))
    out: List[TrashedModelRead] = []
    for model in rows:
        file_count, size_bytes = file_stats.get(model.id or 0, (0, 0))
        assert model.deleted_at is not None
        out.append(
            TrashedModelRead(
                id=model.id,  # type: ignore[arg-type]
                name=model.name,
                slug=model.slug,
                collection=collection_name_for(model),
                tags=sorted(t.name for t in model.tags),
                thumbnail_url=thumb_url(model),
                file_count=file_count,
                size_bytes=size_bytes,
                deleted_at=model.deleted_at,
                expires_at=trash_expires_at(model.deleted_at, retention_days),
            )
        )
    return out
