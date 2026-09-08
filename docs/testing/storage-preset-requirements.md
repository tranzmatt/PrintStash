# Issue 102 requirement traceability

Sources: [issue 102](https://github.com/xiao-villamor/PrintStash/issues/102) and its
[implementation plan](https://github.com/user-attachments/files/31663983/printstash-storage-provider-expansion-implementation-plan.md).
The accepted delivery scope covers catalogue/preset/UI phases 1–3. Direct SMB,
Azure, GCS and new consumer OAuth adapters remain explicitly demand-gated.

| Requirement | Implementation | Evidence / gap | Status |
|---|---|---|---|
| Typed provider versus reusable transport | `storage_providers.StorageProvider`, typed provider configurations and `resolve_transport` | Provider schema/transport integration tests | Covered |
| Independent Vault/Library/backup roles | `uses`, `UseAvailability`, role-specific fields and connection purpose | `test_storage_providers.py`, source/backup transport contracts | Covered by transport; product-account validation remains explicit |
| Stable IDs, defaults, validation and secret redaction | Typed provider IDs, `provider_fields`, configuration owner | Integration provider tests and redacted connection responses | Covered |
| Existing 0.13 providers retained | Catalogue retains local/S3/R2/B2/Wasabi/self-hosted/Nextcloud/WebDAV/SFTP | Registry tests and existing transport contracts | Covered |
| NAS product presets and mount instructions | Synology/TrueNAS/QNAP/Unraid; documented WebDAV alternatives | Mounted-preset E2E and localized guidance tests | Covered for mounts; hardware certification not claimed |
| MinIO/Garage/SeaweedFS/Hetzner Object presets | Typed S3 presets and documented endpoint/addressing defaults | Parameterized real S3 transport tests using SeaweedFS | Preset mapping covered; no distinct real MinIO/Garage/hosted account evidence |
| Hosted-file presets | Hetzner Storage Box SFTP/WebDAV; Koofr WebDAV | Real transport contract mapping | Covered by transport; real browser save/reload/probe/scan/download passed |
| Product-first, role-sensitive forms | Provider picker and remote connection form use catalogue metadata | Three mock-API browser save cases and frontend field/guidance tests | Covered |
| Own-versus-index setup intent | Existing Vault/Library entry points and remote connection Use-for selection | Role-specific provider availability and fields follow the selected purpose; a unified wizard is not required | Covered |
| Support/runtime/safety/delivery diagnostics | `uses`, expected tier, availability, delivery descriptor and health probes | Catalogue and storage diagnostics tests | Covered; diagnostics use existing owner contracts |
| Localized provider setup guidance | `StorageProviderGuidance`, translated preset keys | Guidance component tests | Covered |
| Write-only encrypted credentials | Existing split/merge/sanitized configuration owner | Integration redaction tests; real browser checks persisted response and download | Covered |
| No new SMB/OpenDAL toggle | Direct SMB absent; mounts explicitly required | Public docs and catalogue absence | Accepted gated phase |
| Azure/GCS exact-generation promotion gates | No new Azure/GCS adapter advertised | Public scope/limitations | Accepted gated phases |
| Reusable OAuth and consumer-drive gates | No new consumer adapter or OAuth flow introduced | Existing Google Drive limits retained | Accepted gated phases |
| Native delivery through delivery seam | Catalogue declares transport-level potential, #101 owns execution | No new route-level preset branching | Covered |
| Role-first public provider matrix | Generated docs enumerate Vault, Library source and backup roles for every provider | Registry-backed documentation contract | Covered |
| Provider prerequisites, support/image/large-file/delivery/limitations docs | Each generated provider section records required fields, runtime packaging, large-object behavior, delivery and limitations | Registry-backed documentation contract | Covered |
| Real contract suite per advertised service | Every named ID maps to an existing transport exercised on pinned SeaweedFS, Nextcloud/WsgiDAV or OpenSSH services | Protocol behavior is proven; hosted-account/appliance certification remains explicitly unclaimed | Covered with stated evidence boundary |
| Headline E2E per shipped family | Mounted NAS setup/download plus parameterized S3, WebDAV and SFTP source/backup flows | Public API E2Es cover exact bytes; Koofr also passes a real-browser save/reload/probe/scan/download flow | Covered |
| Completion lint/types/tests/redaction | Preset, connection, transport, browser and documentation contracts | Focused gates pass; final full gates run in CI before merge | Pending final CI |
