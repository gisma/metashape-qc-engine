# Orthomosaic Stability Workflow Manual

## Status

This is the maintained detailed workflow and interpretation manual for the active product-analysis architecture. It describes the current `prepare -> run-analysis/resume-analysis -> evaluate -> review` chain and the interpretation of analyzer and evaluator products.

Implementation truth comes from the code, config, presets, CSV matrices, runner, analyzer, and evaluator, with `docs/current_system_reference.md` as the committed technical reference.

## Purpose

The workflow supports reproducible Agisoft Metashape orthomosaic candidate selection. It tests processing candidates with repeated Metashape builds, compares successful orthomosaics on a canonical grid, summarizes internal stability and support persistence, and writes a selected-product trace for user and domain review.

The output is a documented candidate-selection procedure, not an automatic validation of scientific correctness.

## What the workflow evaluates

The current workflow evaluates:

- repeated-build orthomosaic stability for tested processing candidates;
- support consistency across successful replicates;
- image-value deviation from each candidate's median orthomosaic;
- threshold-dependent RMSE review flags;
- manifest-tracked execution status and paths;
- a selected-product trace under the implemented `continuous_first` policy.

## What it does not evaluate

The current MOF reference workflow does not evaluate:

- absolute geometric accuracy;
- GCP/checkpoint validation;
- cross-date accuracy;
- change-detection suitability;
- platform comparison;
- Dense Cloud, Depth Map, Point Cloud, DSM/DEM quality;
- 3D reconstruction or building reconstruction quality.

Internal stability is not external accuracy. A candidate can be reproducible and still be geometrically wrong.

## Why repeated-build stability is needed

An orthomosaic is a synthetic photogrammetric product. It depends on alignment, tie points, projection surface, seamlines, blending, export sampling, and implementation/runtime behavior. A single successful export only proves that one processing path completed. It does not show whether the same candidate repeatedly produces stable image support and stable image values.

Repeated builds provide samples from the implemented processing procedure. The analyzer aligns successful orthomosaics onto one canonical grid and measures how much valid support and RGB values vary across replicates for each candidate.

## Product analysis workflow

Prepare run-local controls:

```bash
metashape-qc prepare \
  --image-dir "/path/to/input-images" \
  --product-id "product_id" \
  --preset "config/experiments/presets/mof_alignment_mesh_ortho_reference_v1.json" \
  --reps 5 \
  --output-root "/path/to/runs"
```

Run the candidate x replicate matrix:

```bash
metashape-qc run-analysis "<run_dir>/config.yml" \
  --variants "<run_dir>/variants.csv" \
  --reps 5 \
  --run-dir "<run_dir>" \
  --metashape-dir "$METASHAPE_DIR"
```

Resume failed or missing work:

```bash
metashape-qc resume-analysis "<run_dir>/config.yml" \
  --variants "<run_dir>/variants.csv" \
  --reps 5 \
  --run-dir "<run_dir>" \
  --metashape-dir "$METASHAPE_DIR"
```

Evaluate the run directory:

```bash
metashape-qc evaluate "<run_dir>"
```

Reuse existing analyzer outputs when appropriate:

```bash
metashape-qc evaluate "<run_dir>" --skip-analyzer
```

Historical/contextual note: older direct script calls and the legacy `metashape-qc experiment` wrapper may still exist, but active operational documentation uses the command sequence above and run directory terminology.


### Generic technical orthomosaic resolution probe

Before defining fixed product-resolution factors, a single generic resolution probe can be run with `--generic-ortho-resolution`. This probe performs one normal workflow run without a variants table and forces `buildOrthomosaic.orthoRes = 0` for that run only.

The resulting recommended numeric value is derived from the exported GeoTIFF geotransform. It is therefore an observed product property, not a value inferred from the requested configuration. The value can be used as a numeric `buildOrthomosaic.orthoRes` factor in later product-analysis preparation.


## Run directory structure

A prepared and executed run directory contains:

```text
<run_dir>/
  config.yml
  variants.csv
  manifest.csv
  selected_product.json
  qgis_open_selected.sh
  qgis_open_selected.bat
  qgis_open_threshold_review.sh
  qgis_open_threshold_review.bat
  variants/
    <variant_id>/
      configs/
        rep_###.yml
      runs/
        rep_###/
          launcher.log
          output/
          psx/
  stability_union/
    canonical_grid.json
    summary.csv
    summary_key_metrics.tsv
    support_valid_count_histogram.tsv
    evaluation_report.md
    aligned/
    variants/
  threshold_review/
```

The image directory is outside this structure and should contain only the input images intended for Metashape.

## Manifest and statuses

`manifest.csv` is the execution history for the run directory. It records candidate/replicate status, return code, generated config, project directory, output directory, project file, orthomosaic file, launcher log, and elapsed time.

Current statuses:

- `ok`: launcher returned `0` and an orthomosaic TIFF was found.
- `ok_no_ortho`: launcher returned `0` but no orthomosaic TIFF was found.
- `failed`: launcher returned nonzero.

The analyzer uses only manifest rows with `status == "ok"`, a non-empty `ortho_file`, and an existing raster file. Resume preserves manifest history and appends new attempts.

## Analyzer products

The analyzer compares successful orthomosaics on a canonical grid. Default evaluation uses `stability_union` and `grid-mode=union`.

Per-variant analyzer products:

- `median_ortho.tif`: synthetic per-pixel median orthomosaic from aligned successful replicates.
- `valid_count.tif`: number of successful replicates with valid support at each pixel.
- `mad_rgb.tif`: median absolute deviation from the median RGB values.
- `rmse_to_median.tif`: RMSE deviation from the median RGB values.
- `stable_mask_rmse<THRESH>.tif`: pixels with full replicate support and RMSE at or below the configured threshold.
- `unstable_mask_rmse<THRESH>.tif`: supported pixels that do not meet the stable condition.

The stable and unstable masks are analyzer products. Threshold-review `quality_flag_rmse` rasters are evaluator products.

## Evaluator/review products

The evaluator adds compact tables, threshold review, product-selection trace, and QGIS launchers.

Key products:

- `stability_union/summary_key_metrics.tsv`: compact candidate metrics for review.
- `stability_union/support_valid_count_histogram.tsv`: support-count distribution by candidate.
- `stability_union/evaluation_report.md`: human-readable evaluation summary.
- `threshold_review/threshold_sensitivity.tsv`: threshold-dependent stability summaries.
- `threshold_review/threshold_winners.tsv`: threshold-dependent candidate summaries.
- `threshold_review/rmse<THRESH>/variants/<variant_id>/quality_flag_rmse<THRESH>.tif`: Byte review rasters where `0` means invalid/no support, `1` means stable/usable under the threshold, and `2` means unstable/review or exclude.
- `selected_product.json`: machine-readable trace of the implemented selection procedure.
- QGIS launchers: scripts for opening selected-product and threshold-review layers.

`quality_flag_rmse` rasters are interpretation guards. They do not clean, mask, edit, or improve the source orthomosaics.

## Support interpretation

The canonical grid is the rectangular analysis grid used to compare aligned orthomosaics. It may include pixels outside the actual supported footprint of a candidate. This is why both grid fractions and footprint-conditioned support metrics are needed.

Support metrics:

- `any_support_fraction_grid`: fraction of the rectangular canonical grid with valid support in at least one replicate.
- `full_support_fraction_grid`: fraction of the rectangular canonical grid with valid support in all replicates.
- `variable_support_fraction_grid`: fraction of the rectangular canonical grid with support in some but not all replicates.
- `support_persistence_footprint`: `full_support / any_support`, measuring support persistence inside pixels that have any support.
- `support_dropout_footprint`: `variable_support / any_support`, measuring replicate-to-replicate support dropout inside pixels that have any support.

Grid fractions describe the full analysis rectangle. Footprint fractions describe the actual supported footprint. Support persistence is support consistency, not geometric accuracy.

## Selection logic

The current selection policy is `continuous_first`.

Continuous stability is primary. The primary candidate is ranked by lower `p95_rmse_to_median`, lower `mean_rmse_to_median`, lower `p95_mad_rgb`, and lower `mean_mad_rgb`.

Support persistence is a guard/context layer. It identifies candidates with low support dropout and high support persistence, but it does not automatically override the continuous-stability primary candidate.

Threshold quality flags are a guard/context layer. They show how candidate interpretation changes across RMSE thresholds and record warning context when threshold candidates differ from the continuous-stability primary candidate.

`selected_product.json` records:

- `selection_policy`;
- primary variant id;
- selected median orthomosaic path;
- optional medoid original replicate when scoring succeeds;
- support-persistence context;
- threshold-guard context;
- source files;
- warnings.

`median_ortho.tif` is synthetic. The optional medoid original replicate is the original Metashape orthomosaic whose aligned raster is closest to the selected variant median on common valid pixels. If medoid scoring cannot be completed, evaluation remains nonfatal and the warning is recorded.

## Interpretation limits

The selected product is not truth. It is the selected candidate under the implemented ranking within the tested parameter space.

Stability is not accuracy. RMSE/MAD to the median orthomosaic measures internal repeated-build consistency, not external geometric correctness or true detail.

Quality flags are not cleaning. They are threshold-derived interpretation guards based on `rmse_to_median.tif`.

The current workflow does not establish change-detection suitability, cross-date accuracy, platform comparison, or GCP/checkpoint accuracy.

`buildOrthomosaic.orthoRes` is requested orthomosaic pixel size / sampling resolution. Smaller requested pixel size should not be described as better accuracy without external validation.

## MOF reference benchmark

MOF is the current reference benchmark for the implemented workflow.

Reference prepare command:

```bash
metashape-qc prepare \
  --image-dir "/datadisk/data/uav/MOF_repro_test_recovered/input-images" \
  --product-id "mof_alignment_mesh_ortho_reference_v1" \
  --preset "config/experiments/presets/mof_alignment_mesh_ortho_reference_v1.json" \
  --reps 5 \
  --output-root "/datadisk/data/uav/MOF_repro_reference/runs"
```

The MOF matrix varies:

- `alignPhotos.downscale`;
- `alignPhotos.adaptive_fitting`;
- `buildModel.face_count_custom`;
- `buildModel.noiterations`;
- `buildOrthomosaic.orthoRes`.

It expands to `2 x 2 x 3 x 2 x 2 = 48` processing candidates. With `5` replicates, it represents `48 x 5 = 240` Metashape runs.

The MOF template disables Dense/Depth/PointCloud/DEM products and uses mesh-based orthomosaic production. Dense Cloud, Depth Maps, DSM/DEM quality, and 3D reconstruction quality are not part of this reference benchmark.

No completed MOF result claims should be made from the benchmark description alone. Result claims require existing run outputs and inspected evaluation products.

## Franzosenwiese boundary/stress case

Franzosenwiese is useful as a boundary/stress case. It can exercise warning paths, candidate disagreement, high support dropout, or high review burden.

It is not the current reference benchmark and does not establish change-detection suitability.

## Practical review checklist

Review execution first:

- inspect `manifest.csv` for `failed` and `ok_no_ortho` rows;
- confirm the number of successful replicates per candidate is sufficient for interpretation;
- resume missing or failed work when needed.

Review stability and support:

- compare candidates in `stability_union/summary_key_metrics.tsv`;
- inspect `support_valid_count_histogram.tsv`;
- open `valid_count.tif`, `median_ortho.tif`, `mad_rgb.tif`, and `rmse_to_median.tif` for selected and competing candidates.

Review guards:

- inspect `threshold_review/threshold_sensitivity.tsv`;
- inspect `quality_flag_rmse` rasters for relevant thresholds;
- check whether support-persistence or threshold candidates disagree with the continuous-stability primary candidate.

Review the selected-product trace:

- read `selected_product.json`;
- inspect all warnings;
- treat the median product as synthetic;
- use the medoid original replicate only when it is present and appropriate for the downstream task.
