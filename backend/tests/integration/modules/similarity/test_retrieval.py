"""Indexed discovery is bounded, permission filtered and tolerant of repairs."""

import struct

import pytest
from sqlalchemy import text
from sqlmodel import select

from app.db.models import CollectionRole, File, GeometryFingerprint
from app.modules.similarity import retrieval
from tests.factories import build_geometry_fingerprint, surface_cloud_blob


@pytest.fixture
def source(db_session, make_model, make_file):
    return build_geometry_fingerprint(
        db_session,
        make_file(make_model()),
        state="ready",
        normalized_area=1,
        area_volume_ratio=3,
        hull_ratio=1,
        euler_characteristic=2,
        d2_blob=struct.pack("<64f", *([1 / 64] * 64)),
    )


class TestRetrieval:
    def test_retrieves_repaired_topology(
        self,
        db_session,
        make_model,
        make_file,
        make_user,
        source,
        make_geometry_fingerprint,
    ):
        repaired = make_geometry_fingerprint(
            make_file(make_model()),
            state="ready",
            normalized_area=1.05,
            euler_characteristic=-8,
            watertight=False,
            d2_blob=source.d2_blob,
        )
        result = retrieval.find_candidates(
            db_session, source, make_user(superuser=True)
        )
        assert result.fingerprint_ids == (repaired.id,)

    @pytest.mark.parametrize("base", ["thingi10k-70561.stl", "thingi10k-843549.stl"])
    def test_retains_quarter_face_decimation(
        self, db_session, make_model, make_file, make_user, base, tmp_path
    ):
        from app.db.models import FileType
        from app.modules.media.fingerprints import extract
        from app.modules.media.geometry_analysis import _load
        from app.modules.similarity.fingerprints import publish_precomputed
        from tests.factories.similarity_corpus import mesh_for

        first, second = (
            make_file(make_model(), file_type=FileType.STL),
            make_file(make_model(), file_type=FileType.STL),
        )
        dense = tmp_path / "dense.stl"
        reduced = tmp_path / "reduced.stl"
        dense.write_bytes(mesh_for(base, "subdivision").export(file_type="stl"))
        reduced.write_bytes(mesh_for(base, "original").export(file_type="stl"))
        publish_precomputed(
            db_session, first, extract(_load(dense, "stl", triangle_cap=200_000))
        )
        publish_precomputed(
            db_session, second, extract(_load(reduced, "stl", triangle_cap=200_000))
        )
        source = db_session.exec(
            select(GeometryFingerprint).where(
                GeometryFingerprint.file_id == first.id,
                GeometryFingerprint.component_index == 0,
            )
        ).one()
        target = db_session.exec(
            select(GeometryFingerprint).where(
                GeometryFingerprint.file_id == second.id,
                GeometryFingerprint.component_index == 0,
            )
        ).one()

        result = retrieval.find_candidates(
            db_session, source, make_user(superuser=True)
        )

        assert target.face_count * 4 == source.face_count
        assert target.id in result.fingerprint_ids

    def test_bounds_primitive_buckets(
        self,
        db_session,
        make_model,
        make_file,
        make_user,
        source,
        make_geometry_fingerprint,
    ):
        for _ in range(25):
            make_geometry_fingerprint(
                make_file(make_model()),
                state="ready",
                normalized_area=1,
                d2_blob=source.d2_blob,
            )
        result = retrieval.find_candidates(
            db_session, source, make_user(superuser=True), limit=3, bucket_limit=10
        )
        assert len(result.fingerprint_ids) == 3
        assert result.examined == 10
        assert result.skipped_by_budget >= 8

    def test_uses_eight_indexed_hash_lookups(self, db_session, source):
        for group in ("physical", "normalized"):
            for index in range(4):
                setattr(source, f"{group}_hash_{index}", "0" * 64)
        statement = retrieval.hash_lookup(source).compile(
            db_session.get_bind(), compile_kwargs={"literal_binds": True}
        )
        plan = db_session.exec(text("EXPLAIN QUERY PLAN " + str(statement))).all()
        details = "\n".join(str(row) for row in plan)
        for group in ("physical", "normalized"):
            for index in range(4):
                assert f"ix_geometry_fingerprints_{group}_hash_{index}" in details
        assert "SCAN geometry_fingerprints" not in details

    @pytest.mark.parametrize(
        "column,index_name",
        [
            ("normalized_area", "ix_geometry_fingerprint_repair"),
            ("area_volume_ratio", "ix_geometry_fingerprint_strict"),
        ],
    )
    def test_uses_invariant_range_index(self, db_session, source, column, index_name):
        query = select(GeometryFingerprint.id).where(
            GeometryFingerprint.algorithm_version == source.algorithm_version,
            GeometryFingerprint.state == "ready",
            getattr(GeometryFingerprint, column).between(0.9, 1.1),
        )
        sql = query.compile(
            db_session.get_bind(), compile_kwargs={"literal_binds": True}
        )
        plan = db_session.exec(text("EXPLAIN QUERY PLAN " + str(sql))).all()
        assert index_name in str(plan)

    def test_excludes_hidden_target(
        self,
        db_session,
        source,
        make_model,
        make_file,
        make_user,
        make_collection,
        grant_role,
        make_geometry_fingerprint,
    ):
        collection = make_collection()
        source_file = db_session.get(File, source.file_id)
        source_file.model.collection_id = collection.id
        db_session.add(source_file.model)
        db_session.commit()
        make_geometry_fingerprint(
            make_file(make_model()),
            state="ready",
            normalized_area=1,
            d2_blob=source.d2_blob,
        )
        editor = make_user()
        grant_role(editor, collection, CollectionRole.EDIT)
        result = retrieval.find_candidates(db_session, source, editor)
        assert result.fingerprint_ids == ()
        assert result.examined == result.skipped_by_budget == 0

    def test_excludes_changed_target(
        self,
        db_session,
        source,
        make_model,
        make_file,
        make_user,
        make_geometry_fingerprint,
    ):
        file = make_file(make_model())
        make_geometry_fingerprint(
            file, state="ready", normalized_area=1, d2_blob=source.d2_blob
        )
        file.sha256 = "f" * 64
        db_session.add(file)
        db_session.commit()
        assert (
            retrieval.find_candidates(
                db_session, source, make_user(superuser=True)
            ).fingerprint_ids
            == ()
        )

    def test_applies_inertia_window_to_strict_lane(
        self,
        db_session,
        make_user,
        make_model,
        make_file,
        source,
        make_geometry_fingerprint,
    ):
        source.normalized_area = None
        source.inertia_ratio_0 = 0.4
        source.inertia_ratio_1 = 0.7
        db_session.add(source)
        db_session.commit()
        matching = make_geometry_fingerprint(
            make_file(make_model()),
            state="ready",
            area_volume_ratio=3,
            hull_ratio=1,
            euler_characteristic=2,
            inertia_ratio_0=0.41,
            inertia_ratio_1=0.7,
            d2_blob=source.d2_blob,
        )
        make_geometry_fingerprint(
            make_file(make_model()),
            state="ready",
            area_volume_ratio=3,
            hull_ratio=1,
            euler_characteristic=2,
            inertia_ratio_0=0.8,
            inertia_ratio_1=0.9,
            d2_blob=source.d2_blob,
        )
        assert retrieval.find_candidates(
            db_session, source, make_user(superuser=True)
        ).fingerprint_ids == (matching.id,)


class TestSingleBodyComponents:
    """A single-body file's Component 1 repeats its whole row."""

    def test_offers_only_the_whole_row_of_a_single_body_target(
        self,
        db_session,
        source,
        make_model,
        make_file,
        make_user,
        make_geometry_fingerprint,
    ):
        file = make_file(make_model())
        whole = make_geometry_fingerprint(
            file,
            state="ready",
            normalized_area=1,
            component_count=1,
            d2_blob=source.d2_blob,
        )
        make_geometry_fingerprint(
            file,
            state="ready",
            component_index=1,
            normalized_area=1,
            component_count=1,
            d2_blob=source.d2_blob,
        )

        result = retrieval.find_candidates(
            db_session, source, make_user(superuser=True)
        )

        assert result.fingerprint_ids == (whole.id,)

    @pytest.mark.parametrize(
        "component_count", [2, None], ids=["multi-body", "partial-whole"]
    )
    def test_offers_components_unless_the_whole_is_one_body(
        self,
        db_session,
        source,
        make_model,
        make_file,
        make_user,
        make_geometry_fingerprint,
        component_count,
    ):
        file = make_file(make_model())
        rows = [
            make_geometry_fingerprint(
                file,
                state="ready",
                component_index=index,
                normalized_area=1,
                component_count=component_count if index == 0 else 1,
                d2_blob=source.d2_blob,
            )
            for index in range(2)
        ]

        result = retrieval.find_candidates(
            db_session, source, make_user(superuser=True)
        )

        assert set(result.fingerprint_ids) == {row.id for row in rows}

    def test_offers_a_component_whose_whole_row_is_from_another_source(
        self,
        db_session,
        source,
        make_model,
        make_file,
        make_user,
        make_geometry_fingerprint,
    ):
        file = make_file(make_model())
        make_geometry_fingerprint(
            file,
            state="ready",
            normalized_area=1,
            component_count=1,
            source_sha256="e" * 64,
            d2_blob=source.d2_blob,
        )
        component = make_geometry_fingerprint(
            file,
            state="ready",
            component_index=1,
            normalized_area=1,
            component_count=1,
            d2_blob=source.d2_blob,
        )

        result = retrieval.find_candidates(
            db_session, source, make_user(superuser=True)
        )

        assert result.fingerprint_ids == (component.id,)


def near_d2(distance):
    """A D2 histogram whose distance from the uniform source grows with *distance*."""
    values = [1 / 64] * 64
    values[0] += distance
    values[1] = max(values[1] - distance, 0)
    return struct.pack("<64f", *values)


@pytest.fixture
def shapes():
    import trimesh

    cylinder = trimesh.creation.cylinder(radius=5, height=12, sections=48)
    turned = cylinder.copy()
    turned.apply_transform(trimesh.transformations.rotation_matrix(0.8, [1, 1, 0]))
    turned.apply_scale(25.4)
    return {
        "source": surface_cloud_blob(cylinder),
        "copy": surface_cloud_blob(turned),
        "slab": surface_cloud_blob(trimesh.creation.box((10, 20, 2))),
    }


@pytest.fixture
def cloud_target(db_session, make_model, make_file, make_geometry_fingerprint):
    def make(cloud_blob, distance, **overrides):
        return make_geometry_fingerprint(
            make_file(make_model()),
            state="ready",
            normalized_area=1,
            d2_blob=near_d2(distance),
            cloud_blob=cloud_blob,
            **overrides,
        )

    return make


@pytest.fixture
def cloud_source(db_session, source, shapes):
    source.cloud_blob = shapes["source"]
    db_session.add(source)
    db_session.commit()
    return source


class TestCloudOrdering:
    def test_shortlists_a_cloud_match_ranked_past_the_budget(
        self, db_session, make_user, cloud_source, cloud_target, shapes
    ):
        cloud_target(shapes["slab"], 0.0)
        match = cloud_target(shapes["copy"], 0.004)

        result = retrieval.find_candidates(
            db_session, cloud_source, make_user(superuser=True), limit=1
        )

        assert result.fingerprint_ids == (match.id,)

    def test_drops_a_clearly_different_candidate(
        self, db_session, make_user, cloud_source, cloud_target, shapes
    ):
        cloud_target(shapes["slab"], 0.0)
        match = cloud_target(shapes["copy"], 0.004)

        result = retrieval.find_candidates(
            db_session, cloud_source, make_user(superuser=True)
        )

        assert (result.fingerprint_ids, result.rejected_by_cloud) == ((match.id,), 1)

    def test_marks_a_confirmed_candidate_cleared(
        self, db_session, make_user, cloud_source, cloud_target, shapes
    ):
        match = cloud_target(shapes["copy"], 0.004)

        result = retrieval.find_candidates(
            db_session, cloud_source, make_user(superuser=True)
        )

        assert result.cloud_cleared == frozenset({match.id})

    def test_keeps_a_candidate_without_a_cloud_after_confirmed_ones(
        self, db_session, make_user, cloud_source, cloud_target, shapes
    ):
        legacy = cloud_target(None, 0.0)
        match = cloud_target(shapes["copy"], 0.004)

        result = retrieval.find_candidates(
            db_session, cloud_source, make_user(superuser=True)
        )

        assert (result.fingerprint_ids, result.cloud_cleared) == (
            (match.id, legacy.id),
            frozenset({match.id}),
        )

    def test_keeps_descriptor_order_for_a_source_without_a_cloud(
        self, db_session, make_user, source, cloud_target, shapes
    ):
        source.cloud_blob = None
        db_session.add(source)
        db_session.commit()
        slab = cloud_target(shapes["slab"], 0.0)
        match = cloud_target(shapes["copy"], 0.004)

        result = retrieval.find_candidates(
            db_session, source, make_user(superuser=True)
        )

        assert (result.fingerprint_ids, result.cloud_cleared) == (
            (slab.id, match.id),
            frozenset(),
        )

    def test_keeps_an_exact_key_hit_first_whatever_its_cloud(
        self, db_session, make_user, cloud_source, cloud_target, shapes
    ):
        cloud_source.physical_hash_0 = "a" * 64
        db_session.add(cloud_source)
        db_session.commit()
        match = cloud_target(shapes["copy"], 0.0)
        keyed = cloud_target(shapes["slab"], 0.004, physical_hash_0="a" * 64)

        result = retrieval.find_candidates(
            db_session, cloud_source, make_user(superuser=True)
        )

        assert result.fingerprint_ids == (keyed.id, match.id)

    def test_measures_only_five_times_the_budget(
        self, db_session, make_user, cloud_source, cloud_target, shapes
    ):
        decoys = [
            cloud_target(shapes["slab"], index * 0.001)
            for index in range(retrieval.CLOUD_POOL_FACTOR)
        ]
        cloud_target(shapes["copy"], 0.02)

        result = retrieval.find_candidates(
            db_session, cloud_source, make_user(superuser=True), limit=1
        )

        # One decoy is measured and dropped; the match is outside the pool.
        assert (result.fingerprint_ids, result.rejected_by_cloud) == (
            (decoys[1].id,),
            1,
        )
