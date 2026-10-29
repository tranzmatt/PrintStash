"""Editable provenance receipts preserve identity without a per-source read loop."""

import pytest
from sqlmodel import Session

from app.core.errors import OperationError
from app.modules.library.model_views.detail import detail, provenance_detail
from tests._statements import StatementLog
from tests.factories import build_model
from tests.factories.provenance import build_cover, build_provenance_source


class TestProvenanceDetail:
    def test_refuses_absent_model(self, db_session: Session):
        with pytest.raises(OperationError, match="model_not_found"):
            provenance_detail(db_session, 999999)

    def test_scopes_cover_metadata_to_model(self, db_session: Session):
        model = build_model(db_session)
        source = build_provenance_source(db_session, model)
        cover = build_cover(db_session, source)
        other = build_model(db_session)
        other_source = build_provenance_source(db_session, other)
        other_cover = build_cover(db_session, other_source)

        result = provenance_detail(db_session, model.id)

        assert [entry.id for entry in result.sources] == [source.id]
        assert result.sources[0].cover is not None
        assert result.sources[0].cover.id == cover.id
        assert result.sources[0].cover.id != other_cover.id

    def test_keeps_query_count_fixed(
        self, db_session: Session, sql_statements: StatementLog
    ):
        model = build_model(db_session)
        model_id = model.id
        build_cover(db_session, build_provenance_source(db_session, model))
        with sql_statements.recording():
            first = provenance_detail(db_session, model_id)
        initial_count = sql_statements.count
        assert len(first.sources) == 1
        for _ in range(9):
            build_cover(db_session, build_provenance_source(db_session, model))

        with sql_statements.recording():
            expanded = provenance_detail(db_session, model_id)

        assert len(expanded.sources) == 10
        assert all(source.cover is not None for source in expanded.sources)
        assert sql_statements.count == initial_count


class TestFileHashes:
    def test_returns_file_sha_without_geometry(
        self, db_session, make_user, make_model, make_file
    ):
        model = make_model()
        file = make_file(model)
        result = detail(db_session, model.id, make_user(superuser=True))
        assert result is not None
        assert [(row.sha256, row.geometric_sha256) for row in result.files] == [
            (file.sha256, None)
        ]

    def test_returns_current_whole_mesh_sha(
        self, db_session, make_user, make_model, make_file, make_geometry_fingerprint
    ):
        model = make_model()
        file = make_file(model)
        make_geometry_fingerprint(
            file, state="ready", physical_hash_0="a" * 64, normalized_hash_0="b" * 64
        )
        result = detail(db_session, model.id, make_user(superuser=True))
        assert result is not None
        assert result.files[0].geometric_sha256 == "a" * 64

    @pytest.mark.parametrize("state", ["pending", "partial", "unsupported", "failed"])
    def test_omits_unfinished_geometry(
        self,
        db_session,
        make_user,
        make_model,
        make_file,
        make_geometry_fingerprint,
        state,
    ):
        model = make_model()
        file = make_file(model)
        make_geometry_fingerprint(file, state=state, physical_hash_0="a" * 64)
        result = detail(db_session, model.id, make_user(superuser=True))
        assert result is not None
        assert result.files[0].geometric_sha256 is None

    @pytest.mark.parametrize(
        "overrides",
        [
            {"source_sha256": "f" * 64},
            {"algorithm_version": "geometry-obsolete"},
            {"component_index": 1},
            {"physical_hash_0": None},
        ],
        ids=["changed-source", "old-recipe", "component-only", "missing-digest"],
    )
    def test_omits_inapplicable_geometry(
        self,
        db_session,
        make_user,
        make_model,
        make_file,
        make_geometry_fingerprint,
        overrides,
    ):
        model = make_model()
        file = make_file(model)
        make_geometry_fingerprint(
            file, **({"state": "ready", "physical_hash_0": "a" * 64} | overrides)
        )
        result = detail(db_session, model.id, make_user(superuser=True))
        assert result is not None
        assert result.files[0].geometric_sha256 is None

    def test_keeps_hashes_scoped_to_live_model_files(
        self, db_session, make_user, make_model, make_file, make_geometry_fingerprint
    ):
        model = make_model()
        file = make_file(model)
        make_geometry_fingerprint(file, state="ready", physical_hash_0="a" * 64)
        for other in [make_file(model, trashed=True), make_file(make_model())]:
            make_geometry_fingerprint(other, state="ready", physical_hash_0="b" * 64)
        result = detail(db_session, model.id, make_user(superuser=True))
        assert result is not None
        assert [(row.id, row.geometric_sha256) for row in result.files] == [
            (file.id, "a" * 64)
        ]

    def test_keeps_geometry_read_count_fixed(
        self,
        db_session,
        sql_statements,
        make_user,
        make_model,
        make_file,
        make_geometry_fingerprint,
    ):
        model = make_model()
        model_id = model.id
        user = make_user(superuser=True)
        make_geometry_fingerprint(
            make_file(model), state="ready", physical_hash_0="a" * 64
        )
        # Warm relationship loading equally before each measurement.
        detail(db_session, model_id, user)
        with sql_statements.recording():
            first = detail(db_session, model_id, user)
        initial_count = sql_statements.count
        assert first is not None and len(first.files) == 1
        for _ in range(9):
            make_geometry_fingerprint(
                make_file(model), state="ready", physical_hash_0="b" * 64
            )
        detail(db_session, model_id, user)
        with sql_statements.recording():
            expanded = detail(db_session, model_id, user)
        assert expanded is not None and len(expanded.files) == 10
        assert sql_statements.count == initial_count

    def test_refuses_hashes_without_collection_access(
        self, db_session, make_user, make_model, make_file, make_collection
    ):
        model = make_model(collection=make_collection())
        make_file(model)
        assert detail(db_session, model.id, make_user()) is None
