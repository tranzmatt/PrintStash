"""Authorized trash listings and their projections."""

from __future__ import annotations

from typing import List

from sqlalchemy import func
from sqlmodel import Session, select

from app.db.models import (
    Collection,
    CollectionRole,
    File,
    Model,
    MultipartModel,
    MultipartPart,
    User,
)
from app.db.scopes import trashed
from app.modules.identity import rbac
from app.modules.library.trash import trash_expires_at
from app.schemas.models import (
    TrashedModelRead,
)
from app.schemas.multipart_models import TrashedMultipartModelRead

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


def list_trashed_multipart(
    session: Session, user: User, *, limit: int, offset: int, retention_days: int
) -> list[TrashedMultipartModelRead]:
    counts = (
        select(
            MultipartPart.multipart_model_id,
            func.count(MultipartPart.id).label("count"),
        )
        .group_by(MultipartPart.multipart_model_id)
        .subquery()
    )
    stmt = (
        select(MultipartModel, Collection.path, func.coalesce(counts.c.count, 0))
        .outerjoin(Collection, Collection.id == MultipartModel.collection_id)
        .outerjoin(counts, counts.c.multipart_model_id == MultipartModel.id)
        .where(trashed(MultipartModel))
        .order_by(MultipartModel.deleted_at.desc(), MultipartModel.id.desc())
        .offset(offset)
        .limit(limit)
    )
    if not user.is_superuser:
        stmt = stmt.where(
            MultipartModel.collection_id.in_(
                rbac.accessible_collection_ids_stmt(session, user, CollectionRole.EDIT)
            )
        )
    return [
        TrashedMultipartModelRead(
            id=row.id,
            name=row.name,
            slug=row.slug,
            collection=path,
            part_count=count,
            deleted_at=row.deleted_at,
            expires_at=trash_expires_at(row.deleted_at, retention_days),
        )
        for row, path, count in session.exec(stmt).all()
    ]
