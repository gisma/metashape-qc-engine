# Product and Manifest Contract

This document records the current product and manifest contract as implemented.

## Run manifest

The reproducibility runner writes the experiment manifest to:

```text
<experiment_dir>/manifest.csv
```

The manifest is a CSV file with these columns:

```text
experiment_id
variant_id
replicate
status
return_code
config_file
project_dir
output_dir
project_file
ortho_file
launcher_log
elapsed_sec
```

Current status values are:

```text
ok
ok_no_ortho
failed
```

The stability analyzer uses only manifest rows where:

```text
status == "ok"
ortho_file is non-empty
ortho_file exists on disk
```

## Experiment folder shape

The reproducibility runner writes generated configs, projects, outputs, and launcher logs under:

```text
variants/<variant_id>/configs/rep_###.yml
variants/<variant_id>/runs/rep_###/psx/
variants/<variant_id>/runs/rep_###/output/
variants/<variant_id>/runs/rep_###/launcher.log
```

## Analyzer products

The orthomosaic stability analyzer writes:

```text
canonical_grid.json
aligned/<variant_id>/<replicate>_aligned.tif
summary.csv
```

For each variant, it writes:

```text
variants/<variant_id>/valid_count.tif
variants/<variant_id>/median_ortho.tif
variants/<variant_id>/mad_rgb.tif
variants/<variant_id>/rmse_to_median.tif
variants/<variant_id>/stable_mask_rmse<THRESH>.tif
variants/<variant_id>/unstable_mask_rmse<THRESH>.tif
```

## Evaluator products

The support-aware evaluator writes:

```text
summary_key_metrics.tsv
support_valid_count_histogram.tsv
qgis_layers.txt
evaluation_report.md
<experiment_dir>/selected_product.json
```

## Ranking outputs

The evaluator reports three current candidate categories:

```text
continuous stability candidate
threshold-mask candidate
support-persistence candidate
```

These categories are separate outputs. They are not collapsed into one canonical winner.

## Product selection procedure

The concrete product-selection policy is `continuous_first`.

Continuous stability selects the primary variant. Stable image values are the
primary requirement for change detection, so the evaluator uses the existing
continuous-stability ranking as the primary selection list.

Support persistence checks spatial and evaluable support. It marks the
reachable and evaluable output area and provides feasibility / coverage
context, but it does not automatically override the continuous-stability
variant.

The threshold-mask result acts as a rejection / warning guard. It is reported
as threshold-dependent context and is not the primary selection logic.

The concrete output product is resolved in one of two modes:

```text
median_ortho
medoid_replicate
```

`median_ortho` uses the selected variant's existing:

```text
stability_union/variants/<variant_id>/median_ortho.tif
```

`medoid_replicate` uses the original Metashape replicate orthomosaic whose
existing aligned raster is closest to the selected variant's median
orthomosaic. The evaluator prefers:

```text
stability_union/aligned/<variant_id>/<replicate>_aligned.tif
```

and records the corresponding original `ortho_file` from `manifest.csv`. It
does not copy rasters and does not recompute the full analyzer.

## Selected product trace

The evaluator writes a machine-readable technical trace to:

```text
<experiment_dir>/selected_product.json
```

The JSON records:

```text
selection_policy
primary_variant_id
primary_selection_category
product_modes
support_persistence_context
threshold_guard_context
source_files
warnings
```

`selected_product.json` records a technical selection trace for user and domain
review. It does not claim scientific correctness by itself.
