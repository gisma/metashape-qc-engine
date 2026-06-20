# Current System Reference

## Status

This file is the code-derived technical reference for the current implementation. The source of truth is the implemented code, CLI wrappers, YAML schema, presets, CSV variant matrices, runner, analyzer, and evaluator. Existing documentation is contextual only unless confirmed by code or config.

## Scope

Implemented: product analysis for reproducible Agisoft Metashape orthomosaic candidate selection. The workflow prepares product-specific control files, runs repeated Metashape builds across variants and replicates, analyzes orthomosaic stability on a canonical grid, computes support diagnostics, and writes a selected-product trace.

Legacy implemented: direct single-config workflow execution and older wrapper names remain available through the CLI.

Absent/not supported as current benchmark claims: absolute geometric accuracy, GCP/checkpoint validation results, cross-date accuracy, change-detection suitability, platform comparison, dense/depth-map/DSM quality, 3D reconstruction quality, and building reconstruction quality.

Ambiguous: scientific interpretation of the selected product depends on external domain review and validation data that are not produced by the current implementation.

## Source-of-truth files

- `metashape_qc_engine/cli.py`
- `python/prepare_product_experiment.py`
- `python/reproducibility_runner.py`
- `python/evaluate_ortho_stability.py`
- `python/ortho_stability_analyzer.py`
- `python/metashape_workflow.py`
- `python/metashape_workflow_functions.py`
- `python/read_yaml.py`
- `config/base.yml`
- `config/legacy/base2_pre_migration_franzosenwiese.yml`
- `config/experiments/presets/*.json`
- `config/experiments/*.csv`
- `config/experiments/*.yml`
- `pyproject.toml`
- `scripts/*.sh`

## CLI surface

`metashape-qc prepare`

- Status: current.
- Purpose: generate a run-local `config.yml` and `variants.csv` from an image directory, product id, preset, replicate count, and output root.
- Key arguments: `--image-dir`, `--product-id`, `--preset`, `--reps`, `--output-root`, optional `--product-dir`, repeatable `--factor`, `--face-counts`, `--smoothing`, `--variant-id-template`.
- Source: `metashape_qc_engine/cli.py`, `python/prepare_product_experiment.py`.

`metashape-qc run-analysis`

- Status: current.
- Purpose: run variants and replicates into a run directory.
- Key arguments: positional `CONFIG`, `--reps`, `--run-dir`, legacy alias `--experiment-dir`, optional `--variants`, `--metashape-dir`, `--overwrite`.
- Source: `metashape_qc_engine/cli.py`, `python/reproducibility_runner.py`.

`metashape-qc resume-analysis`

- Status: current.
- Purpose: resume a product analysis by skipping successful variant/replicate combinations and rerunning failed or missing combinations.
- Key arguments: same as `run-analysis`; `--experiment-dir` remains a legacy alias for `--run-dir`.
- Source: `metashape_qc_engine/cli.py`, `python/reproducibility_runner.py`.

`metashape-qc evaluate`

- Status: current.
- Purpose: evaluate a completed run directory by running or reusing analyzer outputs, computing support and candidate tables, writing selected-product and review artifacts.
- Key arguments: positional `RUN_DIR`, optional `--skip-analyzer`, `--grid-mode`, `--bands`, `--stable-rmse-threshold`, `--no-overwrite`.
- Source: `metashape_qc_engine/cli.py`, `python/evaluate_ortho_stability.py`.

`metashape-qc run`

- Status: legacy implemented.
- Purpose: run one Metashape workflow config through `scripts/run_metashape_workflow.sh`.
- Key arguments: positional `CONFIG`, optional `--metashape-dir`.
- Source: `metashape_qc_engine/cli.py`, `scripts/run_metashape_workflow.sh`.

`metashape-qc experiment`

- Status: legacy implemented wrapper.
- Purpose: run reproducibility replicates through the same runner used by `run-analysis`.
- Key arguments: positional `BASE_CONFIG`, `--reps`, `--experiment-dir`, optional `--variants`, `--metashape-dir`, `--overwrite`, `--resume`.
- Source: `metashape_qc_engine/cli.py`, `python/reproducibility_runner.py`.

`metashape-qc analyze`

- Status: legacy/direct implemented wrapper.
- Purpose: run the orthomosaic stability analyzer directly from a manifest.
- Key arguments: positional `MANIFEST`, `--output-dir`, optional `--grid-mode`, `--reference-ortho`, `--bands`, `--stable-rmse-threshold`, `--overwrite`.
- Source: `metashape_qc_engine/cli.py`, `python/ortho_stability_analyzer.py`.

## Prepare stage

Implemented behavior:

- Validates that `--image-dir` exists and is a directory.
- Requires at least one supported image file in the image directory.
- Supported image extensions are `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.png`, and `.dng`, case-normalized by suffix.
- Reads a preset JSON file.
- Requires preset fields `template_config`, `template_variants_csv`, `experiment_dir_template`, `variant_id_template`, and `factors`.
- Requires generated-template top-level config keys `load_project`, `photo_path`, `output_path`, `project_path`, and `run_name`.
- Writes run-local `config.yml`.
- Writes run-local `variants.csv`.
- Expands the Cartesian product of effective factor values.
- Prints the generated config path, variants CSV path, run directory, variant count, replicate count, total runs, and a `metashape-qc run-analysis` command.
- Does not start Metashape.

The preset field is still named `experiment_dir_template` internally. User-facing output from prepare prints `Run directory`. Generated paths are resolved under the supplied `--output-root` unless the template itself yields another path.

`--factor COLUMN=VALUE1,VALUE2,...` replaces or adds a factor column. The target column must already exist in the template variants CSV. `--face-counts` is a shortcut for `buildModel.face_count_custom`. `--smoothing` is a shortcut for `buildModel.noiterations`.

`variant_id_template` is rendered from factor values. Placeholders use `{factor.name}`. A `:k` suffix formats integer values divisible by 1000 as three-digit thousands, for example `50000` to `050k`. Generated IDs are sanitized to letters, numbers, underscore, dot, and hyphen, and duplicate generated IDs are rejected.

## Run-analysis and resume-analysis

Implemented behavior:

- Reads the base YAML config with `yaml.safe_load`.
- Reads the variants CSV when provided; otherwise uses one `default` variant with no overrides.
- Requires `--reps >= 2` for runner execution.
- Parses CSV values with YAML semantics where possible. Empty, `null`, `none`, and `na` values are skipped.
- Applies CSV override columns as dotted YAML keys.
- Creates per-variant and per-run subdirectories under `<run_dir>/variants/<variant_id>/`.
- Creates replicate configs under `<run_dir>/variants/<variant_id>/configs/`.
- Creates replicate project/output directories under `<run_dir>/variants/<variant_id>/runs/<run_label>/`.
- Forces each replicate config to use `load_project: ""`.
- Rewrites `run_name`, `project_path`, and `output_path` per replicate.
- Calls `scripts/run_metashape_workflow.sh <rep_config>`.
- Writes launcher stdout/stderr to each run's `launcher.log`.
- Appends rows to `<run_dir>/manifest.csv`.
- Continues after failed replicates.
- Returns nonzero if any new failed replicate occurred.

Resume behavior:

- Reads existing manifest rows when present.
- Treats `ok` and `ok_no_ortho` rows as resumable successes only when required path fields are present.
- Skips successful variant/replicate combinations.
- Reruns failed or missing combinations.
- Preserves manifest history by appending new rows.
- Uses attempt labels such as `rep_001_attempt_002` when rerunning an existing replicate key.

## Manifest contract

The runner writes these manifest columns:

- `experiment_id`
- `variant_id`
- `replicate`
- `status`
- `return_code`
- `config_file`
- `project_dir`
- `output_dir`
- `project_file`
- `ortho_file`
- `launcher_log`
- `elapsed_sec`

Status semantics:

- `ok`: launcher returned `0` and an `*ortho*.tif` file was found in the replicate output directory.
- `ok_no_ortho`: launcher returned `0` but no orthomosaic TIFF was found.
- `failed`: launcher returned nonzero.

The analyzer uses only manifest rows with `status == "ok"`, a non-empty `ortho_file`, and an existing raster file.

## Evaluation stage

Implemented behavior:

- Uses `<run_dir>/stability_union` as the evaluation/analyzer output directory.
- Runs `python/ortho_stability_analyzer.py` unless `--skip-analyzer` is supplied.
- Reads `stability_union/summary.csv`.
- Reads `<run_dir>/manifest.csv`.
- Computes support metrics from per-variant `valid_count.tif`.
- Builds compact candidate rows.
- Ranks continuous stability, threshold quality-flag, and support-persistence candidates.
- Writes `stability_union/summary_key_metrics.tsv`.
- Writes `stability_union/support_valid_count_histogram.tsv`.
- Writes `stability_union/qgis_layers.txt`.
- Writes `stability_union/evaluation_report.md`.
- Writes `<run_dir>/selected_product.json`.
- Writes threshold review rasters and TSVs when thresholds are enabled.
- Writes POSIX and Windows QGIS launcher scripts.

Default evaluator settings are `grid-mode=union`, `bands=3`, `stable-rmse-threshold=15.0`, and threshold review values `5,10,15,20,25,30`.

## Analyzer/stability products

The analyzer aligns successful orthomosaics onto one canonical grid. Grid modes are:

- `union`: combined extent of all usable orthomosaics.
- `intersection`: common overlapping extent.
- `reference`: extent of the reference orthomosaic; if no explicit reference is provided, the first usable ortho is used.

Compatibility checks require matching projection and effectively matching x/y resolution. Rotated or sheared geotransforms are rejected.

Analyzer outputs:

- `stability_union/canonical_grid.json`
- `stability_union/summary.csv`
- `stability_union/aligned/<variant_id>/<replicate>_aligned.tif`
- `stability_union/variants/<variant_id>/valid_count.tif`
- `stability_union/variants/<variant_id>/median_ortho.tif`
- `stability_union/variants/<variant_id>/mad_rgb.tif`
- `stability_union/variants/<variant_id>/rmse_to_median.tif`
- `stability_union/variants/<variant_id>/stable_mask_rmse<THRESH>.tif`
- `stability_union/variants/<variant_id>/unstable_mask_rmse<THRESH>.tif`

Metrics include support counts, median RGB orthomosaic, median absolute deviation to the median by RGB band average, RMSE to the median, and stable/unstable fractions under the configured RMSE threshold. Stable masks require full support across replicates and RMSE at or below the threshold. Unstable masks cover supported pixels that do not meet that stable condition.

## Selection logic

The selected product is a trace of the implemented selection procedure, not a claim of absolute truth.

Continuous stability candidate:

- Primary ranking.
- Sort key: lower `p95_rmse_to_median`, lower `mean_rmse_to_median`, lower `p95_mad_rgb`, lower `mean_mad_rgb`.

Threshold quality-flag candidate:

- Guard/context ranking.
- Sort key: higher `stable_fraction_support_rmse`, then lower `unstable_fraction_support_rmse`.
- Depends on the selected RMSE threshold.

Support-persistence candidate:

- Guard/context ranking.
- Sort key: lower `support_dropout_footprint`, lower `variable_support_fraction_grid`, higher `support_persistence_footprint`.

`selected_product.json` uses `selection_policy: continuous_first`. It records the primary variant, selected median orthomosaic path, optional medoid original replicate, support context, threshold guard context, source files, and warnings. Warnings are added when support-persistence or threshold candidates differ from the continuous-stability primary variant, or when medoid scoring cannot be completed.

## QGIS review artifacts

Implemented launchers:

- `<run_dir>/qgis_open_selected.sh`
- `<run_dir>/qgis_open_selected.bat`
- `<run_dir>/qgis_open_threshold_review.sh`
- `<run_dir>/qgis_open_threshold_review.bat`

Selected launchers include existing selected-variant layers such as median orthomosaic, RMSE-to-median, valid count, threshold quality flag, and medoid replicate paths when available. Threshold launchers include selected-variant median/RMSE/valid-count layers and all generated threshold quality flags.

## Runtime workflow schema

The active runtime schema is the flat/camelCase YAML schema used by `config/base.yml` and `config/experiments/*.yml`. The active runner is procedural and does not use an upstream class workflow.

`python/read_yaml.py` loads YAML with `yaml.SafeLoader`, then converts string values containing `Metashape` into live Metashape objects with `eval()`, except for keys containing `path`, `project`, or `name`. Lists containing Metashape object strings are converted to lists of evaluated Metashape objects.

Active function order in `python/metashape_workflow.py`:

1. `project_setup`
2. `enable_and_log_gpu`
3. optional `add_photos`
4. optional `calibrate_reflectance`
5. optional `align_photos`
6. optional `filter_points_usgs_part1`
7. optional `add_gcps`
8. optional `optimize_cameras`
9. optional `filter_points_usgs_part2`
10. optional `build_depth_maps`
11. optional `build_point_cloud`
12. optional `build_model`
13. `build_dem_orthomosaic`
14. optional `add_align_secondary_photos`
15. `export_report`
16. `finish_run`

`build_dem_orthomosaic` is always called, but DEM and orthomosaic work is controlled by nested config flags.

## Variant and preset mechanism

The current starter/example preset is `config/experiments/presets/mesh_facecount_smoothing_3x3.json`. It varies `buildModel.face_count_custom` and `buildModel.noiterations`.

The current MOF reference preset is `config/experiments/presets/mof_alignment_mesh_ortho_reference_v1.json`.

Template CSV expansion:

- Reads the first data row of the template variants CSV as the base row.
- Computes the Cartesian product of factor values.
- Replaces factor columns in the base row for each combination.
- Renders and sanitizes `variant_id`.
- Writes all generated rows using the original CSV header.

MOF reference matrix factor columns:

- `alignPhotos.downscale`: `1`, `2`
- `alignPhotos.adaptive_fitting`: `true`, `false`
- `buildModel.face_count_custom`: `50000`, `100000`, `250000`
- `buildModel.noiterations`: `5`, `35`
- `buildOrthomosaic.orthoRes`: `0.03`, `0.05`

This expands to `2 x 2 x 3 x 2 x 2 = 48` processing candidates. With 5 replicates, the expected run count is `48 x 5 = 240` Metashape runs.

The MOF variant template disables `buildDepthMaps.enabled`, `buildPointCloud.enabled`, and `buildDem.enabled`, enables `buildModel.enabled`, and enables mesh-based `buildOrthomosaic.surface: [Mesh]`.

`buildOrthomosaic.orthoRes` is passed to Metashape as the requested orthomosaic build resolution. In this reference it is a product sampling parameter, not a claim of geometric accuracy or true detail.

## Current reference benchmark: MOF

MOF is the current reference benchmark for the implemented product-analysis workflow.

Current code/config reference:

- Image directory: `/datadisk/data/uav/MOF_repro_test_recovered/input-images`
- Local supported image count observed in that directory: 48
- Template config: `config/experiments/test_mesh_ortho_mof_forest_knoll_rgb.yml`
- Preset: `config/experiments/presets/mof_alignment_mesh_ortho_reference_v1.json`
- Matrix: Alignment-Mesh-Ortho sensitivity matrix
- Expected size with 5 replicates: 48 processing candidates x 5 replicates = 240 Metashape runs

The matrix is designed to test sensitivity of an RGB UAV mesh orthomosaic product to alignment downscale, adaptive fitting, mesh face count, mesh smoothing iterations, and requested orthomosaic pixel size. Do not claim results before the run outputs exist and are evaluated.

## Boundary/stress case: Franzosenwiese

`config/experiments/test_mesh_ortho_franzosenwiese.yml` is a boundary/stress case configuration. It uses the same active flat/camelCase schema and mesh-orthomosaic pathway, with project-specific paths. It is not the current reference benchmark and does not establish change-detection suitability.

## Explicit non-scope

The current MOF reference benchmark does not establish:

- absolute geometric accuracy
- GCP/checkpoint validation
- cross-date accuracy
- change-detection suitability
- platform comparison
- Dense/Depth-Map/DSM quality
- 3D reconstruction quality
- building reconstruction quality

The implementation has runtime functions and YAML keys for some DEM, depth-map, point-cloud, and GCP operations, but those capabilities are not part of the current MOF reference benchmark claim.

## Terminology

Product analysis: repeated processing and evaluation of candidate orthomosaic products for one image set.

Run directory: concrete directory containing generated `config.yml`, generated `variants.csv`, `manifest.csv`, variant outputs, stability products, threshold review products, QGIS launchers, and `selected_product.json`.

Processing candidate / variant: one row in the variants CSV after factor expansion.

Replicate: one independent Metashape build of a candidate.

Manifest: CSV history of candidate/replicate executions, statuses, paths, return codes, and elapsed time.

Support persistence: fraction of the actual supported orthomosaic footprint that has support in all replicates, implemented as `full_support / any_support`.

Stability: internal repeated-build image-value consistency measured against the per-variant median orthomosaic.

Quality flag: threshold-derived raster review layer from RMSE-to-median values. It is an interpretation guard, not image cleaning.

Selected product trace: JSON record of the implemented selection procedure, source files, product modes, and warnings.

Requested orthomosaic pixel size / sampling resolution: `buildOrthomosaic.orthoRes`, the requested raster sampling parameter passed to Metashape. It is not an accuracy guarantee.

## Open technical decisions

- How to add external geometric validation using GCP/checkpoint or independent reference data.
- How to evaluate cross-date reproducibility and change-detection suitability after the MOF reference analysis.
- Whether future benchmark matrices should include Dense/Depth-Map/DSM products.
- Whether to add platform comparison as a later analysis layer.
- Whether to add a Metashape GUI adapter or AM2/R adapter around the existing file and CLI contracts.
- Whether to migrate from the procedural flat/camelCase runtime to an upstream class-based workflow in a later implementation phase.
