"""Authorized, bounded reads of settings captured by G-code derivatives."""

import json

from sqlalchemy.orm import aliased
from sqlmodel import Session, col, select

from app.db.models import (
    ArtifactDerivative,
    DerivativeKind,
    DerivativeState,
    File,
    FileType,
    Metadata,
    Model,
    User,
)
from app.db.scopes import live
from app.modules.library.model_views.access import accessible_live_model_ids_stmt
from app.schemas.slicer_profiles import (
    CapturedSettingsRead,
    SlicerProfilePage,
    SlicerProfileRead,
)


def list_captured_profiles(
    session: Session, user: User, *, before_id: int | None, limit: int
) -> SlicerProfilePage:
    candidate = aliased(ArtifactDerivative)
    # Recipe upgrades retain previous receipts. Choose one completed capture
    # per file, including while its replacement is still being processed.
    latest_ready = (
        select(candidate.id)
        .where(
            col(candidate.file_id) == col(File.id),
            candidate.kind == DerivativeKind.METADATA,
            candidate.state == DerivativeState.READY,
        )
        .order_by(col(candidate.recipe_version).desc())
        .limit(1)
        .correlate(File)
        .scalar_subquery()
    )
    stmt = (
        select(
            File,
            Model.name,
            Metadata.slicer_name,
            Metadata.slicer_version,
            ArtifactDerivative.output_json,
        )
        .join(Model, Model.id == File.model_id)
        .join(Metadata, Metadata.file_id == File.id)
        .join(ArtifactDerivative, col(ArtifactDerivative.id) == latest_ready)
        .where(
            col(File.model_id).in_(accessible_live_model_ids_stmt(session, user)),
            live(File),
            File.file_type == FileType.GCODE,
            ArtifactDerivative.kind == DerivativeKind.METADATA,
            ArtifactDerivative.state == DerivativeState.READY,
        )
        .order_by(col(File.id).desc())
        .limit(limit + 1)
    )
    if before_id is not None:
        stmt = stmt.where(col(File.id) < before_id)
    rows = session.exec(stmt).all()
    items = []
    for file, model_name, slicer_name, slicer_version, output_json in rows[:limit]:
        output = json.loads(output_json)
        captured = output.get("slicer_settings")
        # Older derivative recipes have no capture yet. The recipe bump queues
        # those Artifacts for re-derivation; do not invent empty preset records.
        if captured is None:
            continue
        settings = CapturedSettingsRead.model_validate(captured)
        if not (settings.printer or settings.filament or settings.process):
            continue
        if file.id is None:
            raise ValueError("captured_settings_require_persisted_file")
        items.append(
            SlicerProfileRead(
                file_id=file.id,
                model_id=file.model_id,
                model_name=model_name,
                filename=file.original_filename,
                uploaded_at=file.uploaded_at,
                slicer_name=slicer_name,
                slicer_version=slicer_version,
                settings=settings,
            )
        )
    next_id = rows[limit - 1][0].id if len(rows) > limit else None
    return SlicerProfilePage(items=items, next_before_id=next_id)
