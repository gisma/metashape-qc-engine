# Workflow Chain

## Status

This is the active architecture and runtime-chain document for `metashape-qc-engine`. Implementation truth comes from the code, config, presets, CSV matrices, runner, analyzer, and evaluator. `docs/current_system_reference.md` is the committed technical reference for the current implementation.

## Active product-analysis chain

```text
prepare -> run-analysis / resume-analysis -> evaluate -> review
```

The workflow analyzes candidate orthomosaic products for one image set. It prepares run-local controls, executes repeated Metashape builds across variants and replicates, evaluates internal repeated-build stability and support persistence, and writes review artifacts. It does not convert the selected product into external truth.

## Prepare stage

`metashape-qc prepare` generates a concrete run directory from an image directory, product id, preset, replicate count, and output root.

Implemented behavior:

- validates that the image directory exists and contains supported image files;
- reads a preset JSON file;
- expands the Cartesian product of preset factor values;
- writes `<run_dir>/config.yml`;
- writes `<run_dir>/variants.csv`;
- prints the run directory, variant count, replicate count, total run count, and the `metashape-qc run-analysis` command.

The generated files are run artifacts. They belong in the run directory, not in the source repository.

Preset JSON still uses the internal field name `experiment_dir_template`; active user-facing documentation should call the resulting path the run directory.

## Runner stage

`metashape-qc run-analysis` consumes the run-local `config.yml` and `variants.csv`.

Implemented behavior:

- reads the base YAML config;
- reads the variants CSV, or uses one `default` variant if none is supplied;
- requires at least two replicates;
- applies CSV override columns as dotted YAML keys;
- creates per-variant and per-replicate directories under `<run_dir>/variants/<variant_id>/`;
- writes replicate configs under `configs/`;
- writes projects, outputs, and launcher logs under `runs/<rep_label>/`;
- forces each replicate config to use a fresh project;
- calls `scripts/run_metashape_workflow.sh <rep_config>`;
- appends every attempt to `<run_dir>/manifest.csv`;
- continues after failed replicates and returns nonzero if any new failure occurred.

Manifest statuses are `ok`, `ok_no_ortho`, and `failed`. The analyzer uses only rows with `status == "ok"`, a non-empty `ortho_file`, and an existing raster file.

## Resume behavior

`metashape-qc resume-analysis` uses the same runner contract as `run-analysis` and the same run directory. It reads existing manifest history, skips successful variant/replicate combinations, and reruns failed or missing combinations. Rerun attempts keep the same variant and replicate identity while using attempt labels such as `rep_001_attempt_002`.

`--experiment-dir` may still exist as a legacy alias for `--run-dir`; active instructions use `--run-dir`.

## Metashape runtime bridge

Metashape workflow execution requires the Agisoft Metashape Python runtime or launcher environment. The active bridge is:

```text
scripts/run_metashape_workflow.sh
```

The bridge resolves `metashape.sh`, adds repo-local vendored Python dependencies to `PYTHONPATH`, and runs:

```text
python/metashape_workflow.py <rep_config>
```

`metashape-qc run` invokes this bridge once for a single config. `run-analysis` and `resume-analysis` invoke it once per generated candidate/replicate config and capture launcher stdout/stderr in each replicate `launcher.log`.

The analyzer and evaluator run in a normal Python environment when required geospatial dependencies are available. They do not require the Metashape runtime unless they are launching workflow execution.

## Procedural Metashape runtime schema

The active runtime schema is the flat/camelCase YAML schema used by `config/base.yml` and `config/experiments/*.yml`.

`python/read_yaml.py` loads YAML with `yaml.SafeLoader`, then converts string values containing `Metashape` into live Metashape objects, except for path/project/name fields. Lists containing Metashape object strings are converted to lists of evaluated Metashape objects.

The active runner is procedural. It does not use the upstream class workflow or the upstream nested snake_case config schema.

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

`build_dem_orthomosaic` is always called, but DEM and orthomosaic work are controlled by nested config flags.

## Analyzer/evaluator stage

`metashape-qc evaluate <run_dir>` uses `<run_dir>/stability_union` as the analyzer/evaluator output directory.

By default it runs the orthomosaic stability analyzer first. With `--skip-analyzer`, it reuses existing analyzer outputs. The evaluator then reads analyzer summaries and the manifest, computes support metrics from `valid_count.tif`, ranks candidates, writes compact review tables, writes threshold review products, and records the selected-product trace.

Analyzer outputs include:

- `stability_union/canonical_grid.json`
- `stability_union/summary.csv`
- `stability_union/aligned/<variant_id>/<replicate>_aligned.tif`
- `stability_union/variants/<variant_id>/valid_count.tif`
- `stability_union/variants/<variant_id>/median_ortho.tif`
- `stability_union/variants/<variant_id>/mad_rgb.tif`
- `stability_union/variants/<variant_id>/rmse_to_median.tif`
- `stability_union/variants/<variant_id>/stable_mask_rmse<THRESH>.tif`
- `stability_union/variants/<variant_id>/unstable_mask_rmse<THRESH>.tif`

Evaluator/review outputs include:

- `stability_union/summary_key_metrics.tsv`
- `stability_union/support_valid_count_histogram.tsv`
- `stability_union/qgis_layers.txt`
- `stability_union/evaluation_report.md`
- `<run_dir>/threshold_review/threshold_sensitivity.tsv`
- `<run_dir>/threshold_review/threshold_winners.tsv`
- `<run_dir>/threshold_review/rmse<THRESH>/variants/<variant_id>/quality_flag_rmse<THRESH>.tif`
- `<run_dir>/selected_product.json`
- QGIS launcher scripts in the run directory

`quality_flag_rmse` rasters are threshold review guards. They do not clean or modify orthomosaics.

## Selected-product trace and QGIS review

`selected_product.json` records the implemented selection procedure. It is a technical trace, not a claim of absolute truth.

The current policy is `continuous_first`: continuous stability selects the primary candidate, support persistence provides guard/context information, and threshold quality flags provide threshold-dependent review context. The median orthomosaic is synthetic. When medoid scoring succeeds, the evaluator also records the closest original Metashape replicate for the selected variant.

QGIS launchers open selected-product and threshold-review layers for inspection. Review remains required before using an output product.

## MOF reference benchmark

The current reference benchmark is MOF:

- Image directory: `/datadisk/data/uav/MOF_repro_test_recovered/input-images`
- Preset: `config/experiments/presets/mof_alignment_mesh_ortho_reference_v1.json`
- Matrix: Alignment-Mesh-Ortho sensitivity
- Factors: `alignPhotos.downscale`, `alignPhotos.adaptive_fitting`, `buildModel.face_count_custom`, `buildModel.noiterations`, `buildOrthomosaic.orthoRes`
- Size: `2 x 2 x 3 x 2 x 2 = 48` candidates
- Expected run count with `--reps 5`: `48 x 5 = 240` Metashape runs

The MOF template disables Dense/Depth/PointCloud/DEM products and builds mesh-based orthomosaics. `buildOrthomosaic.orthoRes` is a requested sampling/product-resolution factor, not an accuracy claim.

## Legacy wrappers and upstream/background note

Implemented compatibility wrappers:

- `metashape-qc run`: direct single-config wrapper around the Metashape runtime bridge.
- `metashape-qc experiment`: legacy wrapper around the reproducibility runner.
- `metashape-qc analyze`: direct wrapper around the orthomosaic stability analyzer.

The AM2/automate-metashape upstream and class workflow material is useful background and attribution context. It is not the current architecture contract. R/config-generation helpers are retained compatibility/background material, not the primary product-analysis workflow.

## Non-scope

The current MOF reference benchmark does not establish:

- absolute geometric accuracy;
- GCP/checkpoint validation;
- cross-date accuracy;
- change-detection suitability;
- platform comparison;
- Dense/Depth-Map/DSM quality;
- 3D reconstruction quality;
- building reconstruction quality.

Franzosenwiese is a boundary/stress case, not the current reference benchmark.
