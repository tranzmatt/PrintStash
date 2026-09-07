"""Transactional label updates shared by single and batch Revision commands."""

from __future__ import annotations

from sqlmodel import Session, select

from app.core.time import utcnow
from app.db.models import (
    File,
    Model,
)
from app.db.scopes import live


def set_revision_labels(
    session: Session, files: list[File], revision_label: str | None
) -> None:
    """Set one label across prevalidated live G-code revisions, without commit."""
    label = (
        revision_label.strip() if revision_label and revision_label.strip() else None
    )
    touched_models: set[int] = set()
    for file_row in files:
        file_row.revision_label = label
        session.add(file_row)
        touched_models.add(file_row.model_id)
    for model in session.exec(
        select(Model).where(Model.id.in_(touched_models), live(Model))  # type: ignore[union-attr]
    ).all():
        model.updated_at = utcnow()
        session.add(model)
