"""Config repository."""

from __future__ import annotations

from sqlmodel import Session

from app.db.models import SystemConfig


def get_or_create(session: Session, *, commit: bool = True) -> SystemConfig:
    """Return the singleton config row, creating an empty one if missing."""
    config = session.get(SystemConfig, 1)
    if config is None:
        config = SystemConfig(id=1)
        session.add(config)
        if commit:
            session.commit()
            session.refresh(config)
    return config
