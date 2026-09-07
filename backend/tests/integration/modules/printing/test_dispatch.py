"""Dispatch enforces actor authority before touching a provider outside HTTP."""

import asyncio

import pytest
from sqlmodel import select

from app.core.errors import ErrorKind, OperationError
from app.db.models import PrintJob
from app.modules.printing.dispatch import send_to_printer
from app.schemas.printers import SendToPrinter


class TestDispatchAuthority:
    def test_inactive_worker_actor_cannot_contact_a_printer(
        self, db_session, make_user, make_printer, make_model, make_file
    ):
        actor = make_user(superuser=True, active=False)
        printer = make_printer()
        model = make_model()
        artifact = make_file(model)
        contacted = []

        def unavailable(*args):
            contacted.append(args)
            raise AssertionError("dependencies must not be accessed before authority")

        with pytest.raises(OperationError) as raised:
            asyncio.run(
                send_to_printer(
                    printer.id,
                    SendToPrinter(file_id=artifact.id),
                    actor,
                    db_session,
                    provider_builder=unavailable,
                    backend_provider=unavailable,
                )
            )

        assert raised.value.kind is ErrorKind.FORBIDDEN
        assert contacted == []
        assert db_session.exec(select(PrintJob)).all() == []
