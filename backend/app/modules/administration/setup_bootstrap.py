"""First-ownership database serialization and availability checks."""

from sqlalchemy import text
from sqlmodel import Session, select

from app.core.errors import ErrorKind, OperationError
from app.db.models import SystemConfig, User


def require_open(session: Session) -> None:
    config = session.get(SystemConfig, 1)
    if config is not None and config.configured_at is not None:
        raise OperationError(kind=ErrorKind.CONFLICT, detail="already_configured")
    if session.exec(select(User.id).limit(1)).first() is not None:
        raise OperationError(kind=ErrorKind.CONFLICT, detail="users_already_exist")


def lock_installation(session: Session) -> None:
    """Serialize first ownership in the database, not in one API process."""
    connection = session.connection()
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    elif connection.dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(72816409531)"))
    else:
        raise OperationError(
            kind=ErrorKind.UNAVAILABLE, detail="setup_database_not_supported"
        )
    session.expire_all()
    require_open(session)
