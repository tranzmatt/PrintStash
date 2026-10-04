# Derivatives

A **derivative** is a pure function of one Artifact's bytes and a **recipe**:
its metadata (geometry, or slicer facts), its thumbnail, and for binary G-code
its converted toolpath. Uploading commits a bare Artifact; derivatives are
produced afterwards by Jobs, so an upload never waits on a renderer and a
renderer crash never loses an upload.

## Data model

`artifact_derivatives` holds one row per Artifact, kind and recipe version:

| Column | Meaning |
| --- | --- |
| `file_id`, `kind`, `recipe_version` | Unique together; a row at an older recipe does not count |
| `state` | `running`, `ready`, `skipped`, `failed` or `cancelled` |
| `attempts`, `next_attempt_at`, `failure_reason` | Retry bookkeeping |
| `storage_key`, `output_json` | Where the output lives and a small summary |
| `duration_ms`, `peak_rss_bytes` | What producing it cost |

The outputs themselves stay with their owners: geometry and slicer facts in
`metadata`, the thumbnail as a blob pointed at by `File.thumbnail_path`, the
toolpath as a blob under `_derivatives/`. No row means **pending**: nothing has
been attempted at the current recipe, so every value the kind supplies is
unknown. Search, filters, sorting and similarity treat an unknown value as
unknown, never as zero.

A kind is satisfied for now when it is `ready` or `skipped` (until an
administrator regenerates it), `cancelled`, `failed` while waiting out its
backoff (`DERIVATIVE_BACKOFF_SECONDS`, doubling, capped at a day), `failed`
after `DERIVATIVE_MAX_ATTEMPTS` or with a deterministic cause (bytes that can
never render), or `running` unless a lost execution left it there too long.

## Why kinds are pulled

Earlier releases pushed enrichment from the upload path, so every new kind or
renderer change needed backfill code and a startup `UPDATE`, and an Artifact
whose push was lost stayed without a thumbnail forever. Now each producer
group's source (`derivatives.source.DerivativeSource`) asks the database which
Artifacts are missing a kind at its current recipe:

- a **bounded anti-join** of live, non-sentinel Artifacts of the group's types
  against satisfying rows, never scanning more than it was asked for;
- first everything above a **high-water mark** (fresh uploads, interactive
  priority), then a **rotating window** of older ids (backfill priority), so a
  pass over a fully derived library of any size costs the same few queries.

A new kind, a recipe bump or "regenerate all" therefore needs no migration
code: the anti-join starts matching again and the reconciler works through the
library at backfill priority while uploads keep interactive priority.

## Producer groups

| Definition | Lane | Kinds | Produced from |
| --- | --- | --- | --- |
| `derivatives.mesh` | `derive.native` | `metadata` (geometry), `thumbnail` | One native mesh load (also hands similarity its fingerprints) |
| `derivatives.gcode` | `derive.light` | `metadata` (slicer facts, material requirements), `thumbnail` | One header read; no embedded image means `skipped` |
| `derivatives.toolpath` | `derive.native` | `toolpath` | The binary G-code converter, under resource limits |

A producer derives only the kinds still owed, records every outcome on the
kind's row, and tells viewers of the Model on `model:<id>` so an open page
refreshes when a thumbnail lands.

## Mesh rendering

The software renderer subtracts the mesh's bounding-box center in float64 before
converting relative coordinates to float32 for camera projection and shading.
Small geometry far from the origin therefore retains the precision provided by
3MF coordinates and transforms or other float64 sources. This does not restore
detail already lost when binary STL coordinates were written as float32. Source
Artifact coordinates and physical metadata are unchanged by rendering.

Only vertices referenced by triangle faces participate in framing, camera
selection and normal welding. The renderer compacts that surface in a private
view and remaps faces inside each existing chunk; unused source vertices remain
unchanged. Face indices must refer to the source vertex array.

Mesh thumbnail recipe 4 refreshes existing previews. Similarity uses view-descriptor
recipe 2 and fingerprint algorithm `geometry-v4-sh5f4577c4`. Search visual recipe 3
and the derived embedding-space rasterizer token `referenced-relative-f64-v2`
invalidate earlier rendered inputs and vectors. Encoder asset manifests and
their digests are unchanged.
Native encoder alignment has its own stable `encoder_space()` identity. Point
exports and search visual profiles use that identity to pair image/text towers;
a renderer update never requires rewriting preplaced Point manifests. Legacy
mesh-view inference uses `space()`, whose identity includes the rasterizer.
Thumbnail and multiview search vectors additionally carry their `VisualRecipe`,
so changed rendered inputs cannot reuse older derived vectors. Rebuild a search
generation after its rendering recipe changes; an incompatible generation is
not silently relabelled or reused.

Historical verifier calibration remains tied to its original fingerprint and
verification versions; it is not relabelled as a new measurement. Fingerprint
preparation already compacts referenced vertices, so unused-vertex rendering
does not change its contents, descriptor recipe or algorithm identity.

## Mesh volume measurements

Mesh metadata publishes a volume only for a closed surface with consistent
triangle winding and a finite, positive signed volume. STL facet vertices are
welded in a measurement copy; this does not repair winding or change the source
Artifact. Open or inconsistently wound surfaces retain their bounding dimensions
and triangle counts, with unknown (`null`) volume. A globally reversed surface
also retains unknown metadata volume under the positive-orientation policy.
Similarity fingerprints have a separate established policy: they report the
magnitude for consistently wound closed surfaces, including a global reversal,
and retain `volume_reason = inconsistent_winding` when winding is inconsistent.

These topology checks do not establish that a surface has no self-intersections,
and the integral is not a Boolean union of overlapping solids. STL coordinates
are assumed to be millimetres. Metadata recipe 4 recalculates existing measurements
to remove volumes previously published for inconsistently wound surfaces; the
fingerprint algorithm is unchanged.

## Bounded STL measurements

Mesh metadata recipe 6 refreshes existing measurements. An STL that exceeds the
full mesh/render cap can still supply exact bounding
coordinates and facet count to a metadata-only request. The scanner reads bounded
binary or ASCII blocks independently of thumbnail rendering, preserves ASCII
coordinates in float64, and accepts measurements only after a complete read of a
stable source. It does not validate closed topology, so volume remains unknown.

Binary STL requires exactly its declared records; trailing bytes, truncation and
non-finite vertices are rejected. ASCII accepts complete facets without an
`endsolid` line, ignores blank/comment lines, and rejects incomplete facets or
content after `endsolid`. Byte, facet, line and line-length limits still apply;
read errors, changed sources and budget refusals publish no complete measurements.
The preview worker shares this parser while retaining its existing float32
coordinate interpretation. Its temporary read-pass adapter remains
local to `stl_preview_worker`; fallback sampling and full mesh loading migrate to
the block iterator separately.

## Measurement precision

Mesh metadata recipe 5 stores dimensions and valid volume without rounding them
to two decimal places. Values remain in millimeters and cubic millimeters;
display formatting is a consumer concern. This preserves small parts and the
precision available from each source, including bounds obtained by complete STL
streaming and fallback scans. Existing rounded metadata is eligible for backfill.
Binary STL still carries float32 coordinates; removing output rounding cannot
recover precision already absent from the input. Volume retains the closure,
winding, finite-value and positive-orientation requirements of recipe 4.

## Bumping a recipe

The recipe constants in `app/modules/derivatives/kinds.py` are the code's
statement that a kind's output would now differ for the same bytes. Increase
one, by hand, in the change that alters what its producer emits: a new
renderer, a parser that reads a field it used to miss, a different encoding.
Do not bump for a refactor that cannot change any output. Every Artifact is
re-derived in the background, and its old output stays visible until the
replacement is ready.

## Adding a kind

1. Add the kind and its recipe constant to `kinds.py`, in the group whose
   producer can compute it from the bytes it already reads (or a new group with
   its own definition and lane).
2. Produce it in `producers.py`, recording `ready`, `skipped` or `failed`
   through `records`; decide which failures are deterministic.
3. Store the output with its owner, never in `artifact_derivatives`.
4. Treat it as unknown until ready wherever it is read.
5. Test the source (`pending` finds it), the producer (each outcome), the Job
   (convergence after commit) and the consumer's unknown case.

## Operating

- **Per Artifact:** the Model's Files tab shows what is still being prepared
  and what failed; an editor can retry a failure
  (`POST /api/v1/files/{id}/derivatives/{kind}/retry`).
- **Library-wide:** Settings → Background work offers, per kind, *Derive
  missing* (nudge only) and *Regenerate all* (every Artifact again, current
  outputs kept until replaced).
- **Audit repair:** a vault audit that finds a thumbnail missing from storage
  invalidates and re-derives it (`derivatives.repair`).

## Mesh geometry outcomes

Mesh replies carry a geometry outcome independently from thumbnail status.
A validated embedded preview can remain ready when geometry is refused. Refused
geometry records a failed metadata derivative, with terminal resource/malformed
input reasons; it does not publish a successful all-unknown measurement row.
Ready geometry can still have an unknown volume for an open mesh.

Metadata recipe 3 replaces the earlier output semantics. The ordinary bounded
Work Source backfills it. Terminal attempts stay exhausted across scans, nudges
and restarts for the same bytes and recipe. Explicit retry, changed content or a
new recipe makes work eligible; timeout backoff keeps the configured maximum.
Original downloads and signed slicer downloads continue to use Artifact bytes.


## On-demand 3D viewer STL

`viewer_stl` recipe 1 is produced by `derivatives.viewer_stl` in `derive.native`.
Only 3MF, OBJ and STEP Artifacts with `files.viewer_requested_at` set are eligible;
uploads, scans and card hover do not request conversion. The first authorized
`GET /api/v1/files/{id}/stl` (or the scoped share endpoint) persists this demand
and nudges the source. Reconciliation recovers it after a lost nudge or restart.
The active-Subject constraint shares work across requests.

Original STL is served directly. Other formats return 202 with `DerivativeRead`
and `Retry-After: 1` until publication, 200 with the stored representation when
ready, or 422 with the recorded failure `detail`. Preparation responses use
`private, no-store`. Resource and invalid-input refusals are terminal for the
recipe; timeouts/storage failures use bounded derivative backoff. Explicit retry
uses the existing derivative retry endpoint. Mesh processing policy gates new
work; published previews remain readable while disabled.

Ready STL objects use immutable owned publication and `storage_key`, so backup,
Vault migration and trash retain their existing ownership contracts. A missing
published object becomes eligible for repair. Legacy STL caches are regenerated
once on access. Original downloads and signed slicer handoff never depend on STL
preparation. The browser waits for STL bytes, displays persisted failures, and
refreshes authenticated previews after derivative completion or policy changes.

## Live processing policy

`modules/derivatives/policy.py` owns the three groups' database overrides and
frozen deployment defaults. Discovery, admission, manual actions and status
projection all consult it; process-local settings overlays do not decide live
policy. Definitions remain registered while disabled so historical Jobs remain
inspectable. `disabled` is a read projection, never a stored derivative state.

Admission locks the configuration singleton using a SQLite write transaction
or PostgreSQL row lock, then opens the derivative attempt in that transaction.
An admitted producer may finish after disablement. The producer repeats this
check on actual execution, including recovery replay; cached engine checkpoints
never grant permission for a new attempt.

The reconciler cancels queued, delayed, interrupted and retrying Jobs with
`derivative_group_disabled`. It preserves healthy execution and settles orphaned
in-flight derivative rows using normal failure/backoff rules. Policy cancellation
does not invoke the user cancellation hook or satisfy a missing derivative. It
does not count towards repeated-submission cooldown.

New regenerate-all markers are scoped to enabled producer definitions in
`derivative_group_regenerations`; earlier kind-wide markers remain readable.
This prevents a thumbnail regeneration from invalidating a disabled group's
outputs on later re-enablement. Nothing changes the recipes.

Administrator config updates accept a Boolean to save an override, explicit
`null` to inherit the environment, and omission to preserve it. Manual retries
and repairs return 409 `derivative_group_disabled` before changing rows.
Automatic audit repair leaves disabled findings unrepaired.

Stored thumbnails and metadata remain available. Binary toolpaths serve the
latest ready published output, including a prior recipe; missing outputs return
409 while disabled. The viewer stops polling until a policy notice or resync.
After commit, the event publisher emits a payload-free `derivative_policy`
notice on the authenticated `derivatives:policy` channel. Views refetch through
their authorized endpoints. Periodic reconciliation recovers lost notices or
nudges.

## Convex hull descriptor

The mesh dependency uses SciPy/Qhull for convex hull volume. The application
passes finite three-dimensional arrays through one array-to-scalar owner;
SciPy objects do not cross that boundary. Translation and scale normalization
precede the native calculation, and no coordinate perturbation is enabled.
Coplanar or degenerate input has an explicit unavailable descriptor. Nonfinite
input and an unrepresentable physical volume are rejected.

The input ceiling is `MAX_ANALYSIS_VERTICES` (6,000,000 points), before
preparation allocations. The old Python point/plane `max_work` counter is
removed; `max_points` bounds inputs, while the native worker supervisor enforces
wall-clock and RSS limits. The point ceiling alone is not a memory guarantee.

Fingerprint algorithm `geometry-v4-sh5f4577c4` separates new hull values and
newly available descriptors from the former Python hull recipe. Existing
fingerprints are recalculated without rewriting historical records or verifier
calibration. Mesh measurements and thumbnail recipes are unchanged.
