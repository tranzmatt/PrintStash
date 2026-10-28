"""Time a cold similarity run on a small mixed corpus, pair by pair.

Run from backend: uv run python -m tests.fakes.similarity_pipeline_benchmark --root /tmp/new-dir
The corpus mixes byte-distinct copies, a mirror, a rescale and multi-body STL
parts of repository designs, so the expected Candidate set is known and checked.
``--corpus wide`` adds benchy variants and a remeshed, rotated and copied Thingi10K
part; its Candidate set is recorded, not asserted. Every verification unit is
logged with the two fingerprints it compared, so pair fan-out is visible.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import io
import json
import os
import platform
import time
from pathlib import Path

SMALL_EXPECTED = {
    ("benchy", "benchy-mirror", "mirrored"),
    ("spatula", "spatula-copy", "identical_geometry"),
    ("cube", "cube-x2", "rescaled"),
}


def _corpus(kind: str, load):
    import numpy as np
    import trimesh

    from tests.paths import CORE_PACKAGE_ROOT, TESTDATA_DIR

    benchy = load(TESTDATA_DIR / "benchy/3dbenchy.stl")
    spatula = load(TESTDATA_DIR / "Spatula_Printables_IS.3mf")
    cube = load(TESTDATA_DIR / "Calibration Cube.stl")
    parts = [
        (path.stem, load(path))
        for path in sorted(
            (CORE_PACKAGE_ROOT / "tests/fixtures/similarity").glob("*.stl")
        )
    ]

    def scaled(mesh, factor):
        copy = mesh.copy()
        copy.apply_scale(factor)
        return copy

    def mirrored(mesh):
        copy = mesh.copy()
        copy.apply_transform(np.diag([-1.0, 1, 1, 1]))
        copy.invert()
        return copy

    def rotated(mesh):
        copy = mesh.copy()
        copy.apply_transform(trimesh.transformations.rotation_matrix(0.7, [0, 0, 1]))
        copy.apply_translation([13, -4, 2])
        return copy

    corpus = [
        ("benchy", benchy),
        ("benchy-mirror", mirrored(benchy)),
        ("spatula", spatula),
        ("spatula-copy", spatula),
        ("cube", cube),
        ("cube-x2", scaled(cube, 2.0)),
        parts[0],
    ]
    if kind == "wide":
        corpus += [
            ("benchy-copy", benchy),
            ("benchy-rotated", rotated(benchy)),
            ("benchy-x1.25", scaled(benchy, 1.25)),
            *parts[1:],
            (f"{parts[0][0]}-remeshed", parts[0][1].subdivide()),
            (f"{parts[1][0]}-rotated", rotated(parts[1][1])),
            (f"{parts[2][0]}-copy", parts[2][1]),
        ]
    return corpus


def _synthetic(count: int):
    """Distinct procedural designs; one in ten also appears transformed."""
    import numpy as np
    import trimesh

    rng = np.random.default_rng(154)
    makers = (
        lambda: trimesh.convex.convex_hull(
            rng.normal(size=(int(rng.integers(12, 60)), 3))
        ),
        lambda: trimesh.creation.cylinder(
            radius=float(rng.uniform(0.3, 2)),
            height=float(rng.uniform(0.5, 4)),
            sections=int(rng.integers(16, 96)),
        ),
        lambda: trimesh.creation.capsule(
            height=float(rng.uniform(0.5, 4)),
            radius=float(rng.uniform(0.3, 1.5)),
        ),
        lambda: trimesh.creation.annulus(
            r_min=float(rng.uniform(0.2, 0.8)),
            r_max=1.0,
            height=float(rng.uniform(0.1, 1.5)),
            sections=int(rng.integers(24, 96)),
        ),
        lambda: trimesh.creation.box(rng.uniform(0.2, 3, size=3)),
    )
    corpus, expected = [], set()
    designs = count * 10 // 11
    for index in range(designs):
        mesh = makers[index % len(makers)]()
        mesh.apply_scale(rng.uniform(0.5, 2, size=3))
        mesh = mesh.subdivide() if len(mesh.faces) < 400 else mesh
        name = f"design-{index:04d}"
        corpus.append((name, mesh))
        if index % 10 == 0 and len(corpus) < count:
            variant = mesh.copy()
            variant.apply_transform(
                trimesh.transformations.random_rotation_matrix(rng.random(3))
            )
            variant.apply_scale(float(rng.choice([1.0, 2.0, 25.4])))
            corpus.append((f"{name}-variant", variant))
            expected.add((name, f"{name}-variant"))
    return corpus[:count], expected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--corpus", choices=("small", "wide", "synthetic"), default="small"
    )
    parser.add_argument("--count", type=int, default=200)
    args = parser.parse_args()
    if args.root.exists():
        parser.error("root must be a new directory; existing results are preserved")
    args.root.mkdir(parents=True)
    os.environ["VAULT_DB_URL"] = f"sqlite:///{args.root / 'library.sqlite'}"
    from sqlmodel import Session, SQLModel, select

    from app.bootstrap.native_resources import configure as configure_native_resources
    from app.core.config import _overlay
    from app.db.models import (
        File,
        FileType,
        GeometryFingerprint,
        Model,
        SimilarityCandidate,
        SimilarityRun,
    )
    from app.db.session import get_engine, get_session_factory
    from app.modules.media.geometry_analysis import _load
    from app.modules.similarity import configuration, processing, runs
    from app.modules.storage.storage_backend.runtime import get_backend
    from tests._env import use_local_storage
    from tests.factories import build_file, build_model, build_user

    _overlay["storage_identity"] = "a" * 64
    use_local_storage(args.root / "storage")
    configure_native_resources(args.root / "data")
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    expected = None
    if args.corpus == "synthetic":
        corpus, expected = _synthetic(args.count)
    else:
        corpus = _corpus(
            args.corpus,
            lambda path: (
                _load(path, path.suffix[1:], triangle_cap=2_000_000).whole_mesh
            ),
        )
    with Session(engine) as session:
        actor = build_user(session, superuser=True)
        configuration.update_settings(session, actor, {"enabled": True})
        for index, (name, mesh) in enumerate(corpus):
            blob = mesh.export(file_type="stl")
            content = (
                f"PrintStash pipeline {index}".encode().ljust(80, b" ") + blob[80:]
            )
            model = build_model(session, name=name)
            file = build_file(
                session,
                model,
                file_type=FileType.STL,
                sha256=hashlib.sha256(content).hexdigest(),
                size_bytes=len(content),
            )
            file.path = get_backend().blob_key(
                model.slug, file.version, file.original_filename
            )
            get_backend().write_stream(io.BytesIO(content), file.path)
            session.add(file)
            session.commit()
        run_id = runs.start(session, actor).id
    del corpus

    worker = processing.SimilarityProcessor(get_session_factory(), get_backend())
    units = []
    started = time.perf_counter()
    while True:
        with Session(engine) as session:
            run = session.get(SimilarityRun, run_id)
            assert run is not None
            if run.state in runs.TERMINAL:
                break
            phase = run.phase
            pending = json.loads(run.checkpoint_json).get("pending_pairs", [])
        tick = time.perf_counter()
        assert worker.work_one(run_id, "benchmark"), "run made no progress"
        units.append(
            {
                "phase": phase,
                "pair": pending[0] if pending else None,
                "seconds": time.perf_counter() - tick,
            }
        )
    total = time.perf_counter() - started

    with Session(engine) as session:
        run = session.get(SimilarityRun, run_id)
        assert run is not None and run.state == "completed", run
        rows = session.exec(
            select(
                GeometryFingerprint.id, Model.name, GeometryFingerprint.component_index
            )
            .join(File, File.id == GeometryFingerprint.file_id)
            .join(Model, Model.id == File.model_id)
        ).all()
        names = {model.id: model.name for model in session.exec(select(Model))}
        found = {
            (names[row.model_a_id], names[row.model_b_id], row.evidence_class)
            for row in session.exec(select(SimilarityCandidate))
        }
        counters = json.loads(run.counters_json)
    fingerprint = {row[0]: (row[1], row[2]) for row in rows}
    by_pair: dict[str, list[float]] = collections.defaultdict(lambda: [0, 0.0])
    for unit in units:
        if unit["pair"] is None:
            continue
        a, b = (fingerprint[value] for value in unit["pair"])
        kind = (
            "whole"
            if not a[1] and not b[1]
            else "component"
            if a[1] and b[1]
            else "mixed"
        )
        key = f"{' <-> '.join(sorted((a[0], b[0])))} [{kind}]"
        by_pair[key][0] += 1
        by_pair[key][1] += unit["seconds"]
    phases: dict[str, float] = collections.defaultdict(float)
    for unit in units:
        phases[unit["phase"]] += unit["seconds"]
    report = {
        "corpus": args.corpus,
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "load_average": os.getloadavg(),
        "total_seconds": round(total, 2),
        "phase_seconds": {key: round(value, 2) for key, value in phases.items()},
        "pair_units": sum(1 for unit in units if unit["pair"] is not None),
        "fingerprint_rows": len(rows),
        "counters": counters,
        "by_pair": {
            key: {"units": value[0], "seconds": round(value[1], 2)}
            for key, value in sorted(by_pair.items(), key=lambda item: -item[1][1])
        },
        "candidates": sorted(found),
    }
    (args.root / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    (args.root / "units.json").write_text(json.dumps(units) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    if args.corpus == "small":
        assert found == SMALL_EXPECTED, found
    if expected is not None:
        pairs = {(a, b) for a, b, _ in found}
        print(
            json.dumps(
                {
                    "expected_found": len(expected & pairs),
                    "expected": len(expected),
                    "extra": sorted(pairs - expected)[:20],
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
