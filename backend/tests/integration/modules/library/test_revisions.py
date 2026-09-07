"""Non-HTTP callers get the same authorized, atomic Revision deletion as the API."""

import pytest
from printstash_core.library import RevisionError
from printstash_core_testkit.revisions import REVISION_EXAMPLES
from sqlmodel import select

from app.db.models import File, FileType
from app.modules.library.revisions import remove_revision


@pytest.fixture
def revision_database(tmp_path):
    from sqlalchemy import event
    from sqlmodel import Session, SQLModel, create_engine

    from tests.factories import build_file, build_model, build_user

    engine = create_engine(
        f"sqlite:///{tmp_path / 'revisions.sqlite'}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )

    @event.listens_for(engine, "connect")
    def configure(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        actor = build_user(session, superuser=True)
        model = build_model(session)
        first = build_file(session, model, file_type=FileType.GCODE, recommended=True)
        survivor = build_file(session, model, file_type=FileType.GCODE)
        newest = build_file(session, model, file_type=FileType.GCODE)
        identities = actor.id, model.id, first.id, survivor.id, newest.id
    try:
        yield engine, identities
    finally:
        engine.dispose()


class TestRevisionConcurrency:
    def test_sqlite_deletions_serialize_before_choosing_the_survivor(
        self, revision_database, monkeypatch
    ):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event

        from sqlmodel import Session

        from app.db.models import User
        from app.modules.library.revisions import SQLRevisionUnitOfWork

        engine, (actor_id, model_id, first_id, survivor_id, newest_id) = (
            revision_database
        )
        first_loaded, second_finished = Event(), Event()
        apply = SQLRevisionUnitOfWork.apply

        def pause_after_snapshot(unit, deletion):
            if deletion.file_id == first_id:
                first_loaded.set()
                # A serialized second writer cannot finish until this operation
                # commits. Without the write lock it removes our chosen survivor
                # during this pause, exposing a lost recommendation deterministically.
                second_finished.wait(timeout=1)
            apply(unit, deletion)

        monkeypatch.setattr(SQLRevisionUnitOfWork, "apply", pause_after_snapshot)

        def delete(file_id):
            with Session(engine) as session:
                actor = session.get(User, actor_id)
                try:
                    remove_revision(session, actor, model_id, file_id)
                finally:
                    if file_id == newest_id:
                        second_finished.set()

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(delete, first_id)
            assert first_loaded.wait(timeout=5)
            second = executor.submit(delete, newest_id)
            first.result(timeout=10)
            second.result(timeout=10)

        with Session(engine) as session:
            assert session.get(File, first_id).deleted_at is not None
            assert session.get(File, newest_id).deleted_at is not None
            assert session.get(File, survivor_id).is_recommended is True

    def test_a_preloaded_session_refreshes_recommendations_after_another_commit(
        self, revision_database
    ):
        from sqlmodel import Session

        from app.db.models import User

        engine, (actor_id, model_id, first_id, survivor_id, newest_id) = (
            revision_database
        )
        with Session(engine) as stale, Session(engine) as other:
            cached = stale.get(File, newest_id)
            assert cached.is_recommended is False
            actor = other.get(User, actor_id)
            remove_revision(other, actor, model_id, first_id)

            remove_revision(stale, stale.get(User, actor_id), model_id, newest_id)

        with Session(engine) as session:
            assert session.get(File, newest_id).deleted_at is not None
            assert session.get(File, survivor_id).is_recommended is True


class TestRemoveRevision:
    def test_promotes_the_newest_surviving_revision(
        self, db_session, make_user, make_model, make_file
    ):
        actor = make_user(superuser=True)
        model = make_model()
        old = make_file(model, recommended=True)
        newest = make_file(model)

        remove_revision(db_session, actor, model.id, old.id)

        db_session.refresh(newest)
        assert newest.is_recommended is True

    def test_records_the_actor_on_the_retained_row(
        self, db_session, make_user, make_model, make_file
    ):
        actor = make_user(superuser=True)
        model = make_model()
        file = make_file(model)

        remove_revision(db_session, actor, model.id, file.id)

        db_session.refresh(file)
        assert file.deleted_at is not None
        assert file.deleted_by == actor.id

    def test_denies_an_actor_without_edit_permission(
        self, db_session, make_user, make_model, make_file
    ):
        actor = make_user()
        model = make_model()
        file = make_file(model)

        with pytest.raises(RevisionError, match="collection_permission_denied"):
            remove_revision(db_session, actor, model.id, file.id)

        db_session.refresh(file)
        assert file.deleted_at is None

    def test_rejects_a_trashed_model(
        self, db_session, make_user, make_model, make_file
    ):
        actor = make_user(superuser=True)
        model = make_model(trashed=True)
        file = make_file(model)

        with pytest.raises(RevisionError, match="model_not_found"):
            remove_revision(db_session, actor, model.id, file.id)

        db_session.refresh(file)
        assert file.deleted_at is None

    def test_does_not_promote_a_trashed_revision(
        self, db_session, make_user, make_model, make_file
    ):
        actor = make_user(superuser=True)
        model = make_model()
        old = make_file(model, recommended=True)
        newest = make_file(model, trashed=True)

        remove_revision(db_session, actor, model.id, old.id)

        db_session.refresh(newest)
        assert newest.is_recommended is False

    def test_refuses_a_file_under_another_model(
        self, db_session, make_user, make_model, make_file
    ):
        actor = make_user(superuser=True)
        model = make_model()
        other = make_model()
        file = make_file(other)

        with pytest.raises(RevisionError, match="file_not_found"):
            remove_revision(db_session, actor, model.id, file.id)

        db_session.refresh(file)
        assert file.deleted_at is None

    def test_refuses_a_mesh(self, db_session, make_user, make_model, make_file):
        actor = make_user(superuser=True)
        model = make_model()
        file = make_file(model, file_type=FileType.STL)

        with pytest.raises(RevisionError, match="revision_not_supported"):
            remove_revision(db_session, actor, model.id, file.id)

        assert (
            db_session.exec(select(File).where(File.id == file.id)).one().deleted_at
            is None
        )


class TestSharedRevisionContract:
    @pytest.mark.parametrize(
        "example", REVISION_EXAMPLES, ids=lambda example: example.name
    )
    def test_shared_business_contract(
        self, example, db_session, make_user, make_model, make_file
    ):
        actor = make_user(superuser=True)
        model = make_model()
        rows = []
        for version, file_type, recommended, trashed in example.files:
            row = make_file(
                model,
                version=version,
                file_type=FileType(file_type),
                recommended=recommended,
                trashed=trashed,
            )
            rows.append(row)
        if example.thumbnail_index is not None:
            model.thumbnail_file_id = rows[example.thumbnail_index].id
            model.thumbnail_path = "existing-cover.png"
            db_session.add(model)
            db_session.commit()
        target = rows[0]
        if example.error:
            with pytest.raises(RevisionError, match=example.error):
                remove_revision(db_session, actor, model.id, target.id)
            db_session.refresh(target)
            assert (target.deleted_at is not None) == example.files[0][3]
            return

        remove_revision(db_session, actor, model.id, target.id)

        db_session.expire_all()
        assert target.deleted_at is not None
        assert target.deleted_by == actor.id
        recommended = [
            row.version for row in rows if row.is_recommended and row.deleted_at is None
        ]
        assert recommended == (
            [] if example.recommended_version is None else [example.recommended_version]
        )
        assert (model.thumbnail_path is not None) == example.thumbnail_survives
        assert model.thumbnail_file_id == (
            rows[example.thumbnail_index].id if example.thumbnail_survives else None
        )


class TestRevisionTransaction:
    def test_inactive_actor_cannot_invoke_the_command(
        self, db_session, make_user, make_model, make_file
    ):
        actor = make_user(superuser=True, active=False)
        model = make_model()
        file = make_file(model)

        with pytest.raises(RevisionError, match="collection_permission_denied"):
            remove_revision(db_session, actor, model.id, file.id)

        db_session.refresh(file)
        assert file.deleted_at is None

    def test_linked_revision_records_a_source_tombstone(
        self,
        db_session,
        make_user,
        make_model,
        make_file,
        make_external_library,
        tmp_path,
    ):
        from app.db.models import ExternalLibraryTombstone

        actor = make_user(superuser=True)
        source = make_external_library(tmp_path)
        model = make_model()
        file = make_file(
            model, external=True, external_library_id=source.id, source_key="part.gcode"
        )

        remove_revision(db_session, actor, model.id, file.id)

        tombstone = db_session.exec(select(ExternalLibraryTombstone)).one()
        assert tombstone.library_id == source.id
        assert tombstone.source_key == "part.gcode"
        assert tombstone.reason == "revision_trashed"

    def test_failed_commit_rolls_back_the_whole_revision_change(
        self,
        db_session,
        make_user,
        make_model,
        make_file,
        make_external_library,
        tmp_path,
        monkeypatch,
    ):
        from app.db.models import ExternalLibraryTombstone

        actor = make_user(superuser=True)
        source = make_external_library(tmp_path)
        model = make_model()
        file = make_file(
            model,
            recommended=True,
            external=True,
            external_library_id=source.id,
            source_key="part.gcode",
        )
        survivor = make_file(model)
        model.thumbnail_file_id = file.id
        model.thumbnail_path = "original-cover.png"
        db_session.add(model)
        db_session.commit()

        def fail_commit():
            raise OSError("commit unavailable")

        monkeypatch.setattr(db_session, "commit", fail_commit)

        with pytest.raises(OSError, match="commit unavailable"):
            remove_revision(db_session, actor, model.id, file.id)

        db_session.expire_all()
        assert file.deleted_at is None
        assert file.is_recommended is True
        assert survivor.is_recommended is False
        assert model.thumbnail_file_id == file.id
        assert model.thumbnail_path == "original-cover.png"
        assert db_session.exec(select(ExternalLibraryTombstone)).all() == []
