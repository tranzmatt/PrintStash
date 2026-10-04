# Durable viewer STL acceptance — #259

Conversion starts on viewer access, never card hover. Failed previews retain their reason without compromising the original.

| # | Behaviour (test name) | Category | Precondition / input | Observable outcome asserted | Tier | Status |
|---|---|---|---|---|---|---|
| 1 | serves_original_stl | Happy | STL | Unchanged original bytes | Integration | ✅ `integration/api/v1/files/test_stl.py::TestFileAsStl::test_serves_an_stl_untouched` |
| 2 | persists_viewer_demand | Happy | First 3MF request | 202 and durable demand | Integration | ✅ `integration/api/v1/files/test_stl.py::TestFileAsStl::test_persists_viewer_demand` |
| 3 | shares_pending_conversion | Edge | Repeated requests | One active Job | Integration | ✅ `integration/api/v1/files/test_stl.py::TestFileAsStl::test_shares_pending_conversion` |
| 4 | does_not_convert_unopened_meshes | Edge | New mesh without viewer access | No viewer Job | Integration | ✅ `integration/api/v1/files/test_stl.py::TestFileAsStl::test_does_not_convert_unopened_meshes` |
| 5 | serves_placed_geometry | Happy | Real transformed 3MF | Correct STL bounds | Integration | ✅ `integration/api/v1/files/test_stl.py::TestFileAsStl::test_serves_placed_geometry` |
| 6 | retains_resource_refusal | Error | 3MF expands above cap | Persisted resource_limit, no automatic rerun | Integration | ✅ `integration/api/v1/files/test_stl.py::TestFileAsStl::test_retains_resource_refusal` |
| 7 | preserves_original_download | Error | Refused geometry | Original download unchanged | E2E | ✅ `e2e/test_ingest.py::TestMeshFailureRecovery::test_original_download_survives_viewer_failure` |
| 8 | permits_explicit_retry | Edge | Failed preview | Retry creates a new eligible attempt | Integration | ✅ `integration/api/v1/files/test_stl.py::TestFileAsStl::test_permits_explicit_retry` |
| 9 | reports_cancelled_preview | Error | Cancelled derivative | 422 cancelled, no renewed work | Integration | ✅ `integration/api/v1/files/test_stl.py::TestFileAsStl::test_reports_cancelled_preview` |
| 10 | honors_processing_policy | Error | Mesh processing disabled | 409 before demand | Integration | ✅ `integration/api/v1/files/test_stl.py::TestFileAsStl::test_honors_processing_policy` |
| 11 | serves_ready_preview_when_disabled | Edge | Published preview, processing disabled | Stored STL served | Integration | ✅ `integration/api/v1/files/test_stl.py::TestFileAsStl::test_serves_ready_preview_when_disabled` |
| 12 | denies_unauthenticated_preview | Error | No session | 401 without demand | Integration | ✅ `integration/api/v1/files/test_stl.py::TestFileAsStl::test_denies_unauthenticated_preview` |
| 13 | hides_trashed_preview | Error | Trashed Artifact | 404 without demand | Integration | ✅ `integration/api/v1/files/test_stl.py::TestFileAsStl::test_hides_trashed_preview` |
| 14 | repairs_missing_output | Error | Published output missing | New work becomes eligible | Integration | ✅ `integration/api/v1/files/test_stl.py::TestFileAsStl::test_repairs_missing_output` |
| 15 | recovers_demand_after_lost_nudge | Edge | Durable marker without hint | Source finds pending work | Integration | ✅ `integration/api/v1/files/test_stl.py::TestFileAsStl::test_recovers_demand_after_lost_nudge` |
| 16 | reports_worker_timeout | Error | Worker timeout | Persistent timeout reason with one attempt | Integration | ✅ `integration/api/v1/files/test_stl.py::TestFileAsStl::test_reports_worker_timeout` |
| 17 | reports_storage_failure | Error | Publication fails | Persistent storage reason | Integration | ✅ `integration/api/v1/files/test_stl.py::TestFileAsStl::test_reports_storage_failure` |
| 18 | honors_share_scope | Error | Shared link for other model | 404 without demand | Integration | ✅ `integration/api/v1/files/test_stl.py::TestFileAsStl::test_honors_share_scope` |
| 19 | prepares_shared_preview | Happy | Authorized share | 202 then stored STL | Integration | ✅ `integration/api/v1/files/test_stl.py::TestFileAsStl::test_prepares_shared_preview` |
| 20 | retains_library_on_upgrade | Edge | Populated old schema | Upgrade preserves files and Jobs | Integration | ✅ `integration/db/migrations/test_viewer_stl.py::TestViewerStlUpgrade::test_retains_library_on_upgrade` |
| 21 | shows_memory_refusal | Error | 422 resource_limit | Localized memory explanation | Frontend unit | ✅ `frontend/src/components/__tests__/stl-viewer.test.tsx::shows a memory refusal` |
| 22 | waits_for_prepared_bytes | Happy | 202 then 200 | Only STL reaches loader | Frontend unit | ✅ `frontend/src/lib/__tests__/use-stl-preview.test.ts::waits for prepared bytes` |
| 23 | stops_polling_terminal_failure | Error | 422 response | No renewed requests | Frontend unit | ✅ `frontend/src/lib/__tests__/use-stl-preview.test.ts::stops polling a terminal failure` |
| 24 | releases_browser_preview | Edge | Unmount during load | Abort and release blob URL | Frontend unit | ✅ `frontend/src/lib/__tests__/use-stl-preview.test.ts::releases the browser preview` |
| 25 | does_not_convert_on_hover | Edge | Hover model card | No /stl request | Frontend unit | ✅ `frontend/src/components/__tests__/model-card.test.tsx::does not convert on hover` |
| 26 | permits_slicer_after_viewer_failure | Error | Refused preview; vault, mounted or S3 original | Signed slicer download retains original bytes | E2E | ✅ `e2e/test_ingest.py::TestMeshFailureRecovery::test_signed_slicer_download_survives_viewer_failure` |
| 27 | retains_memory_refusal_after_reload | Error | Real expanding 3MF in browser | Refusal and recorded attempt survive reload | Playwright | ✅ `frontend/tests/e2e-real/viewer-stl.spec.ts::retains a memory refusal while keeping the original downloadable` |
| 28 | waits_for_artifact_hash | Edge | Unhashed mesh | 409 with no viewer demand | Integration | ✅ `integration/api/v1/files/test_stl.py::TestFileAsStl::test_waits_for_artifact_hash` |
| 29 | preserves_typed_worker_failure | Error | Worker failure frame | Exact typed reason crosses isolation boundary | Unit | ✅ `unit/modules/media/test_stl_isolation.py::TestReplyFrame::test_preserves_a_typed_failure` |
| 30 | rejects_malformed_worker_failure | Error | Unknown or non-ASCII reason | worker_failed rather than malformed bytes | Unit | ✅ `unit/modules/media/test_stl_isolation.py::TestReplyFrame::test_treats_a_malformed_reply_as_a_worker_failure` |
| 31 | converts_cached_obj_using_artifact_format | Happy | Materialized OBJ at .blob path | Job publishes a one-face STL | Integration | ✅ `integration/api/v1/files/test_cache_delivery.py::TestCacheDelivery::test_converts_cached_obj_using_artifact_format` |
| 32 | uses_a_separate_converted_validator | Edge | Original OBJ ETag on STL request | Published derivative has its own validator | Integration | ✅ `integration/api/v1/files/test_delivery.py::TestAuthorizedDelivery::test_uses_a_separate_converted_validator` |
| 33 | aborts_pending_load | Edge | Viewer unmounted before response | Request signal aborted | Frontend unit | ✅ `frontend/src/lib/__tests__/use-stl-preview.test.ts::aborts a pending load on unmount` |
| 34 | unopened_artifact_has_no_viewer_demand | Edge | Factory Artifact default | Demand is absent | Integration | ✅ `repo/test_factories.py::TestBuildFile::test_unopened_artifact_has_no_viewer_demand` |
| 35 | denies_preview_without_collection_access | Error | User without view permission | 403 without demand | Integration | ✅ `integration/api/v1/files/test_stl.py::TestFileAsStl::test_denies_preview_without_collection_access` |
| 36 | shares_concurrent_viewer_preparation | Edge | Four real HTTP requests for a new 3MF | One Job with one attempt produces the shared STL; browser renderer becomes ready | Playwright | ✅ `frontend/tests/e2e-real/viewer-stl.spec.ts::shares concurrent viewer preparation` |
| 37 | preview_blobs_are_allowed_by_frontend_csp | Edge | Production frontend security headers | Same-origin requests and owned Blob loads permitted | Unit | ✅ `repo/test_proxy_config.py::TestFrontendNginxConf::test_preview_blobs_are_allowed_by_frontend_csp` |
| 38 | preserves_step_triangle_refusal | Error | Real STEP above a one-face budget | Isolated worker reports resource_limit | Integration | ✅ `integration/modules/media/test_stl_isolation.py::TestToStlBytes::test_preserves_step_triangle_refusal` |
| 39 | does_not_hide_export_allocation_failure | Error | Export allocation failure | MemoryError reaches the worker supervisor | Unit | ✅ `unit/modules/media/test_stl_isolation.py::TestViewerResourceBounds::test_does_not_hide_export_allocation_failure` |
