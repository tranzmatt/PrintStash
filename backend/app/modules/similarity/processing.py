"""One durable unit of geometry work; runtime owns wakeups and maintenance drain."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext

from printstash_core.mesh.similarity import GeometryError, cloud
from sqlmodel import Session, col, func, select

from app.core.errors import OperationError
from app.db.models import (
    File,
    GeometryFingerprint,
    JobKind,
    SimilarityCandidate,
    SimilarityPairOutcome,
    SimilarityRun,
    SimilarityRunPair,
    User,
)
from app.db.session import SessionFactory
from app.modules.media import mesh_isolation, verification_isolation
from app.modules.media.fingerprints import FingerprintResult, FingerprintResultState
from app.modules.media.mesh_contracts import ThumbnailRequest
from app.modules.media.mesh_facts import FingerprintFailureCode
from app.modules.media.source_preparation import prepare_sources
from app.modules.similarity import (
    candidates,
    fingerprints,
    pairs,
    retrieval,
    runs,
    verification_cache,
)
from app.modules.similarity.configuration import SimilaritySettings, read_settings
from app.modules.storage import artifact_content
from app.modules.storage.storage_backend.contracts import StorageBackend
from app.modules.work.submission import nudge_after_commit
from app.runtime.native_admission import AdmissionTooLarge


class SimilarityProcessor:
    def __init__(
        self,
        sessions: SessionFactory,
        backend: StorageBackend,
        *,
        retain_storage: Callable[[], AbstractContextManager[None]] = nullcontext,
    ):
        self.sessions = sessions
        self.backend = backend
        self._retain_storage = retain_storage

    def work_one(self, run_id: int, writer: str) -> bool:
        """Advance one run by a mesh, shortlist or pair; ``False`` when it cannot.

        ``writer`` is the engine execution doing it: every write the unit
        makes is fenced on it. The checkpoint commits before this returns.
        While similarity is disabled a run only settles a cancellation.
        """
        with self.sessions.scoped_session() as session:
            enabled = read_settings(session).enabled
            run = runs.take(session, run_id, writer)
            if run is None or not (enabled or run.cancel_requested):
                return False
            token = writer
            if run.cancel_requested:
                runs.checkpoint(session, run, token, state="cancelled")
                return True
            actor = session.get(User, run.actor_id) if run.actor_id else None
            if actor is None or not actor.is_active:
                runs.checkpoint(
                    session,
                    run,
                    token,
                    state="failed",
                    failure_code="actor_unavailable",
                )
                return True
            try:
                runs.normalize_scope(
                    session, actor, run.scope, json.loads(run.scope_ids_json)
                )
            except OperationError:
                runs.checkpoint(
                    session,
                    run,
                    token,
                    state="failed",
                    failure_code="scope_permission_changed",
                )
                return True
            progress = json.loads(run.checkpoint_json)
            counters = json.loads(run.counters_json)
            config = SimilaritySettings.model_validate_json(run.settings_json)
            try:
                # Idle/cancellation bookkeeping never reads Artifact bytes.
                # Retain sources only after an authorized work unit is claimed.
                with self._retain_storage():
                    if run.phase == "fingerprint":
                        self._fingerprint(
                            session, run, token, actor, config, progress, counters
                        )
                    elif run.phase == "embeddings":
                        from app.modules.similarity import embeddings

                        embeddings.work_one(
                            self.sessions,
                            session,
                            self.backend,
                            actor,
                            run,
                            token,
                            config,
                            progress,
                            counters,
                        )
                    elif not self._candidates(
                        session, run, token, actor, config, progress, counters
                    ):
                        return False
            except OperationError as exc:
                if exc.kind.value in ("busy", "capacity", "unavailable"):
                    runs.checkpoint(session, run, token)
                    return False
                runs.checkpoint(
                    session,
                    run,
                    token,
                    state="failed",
                    failure_code=FingerprintFailureCode.ANALYSIS_UNAVAILABLE,
                )
            except Exception:
                session.rollback()
                # Native/parser error text may include paths. Retain only an
                # owner-defined failure code and the last committed checkpoint.
                runs.checkpoint(
                    session, run, token, state="failed", failure_code="analysis_failed"
                )
            return True

    def _fingerprint(
        self,
        session: Session,
        run: SimilarityRun,
        token: str,
        actor: User,
        config: SimilaritySettings,
        progress: dict,
        counters: dict,
    ) -> None:
        file = session.exec(
            runs.source_query(session, run, actor)
            .where(File.id > progress.get("file_id", 0))
            .limit(1)
        ).first()
        if file is None:
            runs.checkpoint(
                session,
                run,
                token,
                phase="embeddings" if config.embeddings_enabled else "candidates",
                progress={},
                counters=counters,
            )
            return
        claimed = fingerprints.claim(
            session, file, retry_incomplete=run.trigger == "manual"
        )
        if claimed is None:
            row = session.exec(
                select(GeometryFingerprint).where(
                    GeometryFingerprint.file_id == file.id,
                    GeometryFingerprint.component_index == 0,
                    GeometryFingerprint.source_sha256 == file.sha256,
                    GeometryFingerprint.algorithm_version == run.algorithm_version,
                )
            ).first()
            if row is None or row.state == "pending":
                runs.checkpoint(session, run, token)
                return
            counters["cached"] = counters.get("cached", 0) + 1
        else:
            try:
                try:
                    with prepare_sources(
                        (artifact_content.resolve(file, backend=self.backend),)
                    ) as (path,):
                        if fingerprints.source_digest(path) != file.sha256:
                            result = FingerprintResult(
                                FingerprintResultState.FAILED,
                                failure_code=FingerprintFailureCode.SOURCE_CHANGED,
                            )
                            metrics = None
                        else:
                            metrics = mesh_isolation.generate(
                                ThumbnailRequest(
                                    path=path,
                                    file_type=file.file_type.value,
                                    include_thumbnail=False,
                                    include_geometry=False,
                                    include_fingerprint=True,
                                    triangle_cap=config.triangle_cap,
                                    reason="similarity",
                                )
                            )
                            result = metrics.fingerprint_result or FingerprintResult(
                                FingerprintResultState.FAILED,
                                failure_code=FingerprintFailureCode.ANALYSIS_UNAVAILABLE,
                            )
                except artifact_content.ArtifactContentChangedError:
                    result, metrics = (
                        FingerprintResult(
                            FingerprintResultState.FAILED,
                            failure_code=FingerprintFailureCode.SOURCE_CHANGED,
                        ),
                        None,
                    )
                except (mesh_isolation.MeshWorkerError, AdmissionTooLarge) as exc:
                    # The worker died or was killed for this file's bytes. The run
                    # walks the whole library, so the file fails alone.
                    result, metrics = (
                        FingerprintResult(
                            FingerprintResultState.FAILED,
                            failure_code=(
                                FingerprintFailureCode.RESOURCE_LIMIT
                                if isinstance(exc, AdmissionTooLarge)
                                else FingerprintFailureCode(exc.reason.value)
                            ),
                        ),
                        None,
                    )
                except artifact_content.ArtifactContentError:
                    result, metrics = (
                        FingerprintResult(
                            FingerprintResultState.FAILED,
                            failure_code=FingerprintFailureCode.SOURCE_UNAVAILABLE,
                        ),
                        None,
                    )
                published = fingerprints.publish(
                    session,
                    file,
                    result,
                    fingerprint_id=claimed[0],
                    token=claimed[1],
                    duration_ms=metrics.duration_ms if metrics else None,
                    peak_rss_bytes=metrics.peak_rss_bytes if metrics else None,
                )
                state = result.state.value if published else "stale"
                counters[state] = counters.get(state, 0) + 1
            finally:
                fingerprints.release(session, claimed[0], claimed[1])
                session.commit()
        progress["file_id"] = file.id
        counters["artifacts_processed"] = counters.get("artifacts_processed", 0) + 1
        runs.checkpoint(session, run, token, progress=progress, counters=counters)

    def _candidates(
        self,
        session: Session,
        run: SimilarityRun,
        token: str,
        actor: User,
        config: SimilaritySettings,
        progress: dict,
        counters: dict,
    ) -> bool:
        """Shortlist one fingerprint, else verify one queued pair; ``False`` waits.

        Shortlists queue their pairs for any verifier. Once every source is
        shortlisted this execution verifies too, and the run completes when no
        pair is left. Pairs other verifiers still hold make it wait for them.
        """
        assert run.id is not None
        legacy = progress.pop("pending_pairs", None)
        if legacy is not None:
            # Checkpointed before pairs were rows: queue what the run still owed,
            # keeping the counts its earlier units made.
            cleared = frozenset(progress.pop("cloud_cleared", ()))
            progress["legacy_counters"] = {
                name: counters.get(name, 0) for name in pairs.COUNTERS
            }
            pairs.enqueue(
                session,
                run.id,
                [(source, target) for source, target in legacy],
                cloud_cleared=cleared,
            )
            session.commit()
        sources = (
            runs.source_query(session, run, actor)
            .with_only_columns(col(File.id))
            .order_by(None)
        )
        row = session.exec(
            select(GeometryFingerprint)
            .where(
                col(GeometryFingerprint.file_id).in_(sources),
                GeometryFingerprint.id > progress.get("fingerprint_id", 0),
                GeometryFingerprint.algorithm_version == run.algorithm_version,
                col(GeometryFingerprint.state).in_(("ready", "partial")),
                fingerprints.distinct_shape(),
                # A source edit during fingerprinting cannot contribute old rows.
                col(GeometryFingerprint.source_sha256).in_(
                    select(File.sha256).where(File.id == GeometryFingerprint.file_id)
                ),
            )
            .order_by(col(GeometryFingerprint.id))
            .limit(1)
        ).first()
        if row is not None:
            self._shortlist(session, run, actor, config, row, progress, counters)
            runs.checkpoint(session, run, token, progress=progress, counters=counters)
            return True
        moved = self._verify_next(session, run, actor, config)
        if not moved and not pairs.pending(session, run.id):
            # Many observations can refine one Candidate; report the Candidates.
            counters["candidates"] = session.exec(
                select(func.count())
                .select_from(SimilarityCandidate)
                .where(SimilarityCandidate.run_id == run.id)
            ).one()
            _count_pairs(session, run, progress, counters)
            runs.checkpoint(session, run, token, state="completed", counters=counters)
            return True
        _count_pairs(session, run, progress, counters)
        runs.checkpoint(session, run, token, progress=progress, counters=counters)
        return moved

    def _shortlist(
        self,
        session: Session,
        run: SimilarityRun,
        actor: User,
        config: SimilaritySettings,
        row: GeometryFingerprint,
        progress: dict,
        counters: dict,
    ) -> None:
        shortlist = retrieval.find_candidates(
            session, row, actor, limit=config.max_candidates
        )
        if config.embeddings_enabled:
            from app.modules.similarity.learned_retrieval import extend

            shortlist = extend(
                session, self.sessions, actor, row, shortlist, config.max_candidates
            )
        assert run.id is not None and row.id is not None
        if pairs.enqueue(
            session,
            run.id,
            [(row.id, target) for target in shortlist.fingerprint_ids],
            cloud_cleared=shortlist.cloud_cleared,
        ):
            nudge_after_commit(session, JobKind.SIMILARITY_VERIFY)
        progress["fingerprint_id"] = row.id
        progress["shortlist_rejected_by_cloud"] = (
            progress.get("shortlist_rejected_by_cloud", 0) + shortlist.rejected_by_cloud
        )
        counters["shortlisted"] = counters.get("shortlisted", 0) + len(
            shortlist.fingerprint_ids
        )
        counters["skipped_by_budget"] = (
            counters.get("skipped_by_budget", 0) + shortlist.skipped_by_budget
        )
        _count_pairs(session, run, progress, counters)

    def verify_one(self, run_id: int) -> bool:
        """Verify one queued pair of the run; ``False`` when none can be.

        A ``similarity.verify`` Job calls this beside the run's own analysis
        execution. It never fails the run: an actor or permission that changed
        stops it here, and the analysis execution settles the run.
        """
        with self.sessions.scoped_session() as session:
            run = session.get(SimilarityRun, run_id)
            if (
                not read_settings(session).enabled
                or run is None
                or run.state in runs.TERMINAL
                or run.cancel_requested
                or run.phase != "candidates"
            ):
                return False
            actor = session.get(User, run.actor_id) if run.actor_id else None
            if actor is None or not actor.is_active:
                return False
            config = SimilaritySettings.model_validate_json(run.settings_json)
            try:
                runs.normalize_scope(
                    session, actor, run.scope, json.loads(run.scope_ids_json)
                )
                with self._retain_storage():
                    return self._verify_next(session, run, actor, config)
            except OperationError:
                return False

    def _verify_next(
        self,
        session: Session,
        run: SimilarityRun,
        actor: User,
        config: SimilaritySettings,
    ) -> bool:
        """Lease one pending pair, verify it and settle its outcome."""
        assert run.id is not None
        claimed = pairs.claim(session, run.id)
        if claimed is None:
            return False
        pair, token = claimed
        assert pair.id is not None
        try:
            outcome = self._verify_pair(session, run, actor, config, pair, token)
        except OperationError:
            # Capacity or permission: hand the pair back for a later attempt.
            session.rollback()
            pairs.release(session, pair.id, token)
            session.commit()
            raise
        except Exception:
            # The lease expires and the pair is verified again.
            session.rollback()
            raise
        pairs.settle(session, pair.id, token, outcome)
        session.commit()
        return True

    def _verify_pair(
        self,
        session: Session,
        run: SimilarityRun,
        actor: User,
        config: SimilaritySettings,
        pair: SimilarityRunPair,
        token: str,
    ) -> SimilarityPairOutcome:
        Outcome = SimilarityPairOutcome
        first, second = (
            session.get(GeometryFingerprint, value)
            for value in (pair.fingerprint_a_id, pair.fingerprint_b_id)
        )
        if first is None or second is None:
            return Outcome.SKIPPED
        fa, fb = session.get(File, first.file_id), session.get(File, second.file_id)
        if fa is None or fb is None or fa.model_id == fb.model_id:
            return Outcome.SKIPPED
        if fa.model_id > fb.model_id:
            first, second, fa, fb = second, first, fb, fa
        for file, fp in ((fa, first), (fb, second)):
            if not fingerprints.current_source(session, fp.file_id, fp.source_sha256):
                return Outcome.STALE
            runs.normalize_scope(session, actor, "models", [file.model_id])
        # Neither shortcut publishes evidence, so neither needs source bytes.
        if (first.component_index or second.component_index) and (
            verification_cache.proven_exact_files(session, fa, fb)
        ):
            return Outcome.IMPLIED_BY_WHOLE
        if verification_cache.known_empty(
            session,
            first,
            second,
            sample_points=config.sample_points,
            triangle_cap=config.triangle_cap,
        ):
            return Outcome.VERIFICATION_CACHED
        # Retrieval already measured a cleared pair; learned proposals were not.
        if (
            not pair.cloud_cleared
            and first.cloud_blob is not None
            and second.cloud_blob is not None
            and cloud.rejects(
                cloud.SurfaceCloud.decode(first.cloud_blob),
                cloud.SurfaceCloud.decode(second.cloud_blob),
            )
        ):
            return Outcome.REJECTED_BY_CLOUD
        try:
            with prepare_sources(
                tuple(
                    artifact_content.resolve(file, backend=self.backend)
                    for file in (fa, fb)
                )
            ) as (path_a, path_b):
                if (
                    fingerprints.source_digest(path_a) != first.source_sha256
                    or fingerprints.source_digest(path_b) != second.source_sha256
                ):
                    return Outcome.STALE
                if verification_cache.reusable_pair(
                    session, first, second, sample_points=config.sample_points
                ):
                    return Outcome.VERIFICATION_CACHED
                evidence = verification_isolation.verify_paths(
                    path_a,
                    path_b,
                    first_type=fa.file_type.value,
                    second_type=fb.file_type.value,
                    first_component=first.component_index,
                    second_component=second.component_index,
                    sample_points=config.sample_points,
                    triangle_cap=config.triangle_cap,
                )
        except (
            GeometryError,
            AdmissionTooLarge,
            mesh_isolation.MeshWorkerError,
            artifact_content.ArtifactContentError,
        ):
            # A worker killed for this pair's bytes fails the pair, not the run.
            return Outcome.VERIFICATION_FAILED
        if evidence.evidence_class is None:
            verification_cache.record_empty(
                session, first, second, evidence, triangle_cap=config.triangle_cap
            )
            return Outcome.VERIFIED
        # Persist measured evidence independently of review thresholds. Changing
        # a slider selects durable candidates without repeating geometry work.
        kind = (
            "component_match"
            if first.component_index or second.component_index
            else "whole"
        )
        assert pair.id is not None
        candidate = candidates.publish(
            session,
            first,
            second,
            evidence,
            run=run,
            pair_lease=(pair.id, token),
            kind=kind,
        )
        if candidate is not None and candidate.confidence > 0:
            return Outcome.OBSERVED
        return Outcome.VERIFIED


def _count_pairs(
    session: Session, run: SimilarityRun, progress: dict, counters: dict
) -> None:
    """Refresh the counters that the run's pair outcomes own."""
    assert run.id is not None
    measured = pairs.counters(session, run.id)
    measured["rejected_by_cloud"] += progress.get("shortlist_rejected_by_cloud", 0)
    for name, value in measured.items():
        total = value + progress.get("legacy_counters", {}).get(name, 0)
        if total:
            counters[name] = total
        else:
            counters.pop(name, None)
