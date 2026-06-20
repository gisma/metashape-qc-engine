# Experiment Preparation

Use `python/prepare_product_experiment.py` to generate product-specific experiment inputs from an existing config template and variants CSV.

Required inputs:

- `--image-dir`: directory containing input images.
- `--product-id`: logical dataset or product identifier used for generated names.
- `--preset`: experiment-design template JSON file.
- `--reps`: replicate count for the later experiment.
- `--output-root`: parent directory for experiment runs.

`--product-dir` is optional and defaults to the parent directory of `--image-dir`. The image directory is the actual Metashape input directory; folder names such as `images` or `input-images` are only local conventions.

```bash
python3 python/prepare_product_experiment.py \
  --image-dir /data/beliebiges-produkt/images \
  --product-id beliebiges-produkt \
  --preset config/experiments/presets/mesh_facecount_smoothing_3x3.json \
  --reps 10 \
  --output-root /datadisk/data/uav/runs
```

The helper creates the concrete experiment directory from the preset's `experiment_dir_template`, writes `config.yml` and `variants.csv` inside that directory, then prints the `metashape-qc experiment` command to run. It does not start Metashape.

Generated `config.yml` and `variants.csv` are product/run artifacts. Keep them in the experiment directory and do not commit them to the source repository.

Preset factors are used by default. Override them with repeatable `--factor COLUMN=VALUE1,VALUE2,...` options, or use `--face-counts` for `buildModel.face_count_custom` and `--smoothing` for `buildModel.noiterations`:

```bash
python3 python/prepare_product_experiment.py \
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

It defines a mesh orthomosaic experiment varying:

```text
buildModel.face_count_custom
buildModel.noiterations
```

Factor values come from the preset unless overridden by the implemented CLI options above.

After preparation, run the experiment with the generated files:

```bash
metashape-qc experiment <experiment_dir>/config.yml \
  --reps N \
  --experiment-dir <experiment_dir> \
  --variants <experiment_dir>/variants.csv \
  --metashape-dir <METASHAPE_DIR>
```

Then evaluate and inspect:

```bash
metashape-qc evaluate <experiment_dir>
metashape-qc evaluate <experiment_dir> --skip-analyzer
```

Important outputs:

- `stability_union/summary_key_metrics.tsv`
- `stability_union/support_valid_count_histogram.tsv`
- `stability_union/evaluation_report.md`
- `selected_product.json`
