# metashape-qc-engine

`metashape-qc-engine` is a product-oriented reproducibility and QC workflow around Agisoft Metashape orthomosaic generation.

The workflow supports:

- repeated Metashape runs,
- variant matrices,
- orthomosaic stability analysis,
- support diagnostics,
- selected product tracing.

The project contains adapted components from the UC Davis / AM2 / automate-metashape workflow core and extends them with reproducibility, quality-control, and stability-evaluation logic. See `LICENSE` and `NOTICE.md`.

## Current status

The active engine is still organized around existing runtime scripts:

- `python/metashape_workflow.py`
- `python/metashape_workflow_functions.py`
- `scripts/run_metashape_workflow.sh`

Additional experiment and evaluation components are provided by:

- `python/prepare_product_experiment.py`
- `python/reproducibility_runner.py`
- `python/ortho_stability_analyzer.py`
- `python/evaluate_ortho_stability.py`

The package/CLI layer is intentionally thin and should delegate to the existing runtime scripts without changing workflow logic.

## Current product workflow

Concise end-to-end commands are in [docs/quick_workflow.md](docs/quick_workflow.md).

1. Prepare a product experiment from an image directory, product id, preset, replicate count, and output root:

```bash
python3 python/prepare_product_experiment.py \
  --image-dir /data/product-001/images \
  --product-id product-001 \
  --preset config/experiments/presets/mesh_facecount_smoothing_3x3.json \
  --reps 10 \
  --output-root /data/metashape-qc-runs
```

The helper writes product-specific `config.yml` and `variants.csv` into the concrete experiment directory under the output root. These files are run artifacts and should not be committed.

2. Run the repeated Metashape experiment:

```bash
metashape-qc experiment /data/metashape-qc-runs/product-001_mesh_facecount_smoothing_reps10/config.yml \
  --reps 10 \
  --experiment-dir /data/metashape-qc-runs/product-001_mesh_facecount_smoothing_reps10 \
  --variants /data/metashape-qc-runs/product-001_mesh_facecount_smoothing_reps10/variants.csv \
  --metashape-dir /path/to/metashape-pro
```

Failed Metashape replicates are recorded in `manifest.csv` and the matrix continues. To continue an aborted experiment, rerun the same command with `--resume`; successful variant/replicate combinations are skipped, failed or missing combinations are rerun, and manifest history is preserved.

3. Evaluate the completed experiment:

```bash
metashape-qc evaluate /data/metashape-qc-runs/product-001_mesh_facecount_smoothing_reps10
```

If analyzer outputs already exist:

```bash
metashape-qc evaluate /data/metashape-qc-runs/product-001_mesh_facecount_smoothing_reps10 --skip-analyzer
```

4. Inspect the technical outputs:

- `stability_union/summary_key_metrics.tsv`
- `stability_union/support_valid_count_histogram.tsv`
- `stability_union/evaluation_report.md`
- `selected_product.json`
- `qgis_open_selected.sh` and `qgis_open_selected.bat`
- `threshold_review/threshold_sensitivity.tsv`

## Terminology

- `image directory`: directory containing input images.
- `product id`: logical dataset or product identifier used for generated names.
- `output root`: parent directory for experiment runs.
- `experiment directory`: concrete run directory containing manifest, variants, outputs, stability products, and selected product trace.
- `preset`: experiment-design template, not a dataset.
- `variants CSV`: generated technical matrix consumed by the runner.
- `selected product trace`: technical selection record for user and domain review, not an automatic scientific truth claim.

## Architecture direction

The intended architecture is:

```text
Python core
→ Metashape runtime execution
→ repeated experiments
→ stability / support evaluation
→ controlled product generation
```

Future frontends may include:

* a thin command-line package entry point,
* a Metashape GUI/menu adapter,
* a later AM2/R adapter around the file and CLI contract.

## License and attribution

This repository is distributed under the BSD 3-Clause License.

It contains adapted components from the UC Davis / AM2 / automate-metashape code base. Original copyright, author, license, and disclaimer notices are retained in `LICENSE`; project-specific attribution and scope notes are provided in `NOTICE.md`.

## Repository layout

- `python/` contains the active workflow and analysis scripts used for Metashape execution, reproducibility runs, orthomosaic stability analysis, and support-aware evaluation.
- `metashape_qc_engine/` contains the thin installable CLI wrapper that exposes selected scripts through the `metashape-qc` command.
- `scripts/` contains shell launchers and bootstrap helpers for running the workflow inside the Metashape runtime environment.
- `config/` contains reference YAML configurations, AM2-style derived configuration support, experiment configurations, and legacy pre-migration configurations.
- `R/` contains AM2-style R helper scripts retained as a compatibility layer. The primary runtime logic lives in Python.
- `docs/` contains audit notes, runtime notes, workflow documentation, and archived upstream documentation.
- `calibration/` contains retained calibration CSV input/reference files.
- `prior-versions/` contains archived workflow code for older Metashape compatibility/reference cases.
