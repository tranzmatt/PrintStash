"""Pending Import Jobs: resolving captures, importing them, and retention.

Resolution is pulled: every captured item with a source URL is owed a
resolve, so a capture never depends on the request that made it having
dispatched anything, and the user is waiting on it (interactive, owned by
them). Cancelling a Pending Import's Job fails the item as cancelled but keeps
it retryable; a Job that fails marks the item failed with a display-safe
reason. Settled items are never touched by either. A Pending Import owns its
retry (it may reselect files), so the Job's own retry defers to that flow.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session

from app.core.time import utcnow
from app.db.models import InboxItem, InboxItemState, JobKind, WorkPriority
from app.modules.ingestion import inbox
from app.modules.ingestion.inbox import ResolveSource

SOURCE = ResolveSource()
DEFINITIONS = {definition.name: definition for definition in inbox.definitions()}
RESOLVE = DEFINITIONS[JobKind.INGESTION_INBOX_RESOLVE]
IMPORT = DEFINITIONS[JobKind.INGESTION_INBOX_IMPORT]


@pytest.fixture
def owner(make_user):
    return make_user()


def _item(session: Session, item_id: int) -> InboxItem:
    session.expire_all()
    item = session.get(InboxItem, item_id)
    assert item is not None
    return item


class TestResolveSource:
    def test_a_captured_url_is_owed_a_resolve(
        self, db_session: Session, owner, make_inbox_item
    ) -> None:
        item = make_inbox_item(owner, source_url="https://www.printables.com/model/1")

        (work,) = SOURCE.pending(db_session, now=utcnow(), limit=10)

        assert (work.subject_key, work.priority, work.owner_user_id) == (
            f"inbox_item/{item.id}",
            WorkPriority.INTERACTIVE,
            owner.id,
        )

    def test_a_capture_without_a_url_has_nothing_to_resolve(
        self, db_session: Session, owner, make_inbox_item
    ) -> None:
        make_inbox_item(owner, source_url=None)

        assert SOURCE.pending(db_session, now=utcnow(), limit=10) == []

    @pytest.mark.parametrize(
        "state",
        [
            InboxItemState.REVIEW,
            InboxItemState.COMPLETED,
            InboxItemState.FAILED,
            InboxItemState.DISMISSED,
        ],
    )
    def test_an_item_past_capture_is_not_offered(
        self, db_session: Session, owner, make_inbox_item, state: InboxItemState
    ) -> None:
        make_inbox_item(owner, state=state, source_url="https://example.com/model")

        assert SOURCE.pending(db_session, now=utcnow(), limit=10) == []

    def test_never_offers_more_than_asked(
        self, db_session: Session, owner, make_inbox_item
    ) -> None:
        for index in range(3):
            make_inbox_item(owner, source_url=f"https://example.com/model/{index}")

        assert len(SOURCE.pending(db_session, now=utcnow(), limit=2)) == 2

    def test_is_never_due_on_time_alone(self, db_session: Session) -> None:
        assert SOURCE.next_due(db_session, now=utcnow()) is None


class TestWithdraw:
    @pytest.mark.parametrize(
        "state",
        [InboxItemState.CAPTURED, InboxItemState.RESOLVING, InboxItemState.IMPORTING],
    )
    def test_cancelling_fails_the_item_but_keeps_it_retryable(
        self, db_session: Session, owner, make_inbox_item, state: InboxItemState
    ) -> None:
        item = make_inbox_item(owner, state=state)

        IMPORT.cancel(db_session, f"inbox_item/{item.id}")
        db_session.commit()

        withdrawn = _item(db_session, item.id)
        assert (withdrawn.state, withdrawn.error_code, withdrawn.retryable) == (
            InboxItemState.FAILED,
            "cancelled",
            True,
        )

    def test_a_settled_item_is_not_touched(
        self, db_session: Session, owner, make_inbox_item
    ) -> None:
        item = make_inbox_item(owner, state=InboxItemState.COMPLETED)

        RESOLVE.cancel(db_session, f"inbox_item/{item.id}")
        db_session.commit()

        assert _item(db_session, item.id).state == InboxItemState.COMPLETED


class TestFailure:
    def test_a_failed_job_fails_its_item_with_a_safe_reason(
        self, db_session: Session, owner, make_inbox_item
    ) -> None:
        item = make_inbox_item(owner, state=InboxItemState.IMPORTING)

        IMPORT.on_failure(
            db_session, f"inbox_item/{item.id}", "cannot read /srv/private/secret.stl"
        )
        db_session.commit()

        failed = _item(db_session, item.id)
        assert (failed.state, failed.retryable) == (InboxItemState.FAILED, True)
        assert "/srv/private" not in (failed.error_code or "")

    def test_a_captured_item_is_not_failed_by_a_lost_job(
        self, db_session: Session, owner, make_inbox_item
    ) -> None:
        # Still captured, the source offers it again; failing it would strand it.
        item = make_inbox_item(owner, state=InboxItemState.CAPTURED)

        RESOLVE.on_failure(db_session, f"inbox_item/{item.id}", "boom")
        db_session.commit()

        assert _item(db_session, item.id).state == InboxItemState.CAPTURED

    def test_the_job_retry_defers_to_the_pending_import(
        self, db_session: Session, owner, make_inbox_item
    ) -> None:
        item = make_inbox_item(owner, state=InboxItemState.FAILED)

        assert IMPORT.retry(db_session, f"inbox_item/{item.id}") is False


class TestRetention:
    def test_runs_every_hour(self, db_session: Session) -> None:
        source = DEFINITIONS[JobKind.INGESTION_INBOX_RETENTION].source
        assert source is not None

        assert source.cron(db_session) == "35 * * * *"  # type: ignore[attr-defined]


class TestCompletionOwnership:
    def test_old_completion_preserves_a_new_imports_staging(
        self, db_session, make_job, make_inbox_item, make_model, owner
    ):
        import json

        from app.core.config import settings
        from app.db.models import JobState
        from app.db.session import get_session_factory
        from app.modules.work.contracts import JobExecution

        item = make_inbox_item(owner, state=InboxItemState.IMPORTING)
        model = make_model()
        old = make_job(
            kind=JobKind.INGESTION_INBOX_IMPORT,
            subject=f"inbox_item/{item.id}",
            owner=owner,
            state=JobState.COMPLETED,
            attempts=1,
            status_json=json.dumps({"model_id": model.id}),
        )
        execution = JobExecution(old.id, old.attempts, old.execution_epoch)
        current = make_job(
            kind=old.kind,
            subject=old.subject_key,
            owner=owner,
            state=JobState.RUNNING,
            attempts=1,
        )
        settings.incoming_dir.mkdir(parents=True, exist_ok=True)
        staged = settings.incoming_dir / "current-import.gcode"
        staged.write_bytes(b"new import owns these bytes")
        item.job_id = current.id
        item.staging_key = str(staged)
        db_session.add(item)
        db_session.commit()

        inbox._finish_import(item.id, execution, get_session_factory())

        db_session.refresh(item)
        assert item.state is InboxItemState.IMPORTING
        assert item.job_id == current.id
        assert item.resulting_model_id is None
        assert staged.read_bytes() == b"new import owns these bytes"

    def test_rejected_completion_retains_cover_recovery_ownership(
        self, db_session, make_job, make_inbox_item, make_model, owner, monkeypatch
    ):
        import io
        import json
        import uuid

        from PIL import Image
        from sqlmodel import select

        from app.core.config import settings
        from app.db.models import (
            JobState,
            ModelProvenanceSource,
            ModelSourceCover,
            OwnedStorageObject,
            StagingLease,
            StorageObjectState,
        )
        from app.db.session import get_session_factory
        from app.modules.library import source_covers
        from app.modules.storage.storage_backend.runtime import get_backend
        from app.modules.work.contracts import JobExecution

        model = make_model()
        source = ModelProvenanceSource(
            model_id=model.id,
            provider="test",
            identity_key=uuid.uuid4().hex * 2,
            canonical_url="https://example.test/retired-cover",
        )
        db_session.add(source)
        db_session.commit()
        source_id = source.id
        item = make_inbox_item(owner, state=InboxItemState.IMPORTING)
        old = make_job(
            kind=JobKind.INGESTION_INBOX_IMPORT,
            subject=f"inbox_item/{item.id}",
            owner=owner,
            state=JobState.COMPLETED,
            attempts=1,
            status_json=json.dumps({"model_id": model.id}),
        )
        execution = JobExecution(old.id, old.attempts, old.execution_epoch)
        current = make_job(
            kind=old.kind,
            subject=old.subject_key,
            owner=owner,
            state=JobState.RUNNING,
            attempts=1,
        )
        settings.incoming_dir.mkdir(parents=True, exist_ok=True)
        staged = settings.incoming_dir / "current-cover-import.gcode"
        staged.write_bytes(b"current import staging")
        item.job_id = current.id
        item.staging_key = str(staged)
        db_session.add(item)
        db_session.commit()
        output = io.BytesIO()
        Image.new("RGB", (8, 8), "navy").save(output, format="PNG")
        backend = get_backend()

        def publish_cover(session, _row):
            return source_covers.put(
                session,
                backend,
                provenance_source_id=source_id,
                actor_id=None,
                data=output.getvalue(),
                content_type="image/png",
            )

        monkeypatch.setattr(inbox, "_attach_capture_cover", publish_cover)
        inbox._finish_import(item.id, execution, get_session_factory())

        db_session.expire_all()
        preserved = db_session.get(InboxItem, item.id)
        assert preserved.state is InboxItemState.IMPORTING
        assert preserved.job_id == current.id
        assert preserved.resulting_model_id is None
        assert staged.read_bytes() == b"current import staging"
        cover = db_session.exec(select(ModelSourceCover)).one()
        lease = db_session.exec(
            select(StagingLease).where(StagingLease.model_source_cover_id == cover.id)
        ).one()
        proof = db_session.exec(
            select(OwnedStorageObject).where(
                OwnedStorageObject.key == cover.storage_key
            )
        ).one()
        assert proof.state is StorageObjectState.PENDING
        assert lease.sha256 is not None
        assert backend.object_info(cover.storage_key) is not None
        assert source_covers.reconcile_pending(db_session, backend) == 1
        db_session.commit()
        assert backend.read_bytes(cover.storage_key)
        assert staged.read_bytes() == b"current import staging"
