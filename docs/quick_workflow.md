# Quick workflow

## Terminology

This workflow uses one run directory as the operational container.

A **product** is the intended orthomosaic product for one image set, identified by a `product_id`.

A **product analysis** is the reproducibility-based analysis for that product. It runs several processing variants with repeated Metashape runs and compares their stability.

A **run directory** is the concrete folder that contains the run-local control files, the manifest, all variant/replicate outputs, evaluation outputs, selected-candidate metadata, and QGIS launchers.

A **variant** is one processing candidate, defined by a parameter combination such as face count and smoothing.

A **replicate** is one repeated Metashape run for the same variant.

The command `metashape-qc experiment` currently executes the variant × replicate matrix. Despite the command name, the workflow result is not an “experiment result” in a scientific sense. It is a reproducibility analysis with a best-candidate suggestion.

The command `metashape-qc evaluate` evaluates the run directory and writes the selected candidate trace.

The selected candidate is not a new orthomosaic processing step. It is the documented outcome of the evaluation: the selected variant, the robust median orthomosaic, the medoid original Metashape orthomosaic if available, and quality artifacts for review.


## 1. Prepare a product analysis

Input is an image directory. A product id is required. The preset defines the experiment design, and the output root defines where experiment directories are created.

The preparation step writes run-local control files:

- `<experiment_dir>/config.yml`
- `<experiment_dir>/variants.csv`

It also prints the exact `metashape-qc experiment` command to run.

```bash
python3 python/prepare_product_experiment.py \
  --image-dir "/path/to/images" \
  --product-id "example_product" \
  --preset "config/experiments/presets/mesh_facecount_smoothing_3x3.json" \
  --reps 5 \
  --output-root "/path/to/runs" \
  --face-counts 50000,100000,250000 \
  --smoothing 5,35,80
```

Do not use `config/experiments/generated/` as persistent run input. Regenerate the run-local control files for each product experiment.

## 2. Run the experiment

```bash
metashape-qc experiment "<experiment_dir>/config.yml" \
  --variants "<experiment_dir>/variants.csv" \
  --reps 5 \
  --experiment-dir "<experiment_dir>" \
  --metashape-dir "$METASHAPE_DIR"
```

`METASHAPE_DIR` is the Agisoft Metashape installation directory used by the runner.

`manifest.csv` records each variant/replicate.

## 3. Resume an aborted experiment

```bash
metashape-qc experiment "<experiment_dir>/config.yml" \
  --variants "<experiment_dir>/variants.csv" \
  --reps 5 \
  --experiment-dir "<experiment_dir>" \
  --metashape-dir "$METASHAPE_DIR" \
  --resume
```

Resume behavior:

- `ok` and `ok_no_ortho` rows are skipped.
- `failed` and missing rows are rerun.
- Manifest history is preserved.
- The latest row per `variant_id` + `replicate` is used for the resume decision.
- A single failed replicate must not stop the full matrix.

## 4. Evaluate a completed experiment

```bash
metashape-qc evaluate "<experiment_dir>"
```

If analyzer products already exist:

```bash
metashape-qc evaluate "<experiment_dir>" --skip-analyzer
```

Main outputs:

- `stability_union/summary.csv`
- `stability_union/summary_key_metrics.tsv`
- `stability_union/evaluation_report.md`
- `selected_product.json`
- `qgis_open_selected.sh`
- `qgis_open_selected.bat`

## 5. Threshold quality review

Threshold review is derived from existing `rmse_to_median.tif` rasters. It does not rerun Metashape, and it does not clean or modify orthomosaics.

It writes:

- `threshold_review/threshold_sensitivity.tsv`
- `threshold_review/threshold_winners.tsv`
- `threshold_review/rmse<THR>/variants/<variant_id>/quality_flag_rmse<THR>.tif`
- `qgis_open_threshold_review.sh`
- `qgis_open_threshold_review.bat`

Quality flag values:

- `0` = invalid / no support
- `1` = stable / usable under threshold
- `2` = unstable / review or exclude

Default thresholds: `5,10,15,20,25,30`.

## 6. Product selection logic

Priority:

1. Continuous stability selects the primary variant.
2. Support persistence is a coverage/feasibility check.
3. Threshold quality flags are guard/review layers.

`selected_product.json` points to:

- selected variant
- `median_ortho.tif`
- medoid original Metashape orthomosaic, if available
- aligned medoid raster, if available
- warnings, if applicable

## 7. QGIS launchers

Launchers are standard artifacts.

POSIX:

```bash
./qgis_open_selected.sh
./qgis_open_threshold_review.sh
```

Windows:

```bat
qgis_open_selected.bat
qgis_open_threshold_review.bat
```

Windows users can set `QGIS_BIN`. Launchers use paths relative to the experiment directory.

## 8. Minimal troubleshooting

- If `BASE_CONFIG` is missing, do not use old repo-local generated paths.
- Regenerate run-local control files with `prepare_product_experiment.py`.
- If an experiment was aborted, rerun with `--resume`.
- If evaluation appears idle, it may be writing quality flag rasters; check the `threshold_review` file count.
