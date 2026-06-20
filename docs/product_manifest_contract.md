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
```

## Ranking outputs

The evaluator reports three current candidate categories:

```text
continuous stability candidate
threshold-mask candidate
support-persistence candidate
```

These categories are separate outputs. They are not collapsed into one canonical winner.
