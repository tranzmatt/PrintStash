"""A run's queued pairs: each verified once, by whichever verifier holds its lease.

Several verifiers share one run's pairs. A lease keeps two of them off one
pair, a lost lease can no longer settle it, and a pair whose verifier died is
claimed again once its lease expires. Outcomes add up to the run's counters,
and a finished run drops its pairs.
"""

from datetime import timedelta

import pytest
from sqlmodel import select

from app.core.time import ensure_utc, utcnow
from app.db.models import GeometryFingerprint, SimilarityPairOutcome, SimilarityRunPair
from app.modules.similarity import pairs, runs

Outcome = SimilarityPairOutcome
WRITER = "job:1"


@pytest.fixture
def run(make_user, make_similarity_run):
    return make_similarity_run(
        make_user(superuser=True), state="running", writer=WRITER
    )


@pytest.fixture
def fingerprint(make_model, make_file, make_geometry_fingerprint):
    def make():
        return make_geometry_fingerprint(make_file(make_model()), state="ready").id

    return make


@pytest.fixture
def queued(db_session, run, fingerprint):
    """Two pairs queued on the run, oldest first."""
    ids = [fingerprint() for _ in range(3)]
    pairs.enqueue(db_session, run.id, [(ids[0], ids[1]), (ids[0], ids[2])])
    db_session.commit()
    return db_session.exec(
        select(SimilarityRunPair).order_by(SimilarityRunPair.id)
    ).all()


def reread(db_session, pair):
    db_session.expire_all()
    return db_session.get(SimilarityRunPair, pair.id)


class TestEnqueue:
    def test_stores_a_pair_in_fingerprint_order(self, db_session, run, fingerprint):
        first, second = fingerprint(), fingerprint()

        pairs.enqueue(db_session, run.id, [(second, first)])
        db_session.commit()

        row = db_session.exec(select(SimilarityRunPair)).one()
        assert (row.fingerprint_a_id, row.fingerprint_b_id) == (first, second)

    def test_marks_only_cleared_targets(self, db_session, run, fingerprint):
        source, cleared, other = fingerprint(), fingerprint(), fingerprint()

        pairs.enqueue(
            db_session,
            run.id,
            [(source, cleared), (source, other)],
            cloud_cleared=frozenset({cleared}),
        )
        db_session.commit()

        rows = db_session.exec(select(SimilarityRunPair)).all()
        assert {row.fingerprint_b_id: row.cloud_cleared for row in rows} == {
            cleared: True,
            other: False,
        }

    def test_counts_only_new_pairs(self, db_session, run, fingerprint):
        first, second = fingerprint(), fingerprint()
        pairs.enqueue(db_session, run.id, [(first, second)])

        assert pairs.enqueue(db_session, run.id, [(second, first)]) == 0

    def test_drops_a_pair_whose_fingerprint_is_deleted(self, db_session, run, queued):
        db_session.delete(
            db_session.get(GeometryFingerprint, queued[0].fingerprint_b_id)
        )
        db_session.commit()

        assert [row.id for row in db_session.exec(select(SimilarityRunPair))] == [
            queued[1].id
        ]


class TestClaim:
    def test_leases_the_oldest_pending_pair(self, db_session, run, queued):
        pair, token = pairs.claim(db_session, run.id)

        assert (pair.id, reread(db_session, pair).lease_token) == (queued[0].id, token)

    def test_skips_a_pair_another_verifier_holds(self, db_session, run, queued):
        pairs.claim(db_session, run.id)

        second, _ = pairs.claim(db_session, run.id)

        assert second.id == queued[1].id

    def test_takes_back_a_pair_whose_lease_expired(self, db_session, run, queued):
        held, _ = pairs.claim(db_session, run.id)
        held.lease_expires_at = utcnow() - timedelta(seconds=1)
        db_session.add(held)
        db_session.commit()

        again, _ = pairs.claim(db_session, run.id)

        assert again.id == held.id

    def test_skips_a_settled_pair(self, db_session, run, queued):
        pair, token = pairs.claim(db_session, run.id)
        pairs.settle(db_session, pair.id, token, Outcome.VERIFIED)
        db_session.commit()

        assert pairs.claim(db_session, run.id)[0].id == queued[1].id

    def test_finds_nothing_once_every_pair_is_held(self, db_session, run, queued):
        pairs.claim(db_session, run.id)
        pairs.claim(db_session, run.id)

        assert pairs.claim(db_session, run.id) is None

    def test_leases_for_longer_than_a_worker_may_run(self, db_session, run, queued):
        from app.core.config import settings

        pair, _ = pairs.claim(db_session, run.id)

        remaining = ensure_utc(reread(db_session, pair).lease_expires_at) - utcnow()
        assert remaining > timedelta(seconds=settings.mesh_worker_timeout_seconds)


class TestSettle:
    def test_records_the_outcome_under_its_lease(self, db_session, run, queued):
        pair, token = pairs.claim(db_session, run.id)

        assert pairs.settle(db_session, pair.id, token, Outcome.OBSERVED)
        db_session.commit()

        settled = reread(db_session, pair)
        assert (settled.outcome, settled.lease_token) == (Outcome.OBSERVED, None)

    def test_a_lost_lease_cannot_settle(self, db_session, run, queued):
        pair, token = pairs.claim(db_session, run.id)
        pair.lease_token = "successor"
        db_session.add(pair)
        db_session.commit()

        assert not pairs.settle(db_session, pair.id, token, Outcome.VERIFIED)
        assert reread(db_session, pair).outcome is Outcome.PENDING

    def test_refuses_pending_as_an_outcome(self, db_session, run, queued):
        pair, token = pairs.claim(db_session, run.id)

        with pytest.raises(ValueError, match="pending_is_not_an_outcome"):
            pairs.settle(db_session, pair.id, token, Outcome.PENDING)

    def test_a_released_pair_is_claimable_again(self, db_session, run, queued):
        pair, token = pairs.claim(db_session, run.id)
        pairs.claim(db_session, run.id)

        pairs.release(db_session, pair.id, token)
        db_session.commit()

        assert pairs.claim(db_session, run.id)[0].id == pair.id


class TestCounters:
    def test_adds_up_the_outcomes(self, db_session, run, fingerprint):
        source = fingerprint()
        outcomes = [
            Outcome.VERIFIED,
            Outcome.OBSERVED,
            Outcome.REJECTED_BY_CLOUD,
            Outcome.STALE,
            Outcome.PENDING,
        ]
        pairs.enqueue(db_session, run.id, [(source, fingerprint()) for _ in outcomes])
        db_session.commit()
        for row, outcome in zip(
            db_session.exec(select(SimilarityRunPair).order_by(SimilarityRunPair.id)),
            outcomes,
            strict=True,
        ):
            row.outcome = outcome
            db_session.add(row)
        db_session.commit()

        assert pairs.counters(db_session, run.id) == {
            "verified": 2,
            "observations": 1,
            "verification_cached": 0,
            "rejected_by_cloud": 1,
            "implied_by_whole": 0,
            "stale": 1,
            "verification_failed": 0,
        }

    def test_counts_pending_pairs(self, db_session, run, queued):
        pair, token = pairs.claim(db_session, run.id)
        pairs.settle(db_session, pair.id, token, Outcome.VERIFIED)
        db_session.commit()

        assert pairs.pending(db_session, run.id) == 1


class TestDiscard:
    def test_a_finished_run_drops_its_pairs(self, db_session, run, queued):
        runs.checkpoint(db_session, run, WRITER, state="completed")

        assert db_session.exec(select(SimilarityRunPair)).all() == []

    def test_a_running_checkpoint_keeps_them(self, db_session, run, queued):
        runs.checkpoint(db_session, run, WRITER)

        assert len(db_session.exec(select(SimilarityRunPair)).all()) == 2
