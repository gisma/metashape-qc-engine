# Current Documentation Status

This file is the active documentation index. It defines which project documents are authoritative working documentation and which files are only background, archive material, or source material.

## Active documentation

| File | Applies to | Status |
|---|---|---|
| `README.md` | Project entry point, Level-1A/Level-1B distinction, setup commands, active documentation map | active |
| `WORKFLOW_CHAIN.md` | Architecture map for the two logical workflows and their relationship | active |
| `docs/RUN_LEVEL1A.md` | Level-1A operation: prepare, run-analysis, resume-analysis, evaluate, outputs, failure diagnosis | active |
| `docs/LEVEL1A_METHOD_CORE_MAP.md` | Level-1A method core: replicates, canonical grid, stability ranking, support persistence, median/medoid, non-scope | active |
| `docs/RUN_LEVEL1B.md` | Level-1B operation: wrapper call, chain report, Step-10 products, quality evidence, status diagnosis | active |
| `docs/LEVEL1B_METHOD_CORE_MAP.md` | Level-1B method core: valid mask, six-band RGB/DGLCM-PC1 proxy stack, scaling, explicit YAML baseline radii, ranger, perturbations, Step 9a/9b, Step 10 | active |

## Active configuration and runtime entry points

These files are not explanatory documentation, but they are authoritative for the current runtime.

| File | Applies to | Status |
|---|---|---|
| `pyproject.toml` | Python package metadata, base dependencies, `metashape-qc` CLI | active |
| `requirements-metashape.txt` | Minimal Python requirements for the Agisoft Metashape runtime bridge; not the full project environment | active |
| `scripts/setup_level1a.sh` | Setup/check script for the Level-1A environment | active |
| `scripts/setup_level1b.sh` | Setup/check script for the Level-1B environment | active |
| `config/level1b_default.yaml` | Current Level-1B default parameters | active |
| `metashape_qc_engine/cli.py` | CLI entry point for Level-1A operations | active |
| `metashape_qc_engine/level1b_dumb_runner.py` | Level-1B Python runner | active |
| `metashape_qc_engine/run_level1b_dumb_with_user_header.sh` | Normal Level-1B wrapper with OTB/GDAL/PYTHONPATH environment setup | active |
| `R/level1b_step10_exactextractr_segment_stats.R` | Level-1B Step-10 segment statistics with `exactextractr` | active |

## Logical workflow names

| Name | Meaning | Important files |
|---|---|---|
| Level-1A | Metashape/Product-Analysis/Reproducibility: create, replicate, evaluate, and review orthomosaic candidates | `docs/RUN_LEVEL1A.md`, `docs/LEVEL1A_METHOD_CORE_MAP.md`, `python/`, `scripts/`, `metashape_qc_engine/cli.py` |
| Level-1B | Candidate-Scale-Stability / Segmentation Evidence: turn one finished orthomosaic into a segmentation decision, selected segments, and quality evidence | `docs/RUN_LEVEL1B.md`, `docs/LEVEL1B_METHOD_CORE_MAP.md`, `metashape_qc_engine/level1b_*.py`, `R/level1b_step10_exactextractr_segment_stats.R` |

The repository layout is historical. The logical names Level-1A and Level-1B do not mean that the code is already physically separated into `level1a/` and `level1b/`.

