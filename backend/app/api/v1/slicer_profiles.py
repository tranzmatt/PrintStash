"""Slicer settings observed in accessible G-code Artifacts."""

from fastapi import APIRouter, Depends, Path, Query
from sqlmodel import Session

from app.core.http import get_or_404
from app.core.security import require_user
from app.db.models import FilamentProfile, PrinterProfile, User
from app.db.session import get_session
from app.modules.printing.slicer_profiles import list_captured_profiles
from app.schemas.slicer_profiles import ProfileSettingsKind, SlicerProfilePage

router = APIRouter(prefix="/slicer-profiles", tags=["slicer-profiles"])


@router.get("", response_model=SlicerProfilePage)
def list_slicer_profiles(
    before_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
) -> SlicerProfilePage:
    return list_captured_profiles(session, user, before_id=before_id, limit=limit)


@router.get("/{kind}/{profile_id}", response_model=SlicerProfilePage)
def list_profile_settings(
    kind: ProfileSettingsKind,
    profile_id: int = Path(gt=0),
    before_id: int | None = Query(default=None, gt=0),
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(require_user),
    session: Session = Depends(get_session),
) -> SlicerProfilePage:
    profile = (
        get_or_404(session, FilamentProfile, profile_id, "filament_profile_not_found")
        if kind == ProfileSettingsKind.FILAMENT
        else get_or_404(
            session, PrinterProfile, profile_id, "printer_profile_not_found"
        )
    )
    return list_captured_profiles(
        session, user, before_id=before_id, limit=limit, profile=profile
    )
