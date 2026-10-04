# 3MF reader pilot evidence

This is a geometry-reading experiment, not an adopted parser or performance gate.
The [ADR](../0009-3mf-loader-capabilities.md) records the resulting direction.
No source Artifacts were rewritten, production dependencies changed or CI
workflows triggered.

## Reproduction

From `backend`, use a disposable environment synced with the existing full/dev
extras, then install `lib3mf==2.5.0` only into that environment. Run:

```sh
python -m scripts.pilot_lib3mf run --output /tmp/corpus.json
python -m scripts.pilot_lib3mf run --output /tmp/strict.json --backend lib3mf-buffer --strict
python -m scripts.pilot_lib3mf run --case core-basic --faces 5000 20000 --repeat 30 --output /tmp/series.json
python -m scripts.pilot_lib3mf run --case core-basic --faces 200000 --repeat 3 --output /tmp/large.json
python -m scripts.pilot_lib3mf run --case core-basic --faces 5000 --instances 64 --repeat 3 --output /tmp/instances.json
pytest -q tests/unit/scripts/test_pilot_lib3mf.py tests/integration/scripts/test_pilot_lib3mf.py
```

The harness runs a fresh child for every cell, with a 1 GiB address-space limit
and one BLAS thread, and reverses backend order on alternate repetitions. Inputs
have fixed archive metadata, analytic expectations and recorded hashes. OS file
cache is warm. Input generation and downloading are outside the child timings.

To include real slicer exports, retrieve the immutable URLs in
[external-inputs.json](external-inputs.json), verify each SHA256, save each file
using its `case` name, and pass `--external-directory` to the corpus/strict runs.
These binaries are not redistributed. Their acceptance expectation only declares
geometry availability; this pilot does not certify every slicer feature or derive
their exact geometry expectations from another parser.

## Files

- [samples.csv](samples.csv): all 434 observations, including expected mismatches,
  refusals, warning codes/text, stage costs and process memory. No failures removed.
- [summary.json](summary.json): sample counts, outcomes, medians, min/max and p10/p90.
- [cases.json](cases.json): package hashes, decoded workload limits and independent
  synthetic expectations.
- [environment.json](environment.json): base revision, Python/kernel, cache/thread/
  address-space policy and frozen harness/generator hashes.
- [packaging.json](packaging.json): pinned wheel hashes, common binding digest,
  helpers, license notices and native symbol/version requirements.
- [attestation.json](attestation.json): retrieved ARM PyPI subject statements,
  matching wheel hash; no independent signature verification claimed.
- [image-smoke.json](image-smoke.json): cached amd64 full-image Python 3.11 native
  import/read/public-array success, isolated at 512 MiB/one CPU without network.

Peak RSS uses `/proc/self/status` `VmHWM` after exec. `ru_maxrss` is diagnostic:
it retained roughly 170–190 MiB from the generator parent on some native children
whose actual peak was about 47 MiB. Reporting that inherited value would conceal
the reader's memory difference.

## Observed exploratory medians

Times are milliseconds. `total` starts before backend imports and ends after
materialized arrays and the common geometry summary; `cold_process_ms` in the CSV
also includes process launch/exit. Native wrapper construction and bookkeeping
are included in total; read alone is not the performance claim. Current read cost
excludes the separately timed extraction/graph/materialization seams. Both routes
retain the same normalized array types at the consumer boundary.

| Input | Backend | n | Import | Read | Arrays | Total | Peak RSS MiB |
| --- | --- | --- | --- | --- | --- | --- | --- |
| core-basic | current | 30 | 563.2 | 1.6 | 0.14 | 565.8 | 100.8 |
| core-basic | lib3mf-public | 30 | 142.6 | 1.7 | 0.24 | 152.6 | 46.8 |
| core-basic | lib3mf-buffer | 30 | 142.7 | 1.7 | 0.19 | 152.7 | 46.8 |
| load-5000-copies-1 | current | 30 | 562.1 | 20.3 | 13.62 | 602.3 | 110.2 |
| load-5000-copies-1 | lib3mf-public | 30 | 143.0 | 8.6 | 16.90 | 178.5 | 49.1 |
| load-5000-copies-1 | lib3mf-buffer | 30 | 142.2 | 8.5 | 0.59 | 160.3 | 47.0 |
| load-20000-copies-1 | current | 30 | 568.9 | 77.7 | 64.57 | 735.7 | 138.6 |
| load-20000-copies-1 | lib3mf-public | 30 | 143.2 | 28.2 | 70.57 | 257.0 | 52.3 |
| load-20000-copies-1 | lib3mf-buffer | 30 | 142.1 | 28.3 | 1.78 | 186.2 | 49.9 |

The smallest input is a **four-face tetrahedron**, not a 12-face cube. This shared
WSL x86_64 host is exploratory; these medians do not certify deployment latency,
p95, throughput, contention or release budgets. The current entry point eagerly
imports Trimesh and always flattens; the native prototype materializes through
NumPy/core directly. A future scene-only XML seam may recover some startup cost
without adopting a native dependency; this experiment does not attribute all
end-to-end savings to XML parsing.

At 200,000 faces (n=3/cell), total medians were 2398/1503/542 ms and RSS medians
490/115/92 MiB for current/public/buffer respectively. Array extraction was
677/981/24 ms. This separates fast native reading from costly Python conversion:
public bulk still materializes a list of structure proxies.

A 5,000-face resource placed 64 times (n=3/cell) retained 240,000 bytes of unique
arrays and produced 15,360,000 bytes when materialized. This verifies the scene's
payload multiplicity, not an existing production scene-only API: production
`load_3mf` still flattens every scene. RSS at scene completion and final peak are
retained separately in the observations.

The corpus has 29 synthetic cases plus three pinned slicer projects. The current
reader matches 29/32 declared expectations; native permissive matches 24/32 and
strict matches 25/32. Passing counts include expected refusals and are not a
weighted score for choosing a parser. Important mismatches are retained: required
extensions, legacy printable semantics, unreachable parts/resources, unused
vertices, large-coordinate precision and the Bambu project. The stricter reader
also rejects the pinned Prusa project. See the ADR for the capability policy.

ARM wheel static inspection and binding equality are recorded, but no ARM native
execution was possible on this host. Exact current-main amd64/ARM images and the
Python compatibility matrix remain required before any native dependency adoption.
