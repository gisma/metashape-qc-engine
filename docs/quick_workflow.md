# Quick workflow

This is the concise operational path for a product-analysis run. Use one run directory as the container for generated controls, Metashape outputs, manifest history, analyzer products, evaluator products, threshold review products, QGIS launchers, and `selected_product.json`.

## Minimal command sequence

Optionally determine the generic technical orthomosaic resolution before defining product-resolution factors:

```bash
metashape-qc run-analysis "CONFIG" \
  --reps 1 \
  --run-dir "RUN_DIR" \
  --generic-ortho-resolution
```

This mode runs one normal workflow execution without a variants table and forces `buildOrthomosaic.orthoRes = 0` only for this probe run. The resulting `recommended_numeric_orthoRes` is read from the exported GeoTIFF geotransform, not inferred from the config or from a variant name. The reported value can then be inserted manually into later product preparation as a numeric `buildOrthomosaic.orthoRes` factor.


Prepare run-local controls:

```bash
metashape-qc prepare \
  --image-dir "/path/to/input-images" \
  --product-id "product_id" \
  --preset "config/experiments/presets/mof_alignment_mesh_ortho_reference_v1.json" \
  --reps 5 \
  --output-root "/path/to/runs"
```

`prepare` writes `<run_dir>/config.yml` and `<run_dir>/variants.csv`, then prints the concrete `metashape-qc run-analysis` command. It does not start Metashape.

Run the product analysis:



```bash
metashape-qc run-analysis "<run_dir>/config.yml" \
  --variants "<run_dir>/variants.csv" \
  --reps 5 \
  --run-dir "<run_dir>" \
  --metashape-dir "$METASHAPE_DIR"
```

Resume an interrupted product analysis:

```bash
metashape-qc resume-analysis "<run_dir>/config.yml" \
  --variants "<run_dir>/variants.csv" \
  --reps 5 \
  --run-dir "<run_dir>" \
  --metashape-dir "$METASHAPE_DIR"
```

Evaluate a completed or partially completed run directory:

```bash
metashape-qc evaluate "<run_dir>"
```

If analyzer outputs already exist and should be reused:

```bash
metashape-qc evaluate "<run_dir>" --skip-analyzer
```

## MOF reference prepare command

```bash
metashape-qc prepare \
  --image-dir "/datadisk/data/uav/MOF_repro_test_recovered/input-images" \
  --product-id "mof_alignment_mesh_ortho_reference_v1" \
  --preset "config/experiments/presets/mof_alignment_mesh_ortho_reference_v1.json" \
  --reps 5 \
  --output-root "/datadisk/data/uav/MOF_repro_reference/runs"
```

The MOF Alignment-Mesh-Ortho reference matrix expands to `48` processing candidates. With `5` replicates, the run directory represents `48 x 5 = 240` Metashape runs.

## What to inspect

Core files:

- `<run_dir>/manifest.csv`
- `<run_dir>/selected_product.json`
- `<run_dir>/stability_union/evaluation_report.md`
- `<run_dir>/stability_union/summary_key_metrics.tsv`
- `<run_dir>/stability_union/support_valid_count_histogram.tsv`
- `<run_dir>/threshold_review/threshold_sensitivity.tsv`

Raster products for review:

- `<run_dir>/stability_union/variants/<variant_id>/median_ortho.tif`
- `<run_dir>/stability_union/variants/<variant_id>/valid_count.tif`
- `<run_dir>/stability_union/variants/<variant_id>/mad_rgb.tif`
- `<run_dir>/stability_union/variants/<variant_id>/rmse_to_median.tif`
- `<run_dir>/stability_union/variants/<variant_id>/stable_mask_rmse<THRESH>.tif`
- `<run_dir>/stability_union/variants/<variant_id>/unstable_mask_rmse<THRESH>.tif`
- `<run_dir>/threshold_review/rmse<THRESH>/variants/<variant_id>/quality_flag_rmse<THRESH>.tif`

QGIS launchers:

- `<run_dir>/qgis_open_selected.sh`
- `<run_dir>/qgis_open_selected.bat`
- `<run_dir>/qgis_open_threshold_review.sh`
- `<run_dir>/qgis_open_threshold_review.bat`

`selected_product.json` is a trace of the implemented selection procedure. It is not a claim of absolute truth. `quality_flag_rmse` rasters are threshold interpretation guards; they do not clean or modify orthomosaics.

## Compatibility note

`metashape-qc experiment` remains available as a legacy compatibility wrapper around the same runner. Active operational instructions should use `metashape-qc run-analysis` and `metashape-qc resume-analysis` with `--run-dir`.
