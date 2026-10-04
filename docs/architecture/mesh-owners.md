# Mesh owners

Mesh operations have one owner each. Callers use these destination modules directly;
none imports the compatibility facade or thumbnail/analysis orchestration.

| Responsibility | Owner | Public operations |
| --- | --- | --- |
| Admission, format routing, source estimates, RAM/RSS budgets and reclamation | `app.modules.media.mesh_policy` | `RenderAdmission`, `render_admission`, `render_jobs_limit`, `canonical_suffix`, `estimate_triangle_count`, `detect_memory_limit_bytes`, `ram_triangle_cap`, `load_face_budget`, `exceeds_cap`, `process_rss_bytes`, `process_tree_rss_bytes`, `step_memory_budget_bytes`, `native_memory_budget_bytes`, `reclaim_memory` |
| Materialized source loading, isolated STEP conversion and STL export | `app.modules.media.mesh_loading` | `load_mesh`, `load_step_mesh`, `to_stl_bytes` |
| Source dimensions and signed volume evidence | `app.modules.media.mesh_measurements` | `geometry_from_mesh` |
| Bounded embedded 3MF preview extraction | `app.modules.media.mesh_previews` | `extract_embedded_3mf_thumbnail` |
| Typed request, measurement and thumbnail results | `app.modules.media.mesh_contracts` | Shared data contracts, `MeshMeasurements.unavailable` |
| Bounded 3MF source parsing and reachable resource ownership | `app.modules.media.three_mf_scene` | `read_scene` |
| Explicit materialized mesh preparation | `app.modules.media.mesh_resources` | `load_3mf`, `prepare_loaded_mesh` |

Admission gates and cached detected memory ceilings live only in `mesh_policy`.
Loading remains lazy and preserves scene placements. Measurements preserve source
precision and winding evidence. Embedded preview extraction keeps its archive and
image limits. New consumers enter the bounded isolation seams; only execution
owners call materialization, measurement or rendering primitives directly.

## Compatibility facade inventory

`app.modules.media.mesh_processing` is a temporary import facade. Its operation
aliases delegate to the owners above; its legacy `extract_geometry` wrapper projects
`MeshMeasurements.geometry`. It owns no mutable policy or native algorithms.

| Fixed consumer | Retained operation | Retirement condition |
| --- | --- | --- |
| `backend/tests/unit/modules/media/mesh_processing/test_entry_points.py` | `extract_geometry` | Remove these compatibility assertions with the facade |

There are no production consumers. The repo guard
`TestMeshFacadeInventory.test_only_fixed_legacy_consumers_import_the_facade` rejects
any new consumer. This inventory may shrink, and new code must use a destination
owner. The facade and its remaining tests are removed together after compatibility
retirement; they must not become an alternative implementation.

## Verification

The owner suites in `backend/tests/unit/modules/media/{mesh_policy,mesh_loading,
mesh_measurements,mesh_previews}/` retain the original policy, parser, measurement
and archive assertions at their actual owners. Engine integration assertions from
those suites live in `thumbnail_engine/test_processing.py`; the real-file guards
and reachability checks remain in
`backend/tests/integration/modules/media/test_mesh_processing.py`.

`backend/tests/repo/test_mesh_boundaries.py` also enforces one-way primitive
imports, canonical data-contract imports, safe isolation entry points and the
fixed facade inventory.

Result coverage, codec invariants and the complete behavior matrix are documented
in [mesh result contracts](../mesh-contracts.md).
