# metashape-qc-engine

`metashape-qc-engine` contains two related geospatial evidence workflows:

- **Level-1A** prepares, runs, resumes, evaluates, and reviews Agisoft Metashape orthomosaic product candidates.
- **Level-1B** starts from one finished RGB orthomosaic and produces a selected segmentation product plus segmentation-stability and segment-statistics evidence.

The repository layout is historical and does not cleanly mirror those logical names. Level-1A code is split across `python/`, `scripts/`, and `metashape_qc_engine/cli.py`. Level-1B code is mostly in `metashape_qc_engine/level1b_*.py`, plus its shell wrapper and exactextractr R script.

## Setup

For Level-1A:

```bash
bash scripts/setup_level1a.sh
```

For Level-1B:

```bash
bash scripts/setup_level1b.sh
```

The setup scripts create or reuse `.venv`, install the local Python package, verify required Python imports, and check external tools. They do **not** install licensed or system software such as Agisoft Metashape, OTB, GDAL CLI tools, or R itself.

## Active documentation

| Workflow | Operations | Method and artifact map |
|---|---|---|
| Level-1A | [docs/RUN_LEVEL1A.md](docs/RUN_LEVEL1A.md) | [docs/LEVEL1A_METHOD_CORE_MAP.md](docs/LEVEL1A_METHOD_CORE_MAP.md) |
| Level-1B | [docs/RUN_LEVEL1B.md](docs/RUN_LEVEL1B.md) | [docs/LEVEL1B_METHOD_CORE_MAP.md](docs/LEVEL1B_METHOD_CORE_MAP.md) |

[WORKFLOW_CHAIN.md](WORKFLOW_CHAIN.md) shows how both chains relate. Other manuals are deprecated or background material unless explicitly promoted here.

## Minimal command pointers

### Level-1A

After setup, prepare a run from an image directory and preset:

```bash
metashape-qc prepare \
  --image-dir /path/to/images \
  --product-id PRODUCT_ID \
  --preset /path/to/preset.json \
  --reps 2 \
  --output-root /path/to/runs
```

`prepare` prints the exact `run-analysis`, `resume-analysis`, and `evaluate` commands for the generated run directory. See [RUN_LEVEL1A.md](docs/RUN_LEVEL1A.md).

### Level-1B

Use the environment wrapper as the normal entry point:

```bash
ORTHO=/path/to/ortho.tif \
RUN_ROOT=/path/to/run_root \
OVERWRITE=1 \
bash metashape_qc_engine/run_level1b_dumb_with_user_header.sh
```

See [RUN_LEVEL1B.md](docs/RUN_LEVEL1B.md) for dependencies, statuses, final products, and quality evidence.

## Scope boundaries

- Level-1A does not run Step 9 or Step 10 segmentation.
- Level-1B does not run Metashape reproducibility.
- Level-1B does not create an ecological classification.
- Level-1B does not assign a final quality class; it writes reviewable quality evidence.
- Neither workflow alone establishes absolute geometric accuracy or external truth.

## External software

Level-1A execution requires Agisoft Metashape. Its analyzer/evaluator also imports GDAL Python bindings. Level-1B requires OTB, GDAL Python/CLI components, and R packages used by exactextractr. These components must be installed compatibly with the local operating system and Python/R environments; the setup scripts report their availability but do not install the system software.

The installation method for compatible GDAL Python bindings when `gdal-config` is unavailable is **UNRESOLVED** and system-specific.

## License and attribution

This repository is distributed under the BSD 3-Clause License. Adapted UC Davis / AM2 / automate-metashape components retain their original notices in [LICENSE](LICENSE); project-specific attribution is in [NOTICE.md](NOTICE.md).
