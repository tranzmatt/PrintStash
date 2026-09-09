# Artifact cache behavior coverage

This matrix names requirement assertions. Execution results are recorded separately;
a named test is not a claim that its latest revision passed. Backend paths are relative
to `backend/tests/`.

| # | Behaviour (test name) | Category | Precondition / input | Observable outcome asserted | Tier | Status |
|---|---|---|---|---|---|---|
| 1 | Reuses server-side materialization | Happy | Same remote Artifact twice | One provider transfer | E2E | ✅ `e2e/test_artifact_cache.py::test_materialization_reuses_http_verified_content` |
| 2 | Reuses complete proxy download | Happy | Two canonical GETs | One provider transfer; equal bodies | E2E | ✅ `e2e/test_artifact_cache.py::test_repeat_proxy_download_transfers_provider_bytes_once` |
| 3 | Keeps redirect precedence | Edge | Warm cache; safe provider target | 307; no cache lease | Integration | ✅ `integration/api/v1/files/test_cache_delivery.py::TestCacheDelivery::test_redirect_precedes_cache_selection` |
| 4 | Coalesces concurrent materialization | Edge | Concurrent same-digest misses | One provider transfer | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestArtifactMaterializer::test_coalesces_concurrent_materialization` |
| 5 | Preserves selection before HTTP open | Edge | Clear after plan selects path | Selected bytes remain readable | Integration | ✅ `integration/api/v1/files/test_cache_delivery.py::TestCacheDelivery::test_selected_response_survives_clear_before_open` |
| 6 | Accounts for leased bytes | Edge | Clear during lease | Bytes counted until release | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestArtifactMaterializer::test_accounts_for_bytes_until_lease_release` |
| 7 | Excludes partial Range bodies | Edge | Cold Range request | 206; no complete entry | Integration | ✅ `integration/api/v1/files/test_cache_delivery.py::TestCacheDelivery::test_cold_range_does_not_publish_partial_representation` |
| 8 | Rejects corrupt fill | Error | Wrong length or digest | No entry or temp remains | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestArtifactMaterializer::test_rejects_corrupt_fill` |
| 9 | Rejects corrupt hit | Error | Changed cached file | Miss; error counted | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestArtifactMaterializer::test_rejects_corrupt_hit` |
| 10 | Samples preserved-metadata corruption | Error | Modified bytes; restored mtime | Rehash rejects entry | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestArtifactMaterializer::test_rehash_rejects_corruption_with_preserved_metadata` |
| 11 | Bypasses unavailable index | Error | Corrupt SQLite index | Source materialization succeeds | Integration | ✅ `integration/modules/storage/test_artifact_content.py::TestManagedCacheContent::test_unavailable_index_falls_back_to_source` |
| 12 | Preserves capacity during fallback | Error | Disabled cache; insufficient headroom | Capacity rejection; zero provider bytes | Integration | ✅ `integration/modules/storage/test_artifact_content.py::TestManagedCacheContent::test_fallback_does_not_bypass_capacity` |
| 13 | Excludes external sources | Edge | Linked mounted Artifact | Verified bytes; no cache entry | Integration | ✅ `integration/modules/storage/test_artifact_content.py::TestManagedCacheContent::test_external_sources_remain_outside_managed_cache` |
| 14 | Separates representation versions | Edge | Same digest; different representation version | Old entry misses | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestArtifactMaterializer::test_separates_representation_versions` |
| 15 | Disables without invalidating lease | Edge | Disable during active read | Existing path valid; no new fill | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestArtifactMaterializer::test_disable_preserves_existing_lease` |
| 16 | Applies shrinking limits | Edge | Shrink during fill | Publication revoked | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestArtifactMaterializer::test_shrinking_policy_revokes_oversized_fill` |
| 17 | Requires restart for root change | Edge | Save new root | Effective root unchanged; restart flag | Integration | ✅ `integration/api/v1/test_artifact_cache.py::TestArtifactCacheConfig::test_reports_root_restart_requirement` |
| 18 | Bounds fill memory | Edge | 64 MiB representation in small chunks | Peak Python allocation below 8 MiB | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestArtifactMaterializer::test_fill_uses_bounded_memory` |
| 19 | Preserves canonical metadata | Edge | Cold then cached response | Same validators and disposition | Integration | ✅ `integration/api/v1/files/test_cache_delivery.py::TestCacheDelivery::test_retains_canonical_metadata_on_cache_hit` |
| 20 | Manages Settings cache lifecycle | Happy | Save, reload, clear, reset | Persisted limits; empty idle usage; restored defaults | Playwright | ✅ `frontend/tests/e2e-real/artifact-cache.spec.ts::manages cache policy through Settings` |
| 21 | Keeps audits authoritative | Error | Warm cache; changed remote source | Full audit reports original hash mismatch | E2E | ✅ `e2e/test_artifact_cache.py::test_full_audit_detects_authoritative_corruption_behind_cache` |
| 22 | Reports corrupt disposable cache | Error | Changed cached representation | Corrupt observation; entry discarded | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestArtifactMaterializer::test_cache_audit_discards_corrupt_representation` |
| 23 | Recovers dead writer | Error | Claim belongs to previous process | Reserved bytes released; temp removed | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestArtifactMaterializer::test_recovers_abandoned_claim` |
| 24 | Recovers dead reader | Error | Lease belongs to previous process | Clear reclaims entry | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestArtifactMaterializer::test_recovers_abandoned_lease` |
| 25 | Recovers orphan publication | Error | Published file missing index row | Exact orphan removed | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestArtifactMaterializer::test_recovers_unindexed_publication` |
| 26 | Bounds concurrent fills | Edge | Fill slot already occupied | Second fill refused | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestArtifactMaterializer::test_bounds_concurrent_fill_count` |
| 27 | Bounds bytes while leased | Edge | Byte budget fully leased | New fill refused | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestArtifactMaterializer::test_bounds_bytes_while_leased` |
| 28 | Resets environment policy | Happy | DB override then reset | Environment values and source restored | Integration | ✅ `integration/api/v1/test_artifact_cache.py::TestArtifactCacheConfig::test_reset_restores_environment_defaults` |
| 29 | Denies nonadministrator controls | Error | Member requests clear | 403 | Integration | ✅ `integration/api/v1/test_artifact_cache.py::TestArtifactCacheConfig::test_denies_nonadministrator_changes` |
| 30 | Preserves configuration upgrade | Edge | Prior schema with EUR currency | Upgrade retains EUR; cache override null | Integration | ✅ `integration/db/migrations/test_artifact_cache_policy.py::TestArtifactCachePolicyMigration::test_preserves_existing_configuration_on_upgrade` |
| 31 | Closes unstarted streamed response | Edge | Primed provider; no body consumption | No open provider reader | Integration | ✅ `integration/modules/storage/test_artifact_content.py::TestManagedCacheContent::test_closes_primed_source_without_consuming_response` |
| 32 | Closes unstarted cached response | Edge | Selected lease; no body consumption | No outstanding lease | Integration | ✅ `integration/modules/storage/test_artifact_content.py::TestManagedCacheContent::test_closes_selected_cache_lease_before_first_read` |
| 33 | Converts cached mesh by declared format | Edge | Cached OBJ has private `.blob` filename | Binary STL contains the original triangle | Integration | ✅ `integration/api/v1/files/test_cache_delivery.py::TestCacheDelivery::test_converts_cached_obj_using_artifact_format` |
| 34 | Reads fresh cache policy | Happy | Repeated client reads | Two requests; current policy | Frontend unit | ✅ `frontend/src/lib/api/__tests__/artifact-cache.test.ts::reads current policy without reusing a prior response` |
| 35 | Saves complete cache policy | Happy | Client saves policy | PUT contains every policy field | Frontend unit | ✅ `frontend/src/lib/api/__tests__/artifact-cache.test.ts::persists the complete cache policy` |
| 36 | Reads defaults after client reset | Happy | Client reset | DELETE followed by fresh GET | Frontend unit | ✅ `frontend/src/lib/api/__tests__/artifact-cache.test.ts::reads effective defaults after resetting overrides` |
| 37 | Uses explicit cache clear action | Happy | Client clear | POST to clear endpoint | Frontend unit | ✅ `frontend/src/lib/api/__tests__/artifact-cache.test.ts::clears cache through the explicit clear action` |
| 38 | Falls back from exhausted cache quota | Edge | Cache quota exhausted; temporary volume available | Separately reserved temporary file; exact source bytes | Integration | ✅ `integration/modules/storage/test_artifact_content.py::TestManagedCacheContent::test_cache_capacity_denial_uses_separately_budgeted_temp` |
| 39 | Preserves other admission failures | Error | Reservation unavailable for noncapacity reason | Original error; zero source bytes | Integration | ✅ `integration/modules/storage/test_artifact_content.py::TestManagedCacheContent::test_noncapacity_admission_error_remains_visible` |

| 40 | Private sharded CAS | Edge | Published entry | 0600 body; 0700 private shard | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestCacheCompletionContract::test_shards_private_representation_files` |
| 41 | No-replace publication | Error | Existing destination | Existing bytes preserved | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestCacheCompletionContract::test_never_replaces_an_existing_publication` |
| 42 | Verified temporary fallback | Error | Publication fails | Same verified download; no second source transfer | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestCacheCompletionContract::test_uses_verified_temp_when_publication_fails` |
| 43 | Restores free-space headroom | Edge | Idle entries consume free bytes | Idle bodies evicted before admission | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestCacheCompletionContract::test_reclaims_idle_files_to_restore_headroom` |
| 44 | Stops fill under disk pressure | Error | Headroom disappears mid-fill | Write refused | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestCacheCompletionContract::test_fill_stops_when_headroom_is_lost` |
| 45 | Reports cache metrics | Happy | One fill and hit | Saved bytes, hit ratio and verification timestamp | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestCacheCompletionContract::test_reports_saved_bytes_with_verification_time` |
| 46 | Reports source mismatch during proxy | Error | Source bytes changed | Stream fails; corruption counted; no publication | Integration | ✅ `integration/modules/storage/test_artifact_content.py::TestManagedCacheContent::test_proxy_reports_integrity_failure_after_streaming` |
| 47 | Coalesces proxy readers | Edge | Concurrent canonical streams | One provider transfer | Integration | ✅ `integration/modules/storage/test_artifact_content.py::TestManagedCacheContent::test_coalesces_concurrent_proxy_readers` |
| 48 | Real printer consumer lease | Edge | Clear during upload | Provider reads exact leased bytes; final bytes zero | Integration | ✅ `integration/modules/storage/test_artifact_content.py::TestManagedCacheContent::test_printer_upload_keeps_cache_path_during_clear` |
| 49 | Real archive consumer reuse | Happy | Warm Artifact exported | Exact ZIP member; no second provider transfer | Integration | ✅ `integration/modules/storage/test_artifact_content.py::TestManagedCacheContent::test_archive_export_reuses_verified_artifact` |
| 50 | Hot Range and If-Range | Edge | Matching and stale validators | Canonical 206/200 body; zero further provider bytes | Integration | ✅ `integration/api/v1/files/test_cache_delivery.py::TestCacheDelivery::test_hot_range_preserves_canonical_if_range` |
| 51 | Revoked share cannot use cache | Error | Revoke previously authorized share | 404; no lease or source read | Integration | ✅ `integration/api/v1/files/test_cache_delivery.py::TestCacheDelivery::test_revoked_share_cannot_use_physical_cache` |
| 52 | Protects authoritative roots | Error | Cache root overlaps managed storage | Settings rejected | Integration | ✅ `integration/api/v1/test_artifact_cache.py::TestArtifactCacheConfig::test_rejects_authoritative_root_overlap` |
| 53 | Cache-specific health degradation | Error | Broken local index | Cache unhealthy; original storage unchanged | Integration | ✅ `integration/api/v1/test_artifact_cache.py::TestArtifactCacheConfig::test_health_marks_only_disposable_cache_degraded` |
| 54 | Reclaims after live shrink | Edge | Settings reduce byte budget | Idle entries eventually removed | Integration | ✅ `integration/api/v1/test_artifact_cache.py::TestArtifactCacheConfig::test_shrinking_policy_reclaims_idle_entries` |
| 55 | Recovers wholesale deletion | Error | Cache directory removed | Unavailable health; clean restart refills | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestPrivateCacheRecovery::test_wholesale_deletion_degrades_and_clean_start_recovers` |
| 56 | Rejects replaced root | Error | Root inode replaced | Clear cannot delete foreign directory contents | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestPrivateCacheRecovery::test_replaced_root_cannot_supply_or_delete_another_directory` |
| 57 | Rejects symlink index | Error | Index replaced by symlink | Foreign file never opened or modified | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestPrivateCacheRecovery::test_symlink_index_is_never_opened` |
| 58 | Rotates bounded verification | Edge | Two entries; inspection limit one | Both eventually hash verified | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestPrivateCacheRecovery::test_bounded_full_inspection_rotates_verified_entries` |
| 59 | Nonblocking maintenance | Edge | Filesystem unlink waits | Scheduling returns before unlink completes | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestPrivateCacheRecovery::test_maintenance_returns_before_unlink_finishes` |
| 60 | Cancelled ASGI cache response | Error | Cancel response before first body | Lease released; deferred clear completes | Integration | ✅ `integration/api/v1/files/test_cache_delivery.py::TestCacheDelivery::test_cancelled_asgi_send_releases_selected_cache_lease` |

| 61 | Digest and kind isolation | Edge | New database digest or transformed kind | Existing original entry misses | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestPrivateCacheRecovery::test_new_digest_and_kind_cannot_select_original_entry` |
| 62 | Restart retains verified files | Happy | Reopen local index | Exact cached bytes; zero provider reads | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestPrivateCacheRecovery::test_restarted_index_reuses_verified_entry` |
| 63 | Accounts for POSIX open unlinked bytes | Edge | Body unlinked while lease and descriptor active | Read succeeds; bytes counted through lease | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestPrivateCacheRecovery::test_unlinked_open_file_stays_accounted_until_lease_release` |
| 64 | Cleans failed index publication | Error | Hard-link succeeds; index commit fails | Unindexed body removed; verified temp remains usable | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestCacheCompletionContract::test_removes_publication_when_index_commit_fails` |
| 65 | Batches last-access updates | Edge | Repeated hit inside and outside coarsening window | Timestamp stays stable, then advances after window | Integration | ✅ `integration/modules/storage/test_artifact_materializer.py::TestCacheCompletionContract::test_batches_last_access_timestamp_updates` |
| 66 | Recovers maintenance polling | Error | One poll fails; next succeeds | Stale failure alert clears automatically | Component | ✅ `components/__tests__/artifact-cache-card.test.tsx::ArtifactCacheCard observability::clears a transient polling failure after polling recovers` |

## Focused execution

The coordinated cache run passed 61 backend tests (two workers), including the
actual remote-corruption audit and repeated-download E2E cases. Cached mesh
conversion regression checks passed 13 tests. Frontend component and API-client
checks passed four tests each. The real Settings browser lifecycle passed one
Chromium test against the actual backend. Its earlier failed attempts recorded
`net::ERR_NETWORK_CHANGED` during concurrent container teardown; the coordinated
stable-network rerun passed.

Frontend typechecking, owned-file lint, and the backend architecture check passed
with zero architecture debt. The expanded backend typecheck still reports 15
existing errors in `vault_audit.py`; the new cache modules pass their focused
check. Full suites, coverage ratchets, and combined API snapshot validation are
reserved for the coordinator's final integration gate.

The final conversion route file passed 10 tests. The exhausted-cache admission
regression failed with `storage_capacity_exceeded` before the fix, then the
managed-content group passed all 9 tests with the narrow capacity-only fallback.

The attachment completion pass added sharding, no-replace publication, verified-temp
fallback, proxy singleflight, pressure eviction, asynchronous live shrink, root
protection, health and UI observability. Its four focused backend files passed
77 tests, and component/API tests passed 11. Recovery followups cover ASGI
cancellation, root replacement, index symlinks and bounded verification rotation.
Consumer eligibility, deployment/recovery and reproducible performance measurements
are documented in [the cache design](artifact-cache-design.md).

Frontend observability assertions: ✅ policy source, hit ratio, bytes saved and
verification; ✅ pending reclamation; ✅ cache corruption distinguished from
authoritative storage (`ArtifactCacheCard observability` in the component test).
Full suites and coverage ratchets remain ⏭️ delegated to the integration coordinator.
