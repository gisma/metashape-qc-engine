# Product Analysis Preparation

Use `metashape-qc prepare` to generate product-specific analysis inputs from an existing config template and variants CSV.

Required inputs:

- `--image-dir`: directory containing input images.
- `--product-id`: logical dataset or product identifier used for generated names.
- `--preset`: product-analysis template JSON file.
- `--reps`: replicate count for the later product analysis.
- `--output-root`: parent directory for product analysis runs.

`--product-dir` is optional and defaults to the parent directory of `--image-dir`. The image directory is the actual Metashape input directory; folder names such as `images` or `input-images` are only local conventions.

```bash
metashape-qc prepare \
  --image-dir /data/beliebiges-produkt/images \
  --product-id beliebiges-produkt \
  --preset config/experiments/presets/mesh_facecount_smoothing_3x3.json \
  --reps 10 \
  --output-root /datadisk/data/uav/runs
```

The helper creates the concrete run directory from the preset's run directory template, writes `config.yml` and `variants.csv` inside that directory, then prints the `metashape-qc run-analysis` command to run. It does not start Metashape.

Generated `config.yml` and `variants.csv` are product/run artifacts. Keep them in the run directory and do not commit them to the source repository.

Preset factors are used by default. Override them with repeatable `--factor COLUMN=VALUE1,VALUE2,...` options, or use `--face-counts` for `buildModel.face_count_custom` and `--smoothing` for `buildModel.noiterations`:

```bash
metashape-qc prepare \
  --image-dir /path/to/product/images \
  --product-id PRODUCT_ID \
  --preset config/experiments/presets/mesh_facecount_smoothing_3x3.json \
  --reps 10 \
  --output-root /path/to/runs \
  --face-counts 50000,100000,250000,500000 \
  --smoothing 5,20,35,80
```

The current preset is:

```text
config/experiments/presets/mesh_facecount_smoothing_3x3.json
```

It defines a mesh orthomosaic product analysis varying:

```text
buildModel.face_count_custom
buildModel.noiterations
```

Factor values come from the preset unless overridden by the implemented CLI options above.

## MOF Alignment-Mesh-Ortho Reference Matrix

The MOF reference benchmark preset is:

```text
config/experiments/presets/mof_alignment_mesh_ortho_reference_v1.json
```

It defines an Alignment-Mesh-Ortho sensitivity matrix for an orthomosaic reproducibility benchmark and product analysis. The matrix has 48 processing candidates and varies only parameters already handled by the current config, variant, and preparation system:

```text
alignPhotos.downscale
alignPhotos.adaptive_fitting
buildModel.face_count_custom
buildModel.noiterations
buildOrthomosaic.orthoRes
```

Dense/Depth-Map/DSM excluded: Dense/Depth-Map/DSM products are excluded from this benchmark. The preset keeps `buildDepthMaps.enabled`, `buildPointCloud.enabled`, and `buildDem.enabled` disabled in the variant template and builds mesh-based orthomosaics only. This is an orthomosaic reproducibility and product-selection benchmark, not a full-workflow matrix.

Generic and reference preselection are present as fixed supported columns in the variant template, but are not varied in this v1 matrix so the prepare-compatible Cartesian factor expansion remains bounded. `keypoint_limit`, `keypoint_limit_per_mpx`, `tiepoint_limit`, and `guided_matching` are not current active workflow controls in this repository, so they are not included.

Suitability and change-detection interpretation are not part of this step. Platform comparison is not part of this step. GCP/checkpoint/cross-date accuracy is not part of this step.

```bash
metashape-qc prepare \
  --image-dir "/datadisk/data/uav/MOF/" \
  --product-id "mof_alignment_mesh_ortho_reference_v1" \
  --preset "config/experiments/presets/mof_alignment_mesh_ortho_reference_v1.json" \
  --reps 5 \
  --output-root "/datadisk/data/uav/MOF_repro_reference/runs"
```

After preparation, run the product analysis with the generated files:

```bash
metashape-qc run-analysis <run_dir>/config.yml \
  --variants <run_dir>/variants.csv \
  --reps N \
  --run-dir <run_dir> \
  --metashape-dir <METASHAPE_DIR>
```

Then evaluate and inspect:

```bash
metashape-qc evaluate <run_dir>
metashape-qc evaluate <run_dir> --skip-analyzer
```

Important outputs:

- `stability_union/summary_key_metrics.tsv`
- `stability_union/support_valid_count_histogram.tsv`
- `stability_union/evaluation_report.md`
- `selected_product.json`
