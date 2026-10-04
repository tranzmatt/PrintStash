# Reproducible mesh benchmark inputs

The checked manifest at `backend/benchmarks/mesh/corpus-v1.json` freezes fourteen
small synthetic inputs. Generate their bytes and a portable copy of the manifest:

```sh
cd backend
uv run python -m scripts.mesh_benchmark_corpus --output-dir /tmp/mesh-corpus
```

The generator uses the standard library, explicit little-endian STL records,
fixed ZIP timestamps/permissions/order, and uncompressed ZIP members. Its output
does not depend on trimesh, a slicer, the clock, random state or a native parser.
Every file has a SHA-256, byte size, source format, origin and repository license.
`source_faces` counts complete encoded triangles, including unreachable mesh
resources; the truncated STL has eleven complete records and an incomplete last
record. Resources are null for STL. Instances are null for a cyclic scene whose
expansion has no finite count.

## Target contracts, not a compliance claim

`expectation_scope` is `target_contract_not_observed_compliance`. Expectations are
independent acceptance targets. A parser accepting an input with an expected
refusal is an unresolved contract violation, not a successful validation. The
fixture-generation tests certify the inputs and expectations, not current parser
conformance. Benchmark render outcomes remain separate observed data.

The corpus includes binary STL with an ordinary or `solid` header, a truncated
facet, a mismatched declared count, ASCII whitespace/exponents and an incomplete
ASCII facet. 3MF cases cover millimeters/inches/microns, multiple build instances,
a remote unused vertex, reflection, a component cycle and an unsupported required
extension. The cube has twelve outward-oriented triangles. Physical expectations
come from cube dimensions, unit conversion and disjoint-instance addition:
20 mm cubed is 8,000 mm³; one inch cubed is 16,387.064 mm³; one micron cubed is
10⁻⁹ mm³. Two 20 mm cubes separated by 40 mm have 60 × 20 × 20 mm bounds and
16,000 mm³ volume. Reflection preserves physical volume magnitude.

Accepted cases specify relative tolerance `1e-6` and absolute tolerance zero.
This prevents a collapsed microscopic measurement from passing because an
absolute tolerance exceeds the expected value. Refusals name the violated rule,
not an invented current implementation error code.

The generator and manifest must agree byte for byte. Changing a published input
or expectation requires a new corpus version and explicit baseline decision;
do not silently refresh hashes to hide drift. No third-party model assets are
included. Real slicer exports, large/degenerate/nonfinite meshes, broad production
extension cases and recovery/load families remain further corpus work.

## Measure these inputs

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 uv run python -m scripts.bench_thumbnails \
  --contract-corpus --cold-runs 1 --warm-runs 1 > /tmp/mesh-smoke.json
```

The JSON schema is now version 3. It embeds the contract manifest, actual input
hashes and every render/read attempt, including errors and elapsed cost. The
existing shape profile and `--quick` remain available; they have no frozen
contract manifest. An external model is identified by its actual hash and is not
silently added to the licensed synthetic manifest.

The environment snapshot records Git commit and dirty state, Python/platform,
CPU model/count/affinity, host RAM, visible cgroup CPU quota and memory limits,
thread environment settings, renderer dependency versions, recipe, output
resolution and repetition counts. A missing Git executable or unavailable
platform information produces null, not an invented value. Cgroup v2 limits
include the current visible group and ancestors; conventional v1 mount-root
values are a fallback. Hidden ancestors and nonstandard v1 controller mounts
are not inferred. `cpu_limit_read` and `memory_limit_read` distinguish unavailable
limits from readable unlimited values. Host RAM is not claimed as a container's
memory budget.

These remain same-interpreter engine renders and local persisted representation
reads. Filesystem caches are uncontrolled, and RSS is the current process's
lifetime high-water mark. No HTTP, database lookup or worker startup cost is
included. See [mesh execution telemetry](mesh-telemetry.md) for native worker cost
attribution. A target refusal and a render failure are different concepts: this
CLI does not turn their coincidence into a parser-conformance pass.

`performance_gate_qualified` is false. A smoke run validates the measurement
path; it does not certify latency or percentiles. Use at least 30 observations
per cell for exploration and 100 for a latency gate, with controlled hardware,
limits, cache policy, order and quality checks. Record dispersion and failures;
do not discard timeouts to improve a median. Worker-level, upload-to-visible,
concurrency and soak baselines remain separate evidence.
