# Full Workflow Audit

Repository: `gisma/automate-metashape-2`  
Audit date: 2026-06-15  
Scope: read-only audit of the current checkout, locally fetched `origin/main`, locally fetched `upstream/main`, legacy files under `prior-versions/`, and neighboring `../MetashapeTools`.

## Executive Summary

The current checkout is not a clean adoption of upstream `open-forest-observatory/automate-metashape:main`. Local `main` tracks `origin/main`, and the working tree is clean, but local `origin/main` differs from local `upstream/main`.

The current checked-out workflow appears internally inconsistent:

- `python/metashape_workflow.py` is the older procedural workflow and imports `read_yaml`, but top-level `python/read_yaml.py` does not exist.
- `python/metashape_workflow_functions.py` contains a syntax error at line 915: `resolution = cfg["orthoRes"]"`.
- `config/config-example.yml` uses the newer upstream nested/snake_case schema, while the checked-out workflow expects older top-level/camelCase keys.
- `config/base2.yml` exists and preserves custom/fork-style Ortho+ parameters, but it is not present in `upstream/main`.
- `base2.yml` is only partially compatible with the current procedural code: it has `buildOrthomosaic.orthoRes`, while the code reads top-level `cfg["orthoRes"]`; it has `buildModel.noiterations`, while the code reads top-level `cfg["noiterations"]`.
- Upstream has a class-based `MetashapeWorkflow`, argparse CLI, step isolation, benchmark monitoring, old-config migration, output path reporting, and license wrapper integration assumptions. Those are largely absent or disconnected in the current checkout.

Conclusion: custom fork logic around mesh-based orthomosaic creation and `base2.yml` still exists, but it is partially disconnected and currently not runnable as checked out. The upstream workflow should likely be treated as the new base, with custom Ortho+/`base2.yml`/`MetashapeTools` behavior consciously re-integrated rather than relying on the current merged state.

## 1. Git And Repository State

Current branch:

- `main`, tracking `origin/main`
- `git status --short --branch` reported: `## main...origin/main`
- No modified, staged, or untracked source files were present before this audit file was created.

Remotes:

- `origin`: `https://github.com/gisma/automate-metashape-2.git`
- `upstream`: `https://github.com/open-forest-observatory/automate-metashape.git`

Local `origin/main` versus local `upstream/main`:

- They differ.
- `git diff --name-status origin/main upstream/main` reported:
  - `M README.md`
  - `D config/base2.yml`
  - `M prior-versions/metashape_v1.6-1.8/python/metashape_workflow_functions.py`
  - `M python/metashape_workflow.py`
  - `M python/metashape_workflow_functions.py`
- `git diff --stat origin/main upstream/main` reported 5 changed files, with `config/base2.yml` deleted on upstream.

Relevant current files:

- Present: `config/base2.yml`
- Present: `config/config-example.yml`
- Absent at top level: `config/base.yml`
- Absent at top level: `config/derived.yml`
- Absent at top level: `config/example.yml`
- Absent at top level: `python/read_yaml.py`
- Present only in legacy archive: `prior-versions/metashape_v1.6-1.8/python/read_yaml.py`
- Present only in legacy archive: `prior-versions/metashape_v1.6-1.8/R/prep_configs.R`
- Present: `python/benchmark_monitor.py`
- Present: `python/license_retry_wrapper.py`
- Present: `Dockerfile`
- Present: `.github/workflows/publish-image.yml`, `.github/workflows/black.yml`, `.github/workflows/isort.yml`

Neighbor repository:

- `../MetashapeTools` exists and is readable.
- It contains `msInterface.py`, `msFunctions/`, `docs/`, `README.md`, and project metadata.

## 2. Entry Points

### Primary Python Entry Point

Current checkout:

- `python/metashape_workflow.py`
- Intended usage from README: `python {repo_path}/python/metashape_workflow.py {config_path}/{config_file}.yml`
- Docker entrypoint: `python3 /app/python/metashape_workflow.py /data/config.yml`

Actual responsibility:

- The file starts the procedural workflow.
- It imports `metashape_workflow_functions` as `meta`.
- It attempts to import `read_yaml`.
- It parses the config via `read_yaml.read_yaml(config_file)`.
- It runs the ordered workflow calls directly.

Blocking findings:

- Top-level `python/read_yaml.py` is missing.
- `python/metashape_workflow_functions.py` has a syntax error, so import would fail before workflow execution.
- The stdin/TTY logic appears reversed for normal CLI use: `if sys.stdin.isatty(): config_file = sys.argv[1] else manual_config_file`. Non-interactive Docker/CI execution may ignore the provided argument and use the hard-coded manual path.

### Upstream Python Entry Point

Locally fetched `upstream/main` has a different `python/metashape_workflow.py`:

- Uses `argparse`.
- Supports `--config-file`, `--photo-path`, `--project-path`, `--output-path`, `--project-name`, `--project-crs`, and `--step`.
- Imports `MetashapeWorkflow` from `metashape_workflow_functions.py`.
- Supports full workflow or step-based execution.
- Redirects Metashape chatter to stderr and prints completed output paths as JSON.

This upstream entry point is not the current checked-out file.

### Docker Usage

`Dockerfile`:

- Base image: `nvcr.io/nvidia/cuda:12.8.1-runtime-ubuntu24.04`
- Installs Metashape 2.2.0 wheel, `PyYAML`, `psutil`, and `nvidia-ml-py`.
- Copies repository to `/app`.
- Sets `ENTRYPOINT ["python3", "/app/python/metashape_workflow.py"]`.
- Sets `CMD ["/data/config.yml"]`.

Risk:

- Docker currently calls the older procedural script, not the upstream argparse workflow.
- Because of the current import/syntax/config issues, this image would likely fail at startup unless source files are corrected.

### GitHub Actions

- `.github/workflows/isort.yml`: runs on pushes to `main`, installs `isort`, formats the repository, auto-commits, then calls Black and publish-image.
- `.github/workflows/black.yml`: workflow-call only, runs Black and auto-commits formatting changes.
- `.github/workflows/publish-image.yml`: builds and publishes a container image to GHCR.

Risk:

- Formatter workflows can modify source automatically on `main`.
- There is no workflow test that validates the Metashape workflow imports, config compatibility, or CLI behavior.

### README Entry Points

README currently documents older usage:

- `python {repo_path}/python/metashape_workflow.py {config_path}/{config_file}.yml`
- It refers to `config/example.yml`, `config/base.yml`, `config/derived.yml`, and `R/prep_configs.R`.

Current top-level repo does not contain those config files or `R/prep_configs.R`.

### Example Configuration Files

Current top-level config files:

- `config/base2.yml`: custom/fork-style, older top-level/camelCase schema.
- `config/config-example.yml`: newer upstream-style nested/snake_case schema.

Legacy config files:

- `prior-versions/metashape_v1.6-1.8/config/example.yml`
- `prior-versions/metashape_v1.6-1.8/config/base.yml`
- `prior-versions/metashape_v1.6-1.8/config/derived.yml`

## 3. Configuration System

### Current Checked-Out Parser

The current `python/metashape_workflow.py` expects:

- `from python import read_yaml` or `import read_yaml`
- `cfg = read_yaml.read_yaml(config_file)`

But `python/read_yaml.py` is absent. Therefore the current parser path is disconnected.

### Legacy Parser

`prior-versions/metashape_v1.6-1.8/python/read_yaml.py`:

- Uses `yaml.load(..., Loader=yaml.SafeLoader)`.
- Converts string values containing `Metashape` to Metashape objects with `eval`.
- Recurses nested dictionaries.

This file is archived only and is not importable by the top-level workflow without path changes.

### Upstream Parser

Locally fetched upstream has parser logic inside `MetashapeWorkflow.read_yaml()`:

- Loads YAML directly with `yaml.SafeLoader`.
- Detects old format via top-level keys such as `photo_path`, `project_path`, `output_path`, `run_name`, `project_name`.
- Migrates old camelCase/top-level config to new nested/snake_case config.
- Converts Metashape object strings.
- Applies CLI overrides.

This is a strong upstream modernization, but it is not present in the checked-out workflow file.

### Config File Inventory

| File | Role | Status | Key Parameters |
|---|---|---|---|
| `config/base2.yml` | Custom/fork run config | Current, fork/custom, not upstream | `load_project`, `photo_path`, `photo_path_secondary`, `output_path`, `project_path`, `run_name`, `project_crs`, `subdivide_task`, `use_cuda`, `gpu_multiplier`, `addPhotos`, `calibrateReflectance`, `alignPhotos`, `addGCPs`, `filterPointsUSGS`, `optimizeCameras`, `buildDepthMaps`, `buildPointCloud`, `classifyGroundPoints`, `buildModel`, `buildDem`, `buildOrthomosaic` |
| `config/config-example.yml` | Upstream example config | Current, upstream-style | `project.*`, `add_photos`, `calibrate_reflectance`, `match_photos`, `align_cameras`, `export_cameras`, `build_depth_maps`, `build_point_cloud`, `build_mesh`, `build_dem`, `build_orthomosaic`, `argo.*` |
| `prior-versions/.../config/base.yml` | Old v1.6-1.8 base config | Legacy | Top-level `photo_path`, `multispectral`, `run_name`, `buildDenseCloud`, `buildDem.type`, `buildOrthomosaic.surface`, USGS DEM path/CRS |
| `prior-versions/.../config/derived.yml` | Old batch overrides | Legacy | `####CONFIG_*####` blocks overriding base config |
| `prior-versions/.../config/example.yml` | Old example config | Legacy | Similar to legacy `base.yml` |

### Parameter Coverage

Project paths and image input:

- `base2.yml`: top-level `load_project`, `photo_path`, `photo_path_secondary`, `output_path`, `project_path`, `run_name`.
- `config-example.yml`: nested under `project`.

CRS:

- `base2.yml`: top-level `project_crs`, `addGCPs.gcp_crs`.
- `config-example.yml`: `project.project_crs`, `add_gcps.gcp_crs`.

Alignment:

- `base2.yml`: `alignPhotos` combines `matchPhotos` and `alignCameras`.
- `config-example.yml`: upstream split into `match_photos` and `align_cameras`.

Dense cloud / point cloud:

- `base2.yml`: `buildDepthMaps`, `buildPointCloud`.
- `config-example.yml`: `build_depth_maps`, `build_point_cloud`.

DEM:

- `base2.yml`: `buildDem.surface`, `resolution`, `export`, TIFF options, `nodata`.
- `config-example.yml`: `build_dem.surface`, `resolution`, `export`, TIFF options, `nodata`.

Orthomosaic / export:

- `base2.yml`: `buildOrthomosaic.surface`, `orthoRes`, `blending`, `fill_holes`, `refine_seamlines`, `export`, TIFF options, `nodata`, `remove_after_export`.
- `config-example.yml`: `build_orthomosaic.surface`, no `orthoRes` parameter.

GPU / memory / monitoring:

- `base2.yml`: `use_cuda`, `gpu_multiplier`; no Argo resource section.
- `config-example.yml`: Argo resource settings, GPU scheduling hints, memory requests.
- `benchmark_monitor.py`: resource sampling exists, but current checked-out procedural workflow does not import or use it.

License retry:

- `license_retry_wrapper.py` exists and expects to run `metashape_workflow.py`, monitor first output lines, retry on license errors, and optionally log subprocess output.
- Docker does not currently use the wrapper as entrypoint.

Logging:

- Current procedural workflow writes a text log per step via `with open(log_file, "a")`.
- Upstream adds machine-readable YAML metrics via `BenchmarkMonitor`.

## 4. Workflow Orchestration

### Current Checked-Out Intended Sequence

`python/metashape_workflow.py` intends this order:

1. Parse config with missing `read_yaml`.
2. `project_setup`
3. `enable_and_log_gpu`
4. `add_photos`
5. `calibrate_reflectance`
6. `align_photos`
7. `filter_points_usgs_part1`
8. `add_gcps`
9. `optimize_cameras`
10. `filter_points_usgs_part2`
11. `build_depth_maps`
12. `build_point_cloud`
13. `build_model`
14. `build_dem_orthomosaic`
15. `add_align_secondary_photos`
16. `export_report`
17. `finish_run`

Actual execution status:

- Not runnable as checked out because `read_yaml` is missing and `metashape_workflow_functions.py` has a syntax error.

### Ordered Step Audit

| Step | Function | File | Metashape API Calls | Config Parameters | Input | Output / Side Effects | Optional | Origin |
|---|---|---|---|---|---|---|---|---|
| Config parse | `read_yaml.read_yaml` | Missing top-level; legacy under `prior-versions/.../read_yaml.py` | N/A | Entire YAML | YAML file | `cfg` dict with Metashape strings converted | Required | Legacy/disconnected |
| Project setup | `project_setup` | `python/metashape_workflow_functions.py` | `Metashape.Document`, `doc.open`, `doc.addChunk`, `doc.save`, `Metashape.CoordinateSystem` | `output_path`, `project_path`, `run_name`, `load_project`, `project_crs`, `addGCPs.gcp_crs` | Config | `.psx`, text log, chunk CRS | Required | Older upstream/fork |
| GPU setup | `enable_and_log_gpu` | same | `Metashape.app.enumGPUDevices`, `gpu_mask`, `settings.setValue` | `use_cuda`, `gpu_multiplier` | Metashape app | GPU mask/log settings, CPU disabled for GPU steps | Required in script | Older upstream |
| Add photos | `add_photos` | same | `doc.chunk.addCameraGroup`, `addPhotos`, `addSensor`, `remove` | `photo_path`, `photo_path_secondary`, `addPhotos.*` | Image folders | Cameras, groups, labels, sensors, reference accuracies | Yes | Older upstream plus fork edits |
| Reflectance | `calibrate_reflectance` | same | `locateReflectancePanels`, `loadReflectancePanelCalibration`, `calibrateReflectance` | `photo_path`, `calibrateReflectance.*` | Photos + calibration CSV | Reflectance calibration | Yes | Older upstream |
| Align | `align_photos` | same | `matchPhotos`, `alignCameras`, `exportCameras` | `alignPhotos.*`, `subdivide_task` | Cameras | Tie points, aligned cameras, optional camera XML | Yes | Older upstream |
| Region reset | `reset_region` | same | `chunk.resetRegion` | none | Chunk | Enlarged region Z dimension | Called after alignment/GCP/filter | Fork/older upstream unclear |
| Filter points part 1 | `filter_points_usgs_part1` | same | `optimizeCameras`, `Metashape.TiePoints.Filter`, `removePoints` | `filterPointsUSGS.*`, `optimizeCameras.adaptive_fitting` | Tie points | Reduced sparse cloud, optimized cameras | Yes | Older upstream |
| Add GCPs | `add_gcps` | same | `addMarker`, marker projections/reference | `photo_path`, `addGCPs.*` | Prepared GCP CSV files | Markers, marker accuracies | Yes | Older upstream |
| Optimize cameras | `optimize_cameras` | same | `optimizeCameras`, optional `exportCameras` | `addGCPs.*`, `optimizeCameras.*` | Aligned cameras/GCPs | Optimized cameras, optional XML | Yes | Older upstream |
| Filter points part 2 | `filter_points_usgs_part2` | same | `optimizeCameras`, `TiePoints.Filter.ReprojectionError`, `removePoints` | `filterPointsUSGS.*` | Tie points | Reduced sparse cloud | Yes | Older upstream |
| Depth maps | `build_depth_maps` | same | `buildDepthMaps` | `buildDepthMaps.*`, `subdivide_task` | Aligned cameras | Depth maps | Yes | Older upstream |
| Point cloud | `build_point_cloud` | same | `buildPointCloud`, `smoothModel`, `exportPointCloud` | `buildPointCloud.*`, `project_crs`, `subdivide_task`; code also reads missing top-level `noiterations` | Depth maps | Point cloud, optional LAZ/LAS | Yes | Fork-modified/problematic |
| Ground classification | `classify_ground_points` | same | `point_cloud.classifyGroundPoints` | `classifyGroundPoints.*` | Point cloud | Ground class labels | Conditional | Older upstream |
| Mesh/model | `build_model` | same | `buildModel`, `exportModel` | `buildModel.*` | Tie points | HeightField model, local/georeferenced exports | Yes | Fork/custom overlap |
| DEM + ortho | `build_dem_orthomosaic` | same | `buildDem`, `exportRaster`, `buildOrthomosaic`, `remove` | `buildDem.*`, `buildOrthomosaic.*`, `project_crs`, `subdivide_task` | Point cloud/model | DEM TIFFs, ortho TIFFs, optional removal | Always called, internally conditional | Fork/custom |
| Ortho helper | `build_export_orthomosaic` | same | `buildOrthomosaic`, `exportRaster` | `buildOrthomosaic.*`; code incorrectly reads top-level `orthoRes` | Elevation/model | Orthomosaic, TIFF export | Conditional | Fork/custom, broken |
| Secondary photos | `add_align_secondary_photos` | same | `addPhotos`, `matchPhotos`, `alignCameras` via helper | `photo_path_secondary`, `alignPhotos.*` | Secondary image folder | Secondary cameras aligned | Conditional | Older upstream |
| Report | `export_report` | same | `exportReport` | `output_path` | Chunk | PDF report | Always | Older upstream |
| Finish log | `finish_run` | same | YAML safe load/dump | config file | Log file | Completion marker and config dump | Always | Older upstream |

### Error Handling

Current checked-out workflow:

- Minimal explicit error handling.
- Secondary photos raise `ValueError` if `reset_alignment` or `keep_keypoints` are incompatible.
- No top-level `try/except`.
- No step prerequisite validation.
- No completed-path JSON reporting.

Upstream:

- Catches exceptions in the entry point and exits non-zero after printing completed paths.
- Adds step prerequisite checks.
- Uses `license_retry_wrapper.py` for license retry when invoked by external tooling.

## 5. Ortho / DEM / Export Logic

### Current Ortho/DEM Logic

The current custom/fork logic is concentrated in:

- `config/base2.yml`
- `python/metashape_workflow.py`
- `python/metashape_workflow_functions.py:695-953`

DEM support:

- `DSM-ptcloud`: `buildDem(source_data=Metashape.PointCloudData)`
- `DTM-ptcloud`: `buildDem(source_data=Metashape.PointCloudData, classes=Metashape.PointClass.Ground)`
- `DSM-mesh`: `buildDem(source_data=Metashape.ModelData)`
- Projection: `Metashape.OrthoProjection()` with `projection.crs = Metashape.CoordinateSystem(cfg["project_crs"])`
- Export: `exportRaster(... source_data=Metashape.ElevationData, nodata_value=..., image_compression=...)`

Orthomosaic support:

- Mesh-based ortho can be built without DEM if `"Mesh"` is in `cfg["buildOrthomosaic"]["surface"]`.
- DEM-based ortho is built after each corresponding DEM if the same surface is requested.
- Surface data:
  - Mesh: `Metashape.ModelData`
  - DEM: `Metashape.ElevationData`
- Export: `exportRaster(... source_data=Metashape.OrthomosaicData, nodata_value=..., image_compression=...)`

Broken points:

- Syntax error: `resolution = cfg["orthoRes"]"` at `python/metashape_workflow_functions.py:915`.
- Wrong key path: `base2.yml` defines `buildOrthomosaic.orthoRes`; code reads `cfg["orthoRes"]`.
- Current code removes `doc.chunk.orthomosaics` after export if configured.
- Current code removes `doc.chunk.point_clouds` after DEM/ortho if `buildPointCloud.remove_after_export`.

### Upstream Ortho/DEM Logic

Upstream class-based workflow:

- Uses `build_dem` and `build_orthomosaic` snake_case config.
- Labels DEMs as `DSM-ptcloud`, `DTM-ptcloud`, or `DSM-mesh`.
- Iterates requested orthomosaic surfaces and activates the matching labeled DEM.
- For mesh surface, calls `build_export_orthomosaic(from_mesh=True, file_ending="mesh")`.
- Does not include an `orthoRes` parameter in the shown `buildOrthomosaic` call.
- Adds benchmark monitoring around each `buildDem`, `exportRaster`, `buildOrthomosaic`, and ortho `exportRaster` call.

### Evaluation

| Question | Finding |
|---|---|
| Does current workflow still support custom Ortho+ logic? | Conceptually yes: mesh-based orthomosaic via `buildModel`/`build_export_orthomosaic` exists. Practically no: import/syntax/config-key errors prevent execution. |
| Do relevant parameters still exist? | In `base2.yml`, yes: `buildOrthomosaic.orthoRes`, `surface`, blending, hole filling, seamlines, TIFF options, nodata. In `config-example.yml`, most exist except `orthoRes`. |
| Was workflow simplified by upstream? | Upstream changed architecture rather than simply simplifying: class-based orchestration, split match/align, step execution, metrics, old-config migration. |
| Was custom fork behavior lost? | Partially. `base2.yml` is absent from upstream; current custom code is not integrated with upstream class-based workflow. |
| Are MetashapeTools integration points present? | No imports or calls to `../MetashapeTools` were found in `automate-metashape-2`. |

## 6. Relationship To `../MetashapeTools`

Readable files found:

- `msInterface.py`
- `msFunctions/msOrtho.py`
- `msFunctions/msDenseCloud.py`
- `msFunctions/msSparseCloud.py`
- `msFunctions/msOptimizeSparsecloud.py`
- `msFunctions/gradual_selection.py`
- `msFunctions/msReproducibility.py`
- `msFunctions/msExportTiepointError.py`
- `msFunctions/msError.py`
- `msFunctions/msSubsetImages.py`
- `msFunctions/msPurgeImages.py`
- `msFunctions/ms_Forest_BP_step1.py`
- `msFunctions/ms_Forest_BP_step3.py`
- `msFunctions/ms_Forest_BP_step4.py`
- `msFunctions/msTC_09.py`

Relevant tools/functions:

- `msFunctions/msOrtho.py`
  - `sparse2ortho(chunk, orthoRes)`: resets region, builds HeightField model from tie points, smooths model, builds orthomosaic from `Metashape.ModelData` with explicit `resolution=orthoRes`.
  - `exportOrtho(chunk)`: exports orthomosaic TIFF and report to project-relative `ortho/` and `report/` folders.
- `msInterface.py`
  - Adds Metashape GUI menu items under `Ortho+`.
  - Exposes `Create Orthoimage`, `All-in-one Orthoimage-no-GCP`, dense cloud, sparse cloud, iterative filtering, marker/tiepoint exports, and reproducibility runs.
- `msOptimizeSparsecloud.py` and `gradual_selection.py`
  - Iterative sparse cloud filtering using reconstruction uncertainty, projection accuracy, reprojection error, camera optimization, marker/checkpoint error logic.
- `msDenseCloud.py`
  - Depth maps, point cloud creation, LAZ export.
- `msReproducibility.py`
  - Repeated sparse/mesh/ortho/export runs with fixed thresholds.

Imports/calls from `automate-metashape-2`:

- No `MetashapeTools` imports or calls were found.
- There is conceptual overlap, especially mesh-based orthomosaic creation, `orthoRes`, sparse cloud filtering/optimization, and export behavior.

Duplicated or missing logic:

- Duplicated concept: mesh-based ortho from sparse/tie-point-derived model.
- Duplicated concept: sparse cloud filtering and camera optimization.
- Missing integration: no direct reuse of `sparse2ortho`, `exportOrtho`, `optimizeSparsecloud`, or `gradualSelection`.
- Missing output conventions: `MetashapeTools` writes `ortho/` and `report/` relative to project; `automate-metashape-2` writes to configured `output_path`.

Likely integration points if Ortho+ is restored:

- Add a controlled, explicit Ortho+ step in the upstream `MetashapeWorkflow` class, not an implicit import from a neighboring relative path.
- Map `base2.yml` `buildOrthomosaic.orthoRes` into the new `build_orthomosaic` schema if fixed-resolution mesh ortho is required.
- Decide whether to replicate `sparse2ortho` behavior internally or vendor/import a stable module from `MetashapeTools`.
- Preserve output-path conventions from `automate-metashape-2` unless intentionally adopting `MetashapeTools` project-relative folders.
- Add config toggles for model source data, smoothing iterations, resolution, and export/report behavior.

## 7. Upstream Versus Fork Logic

| Change | Assessment |
|---|---|
| Removal of top-level `python/read_yaml.py` | Harmless only if upstream class parser is used. In current checkout it breaks execution. |
| New class-based `MetashapeWorkflow` upstream | Harmless/upstream modernization and likely best base. Current checkout has not adopted it. |
| New nested/snake_case config example | Upstream modernization. Current checked-out procedural workflow cannot read it. |
| `base2.yml` retained only in fork/current origin | Fork custom logic retained locally but deleted upstream. Needs conscious migration. |
| README still references `config/example.yml`, `base.yml`, `derived.yml`, `R/prep_configs.R` | Documentation is stale relative to current top-level files. |
| Removed top-level R batch config generation | Replacement by upstream config/CLI/Argo approach appears intended, but legacy functionality is only archived. |
| `benchmark_monitor.py` added | Upstream modernization, but disconnected from current procedural workflow. |
| `license_retry_wrapper.py` added | Upstream modernization, but Docker does not use it and current workflow startup is broken. |
| `Dockerfile` added/updated | Upstream modernization, but points at broken current entry point. |
| GitHub Actions formatter/publish workflows | Upstream modernization with risk of auto-format commits; no workflow correctness tests. |
| Current `build_dem_orthomosaic` custom code | Disconnected/recoverable fork logic; contains syntax and config-key errors. |
| MetashapeTools overlap | Conceptual overlap only; no direct integration. |

## 8. Risk Table

| File / function / workflow step | Role in workflow | Origin | Relevance for base2.yml / Ortho+ / MetashapeTools | Risk level | Finding | Recommendation |
|---|---|---|---|---|---|---|
| `python/metashape_workflow.py` | Main entry point | Legacy/fork current | High | Critical | Imports missing `read_yaml`; procedural architecture diverges from upstream; stdin logic may ignore CLI arg in non-interactive runs. | Rebase future work on upstream argparse/class entry point, then migrate custom behavior. |
| `python/metashape_workflow_functions.py:915` | Ortho build | Fork/custom | High | Critical | Syntax error prevents import. | Do not build on current file as-is; compare with upstream and re-integrate only intended custom lines. |
| `python/read_yaml.py` | Config parser | Legacy removed | High | Critical | Missing at top level but imported by current entry point. | Use upstream integrated parser/migrator or restore parser intentionally; avoid accidental dependency on legacy archive. |
| `config/base2.yml` | Custom config | Fork | High | High | Exists locally, deleted upstream; schema is old/camelCase and partly mismatched to current code. | Treat as source material for migration, not as a runnable config. |
| `config/config-example.yml` | Example config | Upstream | Medium | High | Uses upstream schema incompatible with current procedural script. | Accept with upstream class workflow; do not pair with current procedural script. |
| `build_point_cloud` | Dense point cloud/export | Fork-modified | Medium | High | Calls `doc.chunk.smoothModel(cfg["noiterations"])`; key not top-level in `base2.yml` and smoothing a model during point cloud step is suspect. | Verify intended Ortho+ smoothing placement before migration. |
| `build_model` | Mesh/model for ortho | Fork/custom overlap | High | Medium | Builds HeightField from tie points, similar to Ortho+ mesh-based ortho. | Preserve only if Ortho+ requires sparse/tie-point mesh ortho; otherwise use upstream `build_mesh`. |
| `build_dem_orthomosaic` | DEM/ortho/export | Fork/custom and upstream overlap | High | High | Contains custom multi-surface logic but lacks upstream DEM labeling/prerequisite/benchmark behavior. | Port custom resolution/surface behavior into upstream implementation after tests. |
| `benchmark_monitor.py` | Metrics | Upstream | Low | Medium | Present but unused by current workflow. | Retain with upstream base. |
| `license_retry_wrapper.py` | License retry/output monitor | Upstream | Low | Medium | Present but not Docker entrypoint; assumes argparse-style args for log path derivation. | Use with upstream CLI if Argo/container workflow needs retry. |
| `Dockerfile` | Container entry | Upstream | Medium | High | Runs broken current entry point directly. | After workflow migration, point entrypoint to either upstream script or wrapper intentionally. |
| README | User instructions | Legacy/current stale | Medium | Medium | References missing top-level files. | Update only after code/config direction is chosen. |
| `.github/workflows/isort.yml`, `black.yml` | Formatting automation | Upstream | Low | Medium | Auto-commits formatting, no import/config tests. | Add workflow correctness checks later; avoid relying on formatter workflows for validation. |
| `../MetashapeTools/msFunctions/msOrtho.py` | Ortho+ mesh ortho | External/fork-adjacent | High | Medium | Contains explicit `orthoRes` mesh orthomosaic logic not imported here. | Use as reference or formal dependency only after deciding integration boundary. |
| `../MetashapeTools/msOptimizeSparsecloud.py` | Sparse optimization | External/fork-adjacent | Medium | Medium | Richer iterative filtering than current USGS filters. | Compare thresholds and expected products before reintroducing. |

## 9. Current Actual Workflow Diagram

As checked out, the actual executable workflow stops before starting Metashape processing:

```text
CLI / Docker
  -> python/metashape_workflow.py
  -> import metashape_workflow_functions
  -> fails because python/metashape_workflow_functions.py has syntax error at line 915
```

The intended current procedural workflow is:

```text
YAML config
  -> missing python/read_yaml.py parser
  -> python/metashape_workflow.py
  -> project_setup()
  -> enable_and_log_gpu()
  -> add_photos()
  -> calibrate_reflectance()
  -> align_photos()
  -> filter_points_usgs_part1()
  -> add_gcps()
  -> optimize_cameras()
  -> filter_points_usgs_part2()
  -> build_depth_maps()
  -> build_point_cloud()
  -> build_model()
  -> build_dem_orthomosaic()
       -> buildDem/exportRaster for DSM-ptcloud, DTM-ptcloud, DSM-mesh
       -> build_export_orthomosaic()
       -> buildOrthomosaic/exportRaster for mesh or DEM surfaces
  -> add_align_secondary_photos()
  -> export_report()
  -> finish_run()
```

The locally fetched upstream workflow is:

```text
config/config-example.yml or migrated old YAML
  -> MetashapeWorkflow.read_yaml()
  -> optional old-format migration
  -> CLI overrides
  -> python/metashape_workflow.py argparse
  -> MetashapeWorkflow.run() or run_step()
  -> setup()
  -> match_photos()
  -> align_cameras()
  -> build_depth_maps()
  -> build_point_cloud()
  -> build_mesh()
  -> build_dem_orthomosaic()
  -> match_photos_secondary()
  -> align_cameras_secondary()
  -> finalize()
  -> benchmark_monitor text/YAML logs and JSON written-path output
```

## 10. Migration Assessment

What should likely be accepted as the new upstream base:

- The upstream class-based `MetashapeWorkflow` architecture.
- Upstream argparse CLI and `--step` execution.
- Upstream nested/snake_case `config/config-example.yml` schema.
- Upstream benchmark monitoring and output path reporting.
- Upstream old-config migration logic as the compatibility layer.
- Docker and license wrapper concepts, once entrypoint behavior is intentionally chosen.

Custom fork elements that must be consciously re-integrated:

- `config/base2.yml` semantics, especially project defaults and custom Ortho+ parameters.
- Fixed orthomosaic resolution behavior (`orthoRes`) if still required.
- Mesh/sparse-derived orthomosaic behavior inspired by `MetashapeTools/msOrtho.py`.
- Smoothing iterations, if truly part of the Ortho+ result.
- Any desired `MetashapeTools` sparse-cloud filtering/checkpoint-error workflow.
- Any output naming/path conventions from the fork.

Critical files:

- `python/metashape_workflow.py`
- `python/metashape_workflow_functions.py`
- `config/base2.yml`
- `config/config-example.yml`
- `python/benchmark_monitor.py`
- `python/license_retry_wrapper.py`
- `Dockerfile`
- `../MetashapeTools/msFunctions/msOrtho.py`
- `../MetashapeTools/msFunctions/msOptimizeSparsecloud.py`
- `../MetashapeTools/msInterface.py`

Minimal safe restoration strategy:

1. Start from locally fetched `upstream/main` workflow files as the executable base.
2. Treat `config/base2.yml` as migration input, not as a working config.
3. Add an explicit migration path or new schema fields for the fork-only parameters, especially `build_orthomosaic.orthoRes` if required.
4. Port only the smallest necessary Ortho+ behavior into upstream `MetashapeWorkflow.build_mesh()`, `build_dem_orthomosaic()`, or `build_export_orthomosaic()`.
5. Decide whether `MetashapeTools` is a reference implementation, vendored dependency, or external optional integration. Avoid implicit `../MetashapeTools` imports.
6. Add validation that catches: import success, config load success for `config-example.yml`, old/base2 config migration, and construction of expected step order.
7. Only after code behavior is stable, update README and Docker entrypoint to match the chosen workflow.

