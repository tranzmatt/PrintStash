# Reusable exact sample-point lookup

Status: accepted; integrated rollout validation pending.

Verification previously formed squared point distances from two squared norms
and a matrix product. This allocates up to one million cells per query block,
repeats target work for each alignment hypothesis, and cancels small distances
when absolute coordinates are large. A reproduced two-point example at origin
1e9 selected the wrong nearest point: the true distance is 0.25.

Use SciPy's native KDTree behind the core `PointNeighbors` owner. SciPy is already
the optional mesh dependency selected for convex hulls. The owner copies and
deduplicates a floating-point target snapshot, preserving original indices.
Power-of-two scaling avoids squared-distance overflow/underflow without rounding
ordinary coordinates. A roundtrip check refuses ranges that lose representable
coordinates. Physical distances are computed from direct differences with hypot.
Integer arrays are rejected explicitly instead of silently rounding large int64
coordinates to float64. Supported callers already supply analysis float arrays.

Exact queries use `eps=0`, one native thread, and blocks of 256 source points.
Equal or nearly equal native distances trigger a bounded exact comparison and
choose the earliest original index. Duplicate points do not multiply tie work.
Target/source sample limits are 10,000 points each; actual verification uses at
most 5,000 per surface. Alignment ranking batches at most 145 hypotheses of 64
points into one reusable index query. This is sample-point proximity, not a
replacement for triangle-surface proximity or the exact correspondence proof.
[Native query contract](https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.KDTree.query.html).

Deadline checks surround index construction/native calls and run between query
blocks and tie rows. They cannot interrupt a native call itself; the process
supervisor remains the hard timeout and memory boundary. Source/target arrays
and the native index do not cross the owner's interface. No global index cache
or extra native worker pool is introduced.

## Evidence and costs

An exploratory shared-host measurement uses Python 3.12.3, NumPy 2.5.2, SciPy
1.17.1, one BLAS/OpenMP thread, ten warm repetitions and seeded Gaussian points
(seed 154). Build time is included; import time is excluded. Peak RSS is Linux
VmHWM for the entire subprocess. Separate old/new subprocesses include their
respective imports. These are observations, not a deployment throughput gate.

| Work | Previous median | New median | New min–max |
| --- | --- | --- | --- |
| 48 hypotheses, 64 points into 128 targets | 3.50 ms | 4.78 ms | 4.56–5.14 ms |
| 5,000 points into 5,000 targets | 307.29 ms | 14.96 ms | 14.83–15.53 ms |
| Complete identical-tetrahedron verification, 5,000 samples | 713.96 ms | 144.38 ms | 143.21–149.00 ms |

The tiny ranking case is slower by about 1.3 ms. The dense evaluation and measured
whole verification gain justify one maintained numerical implementation rather
than a separate squared-dot fast path. Process peak RSS changes from 55.4 to
69.6 MiB for dense lookup and 59.7 to 78.3 MiB for full verification. Cold import
and whole ingestion/load performance still require integrated measurement.

Regression tests compare indices/distances against an independent exhaustive
hypot oracle, test deterministic ties, immutable ownership, malformed inputs,
sample limits, range refusal and cancellation. Scales 1e-200 and 1e200 retain
finite analytical results. The 20-case licensed verifier corpus preserves all
labels, classifications and splits; compared metric differences are below 7e-11,
within the unchanged 1e-5 gate. Earlier evaluation references remain immutable.
The corrected numerical recipe is `surface-verification-v4`, with a new measured
reference. Previous cached proofs require fresh verification while historical
observations and human review decisions are retained.
