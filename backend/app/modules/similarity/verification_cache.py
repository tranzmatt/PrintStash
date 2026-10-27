"""Reuse verified pair outcomes only for the same inputs and verifier recipe.

Verification is seeded, so the same inputs and recipe give the same outcome:
exact proofs, approximate evidence and empty outcomes are all reusable.

The caller owns authorization and rehashes materialized source bytes first. This
lookup never turns retrieval hashes or approximate evidence into an exact proof.
"""

from __future__ import annotations

import json

from printstash_core.mesh.similarity.verification import (
    VERIFICATION_VERSION,
    Verification,
)
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.db.models import (
    File,
    GeometryFingerprint,
    SimilarityCandidate,
    SimilarityCandidateObservation,
    SimilarityEmptyVerification,
)


def reusable_pair(
    session: Session,
    first: GeometryFingerprint,
    second: GeometryFingerprint,
    *,
    sample_points: int,
) -> bool:
    if first.state != "ready" or second.state != "ready":
        return False
    if first.algorithm_version != second.algorithm_version:
        return False
    fa, fb = session.get(File, first.file_id), session.get(File, second.file_id)
    if fa is None or fb is None:
        return False
    observation = SimilarityCandidateObservation
    encoded = session.exec(
        select(observation.evidence_json)
        .join(SimilarityCandidate, SimilarityCandidate.id == observation.candidate_id)
        .where(
            observation.fingerprint_a_id == first.id,
            observation.fingerprint_b_id == second.id,
            observation.input_hash_a == first.source_sha256,
            observation.input_hash_b == second.source_sha256,
            observation.kind
            == (
                "component_match"
                if first.component_index or second.component_index
                else "whole"
            ),
            SimilarityCandidate.algorithm_version == first.algorithm_version,
            SimilarityCandidate.model_a_id == fa.model_id,
            SimilarityCandidate.model_b_id == fb.model_id,
        )
        # Reverification retains the earlier observation. The latest recipe is
        # the cache candidate; old evidence must not hide a refreshed proof.
        .order_by(col(observation.id).desc())
        .limit(1)
    ).first()
    if encoded is None:
        return False
    try:
        evidence = json.loads(encoded)
    except ValueError:
        return False
    if (
        not isinstance(evidence, dict)
        or evidence.get("version") != VERIFICATION_VERSION
        or type(evidence.get("sample_points")) is not int
        or not evidence["sample_points"] <= 5000
    ):
        return False
    if evidence.get("exact_equivalence") is True:
        # More samples than requested can only tighten an exact proof.
        return sample_points <= evidence["sample_points"]
    # Seeded verification repeats itself for these inputs, so approximate
    # evidence is reused only for the very same sample count.
    return (
        evidence.get("evidence_class") is not None
        and sample_points == evidence["sample_points"]
    )


def known_empty(
    session: Session,
    first: GeometryFingerprint,
    second: GeometryFingerprint,
    *,
    sample_points: int,
    triangle_cap: int,
) -> bool:
    """These inputs were already verified, by this recipe, without evidence."""
    (id_a, hash_a), (id_b, hash_b) = _ordered(first, second)
    return (
        session.exec(
            select(SimilarityEmptyVerification.id).where(
                SimilarityEmptyVerification.fingerprint_a_id == id_a,
                SimilarityEmptyVerification.fingerprint_b_id == id_b,
                SimilarityEmptyVerification.input_hash_a == hash_a,
                SimilarityEmptyVerification.input_hash_b == hash_b,
                SimilarityEmptyVerification.verification_version
                == VERIFICATION_VERSION,
                SimilarityEmptyVerification.sample_points == sample_points,
                SimilarityEmptyVerification.triangle_cap == triangle_cap,
            )
        ).first()
        is not None
    )


def record_empty(
    session: Session,
    first: GeometryFingerprint,
    second: GeometryFingerprint,
    evidence: Verification,
    *,
    triangle_cap: int,
) -> None:
    """Remember a completed verification that produced no Evidence Class."""
    if evidence.evidence_class is not None:
        raise ValueError("similarity_verification_has_evidence")
    if evidence.version != VERIFICATION_VERSION:
        raise ValueError("similarity_verification_recipe_mismatch")
    (id_a, hash_a), (id_b, hash_b) = _ordered(first, second)
    row = SimilarityEmptyVerification(
        fingerprint_a_id=id_a,
        fingerprint_b_id=id_b,
        input_hash_a=hash_a,
        input_hash_b=hash_b,
        verification_version=VERIFICATION_VERSION,
        sample_points=evidence.sample_points,
        triangle_cap=triangle_cap,
    )
    try:
        with session.begin_nested():
            session.add(row)
    except IntegrityError:
        pass  # A concurrent run recorded the same outcome first.


def proven_exact_files(session: Session, first: File, second: File) -> bool:
    """Both whole files are exactly equivalent, so their Components are too.

    Component pairs between such files cannot change the Candidate: exact whole
    evidence has full confidence and outranks any composition summary.
    """
    if first.model_id > second.model_id:
        first, second = second, first
    observation = SimilarityCandidateObservation
    return (
        session.exec(
            select(observation.id)
            .join(
                SimilarityCandidate, SimilarityCandidate.id == observation.candidate_id
            )
            .join(
                GeometryFingerprint,
                GeometryFingerprint.id == observation.fingerprint_a_id,
            )
            .where(
                GeometryFingerprint.file_id == first.id,
                GeometryFingerprint.component_index == 0,
                observation.input_hash_a == first.sha256,
                observation.input_hash_b == second.sha256,
                observation.kind == "whole",
                SimilarityCandidate.model_a_id == first.model_id,
                SimilarityCandidate.model_b_id == second.model_id,
                col(SimilarityCandidate.exact_equivalence).is_(True),
                col(observation.fingerprint_b_id).in_(
                    select(GeometryFingerprint.id).where(
                        GeometryFingerprint.file_id == second.id,
                        GeometryFingerprint.component_index == 0,
                    )
                ),
            )
            .limit(1)
        ).first()
        is not None
    )


def _ordered(
    first: GeometryFingerprint, second: GeometryFingerprint
) -> tuple[tuple[int, str], tuple[int, str]]:
    """Each side's (id, source digest), lower fingerprint id first."""
    if first.id is None or second.id is None:
        raise ValueError("similarity_fingerprint_unsaved")
    sides = ((first.id, first.source_sha256), (second.id, second.source_sha256))
    return (sides[0], sides[1]) if sides[0][0] <= sides[1][0] else (sides[1], sides[0])
