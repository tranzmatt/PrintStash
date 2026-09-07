"""Unattributed."""

from __future__ import annotations

from sqlmodel import Session, select

from app.db.models import (
    FileType,
)


def ensure_unattributed_artifact(session: Session) -> tuple[int, int]:
    """Return (file_id, model_id) of lazily-created external job sentinel rows."""
    from app.db.models import (
        SENTINEL_FILE_HASH,
        SENTINEL_MODEL_HASH,
        File,
        Model,
    )

    model = session.exec(select(Model).where(Model.hash == SENTINEL_MODEL_HASH)).first()
    if model is None:
        model = Model(
            name="__external__",
            slug="__external__",
            hash=SENTINEL_MODEL_HASH,
        )
        session.add(model)
        session.commit()
        session.refresh(model)
    assert model.id is not None

    f = session.exec(select(File).where(File.sha256 == SENTINEL_FILE_HASH)).first()
    if f is None:
        f = File(
            model_id=model.id,
            path="/dev/null",
            original_filename="__external__",
            file_type=FileType.GCODE,
            version=1,
            size_bytes=0,
            sha256=SENTINEL_FILE_HASH,
        )
        session.add(f)
        session.commit()
        session.refresh(f)

    assert f.id is not None
    return f.id, model.id
