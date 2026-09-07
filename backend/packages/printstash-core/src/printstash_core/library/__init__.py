"""Shared library operations; persistence and authorization belong to adapters."""

from .revisions import (
    RevisionDeletion,
    RevisionError,
    RevisionSnapshot,
    RevisionState,
    RevisionUnitOfWork,
    delete_revision,
)

__all__ = [
    "RevisionDeletion",
    "RevisionError",
    "RevisionSnapshot",
    "RevisionState",
    "RevisionUnitOfWork",
    "delete_revision",
]
