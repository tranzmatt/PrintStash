# ADR-0009: Preserve 3MF precision behind an explicit scene reader

Status: Accepted direction — retain the current reader; scene extraction and distribution changes require separate implementation review.

## Decision

Retain the bounded XML reader as the production geometry source while extracting
an explicit scene-reading contract. Lib3MF 2.5.0 remains an evaluated candidate;
its availability on ARM64 is not the reason for retaining the current reader.
Its float32 geometry/placement API and observed slicer compatibility differences
prevent replacing the existing float64 output without changing useful geometry.
Neither a production dependency nor an automatic parser fallback is introduced.

The next adapter should expose `read_scene(source, limits)` independently of
materialization. Its result owns reachable mesh arrays (float64 vertices, int64
faces), source resource identity and affine instances. A consumer explicitly
requests flattened arrays when necessary. Limits cover ZIP members/decoded bytes,
XML, unique geometry, traversal depth, expanded instances and materialized faces;
those are separate limits rather than one triangle cap reused for every operation.
A malformed source, unsupported required capability and exhausted budget remain
distinct refusals.

Capability policy must be explicit: primary OPC relationship, Core meshes and
components, six physical units, and Production parts with nested nonsingular
transforms/reflections are supported. Unknown required extensions are refused.
Optional slicer metadata does not change geometry. Legacy slicer `printable`
filtering is a compatibility rule: the Core 1.4 schema does not declare that
build-item attribute. Do not select all resources merely because their parts have
`.model` suffixes. Ignore unreachable geometry for measurements, while applying
whole-package safety limits. Remove unused vertices from surface bounds without
changing triangles or source bytes.

## Evidence

The reproducible, optional [pilot](../../backend/scripts/pilot_lib3mf.py) compares
the existing reader, Lib3MF public bulk access and direct typed C buffers.
[Inputs](../../backend/tests/factories/three_mf_pilot.py) contain independent
analytic expectations. They include valid OPC package parts and fixed archive
metadata; invalid cases change exactly the source rule being tested. External
slicer binaries are not vendored. Their pinned provenance is recorded separately.

The evidence distinguishes import, native/XML read, array extraction, graph
expansion and physical materialization, plus total time through arrays, cold
process time and memory. Native public bulk access makes two C calls per array
but returns a Python list of ctypes objects; converting those objects remains
linear Python work. The buffer experiment uses the same exported C functions
with preallocated float32/uint32 buffers, then creates owned float64/int64 arrays.
It uses private binding handles and is not an approved application interface.

Each sample runs in a fresh process with one BLAS thread and a 1 GiB address-space
limit. OS file cache is warm; backend order reverses between repetitions. This is
a shared WSL x86_64 machine, not a pinned throughput or release gate. Linux
`VmHWM` measures the executed worker's peak RSS; `ru_maxrss` is retained only as a
diagnostic because it can carry the generator parent's high-water mark through
process creation. Timeouts, child failures and source refusals stay in evidence.

Observed capability differences:

| Case | Current XML reader | Lib3MF permissive | Lib3MF strict |
| --- | --- | --- | --- |
| Supported units / nested reflection / explicit face limits | Preserved | Preserved after adapter traversal limits | Preserved |
| Unknown required extension | Accepted: correction needed | Accepted with warning | Refused |
| Invalid unit | Refused | Defaults to millimetres with warning | Refused |
| Legacy `printable=false/0` | Excluded | Included | Attribute refused |
| Resource coordinates near `1e9` with 10/20/30 mm extent | Extent preserved | All extents collapse to zero | Same float32 API |
| Unused vertex far from triangles | Incorrectly expands bounds | Same through unfiltered arrays | Not a precision remedy |
| Malformed unreachable `.model` part | Refused: reachability correction needed | Ignored | Ignored |
| Prusa pinned roundtrip project | Accepted | Accepted, placement rounded | Attribute refused |
| Bambu pinned calibration project | Accepted | Reader refuses build item | Missing Production UUID refused |
| Orca pinned flow calibration | Accepted | Accepted | Accepted |

Strictness cannot be the application's capability policy: permissive mode loses
required-extension and printable semantics, while strict mode rejects supported
legacy slicer files. A compatibility preflight and float64 geometry extraction
would still be necessary. Lib3MF reads the model before the pilot can inspect
vertex/face counts; a native reader must therefore remain under process memory,
CPU/deadline and package limits even when final arrays fit.

[Performance summaries, raw samples and provenance](0009-3mf-pilot/README.md)
accompany this ADR. The frozen run contains 434 samples with one harness hash. Use medians and dispersion for 30 samples per exploratory cell. The
200,000-face and 64-instance probes use three samples per cell and support only
exploration; they do not establish tail latency. The retained scene is unique
geometry plus instances; the materialized arrays for 64 identical placements are
64 times the unique array payload. Current production still materializes every
scene, so this pilot does not claim that ingestion already gains this property.

## Distribution and licensing

Both candidates remain viable to investigate. The [official 2.5.0 distribution](https://pypi.org/project/lib3mf/2.5.0/)
has a `py3-none-manylinux2014_x86_64` wheel. The separately maintained
[py-lib3mf 2.5.0 distribution](https://pypi.org/project/py-lib3mf/2.5.0/)
has CPython 3.10–3.14 ARM64 wheels tagged manylinux 2.24/2.28 and publishing
attestations. Their generated `lib3mf/Lib3MF.py` files are byte-identical, but the
ARM package's `__init__.py` does not export the official top-level helpers.
`lib3mf.Lib3MF.Wrapper` is their common binding entry. They install the same module
and must not coexist in one environment.

Static ELF inspection finds the required bulk/read/version symbols in both
libraries. The official x86_64 binary requires GLIBC 2.14 and GLIBCXX 3.4.21; the
inspected ARM64 binary requires GLIBC 2.17 and GLIBCXX 3.4.21. Wheel installation
still follows its stricter advertised tags. Runtime execution was performed only
on x86_64. WSL exposes no ARM64 binfmt runner here; neither static inspection nor
binding equality proves native ARM behavior. A read-only wheel/fixture smoke passed in cached full image
`sha256:43c051a206e3c72ed67ce7b0d988b009f14090efa22be9981ecc6f93fead1a0d`,
Python 3.11.16/glibc 2.41, with correct version and public arrays. Execution in
exact current-main images and the ARM/Python compatibility matrix remains an
adoption gate. No workflow was triggered by the pilot.

The [upstream native library and generated binding](https://github.com/3MFConsortium/lib3mf/blob/v2.5.0/LICENSE)
use a two-clause BSD license. The [alternative packaging project](https://github.com/jdegenstein/py-lib3mf/blob/master/pyproject.toml)
declares Apache-2.0 metadata. Wheel notices differ: the official wheel has its
main LICENSE; the ARM wheel has a third-party notice file and the binding's BSD
header. Any distribution proposal must pin source/wheel hashes, preserve applicable
upstream and third-party notices, and verify the package entry, native version and
ABI in each target image. Conditional package pins are an option after those
gates; producing our own common wheels is another. Neither is selected yet.

## Follow-up gates

1. Review the corpus declarations and capability policy before modifying the
   production adapter; unknown-extension and reachability issues need actual
   regressions in that implementation PR.
2. Preserve float64 resource coordinates and transforms, printable compatibility
   and real slicer availability. Do not silently recenter/rewrite source data to
   conceal native float32 loss.
3. Separate scene ownership from flattening, with measured unique-versus-expanded
   budgets and exact equivalence on the small analytic fixtures.
4. Run the pinned corpus and cold through-array measurements on actual amd64 and
   ARM64 target images before accepting either distribution. Recheck source and
   wheel notices as part of the concrete packaging change.
