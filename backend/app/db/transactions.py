"""Transaction ownership for product operations using an existing session."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlmodel import Session


@contextmanager
def rollback_on_failure(session: Session) -> Iterator[None]:
    """The operation commits; any failed exit rolls back its pending SQL.

    This deliberately does not begin a nested transaction or commit on exit.
    The caller may already have opened a transaction while resolving authority.
    No storage compensation is implied by a database rollback.
    """
    try:
        yield
    except BaseException:
        session.rollback()
        raise
