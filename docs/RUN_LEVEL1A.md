# Running Level-1A

Level-1A is the Metashape product-analysis and reproducibility workflow. It builds repeated Metashape products, compares their orthomosaics, and records stability evidence for product review.

The repository layout is historical: Level-1A is split across `python/`, `scripts/`, and `metashape_qc_engine/cli.py`. The user-facing interface is the `metashape-qc` CLI; the Metashape runtime is launched through `scripts/run_metashape_workflow.sh`.

## Prerequisites

- the repository's Python environment and `metashape-qc` command
- a Metashape installation available as `metashape.sh` on Linux/macOS/WSL or `metashape.exe` on Windows; `METASHAPE_DIR` can identify either installation
- an image directory containing supported input images
- a product-analysis preset JSON accepted by `metashape-qc prepare`
- enough storage for per-variant, per-replicate Metashape projects and orthomosaics

### Platform setup

- Linux or WSL2: `bash scripts/setup_level1a.sh`
- macOS: `bash scripts/setup_level1a_macos.sh`
- native Windows dependency environment: `powershell -ExecutionPolicy Bypass -File scripts/setup_level1a_windows.ps1`

The native Windows setup installs Miniforge through `winget` when needed and
uses `.conda-env` so GDAL and `osgeo` come from one compatible conda-forge
build. It detects Metashape through `METASHAPE_DIR`, `PATH`, the normal
`Program Files\Agisoft\Metashape Pro` location, and Windows uninstall-registry
metadata. Level-1A selects `scripts/run_metashape_workflow.ps1` on Windows
and calls the detected `metashape.exe -r`; Linux, macOS, and WSL continue to use
`scripts/run_metashape_workflow.sh` and `metashape.sh`. The complete Level-1A
plus Level-1B chain still requires WSL for Level-1B's Bash runtime wrapper.

## Normal prepare, run, and evaluate example

Prepare creates a run directory and prints the exact paths and follow-up commands. Start with:

```bash
metashape-qc prepare \
  --image-dir /path/to/images \
  --product-id PRODUCT_ID \
  --preset /path/to/preset.json \
  --reps 2 \
  --output-root /path/to/analysis_runs
```

The generated run directory contains `config.yml` and `variants.csv`. Use the run directory printed by `prepare`:

```bash
RUN_DIR=/path/printed/by/prepare

metashape-qc run-analysis "$RUN_DIR/config.yml" \
  --variants "$RUN_DIR/variants.csv" \
  --reps 2 \
  --run-dir "$RUN_DIR"

metashape-qc evaluate "$RUN_DIR"
```

`prepare` prints equivalent `run-analysis`, `resume-analysis`, and `evaluate` commands with resolved paths. Those printed commands are the safest handoff between stages.

## Preparing an analysis

Required `prepare` arguments are `--image-dir`, `--product-id`, `--preset`, `--reps`, and `--output-root`. Optional controls include `--product-dir`, repeated `--factor COLUMN=VALUES`, `--face-counts`, `--smoothing`, `--variant-id-template`, and `--overwrite`.

The preset controls the run-directory template, base config template, variants template, and factor definitions. `prepare` writes:

- `RUN_DIR/config.yml`
- `RUN_DIR/variants.csv`

With `--overwrite`, `prepare` removes only its exact prepared experiment directory after checking that it is under the requested output root and contains preparation artifacts. It does not broadly clean arbitrary directories.

## Running the replicates

`run-analysis` requires the generated config, `--reps` of at least 2, and `--run-dir` (or the legacy alias `--experiment-dir`). Pass the generated variants table with `--variants`. `--metashape-dir` explicitly supplies the Metashape installation directory. `--overwrite` allows writing into an existing non-empty run directory, but does not provide resume semantics.

For every variant/replicate attempt, the runner writes or updates:

- the replicate config
- the Metashape project/output directories
- `RUN_DIR/variants/<variant_id>/runs/<run_label>/launcher.log`
- one appended row in `RUN_DIR/manifest.csv`

The runner continues after an individual failed replicate and reports counts at the end.

## Resuming an interrupted or partial run

Use the same config, variants table, replicate count, and run directory:

```bash
RUN_DIR=/path/printed/by/prepare

metashape-qc resume-analysis "$RUN_DIR/config.yml" \
  --variants "$RUN_DIR/variants.csv" \
  --reps 2 \
  --run-dir "$RUN_DIR"
```

Resume uses the latest `manifest.csv` row for each `(variant_id, replicate)` pair. Duplicate historical rows may remain; the latest row controls the resume decision.

| Status | Meaning | Resume behavior |
|---|---|---|
| `ok` | launcher returned zero and an orthomosaic TIFF was found | skipped when required manifest path fields are populated |
| `ok_no_ortho` | launcher returned zero but no orthomosaic TIFF was found | also considered resumable when required manifest path fields are populated |
| `failed` | launcher returned nonzero | rerun by `resume-analysis` |

For both successful statuses, resume additionally requires non-empty `config_file`, `project_dir`, `output_dir`, `project_file`, and `launcher_log` fields. Evaluation uses only `ok` rows with an existing `ortho_file`; `ok_no_ortho` rows do not enter orthomosaic stability analysis.

## Evaluating stability

```bash
metashape-qc evaluate "$RUN_DIR"
```

By default, evaluation runs the canonical-grid analyzer and then creates compact evaluation outputs. Use `--skip-analyzer` only when `RUN_DIR/stability_union/summary.csv` and its source rasters already exist and should be reused.

Defaults are canonical grid mode `union`, 3 bands, stable RMSE threshold `15.0`, and threshold review values `5,10,15,20,25,30`. CLI options can change grid mode, band count, the primary RMSE threshold, and overwrite behavior.

A reference-grid evaluation requires a reference orthomosaic through the lower-level analyzer; the `evaluate` CLI exposes the grid mode but not a reference-ortho argument. Therefore `metashape-qc evaluate --grid-mode reference` is **UNRESOLVED** as an operational CLI path.

## Outputs to inspect

### Run state

- `RUN_DIR/manifest.csv` — one row per attempt, including status and launcher-log path
- `RUN_DIR/variants/<variant_id>/runs/<run_label>/launcher.log` — stdout/stderr from the Metashape launcher

### `stability_union`

`RUN_DIR/stability_union/` contains:

- `summary.csv` — per-variant support, MAD, RMSE, threshold, and pixel-count summary
- `summary_key_metrics.tsv` — compact rows ordered by continuous stability
- `support_valid_count_histogram.tsv` — support-count and footprint-persistence evidence
- `evaluation_report.md` — readable ranking and interpretation report
- `qgis_layers.txt` — raster paths grouped by variant
- `aligned/<variant_id>/<replicate>_aligned.tif` — canonical-grid inputs
- `variants/<variant_id>/median_ortho.tif`
- `variants/<variant_id>/valid_count.tif`
- `variants/<variant_id>/mad_rgb.tif`
- `variants/<variant_id>/rmse_to_median.tif`
- stable/unstable masks for the evaluated threshold

### Selected-product trace

`RUN_DIR/selected_product.json` records the continuous-stability primary variant, its median orthomosaic, the closest observed replicate (medoid) when available, support-persistence context, threshold-guard context, and disagreements as warnings. It is a reviewable selection trace; it does not prove accuracy.

### QGIS launcher scripts

```bash
bash "$RUN_DIR/qgis_open_selected.sh"
```

`qgis_open_selected.sh` and `.bat` open the selected variant's existing median, RMSE, valid-count, threshold-quality, and medoid files that were available when the launcher was written. Threshold-review launchers open the selected variant plus available quality-flag rasters across reviewed thresholds. They do not recompute analysis.

## What to check first after a failure

1. Read the CLI error and `RUN_DIR/manifest.csv`.
2. Open the `launcher_log` path from the failed manifest row.
3. Confirm that the replicate config, project directory, and output directory exist.
4. For evaluation failure, confirm at least one `ok` row has an existing `ortho_file`.
5. For canonical-grid failure, check reported raster resolution or geotransform incompatibility.
6. If only some replicates failed, use `resume-analysis` with the same controls.

## What Level-1A does not claim

- no absolute geometric accuracy
- no GCP or independent checkpoint validation
- no cross-date accuracy or temporal-change validation
- no ecological or land-cover classification
- no Level-1B segmentation-scale analysis
- no final quality class

The outputs quantify repeated-build product stability and support persistence. Their scientific interpretation still requires domain review.
