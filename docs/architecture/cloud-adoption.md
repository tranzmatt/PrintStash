# Deferred Cloud adoption of shared backend operations

This is a future implementation guide. The current backend refactor changes
PrintStash OSS only. No Cloud adapter, deployment, database change or shared-package
update is included in this delivery.

## Scope and first delivery

Keep common business rules in OSS's `backend/packages/printstash-core` and adopt
them through Cloud's existing upstream revision pins. Cloud retains its own
authentication, organizations, billing, quotas, PostgreSQL queries, S3 ownership,
durable workers, leases and transactional outbox. Do not copy OSS setup, mounted
libraries, local backup/restore or process-local scheduler infrastructure.

The first adoption should be one operation: deleting a live G-code Revision.
The canonical implementation already exists in
`printstash_core.library.delete_revision`, with an operation-specific
`RevisionUnitOfWork` protocol. Its initial upstream commit is
`dfceabfb2eec11d961381ff464ebcf438e40c31a`. Select and verify the desired upstream
revision when this work begins; do not assume Cloud still has the same base.

The shared operation:

1. Loads authorized, current state for one live Model and its live Artifacts.
2. Rejects missing Revisions and Artifacts that are not G-code.
3. Soft-deletes the selected Revision.
4. If it was recommended, promotes the surviving live G-code with the highest
   version. Deleting another Revision preserves the existing recommendation.
5. Clears thumbnail pointers only if they refer to the deleted Revision.
6. Stages the complete change and commits once.

It does not delete stored bytes. Cloud's existing trash lifecycle retains that
responsibility. ORM rows and framework exceptions must not cross into the core.

## Cloud adapter

Implement `backend/app/modules/library/revisions.py` with a SQLModel unit of work
and an operation entry point usable by both HTTP and workers. Keep the router's
current URL, response schema and business-error status codes.

| Port operation | Required Cloud behavior |
| --- | --- |
| Enter / exit | Use the caller's scoped session; roll back pending changes on any failed exit |
| `load(model_id)` | Require an active actor matching validated tenant context; select the live Model with an explicit tenant predicate and `FOR UPDATE`; check collection edit authority |
| Artifact snapshot | Select only this Model's live Files within the same tenant; return immutable `RevisionSnapshot` values |
| `apply(result)` | Soft-delete and clear the old recommendation, flush before promotion to respect the partial unique index, stage thumbnail changes and the Model timestamp |
| `commit()` | Commit the complete SQL operation once, including any required transactional events |

Use `populate_existing=True` for the locked Model and File reads. A caller's
session may already contain stale ORM rows from before another transaction
committed. A database lock alone does not refresh SQLAlchemy's identity map.

Do not obtain tenant authority from an arbitrary organization id passed by the
caller. Reuse Cloud's validated execution context and its membership checks.
Workers must install and validate that context before invoking the operation.
Retain Cloud's root-collection restrictions and scope every persistence access.

Translate `RevisionError.code` at the HTTP boundary. Preserve existing 400, 403
and 404 responses and return the existing Model detail projection after success.
Do not introduce a second implementation of recommendation rules in the router.

## Upstream package adoption

- Copy the complete canonical package, including its tests and
  `printstash_core_testkit.revisions.REVISION_EXAMPLES`; update
  `UPSTREAM_CORE_REVISION` to the exact source commit.
- Make a fresh-checkout pin check fetch an exact missing commit. A fixed release
  tag is insufficient when another revision is pinned.
- Verify all package files against that commit. Do not advance unrelated UI or
  domain pins to conceal independent differences.
- Review printer capability changes before upgrading the package. A new client
  capability does not automatically authorize that operation in Cloud; preserve
  product support policy and declare accepted print formats explicitly.
- Check current Cloud changes before editing. This guide does not imply that
  the adapter or shared-package upgrade is already present there.

## Acceptance matrix for the future delivery

These are required checks, not completed Cloud validation for the OSS refactor.

| # | Behaviour (test name) | Category | Precondition / input | Observable outcome asserted | Tier | Status |
|---|---|---|---|---|---|---|
| 1 | Shared Revision examples | Happy / Edge | Canonical testkit examples against the Cloud adapter | Same deletion, recommendation and thumbnail results as OSS | Integration / PostgreSQL | ⏭️ Deferred |
| 2 | Foreign tenant | Error | Resource belonging to another organization | Rejected without changing any File | Integration / PostgreSQL | ⏭️ Deferred |
| 3 | Actor/context mismatch | Error | Caller differs from validated tenant actor | Rejected without modification | Integration / PostgreSQL | ⏭️ Deferred |
| 4 | Inactive actor | Error | Worker calls the operation with an inactive actor | Rejected before mutation | Integration / PostgreSQL | ⏭️ Deferred |
| 5 | Insufficient collection role | Error | Actor can view but cannot edit | Existing forbidden result; no deletion | Integration / PostgreSQL | ⏭️ Deferred |
| 6 | Trashed resource | Error | Trashed Model or Revision | Existing not-found result; unchanged state | Integration / PostgreSQL | ⏭️ Deferred |
| 7 | Transaction rollback | Error | Commit fails after deletion and promotion are staged | Original recommendation, thumbnail and live File retained | Integration / PostgreSQL | ⏭️ Deferred |
| 8 | Concurrent deletions | Edge | Two real OS processes contend on the same Model row | Both deletions finish; the surviving G-code is recommended | Integration / two processes | ⏭️ Deferred |
| 9 | Cached ORM state | Edge | Session retained a File before another deletion committed | Promotion uses committed state, not cached recommendation flags | Integration / PostgreSQL | ⏭️ Deferred |
| 10 | HTTP compatibility | Happy / Error | Existing endpoint requests and OpenAPI snapshot | Existing response bodies and error statuses | API / Repo | ⏭️ Deferred |
| 11 | Exact source pin | Happy / Error | Fresh checkout, matching copy, source drift or invalid pin | Matching package accepted; drift and invalid revision rejected | Repo | ⏭️ Deferred |
| 12 | Stored bytes survive soft deletion | Edge | Revision with an owned blob | Blob remains available to the trash lifecycle | Integration / S3 | ⏭️ Deferred |

Run the complete Cloud backend suite against real PostgreSQL and S3 after the
focused checks. Two clients in one interpreter do not prove cross-replica
behavior. Keep startup preparation separate from measured delivery latency;
tests for lease expiry should control time instead of depending on millisecond
execution windows.

Deployment verification is a separate later step requiring available Cloud
infrastructure. Do not substitute OSS storage or identity fallbacks if it is
unavailable.

## Subsequent shared operations

Choose one concrete duplicated operation at a time. Define its inputs, results,
errors, transaction boundary and small persistence port; implement its rules
once in the core; adopt it in both products with the same contract examples.
Candidate areas are Revision metadata transitions, Artifact validation and print
job rules. Keep product-specific authorization, quotas and distributed execution
in their adapters. Sharing a filename or moving an ORM helper into the core does
not establish a reusable business boundary.
