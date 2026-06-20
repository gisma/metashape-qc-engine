# metashape-qc-engine

`metashape-qc-engine` is a Python-first quality-control engine for repeated Agisoft Metashape processing, stability evaluation, and controlled product generation.

The current focus is reproducible Metashape product generation through:

- configuration-driven workflow execution,
- repeated runs across parameter variants,
- manifest-based experiment tracking,
- raster-based stability analysis,
- support-aware evaluation reports,
- controlled selection of robust processing states.

The project contains adapted components from the UC Davis / AM2 / automate-metashape workflow core and extends them with reproducibility, quality-control, and stability-evaluation logic. See `LICENSE` and `NOTICE.md`.

## Current status

The active engine is still organized around existing runtime scripts:

- `python/metashape_workflow.py`
- `python/metashape_workflow_functions.py`
- `scripts/run_metashape_workflow.sh`

Additional experiment and evaluation components are provided by:

- `python/reproducibility_runner.py`
- `python/ortho_stability_analyzer.py`
- `python/evaluate_ortho_stability.py`

The package/CLI layer is intentionally thin and should delegate to the existing runtime scripts without changing workflow logic.

## Current command pattern

Single Metashape workflow run:

```bash
METASHAPE_DIR="/path/to/metashape-pro" \
scripts/run_metashape_workflow.sh config/base.yml
````

Repeated experiment:

```bash
python3 python/reproducibility_runner.py \
  config/experiments/test_mesh_ortho_mof_forest_knoll_rgb.yml \
  --variants config/experiments/repro_variants_mesh_smoothing_only.csv \
  --reps 5 \
  --experiment-dir /path/to/experiment \
  --metashape-dir /path/to/metashape-pro
```

Support-aware evaluation:

```bash
python3 python/evaluate_ortho_stability.py /path/to/experiment --skip-analyzer
```

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
