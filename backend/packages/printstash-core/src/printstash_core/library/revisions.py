"""Delete a live G-code Revision without losing its Model's recommendation.

The adapter authorizes and locks the Model before supplying its live Artifacts.
The operation owns the transaction; storage cleanup is deliberately not part of
soft deletion. Adapters record product-specific tombstones in the same commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from typing import Protocol


class RevisionError(ValueError):
    """Stable business error, translated to the transport's error vocabulary."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RevisionSnapshot:
    id: int
    version: int
    file_type: str
    is_recommended: bool


@dataclass(frozen=True)
class RevisionState:
    thumbnail_file_id: int | None
    files: tuple[RevisionSnapshot, ...]


@dataclass(frozen=True)
class RevisionDeletion:
    file_id: int
    promote_file_id: int | None
    clear_thumbnail: bool


class RevisionUnitOfWork(Protocol):
    """One authorized transaction, usable from HTTP or a worker.

    ``load`` rejects missing/trashed Models and unauthorized actors, locks the
    Model, and returns only its live Artifacts within the adapter's validated
    product scope. ``apply`` stages the deletion, clears the old recommendation
    before promoting its successor, and records local lifecycle effects.
    Only ``commit`` commits. Exiting after any failure rolls back pending SQL;
    no operation deletes stored bytes.
    """

    def __enter__(self) -> RevisionUnitOfWork: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...
    def load(self, model_id: int) -> RevisionState: ...
    def apply(self, deletion: RevisionDeletion) -> None: ...
    def commit(self) -> None: ...


def delete_revision(
    model_id: int, file_id: int, *, uow: RevisionUnitOfWork
) -> RevisionDeletion:
    """Soft-delete one Revision and promote the newest surviving G-code if needed."""
    with uow:
        state = uow.load(model_id)
        target = next((file for file in state.files if file.id == file_id), None)
        if target is None:
            raise RevisionError("file_not_found")
        if target.file_type != "gcode":
            raise RevisionError("revision_not_supported")

        replacement = (
            max(
                (
                    file
                    for file in state.files
                    if file.id != file_id and file.file_type == "gcode"
                ),
                key=lambda file: file.version,
                default=None,
            )
            if target.is_recommended
            else None
        )
        deletion = RevisionDeletion(
            file_id=file_id,
            promote_file_id=replacement.id if replacement is not None else None,
            clear_thumbnail=state.thumbnail_file_id == file_id,
        )
        uow.apply(deletion)
        uow.commit()
        return deletion
