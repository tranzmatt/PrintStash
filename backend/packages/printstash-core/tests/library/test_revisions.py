"""The shared deletion operation preserves recommendation and owns its transaction."""

from dataclasses import replace

import pytest

from printstash_core.library import (
    RevisionDeletion,
    RevisionError,
    RevisionSnapshot,
    RevisionState,
    delete_revision,
)


class MemoryUnitOfWork:
    """Transactional state adapter for the framework-free operation."""

    def __init__(self, state: RevisionState, *, fail_commit: bool = False):
        self.state = state
        self.pending = state
        self.fail_commit = fail_commit

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.pending = self.state

    def load(self, _model_id: int) -> RevisionState:
        return self.state

    def apply(self, deletion: RevisionDeletion) -> None:
        self.pending = RevisionState(
            thumbnail_file_id=None
            if deletion.clear_thumbnail
            else self.state.thumbnail_file_id,
            files=tuple(
                replace(file, is_recommended=True)
                if file.id == deletion.promote_file_id
                else file
                for file in self.state.files
                if file.id != deletion.file_id
            ),
        )

    def commit(self) -> None:
        if self.fail_commit:
            raise RuntimeError("commit failed")
        self.state = self.pending


class TestDeleteRevision:
    def test_promotes_the_newest_surviving_gcode(self):
        uow = MemoryUnitOfWork(
            RevisionState(
                None,
                (
                    RevisionSnapshot(1, 1, "gcode", True),
                    RevisionSnapshot(2, 2, "gcode", False),
                    RevisionSnapshot(3, 3, "stl", False),
                ),
            )
        )

        result = delete_revision(1, 1, uow=uow)

        assert result.promote_file_id == 2
        assert uow.state.files == (
            RevisionSnapshot(2, 2, "gcode", True),
            RevisionSnapshot(3, 3, "stl", False),
        )

    def test_preserves_the_recommendation_when_deleting_another_revision(self):
        uow = MemoryUnitOfWork(
            RevisionState(
                None,
                (
                    RevisionSnapshot(1, 1, "gcode", True),
                    RevisionSnapshot(2, 2, "gcode", False),
                ),
            )
        )

        result = delete_revision(1, 2, uow=uow)

        assert result.promote_file_id is None
        assert uow.state.files == (RevisionSnapshot(1, 1, "gcode", True),)

    def test_clears_the_thumbnail_of_the_deleted_revision(self):
        uow = MemoryUnitOfWork(
            RevisionState(1, (RevisionSnapshot(1, 1, "gcode", True),))
        )

        delete_revision(1, 1, uow=uow)

        assert uow.state.thumbnail_file_id is None

    def test_retains_the_thumbnail_of_another_artifact(self):
        uow = MemoryUnitOfWork(
            RevisionState(
                2,
                (
                    RevisionSnapshot(1, 1, "gcode", True),
                    RevisionSnapshot(2, 2, "stl", False),
                ),
            )
        )

        delete_revision(1, 1, uow=uow)

        assert uow.state.thumbnail_file_id == 2

    def test_leaves_no_recommendation_after_the_last_gcode(self):
        uow = MemoryUnitOfWork(
            RevisionState(None, (RevisionSnapshot(1, 1, "gcode", True),))
        )

        result = delete_revision(1, 1, uow=uow)

        assert result.promote_file_id is None
        assert uow.state.files == ()

    def test_refuses_a_missing_revision(self):
        uow = MemoryUnitOfWork(RevisionState(None, ()))

        with pytest.raises(RevisionError, match="file_not_found") as caught:
            delete_revision(1, 1, uow=uow)

        assert caught.value.code == "file_not_found"
        assert uow.state.files == ()

    def test_refuses_a_non_gcode_artifact(self):
        original = RevisionState(None, (RevisionSnapshot(1, 1, "stl", False),))
        uow = MemoryUnitOfWork(original)

        with pytest.raises(RevisionError, match="revision_not_supported"):
            delete_revision(1, 1, uow=uow)

        assert uow.state == original

    def test_failed_commit_preserves_the_original_state(self):
        original = RevisionState(1, (RevisionSnapshot(1, 1, "gcode", True),))
        uow = MemoryUnitOfWork(original, fail_commit=True)

        with pytest.raises(RuntimeError, match="commit failed"):
            delete_revision(1, 1, uow=uow)

        assert uow.state == original
