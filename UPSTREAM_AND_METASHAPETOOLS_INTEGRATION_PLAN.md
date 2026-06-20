# Upstream And MetashapeTools Integration Plan

## Current State

- Current branch: `integrate-metashape-tools-upstream-review`
- Current HEAD commit: `2d2debe90cbcd0df714be72799b65f4ca8c5edfe` (`2d2debe`)
- Plan assumption: `pure-pre-merge`
- This plan does not assume the later `recovery-fork-workflow` branch state.

Phase 0 status:

- Done: current fork procedural workflow is the implementation base for this plan.
- Done: `config/base.yml` style remains the assumed canonical fork config shape for the first implementation step.
- Done: upstream comparison target is `upstream/main`.
- Done: MetashapeTools reference target is `../MetashapeTools`.
- Open: repair current procedural syntax/config-path issues when code changes are allowed.
- Open: confirm the procedural full workflow imports and parses config.
- Open: confirm the mesh orthomosaic branch reads `buildOrthomosaic.orthoRes` correctly.
- Open: move mesh smoothing out of `build_point_cloud()` and into the mesh/model phase.
- Open: perform an end-to-end smoke run or equivalent Metashape-safe validation.

## Immediate Next Implementation Target

The first implementation phase is: integrate MetashapeTools Ortho+ mesh orthomosaic logic into the existing procedural workflow.

Do not integrate sparse optimization yet. Do not integrate the upstream class workflow. Do not migrate the config schema.

## Scope

This plan uses the current fork workflow as the base implementation, compares it against `upstream/main`, and uses `../MetashapeTools` as a tool and algorithm reference. The goal is not to replace the fork with upstream wholesale. The safer route is to keep the fork's procedural workflow working first, then selectively port upstream features and MetashapeTools-derived forest orthomosaic behavior behind explicit configuration.

The current fork keeps the legacy procedural runner:

```text
project_setup
enable_and_log_gpu
add_photos
calibrate_reflectance
align_photos
filter_points_usgs_part1
add_gcps
optimize_cameras
filter_points_usgs_part2
build_depth_maps
build_point_cloud
build_model
build_dem_orthomosaic
add_align_secondary_photos
export_report
finish_run
```

`upstream/main` has moved to a class-based `MetashapeWorkflow` with step-addressable execution, new config names, benchmark monitoring, JSON output path reporting, and Argo-oriented resource metadata. `../MetashapeTools` is mostly Metashape menu-script code, so it should be treated as an algorithm reference rather than imported directly into this command-line workflow.

## 1. Upstream Innovations

### Class-Based Workflow

`upstream/main` wraps workflow state in `MetashapeWorkflow` instead of passing `doc`, `log_file`, `run_id`, and `cfg` through standalone functions. This gives upstream a clear place to store:

- `self.doc`
- `self.cfg`
- `self.project_name`
- `self.log_file`
- `self.yaml_log_file`
- `self.written_paths`
- `self.benchmark`

This is useful, but it is also the largest structural difference from the fork. It should be integrated last, or not integrated at all until the procedural workflow is stable.

### Step-Based Execution

Upstream supports `--step` with named steps:

- `setup`
- `match_photos`
- `align_cameras`
- `build_depth_maps`
- `build_point_cloud`
- `build_mesh`
- `build_dem_orthomosaic`
- `match_photos_secondary`
- `align_cameras_secondary`
- `finalize`

This is a real improvement for long Metashape runs, Argo execution, and recovery after failed steps. The fork can adopt this concept without immediately adopting the full class rewrite by adding procedural step dispatch around existing functions.

### Split Photo Matching And Camera Alignment

The fork's `align_photos()` combines `matchPhotos()` and `alignCameras()`. Upstream splits these into:

- `match_photos()`
- `align_cameras()`

That split is valuable for MetashapeTools integration because the forest workflow needs a preliminary sparse pass, overlap reduction, and a second higher-quality sparse pass. Those operations map more cleanly when matching and alignment are explicit phases.

### New Config Format With Backward Migration

Upstream groups global settings under `project:` and renames old camelCase keys to snake_case:

- `addPhotos` -> `add_photos`
- `alignPhotos` -> `match_photos` plus `align_cameras`
- `addGCPs` -> `add_gcps`
- `filterPointsUSGS` -> `filter_points_usgs`
- `optimizeCameras` -> `optimize_cameras`
- `buildDepthMaps` -> `build_depth_maps`
- `buildPointCloud` -> `build_point_cloud`
- `classifyGroundPoints` -> `classify_ground_points`
- `buildModel` -> `build_mesh`
- `buildDem` -> `build_dem`
- `buildOrthomosaic` -> `build_orthomosaic`

Upstream also includes `is_old_config_format()` and `migrate_config_to_new_format()`. This is important if the fork eventually adopts upstream naming, because the fork currently relies on old top-level keys such as `photo_path`, `run_name`, and `buildOrthomosaic`.

### Benchmark Monitoring

Upstream adds `python/benchmark_monitor.py` and wraps Metashape API calls in benchmark contexts. It records runtime, CPU utilization, GPU utilization, process memory, container memory, system memory, available CPUs, GPUs, node, and GPU model. It writes both the existing human-readable log and a machine-readable YAML metrics file.

This is directly relevant for long forest orthomosaic runs because MetashapeTools-style prefiltering and mesh-based orthomosaic generation can change runtime and memory substantially.

### Progress Callbacks

Upstream adds `_make_progress_callback()` and passes `progress=` into heavy Metashape calls such as `matchPhotos()`, `alignCameras()`, and `buildDepthMaps()`. It emits percentage progress to stderr at `PROGRESS_INTERVAL_PCT`.

This should be ported with minimal behavior risk. It is especially useful for batch and cluster environments.

### Written Path Reporting

Upstream tracks output files in `self.written_paths` and prints them as JSON at the end of a run. This enables external workflow systems to discover products without parsing filenames from logs.

The procedural fork can adopt a simpler version by returning or appending written paths from export functions before a full class migration.

### GPU Handling

The fork enables the first GPU if no GPU mask exists and honors `use_cuda` / `gpu_multiplier`. Upstream enables all detected GPUs and removes the old CUDA and GPU multiplier config from the example. Both approaches have value:

- Keep the fork's explicit `use_cuda` and `gpu_multiplier` knobs because they were added for HPC stability.
- Consider upstream's all-GPU mask behavior as an optional config, not a hard replacement.

### Sensor Type And Paired Altitude Offset

Upstream adds:

- `add_photos.sensor_type`
- `add_photos.apply_paired_altitude_offset`
- `add_photos.paired_altitude_offset`
- `add_photos.lower_offset_folders`
- `add_photos.upper_offset_folders`

These are low-risk additions if kept optional. They belong in the fork's `add_photos()` phase after camera labels, sensor assignment, and RTK accuracy handling.

### Export And Product Improvements

Upstream adds or improves:

- point-cloud `export_format`, including COPC
- `build_mesh.shift_crs_to_cameras`
- mesh export metadata for local shifted CRS use cases
- output path tracking for exported products
- point cloud removal after export in `finalize`

These should be selectively ported after the fork's existing mesh and orthomosaic behavior is repaired.

## 2. Destructive Upstream Changes

These changes are "destructive" relative to the current fork because applying them directly would break existing fork configs, scripts, or workflow assumptions.

### Config Key Rename

Upstream's config format is not a drop-in replacement for the fork. The fork expects old top-level keys:

- `photo_path`
- `photo_path_secondary`
- `output_path`
- `project_path`
- `run_name`
- `project_crs`
- `subdivide_task`
- `use_cuda`
- `gpu_multiplier`
- `addPhotos`
- `alignPhotos`
- `buildModel`
- `buildOrthomosaic`

Upstream expects a nested `project:` section and snake_case processing sections. Direct replacement would break existing fork configs unless migration is installed first and every function reads the migrated shape.

### `run_name` Becomes `project_name`

The fork names outputs with timestamped `run_id` values such as:

```text
<run_name>_<YYYYMMDDTHHMM>
```

Upstream uses stable project names such as:

```text
<project_name>.psx
<project_name>_log.txt
```

This is a behavioral change. Stable names help step-based execution, but they can overwrite or collide with repeated full runs. The fork should preserve timestamped run IDs for full procedural runs unless step mode explicitly opts into stable project names.

### Full Class Rewrite

Replacing procedural functions with upstream's `MetashapeWorkflow` class in one merge would make the fork's current recovery work harder to audit. It would also obscure the MetashapeTools integration points, because the fork's current procedural chain is easier to map to the external tool phases.

### Split `alignPhotos`

Upstream splits `alignPhotos` into `match_photos` and `align_cameras`. That is an improvement, but it changes the meaning of `alignPhotos.enabled`, `alignPhotos.export`, and the timing of GCP/filter/optimize operations. The fork should preserve the old `align_photos()` wrapper until split steps are tested.

### Export Camera Config Moved

The fork stores camera export under:

```yaml
alignPhotos:
  export: true

optimizeCameras:
  export: true
```

Upstream uses:

```yaml
export_cameras:
  enabled: true
```

Direct adoption changes when camera XML is exported and whether optimize exports overwrite align exports.

### GPU Knob Removal

Upstream no longer exposes the fork's explicit `use_cuda` and `gpu_multiplier` settings in the example config. Removing these from the fork would discard existing HPC stability controls.

### Output File Naming And JSON Reporting

Upstream reports written paths as JSON and names outputs with `project_name`. The fork's output naming is `run_id`-based. Any integration must avoid silently changing filenames expected by downstream scripts.

### Benchmark Dependency Surface

Upstream introduces `psutil` and optional `pynvml`. This is useful but changes runtime dependencies. Add this only with dependency checks or graceful degradation.

### Upstream `manual_config_file`

Upstream points the interactive fallback to `config/config-base.yml`, while the current upstream tree contains `config/config-example.yml`. The current fork has `config/base.yml`. Do not adopt this path without resolving the expected config filename.

## 3. Relevant MetashapeTools Functions

`../MetashapeTools` should be mined for workflow logic, thresholds, and export ideas. It should not be imported directly without refactoring because functions assume `Metashape.app.document`, UI prompts, menu registration, and folder layouts such as `ortho/`, `report/`, `tlas/`, and `laz/`.

### Sparse Cloud Creation And Overlap Reduction

File: `../MetashapeTools/msFunctions/msSparseCloud.py`

- `createSparse(chunk, kpl=40000, tpl=4000, ds=1)`
  - Runs `matchPhotos()` with `keypoint_limit`, `tiepoint_limit`, `downscale`, and `reference_preselection=True`.
  - Runs `alignCameras(adaptive_fitting=True, reset_alignment=True)`.
  - Resets region.

- `fastCreateSparse(chunk, kpl=10000, tpl=1000, overl=8)`
  - Runs `analyzeImages()`.
  - Disables cameras with `Image/Quality < 0.75`.
  - Runs low-quality `matchPhotos()` and `alignCameras()`.
  - Builds a height-field model from tie points.
  - Smooths model with `smoothModel(10)`.
  - Runs `reduceOverlap(overlap=overl, use_selection=False)`.
  - Resets region.

- `filterSparse(chunk)`
  - Applies Reconstruction Uncertainty, Reprojection Error, and Projection Accuracy filters.
  - Optimizes cameras after each filter.

### Sparse Cloud Optimization With Checkpoints

File: `../MetashapeTools/msFunctions/msOptimizeSparsecloud.py`

- `pointcloudMetrics(chunk, outpath)`
  - Exports min, max, and mean values for Reconstruction Uncertainty, Reprojection Error, and Projection Accuracy.

- `optimizeSparsecloud(chunk)`
  - Optimizes cameras with explicit fit parameters.
  - Exports original marker errors.
  - Exports initial sparse cloud metrics.
  - Applies RU, RE, and PA filters.
  - Copies the chunk into a temporary processing chunk.
  - Iteratively lowers RE threshold while checkpoint error improves.
  - Removes temporary chunk and applies the second-best RE threshold to the real chunk.
  - Exports optimized marker errors and optimized point-cloud metrics.

This is the most important MetashapeTools logic for GCP/checkpoint-aware optimization. It should be rewritten into pure procedural functions that take `doc`, `log_file`, `run_id`, and `cfg`, not imported as-is.

### Mesh-Based Orthomosaic

File: `../MetashapeTools/msFunctions/msOrtho.py`

- `sparse2ortho(chunk, orthoRes)`
  - Resets region.
  - Builds height-field mesh from tie points.
  - Smooths model with `smoothModel(35)`.
  - Builds orthomosaic from `Metashape.ModelData`.
  - Uses `fill_holes=True`, `refine_seamlines=True`, and configured orthomosaic resolution.

- `exportOrtho(chunk)`
  - Exports orthomosaic.
  - Exports report.

This directly maps to the fork's current `build_model()` and `build_export_orthomosaic(..., from_mesh=True)` work.

### Dense Cloud

File: `../MetashapeTools/msFunctions/msDenseCloud.py`

- `createDenseCloud(chunk)`
  - Builds depth maps at downscale 4 with moderate filtering.
  - Builds point cloud with colors, depth retention, and confidence.
  - Exports LAZ with colors and confidence.

This overlaps with the fork's `build_depth_maps()` and `build_point_cloud()` phases.

### Error Exports

Files:

- `../MetashapeTools/msFunctions/msError.py`
- `../MetashapeTools/msFunctions/msExportTiepointError.py`

Relevant functions:

- `exportMarker(chunk)`
  - Exports marker reference/error data.

- `getPointCoords(chunk)`
  - Projects sparse/tie-point coordinates into chunk CRS.

- `getErrors(chunk)`
  - Gets RU, RE, PA, and Image Count values.

- `writeErrors(chunk, filename)`
  - Writes tie-point coordinates plus error metrics.

- `ExportTiepointError(chunk, filename=None)`
  - Wrapper for tie-point error export.

These should be added as optional diagnostics after alignment/filtering and after MetashapeTools-style sparse optimization.

### Forest Best-Practice Chains

Files:

- `../MetashapeTools/msFunctions/ms_Forest_BP_step1.py`
- `../MetashapeTools/msFunctions/ms_Forest_BP_step4.py`

Relevant workflow:

- Step 1, pre-GCP:
  - optional overlap reduction through `fastCreateSparse(overl=8)`
  - second sparse creation through `createSparse()`

- Step 3, optimize sparse cloud:
  - exposed through menu scripts and backed by sparse optimization functions

- Step 4, post-GCP:
  - `sparse2ortho()`
  - `exportOrtho()`
  - `exportMarker()`

This is the conceptual template for an optional fork workflow profile such as `forest_ortho`.

## 4. Mapping Into Existing Procedural Workflow

The current fork should remain the base. Integration points should be added as optional procedural functions, guarded by config, with old behavior preserved when disabled.

### Project Setup

Current function:

```text
project_setup(cfg, config_file)
```

Potential upstream additions:

- optional stable project naming for step mode
- optional YAML metrics path
- optional `written_paths` dictionary

Do not change default timestamped `run_id` behavior for full runs.

### GPU Setup

Current function:

```text
enable_and_log_gpu(log_file, cfg)
```

Potential upstream additions:

- optional all-GPU mask behavior
- benchmark header setup
- richer GPU logging

Keep:

- `use_cuda`
- `gpu_multiplier`

### Add Photos

Current function:

```text
add_photos(doc, cfg, secondary=False)
```

Potential upstream additions:

- `sensor_type`
- paired altitude offset
- improved multiple-initial-sensor removal for `separate_calibration_per_path`

MetashapeTools additions:

- optional image-quality analysis and disabling low-quality cameras before matching

Suggested config shape, while preserving old keys:

```yaml
addPhotos:
  sensor_type: Metashape.Sensor.Type.Frame
  analyze_quality:
    enabled: false
    min_quality: 0.75
```

### Match And Align Photos

Current function:

```text
align_photos(doc, log_file, run_id, cfg)
```

Recommended migration:

- first extract procedural `match_photos()` and `align_cameras()` helpers
- keep `align_photos()` as compatibility wrapper
- add progress callbacks to both calls
- add optional keypoint/tiepoint limits

MetashapeTools mapping:

- `fastCreateSparse()` becomes optional preliminary sparse pass:
  - analyze image quality
  - low-quality matching with `downscale=4`, low keypoint/tiepoint limits
  - align
  - build temporary height-field mesh from tie points
  - smooth 10
  - reduce overlap

- `createSparse()` becomes optional final sparse pass:
  - `keypoint_limit=40000`
  - `tiepoint_limit=4000`
  - `downscale=1`
  - align
  - reset region

Suggested procedural placement:

```text
if cfg["forestOrtho"]["pre_gcp_sparse"]["enabled"]:
    meta.forest_pre_gcp_sparse(doc, log, run_id, cfg)
else:
    meta.align_photos(doc, log, run_id, cfg)
    meta.reset_region(doc)
```

### USGS Filtering And Sparse Optimization

Current functions:

```text
filter_points_usgs_part1(doc, log_file, cfg)
filter_points_usgs_part2(doc, log_file, cfg)
optimize_cameras(doc, log_file, run_id, cfg)
```

MetashapeTools mapping:

- Keep USGS filtering as existing default.
- Add optional `optimize_sparse_cloud_checkpoint()` based on `optimizeSparsecloud()`.
- Run it after GCP/checkpoint import and before product generation.

Suggested placement:

```text
if cfg["addGCPs"]["enabled"]:
    meta.add_gcps(doc, cfg)
    meta.reset_region(doc)

if cfg["optimizeSparseCloud"]["enabled"]:
    meta.optimize_sparse_cloud_checkpoint(doc, log, run_id, cfg)
    meta.reset_region(doc)
elif cfg["optimizeCameras"]["enabled"]:
    meta.optimize_cameras(doc, log, run_id, cfg)
    meta.reset_region(doc)
```

This avoids running both optimizers by default and makes checkpoint-aware optimization a deliberate choice.

### Diagnostics And Error Exports

MetashapeTools functions should become optional export helpers:

- marker error export after `add_gcps()` and after sparse optimization
- tie-point error export after alignment/filtering
- point-cloud metric export before and after optimization

Suggested config:

```yaml
diagnostics:
  export_marker_errors: false
  export_tiepoint_errors: false
  export_sparse_metrics: false
```

Suggested procedural placement:

```text
if cfg["diagnostics"]["export_tiepoint_errors"]:
    meta.export_tiepoint_errors(doc, run_id, cfg, suffix="post-align")

if cfg["diagnostics"]["export_marker_errors"]:
    meta.export_marker_errors(doc, run_id, cfg, suffix="post-gcp")
```

### Depth Maps And Point Cloud

Current functions:

```text
build_depth_maps(doc, log_file, cfg)
build_point_cloud(doc, log_file, run_id, cfg)
```

Upstream additions:

- progress callbacks
- benchmark wrapping
- point-cloud export format selection
- output path tracking

MetashapeTools mapping:

- `createDenseCloud()` largely duplicates current functionality.
- The only immediately useful additions are point confidence export and clearer LAZ export options.

Important caution:

The current fork has `doc.chunk.smoothModel(cfg["noiterations"])` inside `build_point_cloud()`. `smoothModel()` applies to models, not point clouds. This looks like a misplaced MetashapeTools mesh smoothing step and should be moved to `build_model()` when code changes are allowed.

### Mesh Build

Current function:

```text
build_model(doc, log_file, run_id, cfg)
```

MetashapeTools mapping:

- `sparse2ortho()` builds a height-field model from tie points.
- It smooths model with 35 iterations for forest orthomosaic.

Fork-specific behavior already points in this direction:

- `surface_type=Metashape.HeightField`
- `source_data=Metashape.TiePointsData`
- `buildModel.noiterations: 35`

Recommended procedural behavior:

```text
if cfg["buildModel"]["enabled"]:
    meta.build_model(doc, log, run_id, cfg)
```

Inside `build_model()` when code changes are later allowed:

- build height-field mesh from configured source data
- smooth model with `cfg["buildModel"]["noiterations"]`
- export local/georeferenced mesh as existing fork requires

### DEM And Orthomosaic

Current functions:

```text
build_dem_orthomosaic(doc, log_file, run_id, cfg)
build_export_orthomosaic(doc, log_file, run_id, cfg, file_ending, from_mesh=False)
```

MetashapeTools mapping:

- mesh orthomosaic should be built from `Metashape.ModelData`
- use `refine_seamlines=True`
- use configured `orthoRes`
- export marker errors and reports optionally

Important fork repair target when code changes are allowed:

```text
resolution = cfg["orthoRes"]"
```

This should become:

```text
resolution=cfg["buildOrthomosaic"]["orthoRes"]
```

The mesh orthomosaic branch should run after a valid mesh exists. If `buildModel.enabled` is false and `buildOrthomosaic.surface` includes `Mesh`, the workflow should fail early with a clear prerequisite error.

### Secondary Photos

Current function:

```text
add_align_secondary_photos(doc, log_file, run_id, cfg)
```

Upstream split:

- `match_photos_secondary()`
- `align_cameras_secondary()`

This can be adopted later. For now, preserve the fork's behavior because it saves and restores the transform matrix around secondary alignment.

### Finalization

Current functions:

```text
export_report(doc, run_id, cfg)
finish_run(log_file, config_file)
```

Upstream additions:

- `finalize()` step
- output path JSON
- point-cloud removal after exports

MetashapeTools additions:

- marker error export
- report export after orthomosaic

Suggested behavior:

- keep existing report and log behavior
- optionally write a sidecar JSON manifest of produced paths
- do not replace log contents until benchmark logging is fully integrated

## 5. Integration Phases

### Phase 0: Stabilize Current Fork

Objective: make the current procedural fork runnable before adding new behavior.

Tasks:

- Repair syntax and config path issues in the current fork when code changes are allowed.
- Keep `config/base.yml` style as the canonical fork config during stabilization.
- Confirm the procedural full workflow can import and parse config.
- Confirm the mesh orthomosaic branch uses `buildOrthomosaic.orthoRes` correctly.
- Move model smoothing out of `build_point_cloud()` and into `build_model()`.

Exit criteria:

- The current procedural workflow imports.
- A dry import/check catches no syntax errors.
- Existing old-format configs still work.

### Phase 1: Low-Risk Upstream Ports

Objective: bring in upstream improvements that do not force a workflow rewrite.

Tasks:

- Add progress callback helper.
- Add optional benchmark monitor with graceful dependency handling.
- Add optional written-path tracking.
- Port sensor type support.
- Port paired altitude offset support.
- Improve separate calibration sensor handling for multiple initial sensors.
- Preserve `use_cuda`, `gpu_multiplier`, timestamped `run_id`, and old config keys.

Exit criteria:

- Default old-format fork workflow behavior is unchanged.
- New features are inert unless configured.

### Phase 2: Procedural Step Split

Objective: prepare for both upstream step execution and MetashapeTools sparse workflow without a class rewrite.

Tasks:

- Extract `match_photos()` from existing `align_photos()`.
- Extract `align_cameras()` from existing `align_photos()`.
- Keep `align_photos()` as a compatibility wrapper.
- Add optional `--step` dispatch around procedural functions.
- Add prerequisite checks for step mode only.

Exit criteria:

- Full workflow still follows the current fork sequence.
- Step mode can run at least setup, match, align, depth maps, point cloud, mesh, DEM/ortho, and finalize.

### Phase 3: MetashapeTools Diagnostics

Objective: integrate safe export/reporting helpers before changing the core algorithm.

Tasks:

- Add marker error export helper based on `exportMarker()`.
- Add tie-point error export helper based on `writeErrors()`.
- Add sparse metric export helper based on `pointcloudMetrics()`.
- Put diagnostics behind explicit config keys.
- Ensure output paths use `cfg["output_path"]` and `run_id`, not MetashapeTools' implicit project subfolders.

Exit criteria:

- Diagnostics can be enabled independently.
- Diagnostics do not change camera alignment or product generation.

### Phase 4: Forest Pre-GCP Sparse Workflow

Objective: add the MetashapeTools pre-GCP sparse/overlap reduction workflow as an optional mode.

Tasks:

- Add optional image quality analysis and camera disable threshold.
- Add preliminary sparse pass equivalent to `fastCreateSparse()`.
- Add overlap reduction parameter.
- Add second sparse pass equivalent to `createSparse()`.
- Log camera counts before and after quality filtering and overlap reduction.
- Keep default fork `align_photos()` path unchanged.

Suggested config:

```yaml
forestOrtho:
  enabled: false
  pre_gcp_sparse:
    enabled: false
    min_image_quality: 0.75
    fast_keypoint_limit: 10000
    fast_tiepoint_limit: 1000
    fast_downscale: 4
    overlap: 8
    mesh_smoothing_iterations: 10
    final_keypoint_limit: 40000
    final_tiepoint_limit: 4000
    final_downscale: 1
```

Exit criteria:

- Forest pre-GCP mode produces an aligned sparse cloud.
- Disabled cameras and overlap-reduced cameras are auditable in logs.
- Existing non-forest alignment remains unchanged.

### Phase 5: Checkpoint-Aware Sparse Optimization

Objective: port the most valuable `optimizeSparsecloud()` behavior without UI or global document assumptions.

Tasks:

- Add `optimize_sparse_cloud_checkpoint(doc, log_file, run_id, cfg)`.
- Export original marker errors and sparse metrics.
- Apply initial RU, RE, and PA filtering.
- Optimize cameras with explicit fit parameters controlled by config.
- Copy a temporary chunk for checkpoint threshold search.
- Compute checkpoint error from disabled reference markers.
- Find the best RE threshold without leaving temporary chunks behind.
- Apply selected threshold to the real chunk.
- Export optimized marker errors and sparse metrics.

Suggested config:

```yaml
optimizeSparseCloud:
  enabled: false
  reconstruction_uncertainty: 10
  projection_accuracy: 2.0
  reprojection_error: 1.0
  reprojection_error_step: 0.1
  require_checkpoints: true
```

Exit criteria:

- If checkpoints are missing, workflow either fails clearly or falls back according to config.
- Temporary chunks are always removed after success or failure.
- The chosen RE threshold and checkpoint error curve are logged.

### Phase 6: Mesh Orthomosaic Profile

Objective: align the fork's mesh and orthomosaic behavior with MetashapeTools ForestOrtho Step 4.

Tasks:

- Build height-field mesh from tie points when forest mesh mode is enabled.
- Smooth mesh with configured iterations, defaulting to 35 for forest mode.
- Build orthomosaic from `Metashape.ModelData`.
- Use `refine_seamlines=True`, `fill_holes=True`, and configured orthomosaic resolution.
- Export orthomosaic, marker error, and report.
- Require `buildModel.enabled` or an existing model when `buildOrthomosaic.surface` includes `Mesh`.

Suggested config:

```yaml
buildModel:
  source_data: Metashape.TiePointsData
  surface_type: Metashape.HeightField
  noiterations: 35

buildOrthomosaic:
  orthoRes: 0.05
  surface: ["Mesh"]
```

Exit criteria:

- Mesh orthomosaic output matches the intended MetashapeTools-style workflow.
- DEM-based orthomosaic paths still work independently.

### Phase 7: Upstream Config Migration And Optional Class Adoption

Objective: decide whether to keep the procedural fork or converge toward upstream's class structure.

Tasks:

- Add old-to-new config migration only after procedural behavior is stable.
- Support both old and new config keys during transition.
- Decide whether `run_name` remains primary or becomes an alias of `project_name`.
- Decide whether timestamped run IDs remain default for full runs.
- If adopting `MetashapeWorkflow`, port fork-specific and MetashapeTools-derived features into methods after they are already tested procedurally.

Exit criteria:

- Existing fork configs work.
- Upstream-style configs work.
- Filename behavior is explicit and documented.

## Recommended Order

1. Repair and stabilize the current procedural fork.
2. Port low-risk upstream features that do not change config shape.
3. Split match and align procedurally.
4. Add MetashapeTools diagnostics.
5. Add optional ForestOrtho pre-GCP sparse workflow.
6. Add checkpoint-aware sparse optimization.
7. Finish mesh orthomosaic profile.
8. Only then decide whether to migrate toward upstream's class-based architecture.

## Key Decisions To Make Before Implementation

- Whether old top-level fork config remains canonical, or whether upstream-style nested config becomes canonical.
- Whether full runs keep timestamped `run_id` output names.
- Whether ForestOrtho behavior is a single `forestOrtho.enabled` profile or several independent feature flags.
- Whether checkpoint-aware sparse optimization should replace or sit beside `filterPointsUSGS`.
- Whether all-GPU enabling should be default or config-controlled.
- Whether benchmark logging is required or optional when `psutil` / `pynvml` are unavailable.

## Summary

The safest integration path is incremental. Upstream contributes operational structure: step mode, progress reporting, metrics, path manifests, config migration, and useful add-photo options. MetashapeTools contributes photogrammetry strategy: image quality filtering, overlap reduction, two-pass sparse alignment, checkpoint-aware sparse optimization, tie-point diagnostics, marker-error exports, and mesh-based forest orthomosaics.

The fork should keep its procedural workflow as the base until these behaviors are isolated and tested. After that, the project can either remain procedural with upstream-inspired features or move toward upstream's `MetashapeWorkflow` class with much lower risk.
