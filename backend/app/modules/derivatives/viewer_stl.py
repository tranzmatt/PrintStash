"""On-demand STL previews: durable demand and production in a supervised Job."""

from __future__ import annotations

import secrets
import tempfile
import time
from pathlib import Path

from sqlmodel import Session

from app.core.time import utcnow
from app.db.models import DerivativeKind, DerivativeState, File, JobKind
from app.db.session import get_session_factory
from app.modules.media import stl_isolation
from app.modules.media.mesh_isolation import MeshWorkerError
from app.modules.media.thumbnail_engine import ThumbnailFailureReason
from app.modules.storage.artifact_content import ArtifactContentError, resolve
from app.modules.storage.capacity import CapacityManager, CapacityResource
from app.modules.storage.capacity_estimates import vault_allocation
from app.modules.storage.storage_backend.contracts import StorageCollisionError
from app.modules.storage.storage_backend.runtime import get_backend
from app.modules.storage.storage_ownership import publish_bytes

from . import policy, records
from .kinds import VIEWER_STL_RECIPE


def request(session: Session, file: File) -> None:
    """Persist demand once; polling never resets a failure or starts native work."""
    from app.modules.work import nudge

    policy.lock(session)
    policy.require_enabled(session, JobKind.DERIVATIVES_VIEWER_STL)
    session.refresh(file)
    if file.viewer_requested_at is None:
        file.viewer_requested_at = utcnow()
        session.add(file)
    session.commit()
    if records.needed(
        session, file, {DerivativeKind.VIEWER_STL: VIEWER_STL_RECIPE}, now=utcnow()
    ):
        nudge(JobKind.DERIVATIVES_VIEWER_STL)


def produce(file_id: int):
    from .producers import Outcome, _begin, _fail, _live_file, _row

    begun = _begin(file_id, JobKind.DERIVATIVES_VIEWER_STL)
    if begun is None or DerivativeKind.VIEWER_STL not in begun[1]:
        return Outcome({})
    file, _needed = begun
    started = time.monotonic()

    def failed(reason: ThumbnailFailureReason, *, deterministic: bool) -> Outcome:
        _fail(
            file_id,
            DerivativeKind.VIEWER_STL,
            VIEWER_STL_RECIPE,
            reason.value,
            deterministic=deterministic,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return Outcome({DerivativeKind.VIEWER_STL: DerivativeState.FAILED})

    estimate = max(file.size_bytes * 3, 16 * 1024**2)
    try:
        with CapacityManager(get_session_factory()).hold(
            f"derive:viewer-stl:{file_id}:{time.monotonic_ns()}",
            [
                CapacityResource.for_path(
                    Path(tempfile.gettempdir()), estimate, role="mesh conversion"
                ),
                vault_allocation(estimate, role="derived STL publication"),
            ],
        ):
            with resolve(file).materialize(capacity_claimed=True) as source:
                data = stl_isolation.to_stl_bytes(
                    source, file_type=file.file_type.value
                )
            if data is None:
                return failed(ThumbnailFailureReason.INVALID_SOURCE, deterministic=True)
            backend = get_backend()
            key = backend.blob_key(
                "_derivatives",
                0,
                f"{file.sha256}-viewer-stl-r{VIEWER_STL_RECIPE}-{secrets.token_hex(12)}.stl",
            )
            with get_session_factory().scoped_session() as session:
                _live_file(session, file_id)
                receipt = publish_bytes(
                    session, backend, key, data, object_kind="viewer_stl"
                )
                records.mark_ready(
                    session,
                    _row(
                        session, file_id, DerivativeKind.VIEWER_STL, VIEWER_STL_RECIPE
                    ),
                    now=utcnow(),
                    storage_key=receipt.key,
                    output={"size": receipt.size},
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
                session.commit()
    except MeshWorkerError as exc:
        return failed(
            exc.reason,
            deterministic=exc.reason
            in {
                ThumbnailFailureReason.RESOURCE_LIMIT,
                ThumbnailFailureReason.INVALID_SOURCE,
                ThumbnailFailureReason.UNSUPPORTED_FORMAT,
                ThumbnailFailureReason.NO_GEOMETRY,
            },
        )
    except ArtifactContentError:
        return failed(ThumbnailFailureReason.INVALID_SOURCE, deterministic=True)
    except (OSError, StorageCollisionError):
        return failed(ThumbnailFailureReason.STORAGE, deterministic=False)
    return Outcome({DerivativeKind.VIEWER_STL: DerivativeState.READY})
