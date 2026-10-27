"""Read-only print-specific slicer evidence, never a restorable preset claim."""

from datetime import datetime

from pydantic import BaseModel


class CapturedSettingsRead(BaseModel):
    printer: dict[str, str]
    filament: dict[str, str]
    process: dict[str, str]


class SlicerProfileRead(BaseModel):
    file_id: int
    model_id: int
    model_name: str
    filename: str
    uploaded_at: datetime
    slicer_name: str | None
    slicer_version: str | None
    settings: CapturedSettingsRead


class SlicerProfilePage(BaseModel):
    items: list[SlicerProfileRead]
    next_before_id: int | None
