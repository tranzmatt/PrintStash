"""A Subject depends on every Collection above it, found in one statement.

A Model's passages repeat its collection path, so renaming or moving any
ancestor must re-project it. Projection prepares a dependency set for every
Subject it touches, so the walk up the tree is paid once per Subject: one
statement rather than one per level. Trashed ancestors still count, since
restoring them changes the path again, and a corrupt parent cycle ends.
"""

from __future__ import annotations

from printstash_core.search.passages import SearchSubject, SubjectType
from sqlalchemy import event
from sqlmodel import Session

from app.db.projections import ContentSource
from app.modules.search.dependencies import extraction_dependencies


def _collections(sources: set[ContentSource]) -> set[int]:
    return {source.id for source in sources if source.kind == "collection"}


class TestCollectionAncestors:
    def test_a_model_depends_on_every_ancestor(
        self, db_session: Session, make_collection, make_model
    ) -> None:
        root = make_collection("Home")
        middle = make_collection("Storage", parent=root)
        leaf = make_collection("Shelves", parent=middle)
        model = make_model(collection=leaf)

        sources = extraction_dependencies(
            db_session, SearchSubject(SubjectType.MODEL, model.id)
        )

        assert _collections(sources) == {root.id, middle.id, leaf.id}

    def test_a_trashed_ancestor_still_counts(
        self, db_session: Session, make_collection, make_model
    ) -> None:
        root = make_collection("Archive", trashed=True)
        leaf = make_collection("Old", parent=root)
        model = make_model(collection=leaf)

        sources = extraction_dependencies(
            db_session, SearchSubject(SubjectType.MODEL, model.id)
        )

        assert _collections(sources) == {root.id, leaf.id}

    def test_a_parent_cycle_ends(
        self, db_session: Session, make_collection, make_model
    ) -> None:
        first = make_collection("First")
        second = make_collection("Second", parent=first)
        first.parent_id = second.id
        db_session.add(first)
        db_session.commit()
        model = make_model(collection=second)

        sources = extraction_dependencies(
            db_session, SearchSubject(SubjectType.MODEL, model.id)
        )

        assert _collections(sources) == {first.id, second.id}

    def test_reads_as_much_for_a_deep_tree_as_for_a_shallow_one(
        self, db_session: Session, make_collection, make_model
    ) -> None:
        def reads(depth: int) -> int:
            parent = None
            for level in range(depth):
                parent = make_collection(f"Depth {depth} level {level}", parent=parent)
            model = make_model(f"At depth {depth}", collection=parent)
            db_session.expire_all()
            seen: list[str] = []

            def record(_conn, _cursor, statement, *_rest) -> None:
                if "FROM collections" in statement:
                    seen.append(statement)

            target = db_session.get_bind()
            event.listen(target, "before_cursor_execute", record)
            try:
                extraction_dependencies(
                    db_session, SearchSubject(SubjectType.MODEL, model.id)
                )
            finally:
                event.remove(target, "before_cursor_execute", record)
            return len(seen)

        assert reads(5) == reads(1)
