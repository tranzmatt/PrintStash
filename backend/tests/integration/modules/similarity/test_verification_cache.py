"""Cached outcomes remain tied to the actual inputs, geometry and sampling recipe."""

import json
from dataclasses import replace

import pytest
from printstash_core.mesh.similarity.verification import verify_meshes
from sqlmodel import select

from app.db.models import (
    File,
    GeometryFingerprint,
    SimilarityCandidateObservation,
    SimilarityEmptyVerification,
)
from app.modules.similarity import candidates, review, verification_cache
from tests.factories.geometry import tetrahedron


@pytest.fixture(scope="module")
def exact_proof():
    mesh = tetrahedron()
    return verify_meshes(
        mesh.vertices, mesh.faces, mesh.vertices, mesh.faces, sample_points=256
    )


@pytest.fixture
def verified_pair(
    db_session, make_model, make_file, make_geometry_fingerprint, exact_proof
):
    first = make_geometry_fingerprint(make_file(make_model()), state="ready")
    second = make_geometry_fingerprint(make_file(make_model()), state="ready")
    assert candidates.publish(db_session, first, second, exact_proof) is not None
    return first, second


class TestVerificationCache:
    @pytest.mark.parametrize(
        "previous_version", [None, "surface-verification-v2", "surface-verification-v3"]
    )
    def test_retains_refreshed_recipe_for_reuse(
        self,
        db_session,
        make_model,
        make_file,
        make_user,
        make_geometry_fingerprint,
        exact_proof,
        previous_version,
    ):
        pair = [
            make_geometry_fingerprint(make_file(make_model()), state="ready")
            for _ in range(2)
        ]
        prior = (
            replace(exact_proof, version=previous_version)
            if previous_version is not None
            else exact_proof
        )
        candidate = candidates.publish(db_session, *pair, prior)
        review.decide(
            db_session,
            make_user(superuser=True),
            candidate.id,
            review.DecisionRequest(
                request_id="preserve-rejection",
                version=candidate.version,
                action="reject",
            ),
        )
        original = db_session.exec(select(SimilarityCandidateObservation)).one()
        snapshot = original.evidence_json
        mesh = tetrahedron()
        refreshed = verify_meshes(
            mesh.vertices, mesh.faces, mesh.vertices, mesh.faces, sample_points=512
        )

        candidates.publish(db_session, *pair, refreshed)

        assert verification_cache.reusable_pair(db_session, *pair, sample_points=512)
        assert len(db_session.exec(select(SimilarityCandidateObservation)).all()) == 2
        db_session.refresh(original)
        db_session.refresh(candidate)
        assert original.evidence_json == snapshot
        assert candidate.review_state == "rejected"

    def test_rechecks_previous_point_distance_recipe(self, db_session, verified_pair):
        observation = db_session.exec(select(SimilarityCandidateObservation)).one()
        evidence = json.loads(observation.evidence_json)
        evidence["version"] = "surface-verification-v3"
        observation.evidence_json = json.dumps(evidence)
        db_session.add(observation)
        db_session.commit()

        assert not verification_cache.reusable_pair(
            db_session, *verified_pair, sample_points=256
        )

    @pytest.mark.parametrize("side", [0, 1])
    def test_rechecks_deleted_artifact(self, db_session, verified_pair, side):
        fingerprint = verified_pair[side]
        db_session.refresh(fingerprint)
        artifact = db_session.get(File, fingerprint.file_id)
        db_session.expunge(fingerprint)
        db_session.delete(artifact)
        db_session.commit()

        assert not verification_cache.reusable_pair(
            db_session, *verified_pair, sample_points=256
        )

    def test_rechecks_reassigned_artifact(self, db_session, verified_pair, make_model):
        first, _ = verified_pair
        artifact = db_session.get(File, first.file_id)
        artifact.model_id = make_model().id
        db_session.add(artifact)
        db_session.commit()

        assert not verification_cache.reusable_pair(
            db_session, *verified_pair, sample_points=256
        )

    def test_reuses_complete_exact_proof(self, db_session, verified_pair):
        assert verification_cache.reusable_pair(
            db_session, *verified_pair, sample_points=256
        )

    def test_rechecks_increased_sample_count(self, db_session, verified_pair):
        assert not verification_cache.reusable_pair(
            db_session, *verified_pair, sample_points=512
        )

    @pytest.mark.parametrize(
        "changed",
        ["first_state", "second_state", "algorithm", "input_hash", "component"],
    )
    def test_rechecks_changed_geometry(self, db_session, verified_pair, changed):
        first, second = verified_pair
        if changed == "first_state":
            first.state = "partial"
        elif changed == "second_state":
            second.state = "partial"
        elif changed == "algorithm":
            second.algorithm_version = "geometry-next"
        elif changed == "component":
            first.component_index = 1
        else:
            first.source_sha256 = "b" * 64

        assert not verification_cache.reusable_pair(
            db_session, first, second, sample_points=256
        )

    @pytest.mark.parametrize(
        "encoded",
        [
            "invalid",
            "[]",
            '{"exact_equivalence":true}',
            '{"exact_equivalence":true,"version":"old","sample_points":256}',
        ],
    )
    def test_rechecks_invalid_cached_recipe(self, db_session, verified_pair, encoded):
        observation = db_session.exec(select(SimilarityCandidateObservation)).one()
        observation.evidence_json = encoded
        db_session.add(observation)
        db_session.commit()

        assert not verification_cache.reusable_pair(
            db_session, *verified_pair, sample_points=256
        )

    @pytest.mark.parametrize(
        ("sample_points", "reused"),
        [(256, True), (512, False)],
        ids=["same-samples", "more-samples"],
    )
    def test_reuses_approximate_evidence_only_for_the_same_samples(
        self,
        db_session,
        make_model,
        make_file,
        make_geometry_fingerprint,
        exact_proof,
        sample_points,
        reused,
    ):
        first = make_geometry_fingerprint(make_file(make_model()), state="ready")
        second = make_geometry_fingerprint(make_file(make_model()), state="ready")
        candidates.publish(
            db_session,
            first,
            second,
            replace(
                exact_proof,
                exact_equivalence=False,
                evidence_class="similar_shape",
                confidence=0.95,
            ),
        )

        assert (
            verification_cache.reusable_pair(
                db_session, first, second, sample_points=sample_points
            )
            is reused
        )

    @pytest.mark.parametrize("count", [True, "256", 5001])
    def test_rechecks_invalid_sample_recipe(self, db_session, verified_pair, count):
        observation = db_session.exec(select(SimilarityCandidateObservation)).one()
        recipe = json.loads(observation.evidence_json)
        observation.evidence_json = json.dumps(recipe | {"sample_points": count})
        db_session.add(observation)
        db_session.commit()

        assert not verification_cache.reusable_pair(
            db_session, *verified_pair, sample_points=256
        )


@pytest.fixture(scope="module")
def empty_outcome():
    import trimesh

    mesh = tetrahedron()
    box = trimesh.creation.box((10, 20, 30))
    evidence = verify_meshes(
        mesh.vertices, mesh.faces, box.vertices, box.faces, sample_points=256
    )
    assert evidence.evidence_class is None
    return evidence


@pytest.fixture
def unrelated_pair(db_session, make_model, make_file, make_geometry_fingerprint):
    return tuple(
        make_geometry_fingerprint(make_file(make_model()), state="ready")
        for _ in range(2)
    )


def known(session, pair, *, sample_points=256, triangle_cap=2_000_000):
    return verification_cache.known_empty(
        session, *pair, sample_points=sample_points, triangle_cap=triangle_cap
    )


class TestEmptyVerification:
    def test_reports_a_recorded_empty_outcome(
        self, db_session, unrelated_pair, empty_outcome
    ):
        verification_cache.record_empty(
            db_session, *unrelated_pair, empty_outcome, triangle_cap=2_000_000
        )

        assert known(db_session, unrelated_pair)

    def test_reports_the_outcome_for_the_reversed_pair(
        self, db_session, unrelated_pair, empty_outcome
    ):
        verification_cache.record_empty(
            db_session, *unrelated_pair, empty_outcome, triangle_cap=2_000_000
        )

        assert known(db_session, unrelated_pair[::-1])

    def test_reports_nothing_for_an_unverified_pair(self, db_session, unrelated_pair):
        assert not known(db_session, unrelated_pair)

    @pytest.mark.parametrize("side", [0, 1])
    def test_ignores_the_outcome_after_a_source_change(
        self, db_session, unrelated_pair, empty_outcome, side
    ):
        verification_cache.record_empty(
            db_session, *unrelated_pair, empty_outcome, triangle_cap=2_000_000
        )
        unrelated_pair[side].source_sha256 = "c" * 64

        assert not known(db_session, unrelated_pair)

    @pytest.mark.parametrize(
        "recipe",
        [{"sample_points": 512}, {"triangle_cap": 1_000_000}],
        ids=["sample-points", "triangle-cap"],
    )
    def test_ignores_the_outcome_of_another_recipe(
        self, db_session, unrelated_pair, empty_outcome, recipe
    ):
        verification_cache.record_empty(
            db_session, *unrelated_pair, empty_outcome, triangle_cap=2_000_000
        )

        assert not known(db_session, unrelated_pair, **recipe)

    def test_ignores_the_outcome_of_a_previous_verifier(
        self, db_session, unrelated_pair, empty_outcome
    ):
        verification_cache.record_empty(
            db_session, *unrelated_pair, empty_outcome, triangle_cap=2_000_000
        )
        row = db_session.exec(select(SimilarityEmptyVerification)).one()
        row.verification_version = "surface-verification-v3"
        db_session.add(row)
        db_session.commit()

        assert not known(db_session, unrelated_pair)

    def test_records_a_repeated_outcome_once(
        self, db_session, unrelated_pair, empty_outcome
    ):
        for pair in (unrelated_pair, unrelated_pair[::-1]):
            verification_cache.record_empty(
                db_session, *pair, empty_outcome, triangle_cap=2_000_000
            )
        db_session.commit()

        assert len(db_session.exec(select(SimilarityEmptyVerification)).all()) == 1

    def test_refuses_to_record_evidence(self, db_session, unrelated_pair, exact_proof):
        with pytest.raises(ValueError, match="similarity_verification_has_evidence"):
            verification_cache.record_empty(
                db_session, *unrelated_pair, exact_proof, triangle_cap=2_000_000
            )

    def test_refuses_to_record_another_verifier_recipe(
        self, db_session, unrelated_pair, empty_outcome
    ):
        with pytest.raises(ValueError, match="similarity_verification_recipe_mismatch"):
            verification_cache.record_empty(
                db_session,
                *unrelated_pair,
                replace(empty_outcome, version="surface-verification-v3"),
                triangle_cap=2_000_000,
            )

    @pytest.mark.parametrize("side", [0, 1])
    def test_forgets_the_outcome_with_either_fingerprint(
        self, db_session, unrelated_pair, empty_outcome, side
    ):
        verification_cache.record_empty(
            db_session, *unrelated_pair, empty_outcome, triangle_cap=2_000_000
        )
        db_session.commit()
        db_session.delete(db_session.get(GeometryFingerprint, unrelated_pair[side].id))
        db_session.commit()

        assert db_session.exec(select(SimilarityEmptyVerification)).all() == []


@pytest.fixture
def whole_files(db_session, verified_pair):
    return tuple(db_session.get(File, row.file_id) for row in verified_pair)


class TestProvenExactFiles:
    def test_proves_files_with_exact_whole_evidence(self, db_session, whole_files):
        assert verification_cache.proven_exact_files(db_session, *whole_files)

    def test_proves_files_in_either_order(self, db_session, whole_files):
        assert verification_cache.proven_exact_files(db_session, *whole_files[::-1])

    def test_does_not_prove_unverified_files(self, db_session, make_model, make_file):
        assert not verification_cache.proven_exact_files(
            db_session, make_file(make_model()), make_file(make_model())
        )

    @pytest.mark.parametrize("side", [0, 1])
    def test_does_not_prove_files_after_a_source_change(
        self, db_session, whole_files, side
    ):
        whole_files[side].sha256 = "d" * 64
        db_session.add(whole_files[side])
        db_session.commit()

        assert not verification_cache.proven_exact_files(db_session, *whole_files)

    def test_does_not_prove_files_with_approximate_evidence(
        self, db_session, make_model, make_file, make_geometry_fingerprint, exact_proof
    ):
        pair = [
            make_geometry_fingerprint(make_file(make_model()), state="ready")
            for _ in range(2)
        ]
        candidates.publish(
            db_session,
            *pair,
            replace(
                exact_proof,
                exact_equivalence=False,
                evidence_class="similar_shape",
                confidence=0.95,
            ),
        )
        files = [db_session.get(File, row.file_id) for row in pair]

        assert not verification_cache.proven_exact_files(db_session, *files)

    def test_does_not_prove_files_from_component_evidence(
        self, db_session, make_model, make_file, make_geometry_fingerprint, exact_proof
    ):
        pair = [
            make_geometry_fingerprint(
                make_file(make_model()), state="ready", component_index=1
            )
            for _ in range(2)
        ]
        candidates.publish(db_session, *pair, exact_proof, kind="component_match")
        files = [db_session.get(File, row.file_id) for row in pair]

        assert not verification_cache.proven_exact_files(db_session, *files)
