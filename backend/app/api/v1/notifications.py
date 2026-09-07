"""Notification channel management — superuser-only CRUD + test send.

Channels carry secret-bearing config (webhook URLs, bot tokens); reads mask
those values and updates preserve a stored secret when it is re-sent blank,
mirroring the S3/MakerWorld secret handling in :mod:`app.api.v1.config`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.core.security import require_superuser
from app.db.models import NotificationTarget
from app.db.session import get_session
from app.modules.administration import runtime_config
from app.modules.notifications import notifications

router = APIRouter(prefix="/notifications", tags=["notifications"])


# --------------------------------------------------------------------------- #
# schemas
# --------------------------------------------------------------------------- #
class NotificationsSettings(BaseModel):
    enabled: bool = False


class NotificationsSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class ChannelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    target: NotificationTarget
    config: Dict[str, Any] = Field(default_factory=dict)
    events: List[str] = Field(default_factory=list)
    printer_ids: Optional[List[int]] = None
    enabled: bool = True


class ChannelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    config: Optional[Dict[str, Any]] = None
    events: Optional[List[str]] = None
    printer_ids: Optional[List[int]] = None
    enabled: Optional[bool] = None


# --------------------------------------------------------------------------- #
# master switch
# --------------------------------------------------------------------------- #
@router.get(
    "",
    dependencies=[Depends(require_superuser)],
    summary="Notifications master switch + channels",
)
def get_settings(session: Session = Depends(get_session)) -> Dict[str, Any]:
    return {
        "enabled": runtime_config.notifications_enabled(session),
        "channels": notifications.list_channels(session),
    }


@router.put(
    "",
    dependencies=[Depends(require_superuser)],
    summary="Enable or disable notifications globally",
)
def update_settings(
    body: NotificationsSettingsUpdate, session: Session = Depends(get_session)
) -> NotificationsSettings:
    runtime_config.set_notifications_enabled(session, body.enabled)
    return NotificationsSettings(enabled=body.enabled)


# --------------------------------------------------------------------------- #
# channels
# --------------------------------------------------------------------------- #
@router.get(
    "/channels",
    dependencies=[Depends(require_superuser)],
    summary="List notification channels",
)
def list_channels(session: Session = Depends(get_session)) -> List[Dict[str, Any]]:
    return notifications.list_channels(session)


@router.post(
    "/channels",
    dependencies=[Depends(require_superuser)],
    status_code=status.HTTP_201_CREATED,
    summary="Create a notification channel",
)
def create_channel(
    body: ChannelCreate, session: Session = Depends(get_session)
) -> Dict[str, Any]:
    try:
        channel = notifications.create_channel(
            session,
            name=body.name,
            target=body.target,
            config=body.config,
            events=body.events,
            printer_ids=body.printer_ids,
            enabled=body.enabled,
        )
    except notifications.NotificationConfigError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return notifications.serialize_channel(channel)


@router.patch(
    "/channels/{channel_id}",
    dependencies=[Depends(require_superuser)],
    summary="Update a notification channel",
)
def update_channel(
    channel_id: int,
    body: ChannelUpdate,
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    channel = notifications.get_channel(session, channel_id)
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "channel not found")
    fields = body.model_dump(exclude_unset=True)
    try:
        channel = notifications.update_channel(
            session,
            channel,
            name=body.name,
            config=body.config,
            events=body.events,
            printer_ids=body.printer_ids,
            printer_ids_set="printer_ids" in fields,
            enabled=body.enabled,
        )
    except notifications.NotificationConfigError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return notifications.serialize_channel(channel)


@router.delete(
    "/channels/{channel_id}",
    dependencies=[Depends(require_superuser)],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a notification channel",
)
def delete_channel(channel_id: int, session: Session = Depends(get_session)) -> None:
    channel = notifications.get_channel(session, channel_id)
    if channel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "channel not found")
    notifications.delete_channel(session, channel)


@router.post(
    "/channels/{channel_id}/test",
    dependencies=[Depends(require_superuser)],
    summary="Send a test notification to a channel",
)
async def test_channel(
    channel_id: int, session: Session = Depends(get_session)
) -> Dict[str, Any]:
    if notifications.get_channel(session, channel_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "channel not found")
    return await notifications.send_test(channel_id)


@router.get(
    "/deliveries",
    dependencies=[Depends(require_superuser)],
    summary="Recent notification deliveries",
)
def list_deliveries(
    limit: int = 50, session: Session = Depends(get_session)
) -> List[Dict[str, Any]]:
    return notifications.list_recent_deliveries(session, limit=min(max(limit, 1), 200))
