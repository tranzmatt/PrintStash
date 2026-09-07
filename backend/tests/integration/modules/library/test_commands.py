"""Library mutations retain their authority and transaction outside HTTP."""

import pytest
from sqlmodel import select

from app.core.errors import ErrorKind, OperationError
from app.db.models import ModelTagLink, Tag
from app.modules.library.commands import update_model
from app.schemas.models import ModelUpdate


class TestUpdateModel:
    def test_worker_cannot_edit_without_authority(
        self, db_session, make_user, make_model
    ):
        actor = make_user()
        model = make_model(name="Original")

        with pytest.raises(OperationError) as raised:
            update_model(model.id, ModelUpdate(name="Changed"), actor, db_session)

        assert raised.value.kind is ErrorKind.FORBIDDEN
        db_session.refresh(model)
        assert model.name == "Original"

    def test_failed_tag_assignment_does_not_commit_partial_metadata(
        self, db_session, make_user, make_model, monkeypatch
    ):
        actor = make_user(superuser=True)
        model = make_model(name="Original")
        add = db_session.add

        def reject_link(row, **kwargs):
            if isinstance(row, ModelTagLink):
                raise RuntimeError("tag assignment failed")
            return add(row, **kwargs)

        monkeypatch.setattr(db_session, "add", reject_link)

        with pytest.raises(RuntimeError, match="tag assignment failed"):
            update_model(
                model.id,
                ModelUpdate(name="Changed", tags=["new-tag"]),
                actor,
                db_session,
            )

        db_session.expire_all()
        assert model.name == "Original"
        assert db_session.exec(select(Tag).where(Tag.name == "new-tag")).all() == []
