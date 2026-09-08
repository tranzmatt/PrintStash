# Issue 108 requirement traceability

Source: issue #108 and its attached “storage capacity policy and Artifact-type
insights” implementation plan. This audit covers the attachment phase by phase;
`Partial` and `Gap` are remaining required work, not deferrals.

| Requirement | Implemented evidence | Remaining work | Status |
|---|---|---|---|
| Phase 1: inventory taxonomy and current behavior | `ownership_snapshot()` census, SQL grouping by stable `File.file_type`, external-byte separation, shared-object identity de-duplication, local/remote fixtures | Explicitly inventory every private/temp root and document all shared-derived attribution rules | Partial |
| Phase 2: typed inventory snapshot | Typed aggregate/bucket/volume models, SQL aggregation, bounded 366-row history reads, no interactive remote walk | Version the schema; add resource/storage/ownership/Collection dimensions, audit/unclaimed evidence, freshness/warnings, and a TTL/single-flight provider measurement owner that preserves stale evidence on failure | Partial |
| Phase 3: physical/logical accounting | Logical, unique-owned, external, staging, backup, live/trash, primary/derived/embedded categories are kept distinct | Complete the resource-class taxonomy, retention eligibility, provider-unattributed/audit comparison, and labelled logical attribution for shared derived bytes | Partial |
| Phase 4: provider capacity capability | Local/mounted roots use `statvfs`; remote quota absence remains unknown rather than zero; absolute/percentage headroom is shared | Add structured `capacity()` to adapters, real quota-capable provider contracts, measurement source/reliability/freshness, and degraded last-known evidence on adapter failure | Partial |
| Phase 5: planned-operation estimates | Common `CapacityResource` estimates cover upload staging, archive import/export, backup, restore, migration and exercised cache paths | Cover thumbnail/conversion rebuild, audit materialization, every remote cache path, and document read-only/no-allocation exceptions | Partial |
| Phase 6: admission and reservations | Common policy, structured 507 mapping, same-volume de-duplication, durable serialized claims, renewal/release/restart reconciliation, and pre-read upload denial | Integrate and test every storage-heavy allocator; persist recent decisions/failures; define the safe admin-override contract for unknown capacity | Partial |
| Phase 7: history and forecasting | Daily aggregate samples are bounded to 366; minimum evidence, positive growth, unknown capacity, flat growth and outliers are tested | Retain short-term higher resolution then downsample; store category series; expose sample window/confidence and prediction error | Partial |
| Phase 8: UI and RBAC | Storage overview distinguishes logical/unique/external/temp, volumes/headroom, history and advisory forecast; Collection/Model drilldowns are RBAC-scoped and paginated; staging cleanup is confirmed and audited | Show freshness, full Artifact/lifecycle/resource charts, cleanup estimates, audit/unattributed warnings, active reservations and recent blockers; route trash/cache/backup cleanup to existing owners with previews | Partial |
| Phase 9: metrics and health | General storage health remains available | Add bounded inventory/capacity/forecast/cleanup metrics and detailed health fields for known/stale capacity, inventory age, headroom, forecast availability and recent failures without provider walks on scrape | Gap |
| Unit test plan | Policy edges, shared-domain headroom, reservation lifetime, forecast evidence/outliers and privacy-oriented aggregation have coverage | Add downsampling, full taxonomy and response/metric privacy cases for the completed schema | Partial |
| Integration test plan | SQLite/PostgreSQL reservation serialization, distinct roots, upload/backup/restore/migration admission, RBAC drilldowns and explicit cleanup have coverage | Add quota/no-quota/stale/error provider cases, inventory cache failure behavior, full cleanup-category isolation and audit-unattributed comparison | Partial |
| E2E test plan | Real app cleanup refreshes inventory; large upload is denied before body staging; non-admin Collection visibility is tested at the API | Seed and reconcile every Artifact/resource/lifecycle class through the UI, prove cleanup permits a later large upload, and add browser proof that inaccessible Collection/Model storage cannot be inferred | Partial |
| Completion gate | Focused backend tests and frontend unit/repository gates pass; lint and TypeScript are green | Finish the gaps above, run full backend/coverage/OpenAPI/browser gates, and complete security/privacy review | Pending |

The implemented slice is useful and fail-closed, but it does not yet satisfy the
attachment’s full completion gate. The public feature should not be described as
complete until every `Partial`/`Gap` row above is closed or the issue scope is
explicitly revised.
