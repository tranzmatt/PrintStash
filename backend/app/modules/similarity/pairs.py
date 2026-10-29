"""A run's shortlisted pairs: queued by shortlisting, leased and settled by verifiers.

Shortlisting one fingerprint takes well under a second; verifying one pair takes
seconds. Pairs are rows so any number of verifiers (the run's own analysis
execution and its ``similarity.verify`` Jobs) share them: a verifier leases one
pair, verifies it, and settles its outcome under that lease. A lease outlives a
worker's own timeout, so only a verifier that died leaves a pair to expire and
be claimed again. Outcomes become run counters; the terminal checkpoint deletes
the rows.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable
from datetime import timedelta

from sqlalchemy import delete, func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.time import utcnow
from app.db.models import SimilarityPairOutcome, SimilarityRunPair

Outcome = SimilarityPairOutcome

# The counters a run reports from its pairs' outcomes, and which outcomes each
# one counts. ``verified`` counts every measured pair, as it always has.
COUNTERS: dict[str, tuple[Outcome, ...]] = {
    "verified": (Outcome.VERIFIED, Outcome.OBSERVED),
    "observations": (Outcome.OBSERVED,),
    "verification_cached": (Outcome.VERIFICATION_CACHED,),
    "rejected_by_cloud": (Outcome.REJECTED_BY_CLOUD,),
    "implied_by_whole": (Outcome.IMPLIED_BY_WHOLE,),
    "stale": (Outcome.STALE,),
    "verification_failed": (Outcome.VERIFICATION_FAILED,),
}


def lease_seconds() -> int:
    """Longer than a verification worker may run, plus its admission wait."""
    return 2 * settings.mesh_worker_timeout_seconds + 60


def enqueue(
    session: Session,
    run_id: int,
    pairs: Iterable[tuple[int, int]],
    *,
    cloud_cleared: frozenset[int] = frozenset(),
) -> int:
    """Queue each ``(source, target)`` once per run, whichever side shortlisted it.

    ``cloud_cleared`` names targets whose clouds retrieval already measured.
    Returns how many pairs were new. The caller commits.
    """
    added = 0
    for source, target in pairs:
        first, second = sorted((source, target))
        try:
            with session.begin_nested():
                session.add(
                    SimilarityRunPair(
                        run_id=run_id,
                        fingerprint_a_id=first,
                        fingerprint_b_id=second,
                        cloud_cleared=target in cloud_cleared,
                    )
                )
                session.flush()
        except IntegrityError:
            continue  # Already queued from the other side.
        added += 1
    return added


def claim(session: Session, run_id: int) -> tuple[SimilarityRunPair, str] | None:
    """Lease the oldest unleased pending pair of the run; commits the lease."""
    for _ in range(8):
        now = utcnow()
        claimable = (
            col(SimilarityRunPair.run_id) == run_id,
            col(SimilarityRunPair.outcome) == Outcome.PENDING,
            or_(
                col(SimilarityRunPair.lease_expires_at).is_(None),
                col(SimilarityRunPair.lease_expires_at) <= now,
            ),
        )
        pair_id = session.exec(
            select(SimilarityRunPair.id)
            .where(*claimable)
            .order_by(col(SimilarityRunPair.id))
            .limit(1)
        ).first()
        if pair_id is None:
            return None
        token = secrets.token_hex(32)
        changed = session.connection().execute(
            update(SimilarityRunPair)
            .where(col(SimilarityRunPair.id) == pair_id, *claimable)
            .values(
                lease_token=token,
                lease_expires_at=now + timedelta(seconds=lease_seconds()),
            )
        )
        session.commit()
        if changed.rowcount == 1:
            pair = session.get(SimilarityRunPair, pair_id)
            assert pair is not None
            session.refresh(pair)
            return pair, token
    return None  # Every attempt lost a race; the caller tries again later.


def held(pair_id: int, token: str):
    """SQL truth that ``token`` still holds the pending pair: the publication fence."""
    return (
        select(SimilarityRunPair.id)
        .where(
            col(SimilarityRunPair.id) == pair_id,
            col(SimilarityRunPair.lease_token) == token,
            col(SimilarityRunPair.outcome) == Outcome.PENDING,
        )
        .exists()
    )


def settle(session: Session, pair_id: int, token: str, outcome: Outcome) -> bool:
    """Record the outcome while the lease is still held; the caller commits."""
    if outcome is Outcome.PENDING:
        raise ValueError("pending_is_not_an_outcome")
    changed = session.connection().execute(
        update(SimilarityRunPair)
        .where(
            col(SimilarityRunPair.id) == pair_id,
            col(SimilarityRunPair.lease_token) == token,
            col(SimilarityRunPair.outcome) == Outcome.PENDING,
        )
        .values(outcome=outcome, lease_token=None, lease_expires_at=None)
    )
    return changed.rowcount == 1


def release(session: Session, pair_id: int, token: str) -> None:
    """Hand an unfinished pair back (capacity was busy); the caller commits."""
    session.connection().execute(
        update(SimilarityRunPair)
        .where(
            col(SimilarityRunPair.id) == pair_id,
            col(SimilarityRunPair.lease_token) == token,
            col(SimilarityRunPair.outcome) == Outcome.PENDING,
        )
        .values(lease_token=None, lease_expires_at=None)
    )


def pending(session: Session, run_id: int) -> int:
    return session.exec(
        select(func.count())
        .select_from(SimilarityRunPair)
        .where(
            col(SimilarityRunPair.run_id) == run_id,
            col(SimilarityRunPair.outcome) == Outcome.PENDING,
        )
    ).one()


def counters(session: Session, run_id: int) -> dict[str, int]:
    """The run counters its pairs' outcomes add up to, zeros included."""
    by_outcome = {
        outcome: count
        for outcome, count in session.exec(
            select(SimilarityRunPair.outcome, func.count())
            .where(col(SimilarityRunPair.run_id) == run_id)
            .group_by(col(SimilarityRunPair.outcome))
        ).all()
    }
    return {
        name: sum(by_outcome.get(outcome, 0) for outcome in outcomes)
        for name, outcomes in COUNTERS.items()
    }


def discard(session: Session, run_id: int) -> None:
    """Drop a finished run's pairs; the caller commits."""
    session.connection().execute(
        delete(SimilarityRunPair).where(col(SimilarityRunPair.run_id) == run_id)
    )
