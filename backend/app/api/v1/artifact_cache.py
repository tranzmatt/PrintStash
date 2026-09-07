"""Administrator controls for disposable verified Artifact materializations."""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.core.security import require_superuser
from app.db.session import get_session
from app.modules.administration import artifact_cache_config
from app.modules.administration.artifact_cache_config import (
    CacheSettings,
    CacheSettingsRead,
)

router = APIRouter(
    prefix="/config/artifact-cache",
    tags=["config"],
    dependencies=[Depends(require_superuser)],
)


@router.get("", response_model=CacheSettingsRead)
def read_cache(session: Session = Depends(get_session)):
    return artifact_cache_config.read_settings(session)


@router.put("", response_model=CacheSettingsRead)
def update_cache(body: CacheSettings, session: Session = Depends(get_session)):
    return artifact_cache_config.update_settings(session, body)


@router.delete("", response_model=CacheSettingsRead)
def reset_cache(session: Session = Depends(get_session)):
    return artifact_cache_config.update_settings(session, None)


@router.post("/clear", response_model=CacheSettingsRead)
def clear_cache(session: Session = Depends(get_session)):
    return artifact_cache_config.clear_cache(session)
