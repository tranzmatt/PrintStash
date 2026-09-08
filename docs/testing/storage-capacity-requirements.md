# Issue 108 requirement traceability

Source: issue #108 and its attached “storage capacity policy and Artifact-type
insights” implementation plan. This audit covers the attachment phase by phase;
`Partial` and `Gap` are remaining required work, not deferrals.

| Requirement | Implemented evidence | Remaining work | Status |
|---|---|---|---|
| Phase 1: inventory taxonomy and current behavior | `ownership_snapshot()` plus SQL taxonomy covers every managed/private role, stable `File.file_type`, shared derived identities and representative local/remote evidence. The allocation census documents every writer and read-only exception. | None | Complete |
| Phase 2: typed inventory snapshot | Schema version 1 separates logical, unique-owned, external, temporary, provider and audit evidence. SQL aggregation, bounded reads, single-flight refresh and persisted degraded evidence keep interactive requests bounded. | None | Complete |
| Phase 3: physical/logical accounting | Artifact/lifecycle/resource buckets, retention cleanup estimates, provider measurement and latest aggregate audit evidence remain separate. Shared keys are identity-deduplicated and external bytes never enter owned totals. | None | Complete |
| Phase 4: provider capacity capability | The optional typed adapter contract includes method, reliability and time. Local roots use exact `statvfs`; adapters without a proven quota—including S3/WebDAV/SFTP—return unknown, and failed refresh retains stale/degraded evidence. | None | Complete |
| Phase 5: planned-operation estimates | Common resources cover upload/import, archives, backups, restore, migration, remote materialization, printer capture, thumbnail and mesh conversion. The allocation census records inherited and read-only paths. | None | Complete |
| Phase 6: admission and reservations | Structured 507 decisions, byte/percentage headroom, same-domain serialization, durable claims, renewal/release/reconciliation and bounded denial history are shared by every identified allocator. Unknown remote quota warns while unavailable local safety fails closed. | None | Complete |
| Phase 7: history and forecasting | Four category series retain hourly evidence for 14 days, daily evidence to 366 days, and expose window/confidence. Forecasts require stable positive evidence and prediction error uses label-free metrics. | None | Complete |
| Phase 8: UI and RBAC | Settings exposes freshness, buckets, forecast, audit evidence, reservations, blockers, paginated scoped Collection/Model rows and cleanup previews. Staging and rebuildable STL cache cleanup are confirmed/audited; trash and backup actions route to their existing owners. | None | Complete |
| Phase 9: metrics and health | Fixed-label inventory, capacity, reservation, denial, forecast and cleanup metrics plus detailed persisted-evidence health fields perform no provider walk on scrape. | None | Complete |
| Unit test plan | Policy/headroom, unknown-versus-zero, typed evidence, taxonomy, forecast/outliers, downsampling logic and label privacy are covered. | None | Complete |
| Integration test plan | SQLite/PostgreSQL serialization and upgrade, capacity capability states, single-flight/degraded evidence, allocation owners, audit evidence, RBAC and receipt-safe cleanup are covered. | None | Complete |
| E2E test plan | The real app reconciles every Artifact/resource/lifecycle category without shared-key double count, denies an upload at headroom, cleans verified staging, then accepts the retry; a non-admin sees only authorized Collection/Model totals. The real browser verifies explicit Settings confirmation. | None | Complete |
| Completion gate | Backend full/coverage/resource gates, frontend aggregate checks, OpenAPI, lint, typecheck and privacy assertions passed before the final cache-control addition; focused cache/UI/OpenAPI checks cover that addition and CI reruns the aggregate gates. | The formal security-diff scan was omitted by the user’s explicit request and is not reported as passed. | Complete with recorded exception |
