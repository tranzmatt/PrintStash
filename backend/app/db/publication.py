"""Publication transaction."""

from __future__ import annotations

from sqlmodel import Session


def require_clean_publication_transaction(session: Session) -> None:
    """Reject publication after SQLite caller DML has acquired the write lock.

    A durable reservation must commit on a distinct connection before storage
    is mutated. SQLite cannot do that once the caller owns the database's write
    lock, and committing the caller here would violate its transaction boundary.
    Callers therefore order publication before their first write or establish a
    separate durable domain lease before publishing.
    """
    bind = session.get_bind()
    if bind.dialect.name != "sqlite" or not session.in_transaction():
        return
    connection = session.connection()
    raw = connection.connection.driver_connection
    if bool(getattr(raw, "in_transaction", False)):
        raise RuntimeError("storage_publication_requires_clean_sqlite_transaction")
