"""Compact surface clouds that reject clearly different pairs before verification.

Verification loads both meshes and refines an alignment against the full
triangle surface: seconds per pair, and most shortlisted pairs in a large
library do not match. A fingerprint keeps 512 area-weighted surface samples in
its own principal frame, scaled by its radius. Two clouds are aligned under the
signed axis permutations and the original axes, refined by point ICP, and their
mean symmetric distance is divided by each cloud's own sampling spacing.

Independent samplings of one surface score about 1 whatever its area. Every
labelled derivative in the similarity corpus (mirrored, rescaled, rotated,
re-exported, subdivided and repaired copies) scores at most 1.02, and every pair
the verifier accepted in a 200-design synthetic library at most 1.13; in both,
no pair scoring above that produced evidence. The rejection score leaves a
margin above the larger. A pair below it is verified exactly as before, so a
cloud never creates or changes evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations, product
from typing import TYPE_CHECKING

from .fingerprint import GeometryError
from .geometry import Surface, sample_surface
from .point_neighbors import PointNeighbors

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    FloatArray = NDArray[np.float64]

CLOUD_RECIPE = "surface-cloud-v1"
CLOUD_POINTS = 512
REJECT_SCORE = 1.3
_SEEDS = (154, 155)
_STARTS_PER_PARITY = 3
_ICP_STEPS = 12
_CONVERGED = 1e-4
_RANK_STRIDE = 4
_MIN_SPACING = 1e-6
_FLOATS = CLOUD_POINTS * 3 + 9 + 1
CLOUD_BYTES = _FLOATS * 4


@dataclass(frozen=True)
class SurfaceCloud:
    points: FloatArray
    frame: FloatArray
    spacing: float

    def encode(self) -> bytes:
        import numpy as np

        values = np.concatenate(
            (self.points.ravel(), self.frame.ravel(), [self.spacing])
        )
        return values.astype("<f4").tobytes()

    @classmethod
    def decode(cls, blob: bytes) -> SurfaceCloud:
        import numpy as np

        if len(blob) != CLOUD_BYTES:
            raise GeometryError("invalid_surface_cloud")
        values = np.frombuffer(blob, dtype="<f4").astype(np.float64)
        if not np.isfinite(values).all() or not values[-1] > 0:
            raise GeometryError("invalid_surface_cloud")
        points = values[: CLOUD_POINTS * 3].reshape(CLOUD_POINTS, 3)
        frame = values[CLOUD_POINTS * 3 : -1].reshape(3, 3)
        return cls(points, frame, float(values[-1]))


def surface_cloud(surface: Surface) -> SurfaceCloud:
    """Two independent samplings: one is kept, both measure its own spacing."""
    import numpy as np

    kept, other = (
        sample_surface(surface, CLOUD_POINTS, seed) @ surface.frame / surface.radius
        for seed in _SEEDS
    )
    # Round-trip through storage precision so a fresh cloud scores as a stored one.
    kept = kept.astype("<f4").astype(np.float64)
    spacing = float(
        (
            PointNeighbors(kept).query(other)[0].mean()
            + PointNeighbors(other).query(kept)[0].mean()
        )
        / 2
    )
    # Below float32 resolution of radius-scaled points the spacing is noise.
    if not spacing > _MIN_SPACING:
        raise GeometryError("degenerate_surface_cloud")
    return SurfaceCloud(kept, surface.frame.astype("<f4").astype(np.float64), spacing)


def _hypotheses(left: SurfaceCloud, right: SurfaceCloud) -> list[FloatArray]:
    import numpy as np

    signed = [
        np.eye(3)[:, list(order)] * np.array(signs)
        for order in permutations(range(3))
        for signs in product((-1.0, 1.0), repeat=3)
    ]
    # The original axes: exports that only moved the origin keep them.
    return [*signed, right.frame.T @ left.frame]


def _kabsch(source: FloatArray, target: FloatArray) -> tuple[FloatArray, FloatArray]:
    import numpy as np

    source_center, target_center = source.mean(axis=0), target.mean(axis=0)
    u, _, vt = np.linalg.svd((source - source_center).T @ (target - target_center))
    rotation = u @ np.diag([1.0, 1.0, float(np.sign(np.linalg.det(u @ vt)))]) @ vt
    return rotation, target_center - source_center @ rotation


def alignment_score(left: SurfaceCloud, right: SurfaceCloud) -> float:
    """Best aligned symmetric distance, in units of the clouds' own spacing."""
    import numpy as np
    from scipy.spatial import cKDTree  # pyright: ignore[reportMissingTypeStubs]

    # A score needs distances only, never tie-exact indices, so the plain index
    # suffices; one native thread keeps the caller's admission accounting.
    left_index, right_index = cKDTree(left.points), cKDTree(right.points)
    hypotheses = _hypotheses(left, right)
    probe = right.points[::_RANK_STRIDE]
    ranked = sorted(
        (float(left_index.query(probe @ hypothesis, workers=1)[0].mean()), order)
        for order, hypothesis in enumerate(hypotheses)
    )
    best = np.inf
    for parity in (1.0, -1.0):
        starts = [
            hypotheses[order]
            for _, order in ranked
            if np.sign(np.linalg.det(hypotheses[order])) == parity
        ][:_STARTS_PER_PARITY]
        for start in starts:
            rotation, offset = start, np.zeros(3)
            previous = np.inf
            for _ in range(_ICP_STEPS):
                moved = right.points @ rotation + offset
                distances, nearest = left_index.query(moved, workers=1)
                error = float(distances.mean())
                if error >= previous * (1 - _CONVERGED):
                    break
                previous = error
                step, shift = _kabsch(moved, left.points[nearest])
                rotation, offset = rotation @ step, offset @ step + shift
            moved = right.points @ rotation + offset
            forward = left_index.query(moved, workers=1)[0].mean()
            # Left points in the right cloud's frame: the inverse rigid motion.
            backward = right_index.query(
                (left.points - offset) @ rotation.T, workers=1
            )[0].mean()
            best = min(best, float((forward + backward) / 2))
    return best / ((left.spacing + right.spacing) / 2)


def rejects(left: SurfaceCloud, right: SurfaceCloud) -> bool:
    """Whether the pair is too far apart for any Evidence Class."""
    return alignment_score(left, right) > REJECT_SCORE
