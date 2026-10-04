"""Single orchestration seam for mesh thumbnail generation.

The engine owns strategy selection and resource cleanup. Persistence remains a
separate concern because thumbnails are retryable derivatives of committed
Artifacts.
"""

from __future__ import annotations

import resource
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from printstash_core.mesh.measurements import (
    InvalidMeshMeasurements,
    VolumeNotCalculated,
    VolumeNotCalculatedCause,
    validate_geometry_extents,
)
from printstash_core.mesh.similarity import GeometryError
from printstash_core.mesh.similarity.budgets import MAX_ANALYSIS_FACES

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.media import (
    mesh_loading,
    mesh_measurements,
    mesh_policy,
    mesh_previews,
    mesh_render,
    stl_fallback,
    stl_streaming,
)
from app.modules.media.fingerprints import (
    FingerprintResult,
    FingerprintResultState,
    extract,
)
from app.modules.media.mesh_contracts import (
    Geometry,
    GeometryNotLoaded,
    GeometryNotRequested,
    GeometryOutcome,
    GeometryReady,
    GeometryRefused,
    GeometryRepresentation,
    MeshCoverage,
    PreviewCoverage,
    SourceScanState,
    ThumbnailFailureReason,
    ThumbnailMetricsSink,
    ThumbnailRequest,
    ThumbnailResult,
    ThumbnailStrategy,
)
from app.modules.media.mesh_facts import (
    CompleteGeometry,
    FingerprintFailureCode,
    SampledGeometry,
)
from app.modules.media.mesh_resources import (
    ExpandedScene,
    PreparedMesh,
    load_3mf,
    prepare_loaded_mesh,
)
from app.modules.media.mesh_telemetry import (
    MeshPhase,
    PhaseOutcome,
    PhaseRecorder,
)
from app.modules.media.stl_reader import InvalidSTL, STLReadFailure, scan_stl

if TYPE_CHECKING:
    from trimesh import Trimesh

logger = get_logger(__name__)


class NoopThumbnailMetrics:
    def increment(self, name: str, *, labels: dict[str, str]) -> None:
        del name, labels

    def observe(self, name: str, value: float, *, labels: dict[str, str]) -> None:
        del name, value, labels


def _empty_geometry() -> Geometry:
    return {
        "bbox_x_mm": None,
        "bbox_y_mm": None,
        "bbox_z_mm": None,
        "volume_mm3": None,
        "triangle_count": None,
    }


def _peak_rss_bytes() -> int | None:
    try:
        # Linux reports KiB; macOS reports bytes. The supported server images
        # are Linux, while the conservative branch keeps local development sane.
        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value * 1024 if value < 1 << 40 else value
    except (OSError, ValueError):
        return None


def _prepare_sampled_stl(
    path: Path, *, triangle_cap: int
) -> tuple[PreparedMesh, SourceScanState] | None:
    """Keep sample buffers within one lifetime, including construction failures."""
    import numpy as np
    import trimesh

    sampled = stl_fallback.sample_stl_geometry(
        path, max_triangles=min(10_000, triangle_cap)
    )
    if sampled is None or not sampled.sampled_triangles:
        return None
    points = np.array(sampled.coordinates, dtype=np.float64).reshape((-1, 3))
    mesh = trimesh.Trimesh(
        vertices=points,
        faces=np.arange(len(points)).reshape((-1, 3)),
        process=False,
    )
    prepared = PreparedMesh(
        mesh,
        ExpandedScene((), ()),
        geometry=SampledGeometry(FingerprintFailureCode.SAMPLED_SOURCE),
    )
    return prepared, (
        SourceScanState.COMPLETE if sampled.complete else SourceScanState.PARTIAL
    )


@dataclass
class ThumbnailEngine:
    metrics: ThumbnailMetricsSink = field(default_factory=NoopThumbnailMetrics)

    def generate(self, request: ThumbnailRequest) -> ThumbnailResult:
        started = time.monotonic()
        phases = PhaseRecorder()
        try:
            source_bytes = request.path.stat().st_size
        except OSError:
            source_bytes = None
        width = int(request.width or settings.model_thumbnail_width)
        height = int(request.height or round(width * 3 / 4))
        suffix = mesh_policy.canonical_suffix(request.path, request.file_type)
        geometry = _empty_geometry()
        volume = VolumeNotCalculated(
            VolumeNotCalculatedCause.GEOMETRY_UNAVAILABLE
            if request.include_geometry
            else VolumeNotCalculatedCause.NOT_REQUESTED
        )
        geometry_outcome: GeometryOutcome = (
            GeometryRefused(ThumbnailFailureReason.INVALID_SOURCE)
            if request.include_geometry
            else GeometryNotRequested()
        )
        strategy = ThumbnailStrategy.NONE
        source_scan = SourceScanState.NOT_SCANNED
        geometry_representation: GeometryRepresentation = GeometryNotLoaded()
        preview_coverage = PreviewCoverage.NOT_PRODUCED
        failure: ThumbnailFailureReason | None = None
        image: bytes | None = None
        mesh: Trimesh | None = None
        prepared: PreparedMesh | None = None
        fingerprint_result: FingerprintResult | None = None
        sample_buffers_pending = False

        def report(label: str) -> None:
            if request.report is not None:
                request.report(label)

        if (
            type(request.triangle_cap) is not int
            or not 100 <= request.triangle_cap <= MAX_ANALYSIS_FACES
        ):
            raise ValueError("invalid_triangle_cap")
        phases.start(MeshPhase.ADMISSION, input_bytes=source_bytes)
        report("loading_mesh")
        if request.file_type is None:
            over_cap = mesh_policy.exceeds_cap(request.path)
        else:
            over_cap = mesh_policy.exceeds_cap(request.path, file_type=suffix)
        phases.finish()

        if over_cap and request.include_geometry:
            geometry_outcome = GeometryRefused(ThumbnailFailureReason.RESOURCE_LIMIT)

        embedded = None
        try:
            with mesh_policy.render_admission():
                if (
                    request.include_thumbnail
                    and suffix == ".3mf"
                    and (
                        not over_cap
                        or settings.use_embedded_3mf_preview_for_large_files
                    )
                ):
                    phases.start(MeshPhase.EMBEDDED, input_bytes=source_bytes)
                    embedded = mesh_previews.extract_embedded_3mf_thumbnail(
                        request.path,
                        validate_image=True,
                        file_type=suffix if request.file_type is not None else None,
                    )

                    phases.finish(
                        output_bytes=len(embedded) if embedded is not None else None
                    )

                # A thumbnail-only repair can return a validated embedded image
                # without parsing the mesh archive. Ingestion still loads safe
                # meshes once because it also needs exact geometry metadata.
                if (
                    embedded is not None
                    and not request.include_geometry
                    and not request.include_fingerprint
                ):
                    image = embedded
                    strategy = ThumbnailStrategy.EMBEDDED
                    preview_coverage = PreviewCoverage.DOCUMENT_SUPPLIED
                else:
                    if not over_cap:
                        phases.start(MeshPhase.LOAD, input_bytes=source_bytes)
                        if suffix == ".3mf":
                            # The ZIP-size estimate cannot account for repeated
                            # build/component instances. Trimesh expands those
                            # placements while loading and can exhaust the API
                            # process before the post-load face cap runs (#259).
                            # The resource loader counts expanded faces before
                            # composing a mesh and bounds XML parsing too.
                            face_cap = mesh_policy.load_face_budget(suffix)
                            try:
                                prepared = load_3mf(request.path, max_faces=face_cap)
                                mesh = prepared.whole_mesh
                            except GeometryError as exc:
                                if exc.code in {
                                    "archive_resource_limit",
                                    "resource_limit",
                                    "scene_resource_limit",
                                }:
                                    over_cap = True
                                if request.include_geometry:
                                    geometry_outcome = GeometryRefused(
                                        ThumbnailFailureReason.RESOURCE_LIMIT
                                        if over_cap
                                        else ThumbnailFailureReason.INVALID_SOURCE
                                    )
                                if request.include_fingerprint:
                                    fingerprint_result = FingerprintResult(
                                        FingerprintResultState.FAILED,
                                        failure_code=FingerprintFailureCode(exc.code),
                                    )
                        elif request.include_fingerprint and suffix in (
                            ".step",
                            ".stp",
                        ):
                            try:
                                mesh = mesh_loading.load_step_mesh(
                                    request.path, include_brep=True
                                )
                            except GeometryError as exc:
                                if request.include_geometry:
                                    geometry_outcome = GeometryRefused(
                                        ThumbnailFailureReason.UNSUPPORTED_FORMAT
                                        if exc.code == "step_unavailable"
                                        else ThumbnailFailureReason.TIMEOUT
                                        if exc.code == "tessellation_timeout"
                                        else ThumbnailFailureReason.RESOURCE_LIMIT
                                        if exc.code
                                        in {"worker_oom", "geometry_work_limit"}
                                        else ThumbnailFailureReason.INVALID_SOURCE
                                    )
                                fingerprint_result = FingerprintResult(
                                    FingerprintResultState.UNSUPPORTED
                                    if exc.code == "step_unavailable"
                                    else FingerprintResultState.FAILED,
                                    failure_code=FingerprintFailureCode(exc.code),
                                )
                        elif request.file_type is None:
                            mesh = mesh_loading.load_mesh(request.path)
                        else:
                            mesh = mesh_loading.load_mesh(
                                request.path, file_type=suffix
                            )

                        phases.finish(
                            outcome=PhaseOutcome.COMPLETED
                            if mesh is not None
                            else PhaseOutcome.FAILED,
                            triangle_count=len(mesh.faces)
                            if mesh is not None
                            else None,
                        )

                    if mesh is not None:
                        source_scan = SourceScanState.COMPLETE
                        geometry_representation = CompleteGeometry()

                    report("extracting_geometry")
                    if request.include_geometry:
                        phases.start(MeshPhase.MEASUREMENTS)
                        if (
                            over_cap
                            and suffix == ".stl"
                            and not request.include_thumbnail
                        ):
                            try:
                                measured = scan_stl(request.path)
                            except (InvalidSTL, OSError) as exc:
                                geometry_outcome = GeometryRefused(
                                    ThumbnailFailureReason.RESOURCE_LIMIT
                                    if isinstance(exc, InvalidSTL)
                                    and exc.reason is STLReadFailure.RESOURCE_LIMIT
                                    else ThumbnailFailureReason.INVALID_SOURCE
                                )
                            else:
                                source_scan = SourceScanState.COMPLETE
                                volume = VolumeNotCalculated(
                                    VolumeNotCalculatedCause.TOPOLOGY_NOT_EVALUATED
                                )
                                geometry.update(
                                    {
                                        "bbox_x_mm": measured.bounds_max[0]
                                        - measured.bounds_min[0],
                                        "bbox_y_mm": measured.bounds_max[1]
                                        - measured.bounds_min[1],
                                        "bbox_z_mm": measured.bounds_max[2]
                                        - measured.bounds_min[2],
                                        "triangle_count": measured.triangle_count,
                                    }
                                )
                        else:
                            measured = mesh_measurements.geometry_from_mesh(mesh)
                            geometry, volume = measured.geometry, measured.volume
                        validate_geometry_extents(geometry)
                        phases.finish(
                            triangle_count=int(geometry["triangle_count"])
                            if geometry["triangle_count"] is not None
                            else None,
                            outcome=PhaseOutcome.COMPLETED
                            if geometry["triangle_count"] is not None
                            else PhaseOutcome.FAILED,
                        )
                        if geometry["triangle_count"] is not None:
                            geometry_outcome = GeometryReady()
                        elif over_cap and (
                            suffix != ".stl" or request.include_thumbnail
                        ):
                            geometry_outcome = GeometryRefused(
                                ThumbnailFailureReason.RESOURCE_LIMIT
                            )

                    if request.include_fingerprint and fingerprint_result is None:
                        phases.start(MeshPhase.FINGERPRINT)
                        report("extracting_fingerprint")
                        try:
                            # Analysis admission cannot remove useful measurements
                            # or a preview from a mesh admitted by the load budget.
                            if (
                                mesh is not None
                                and len(mesh.faces) > request.triangle_cap
                            ):
                                raise GeometryError("geometry_work_limit")
                            if prepared is None and mesh is not None:
                                prepared = prepare_loaded_mesh(
                                    mesh, file_type=suffix.lstrip(".")
                                )
                            if prepared is None and suffix == ".stl" and over_cap:
                                sample_buffers_pending = True
                                sampled_preparation = _prepare_sampled_stl(
                                    request.path, triangle_cap=request.triangle_cap
                                )
                                if sampled_preparation is not None:
                                    prepared, sampled_scan = sampled_preparation
                                    del sampled_preparation
                                    if source_scan is not SourceScanState.COMPLETE:
                                        source_scan = sampled_scan
                            if (
                                prepared is not None
                                and len(prepared.whole_mesh.faces)
                                > request.triangle_cap
                            ):
                                raise GeometryError("geometry_work_limit")
                            if prepared is not None and isinstance(
                                geometry_representation, GeometryNotLoaded
                            ):
                                geometry_representation = prepared.geometry
                                if isinstance(prepared.geometry, CompleteGeometry):
                                    source_scan = SourceScanState.COMPLETE
                            fingerprint_result = (
                                extract(prepared)
                                if prepared is not None
                                else FingerprintResult(
                                    FingerprintResultState.UNSUPPORTED
                                    if suffix in (".step", ".stp")
                                    else FingerprintResultState.FAILED,
                                    failure_code=FingerprintFailureCode.STEP_UNAVAILABLE
                                    if suffix in (".step", ".stp")
                                    else FingerprintFailureCode.RESOURCE_LIMIT
                                    if over_cap
                                    else FingerprintFailureCode.INVALID_SOURCE,
                                )
                            )
                        except (GeometryError, ValueError, MemoryError) as exc:
                            fingerprint_result = FingerprintResult(
                                FingerprintResultState.FAILED,
                                failure_code=FingerprintFailureCode(exc.code)
                                if isinstance(exc, GeometryError)
                                else FingerprintFailureCode.ANALYSIS_FAILED,
                            )

                        finally:
                            # Fingerprints contain serialized descriptors, never
                            # mesh buffers. Render keeps only its loaded mesh;
                            # fallback must not overlap with analysis allocations.
                            prepared = None

                        phases.finish(
                            outcome=PhaseOutcome.COMPLETED
                            if fingerprint_result.state is FingerprintResultState.READY
                            else PhaseOutcome.FAILED
                        )

                    if not request.include_thumbnail:
                        return ThumbnailResult(
                            image=None,
                            geometry=geometry,
                            geometry_outcome=geometry_outcome,
                            volume=volume,
                            strategy=ThumbnailStrategy.NONE,
                            coverage=MeshCoverage(
                                source_scan, geometry_representation, preview_coverage
                            ),
                            failure_reason=None,
                            duration_ms=max(
                                round((time.monotonic() - started) * 1000), 0
                            ),
                            peak_rss_bytes=_peak_rss_bytes(),
                            fingerprint_result=fingerprint_result,
                            phase_stats=phases.snapshot(),
                        )

                    phases.start(MeshPhase.RENDER)
                    report("rendering_thumbnail")
                    if embedded is not None:
                        image = embedded
                        strategy = ThumbnailStrategy.EMBEDDED
                        preview_coverage = PreviewCoverage.DOCUMENT_SUPPLIED
                    elif mesh is not None:
                        cap = int(settings.mesh_max_render_triangles)
                        ram_cap = mesh_policy.ram_triangle_cap(suffix)
                        if ram_cap is not None:
                            cap = min(cap, ram_cap)
                        if len(mesh.faces) > cap:
                            failure = ThumbnailFailureReason.RESOURCE_LIMIT
                            logger.warning(
                                "thumbnail_engine: post-load triangle budget exceeded",
                                extra={
                                    "strategy": "full",
                                    "triangles": len(mesh.faces),
                                },
                            )
                        else:
                            try:
                                image = mesh_render.render_mesh_thumbnail(
                                    mesh,
                                    request.path.name,
                                    width=width,
                                    height=height,
                                    output_format=request.output_format,
                                )
                            except Exception:  # noqa: BLE001 - bounded fallbacks remain
                                logger.exception(
                                    "thumbnail_engine: full renderer failed",
                                    extra={"format": suffix},
                                )
                            if image is not None:
                                strategy = ThumbnailStrategy.FULL
                                preview_coverage = PreviewCoverage.COMPLETE

                    phases.finish(
                        output_bytes=len(image) if image is not None else None,
                        outcome=PhaseOutcome.COMPLETED
                        if image is not None
                        else PhaseOutcome.FAILED,
                    )

                    if (
                        image is None
                        and suffix == ".stl"
                        and (over_cap or mesh is not None)
                    ):
                        release_buffers = mesh is not None or sample_buffers_pending
                        prepared = None
                        mesh = None
                        sample_buffers_pending = False
                        if release_buffers:
                            mesh_policy.reclaim_memory()
                        phases.start(MeshPhase.STREAMING, input_bytes=source_bytes)
                        streamed = stl_streaming.render_stl_preview_isolated(
                            request.path, width=width, height=height
                        )
                        phases.finish(
                            output_bytes=len(streamed.png)
                            if streamed is not None
                            else None,
                            triangle_count=streamed.triangle_count
                            if streamed is not None
                            else None,
                            outcome=PhaseOutcome.COMPLETED
                            if streamed is not None
                            else PhaseOutcome.FAILED,
                        )
                        if streamed is not None:
                            image = streamed.png
                            strategy = ThumbnailStrategy.STREAMING
                            source_scan = SourceScanState.COMPLETE
                            preview_coverage = PreviewCoverage.COMPLETE
                            if (
                                request.include_geometry
                                and geometry["triangle_count"] is None
                            ):
                                volume = VolumeNotCalculated(
                                    VolumeNotCalculatedCause.TOPOLOGY_NOT_EVALUATED
                                )
                                geometry.update(
                                    {
                                        "bbox_x_mm": streamed.bounds_max[0]
                                        - streamed.bounds_min[0],
                                        "bbox_y_mm": streamed.bounds_max[1]
                                        - streamed.bounds_min[1],
                                        "bbox_z_mm": streamed.bounds_max[2]
                                        - streamed.bounds_min[2],
                                        "triangle_count": streamed.triangle_count,
                                    }
                                )

                    if image is None and suffix == ".stl":
                        phases.start(MeshPhase.FALLBACK, input_bytes=source_bytes)
                        fallback = stl_fallback.render_stl_thumbnail(
                            request.path, width=width, height=height
                        )
                        phases.finish(
                            output_bytes=len(fallback.png)
                            if fallback is not None
                            else None,
                            triangle_count=fallback.triangle_count
                            if fallback is not None
                            else None,
                            outcome=PhaseOutcome.COMPLETED
                            if fallback is not None
                            else PhaseOutcome.FAILED,
                        )
                        if fallback is not None:
                            image = fallback.png
                            strategy = ThumbnailStrategy.FALLBACK
                            preview_coverage = (
                                PreviewCoverage.COMPLETE
                                if fallback.complete
                                and fallback.sampled_triangles
                                == fallback.triangle_count
                                else PreviewCoverage.PARTIAL
                            )
                            if fallback.complete:
                                source_scan = SourceScanState.COMPLETE
                            elif source_scan is SourceScanState.NOT_SCANNED:
                                source_scan = SourceScanState.PARTIAL
                            if (
                                request.include_geometry
                                and fallback.complete
                                and geometry["triangle_count"] is None
                            ):
                                volume = VolumeNotCalculated(
                                    VolumeNotCalculatedCause.TOPOLOGY_NOT_EVALUATED
                                )
                                geometry.update(
                                    {
                                        "bbox_x_mm": fallback.bounds_max[0]
                                        - fallback.bounds_min[0],
                                        "bbox_y_mm": fallback.bounds_max[1]
                                        - fallback.bounds_min[1],
                                        "bbox_z_mm": fallback.bounds_max[2]
                                        - fallback.bounds_min[2],
                                        "triangle_count": fallback.triangle_count,
                                    }
                                )

                    if image is None and failure is None:
                        failure = (
                            ThumbnailFailureReason.RESOURCE_LIMIT
                            if over_cap
                            else ThumbnailFailureReason.NO_GEOMETRY
                            if mesh is None
                            else ThumbnailFailureReason.RENDERER_NO_OUTPUT
                        )
        except InvalidMeshMeasurements:
            phases.fail_active()
            geometry = _empty_geometry()
            if request.include_geometry:
                geometry_outcome = GeometryRefused(
                    ThumbnailFailureReason.INVALID_SOURCE
                )
                volume = VolumeNotCalculated(
                    VolumeNotCalculatedCause.GEOMETRY_UNAVAILABLE
                )
            if request.include_fingerprint:
                fingerprint_result = FingerprintResult(
                    FingerprintResultState.FAILED,
                    failure_code=FingerprintFailureCode.INVALID_SOURCE,
                )
            if embedded is not None:
                image = embedded
                strategy = ThumbnailStrategy.EMBEDDED
                preview_coverage = PreviewCoverage.DOCUMENT_SUPPLIED
            elif request.include_thumbnail:
                failure = ThumbnailFailureReason.INVALID_SOURCE
        except MemoryError:
            phases.fail_active()
            prepared = None
            mesh = None
            sample_buffers_pending = False
            mesh_policy.reclaim_memory()
            if request.include_geometry and not isinstance(
                geometry_outcome, GeometryReady
            ):
                geometry_outcome = GeometryRefused(
                    ThumbnailFailureReason.RESOURCE_LIMIT
                )
            if request.include_fingerprint:
                fingerprint_result = FingerprintResult(
                    FingerprintResultState.FAILED,
                    failure_code=FingerprintFailureCode.RESOURCE_LIMIT,
                )
            if embedded is not None:
                image = embedded
                strategy = ThumbnailStrategy.EMBEDDED
                preview_coverage = PreviewCoverage.DOCUMENT_SUPPLIED
            else:
                failure = ThumbnailFailureReason.RESOURCE_LIMIT
        finally:
            phases.fail_active()
            prepared = None
            if mesh is not None or sample_buffers_pending:
                mesh = None
                mesh_policy.reclaim_memory()

        if request.include_geometry and geometry["triangle_count"] is not None:
            geometry_outcome = GeometryReady()
        if image is not None:
            failure = None
        duration_ms = max(round((time.monotonic() - started) * 1000), 0)
        labels = {
            "format": suffix.removeprefix(".") or "unknown",
            "strategy": strategy.value,
            "outcome": "generated" if image is not None else "failed",
            "reason": failure.value if failure is not None else "none",
        }
        self.metrics.increment("thumbnail_generation_total", labels=labels)
        self.metrics.observe(
            "thumbnail_generation_duration_ms", float(duration_ms), labels=labels
        )
        try:
            self.metrics.observe(
                "thumbnail_input_bytes",
                float(request.path.stat().st_size),
                labels=labels,
            )
        except OSError:
            pass
        if image is not None:
            self.metrics.observe(
                "thumbnail_renderer_output_bytes", float(len(image)), labels=labels
            )
        triangles = geometry.get("triangle_count")
        if triangles is not None:
            self.metrics.observe("thumbnail_triangles", float(triangles), labels=labels)
        peak_rss = _peak_rss_bytes()
        if peak_rss is not None:
            self.metrics.observe(
                "thumbnail_peak_rss_bytes", float(peak_rss), labels=labels
            )
        return ThumbnailResult(
            image=image,
            geometry=geometry,
            geometry_outcome=geometry_outcome,
            volume=volume,
            strategy=strategy,
            coverage=MeshCoverage(
                source_scan, geometry_representation, preview_coverage
            ),
            failure_reason=failure,
            duration_ms=duration_ms,
            peak_rss_bytes=peak_rss,
            fingerprint_result=fingerprint_result,
            phase_stats=phases.snapshot(),
        )


__all__ = [
    "NoopThumbnailMetrics",
    "ThumbnailEngine",
]
