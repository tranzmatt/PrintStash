"""Operator recovery for a PrintJob whose physical print no longer exists.

Resolving a stale active row repairs PrintStash history only.  It must never send
a printer command, and it is deliberately unavailable while the printer still
reports an active print.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session

from app.db.models import File, Printer, PrinterStatus, PrintJobState, User
from app.modules.printing import fleet


class TestResolveActiveJob:
    @pytest.mark.parametrize(
        "state",
        [
            PrintJobState.UPLOADING,
            PrintJobState.STARTED,
            PrintJobState.PRINTING,
            PrintJobState.PAUSED,
        ],
    )
    def test_marks_a_stale_job_failed(
        self,
        db_session: Session,
        operator: User,
        artifact: File,
        printer: Printer,
        make_print_job,
        state: PrintJobState,
    ) -> None:
        job = make_print_job(
            artifact,
            printer=printer,
            state=state,
        )

        resolved = fleet.resolve_active_job(db_session, int(job.id), "failed", operator)

        assert resolved.state == PrintJobState.FAILED
        assert resolved.error == "operator_marked_failed"
        assert resolved.finished_at is not None

    def test_marks_a_stale_job_cancelled(
        self,
        db_session: Session,
        operator: User,
        artifact: File,
        printer: Printer,
        make_print_job,
    ) -> None:
        job = make_print_job(
            artifact,
            printer=printer,
            state=PrintJobState.PAUSED,
        )

        resolved = fleet.resolve_active_job(
            db_session, int(job.id), "cancelled", operator
        )

        assert resolved.state == PrintJobState.CANCELLED
        assert resolved.error is None

    @pytest.mark.parametrize(
        "state",
        [
            PrintJobState.QUEUED,
            PrintJobState.COMPLETED,
            PrintJobState.CANCELLED,
            PrintJobState.FAILED,
        ],
    )
    def test_refuses_a_job_outside_the_active_lifecycle(
        self,
        db_session: Session,
        operator: User,
        artifact: File,
        printer: Printer,
        make_print_job,
        state: PrintJobState,
    ) -> None:
        job = make_print_job(artifact, printer=printer, state=state)

        with pytest.raises(fleet.FleetError, match="queue_job_not_resolvable"):
            fleet.resolve_active_job(db_session, int(job.id), "failed", operator)

    @pytest.mark.parametrize(
        "printer_status", [PrinterStatus.PRINTING, PrinterStatus.PAUSED]
    )
    def test_refuses_a_job_while_the_printer_is_active(
        self,
        db_session: Session,
        operator: User,
        artifact: File,
        printer: Printer,
        make_print_job,
        printer_status: PrinterStatus,
    ) -> None:
        printer.status = printer_status
        db_session.add(printer)
        db_session.commit()
        job = make_print_job(
            artifact,
            printer=printer,
            state=PrintJobState.PRINTING,
        )

        with pytest.raises(fleet.FleetError, match="printer_still_active"):
            fleet.resolve_active_job(db_session, int(job.id), "failed", operator)

    def test_hides_a_trashed_job(
        self,
        db_session: Session,
        operator: User,
        artifact: File,
        printer: Printer,
        make_print_job,
    ) -> None:
        job = make_print_job(artifact, printer=printer, state=PrintJobState.PAUSED)
        job.deleted_at = job.updated_at
        db_session.add(job)
        db_session.commit()

        with pytest.raises(fleet.FleetError, match="queue_job_not_found"):
            fleet.resolve_active_job(db_session, int(job.id), "failed", operator)
