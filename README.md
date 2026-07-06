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

For macOS:

```bash
bash scripts/setup_level1a_macos.sh
bash scripts/setup_level1b_macos.sh
```

For Windows PowerShell:

```powershell
$env:OTB_ROOT = "C:\path\to\OTB"
$env:SAGA_ROOT = "C:\path\to\saga_cmd.exe"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_level1a_windows.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_level1b_windows.ps1
```

The Linux and macOS scripts create or reuse `.venv`. The native Windows
scripts create or reuse `.conda-env` and install the mutually compatible Python,
GDAL, rasterio, and `osgeo` packages from conda-forge. If Conda is absent, they
install Miniforge through `winget`; if `winget` is unavailable, they stop with
the manual Miniforge download address.

### Windows via WSL2

Both levels have native PowerShell launchers. WSL2 remains an alternative
when OTB, SAGA, GDAL, R, and Metashape are maintained as Linux installations. Install/open an Ubuntu WSL distribution, enter the repository from
WSL, and run the normal Linux setup scripts:

```powershell
wsl --install -d Ubuntu
wsl
```

Then, inside the WSL shell:

```bash
cd /path/inside/wsl/to/metashape-qc-engine
bash scripts/setup_level1a.sh
bash scripts/setup_level1b.sh
```

OTB, SAGA, GDAL, R, and a Linux `metashape.sh` required by Level-1A must be
installed or exposed inside WSL. Native Windows installations are not silently
reused by the Linux runners.

Native Level-1B requires `OTB_ROOT` to identify the extracted Windows OTB
package and `SAGA_ROOT` when `saga_cmd.exe` is not on `PATH`. `OTB_ROOT` must
contain `otbenv.ps1` or `otbenv.bat`; `SAGA_ROOT` may name either the SAGA
installation directory or `saga_cmd.exe` itself. The PowerShell wrapper loads
the OTB environment only for OTB subprocesses so its GDAL DLLs do not replace
the conda-forge Python GDAL runtime.

The Level-1A Windows setup also installs `requirements-metashape.txt` into
`python\vendor`. This is required because Metashape uses its own Python runtime
and cannot import PyYAML from `.conda-env`.

### Native Windows end-to-end run

The repository includes `ps-run.ps1` for the configured MOF Level-1A to
Level-1B chain. Before starting it, review these values near the top of the
file and adapt them to the local installation and dataset:

- `IMAGE_DIR`, `PRODUCT_ID`, `REPS`, `L1A_ROOT`, and `L1B_RUN`;
- `OTB_ROOT`, pointing to an OTB package containing `otbenv.ps1` or
  `otbenv.bat`;
- `SAGA_ROOT`, pointing to the SAGA directory or directly to `saga_cmd.exe`.

Run the complete chain from the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\ps-run.ps1
```

The script prepares a new Level-1A run only when its control files do not yet
exist. If `manifest.csv` exists, it selects `resume-analysis` automatically;
otherwise it selects `run-analysis`. Successful analysis is evaluated, the
selected median orthomosaic is read from `selected_product.json`, and Level-1B
is then launched with that product.

On Windows, the Level-1A runner automatically assigns a temporary short drive
letter for paths passed to Metashape. This avoids Metashape's legacy path-length
limit without changing the canonical run directory, manifest paths, IDs, or
Linux/macOS behavior. Do not start two `ps-run.ps1` instances for the same run
directory concurrently.

No setup script installs Agisoft Metashape, SAGA GIS, OTB, R itself, or other
licensed/system software automatically.

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

The YAML defines an admissible segmentation-radius domain; scene-adaptive multiband variogram pre-screening materializes the concrete Step-9a scale families. DGLCM measurement radii and channel names do not define that ladder. Each scale/ranger combination is evaluated with four deterministic translations of a radius-controlled hexagonal seed lattice and SAGA Seeded Region Growing; Step 9 ranks the robust geometric mean of seed-, ranger-, and radius-boundary persistence plus continuous scale-match support. Boundary distances are normalized by candidate radius; historical fixed edge/jump penalties are diagnostic only. See [RUN_LEVEL1B.md](docs/RUN_LEVEL1B.md) for dependencies, statuses, final products, and quality evidence.

## Scope boundaries

- Level-1A does not run Step 9 or Step 10 segmentation.
- Level-1B does not run Metashape reproducibility.
- Level-1B does not create an ecological classification.
- Level-1B does not assign a final quality class; it writes reviewable quality evidence.
- Neither workflow alone establishes absolute geometric accuracy or external truth.

## External software

Level-1A execution requires Agisoft Metashape. Its analyzer/evaluator also imports GDAL Python bindings. Level-1B requires OTB—including `DimensionalityReduction` and `HaralickTextureExtraction` for its deterministic six-band RGB proxy stack—SAGA GIS for Seeded Region Growing, GDAL Python/CLI components, and R packages used by exactextractr. These components must be installed compatibly with the local operating system and Python/R environments; the setup scripts report their availability but do not install the system software.

On native Windows, the setup scripts install matching GDAL Python bindings from conda-forge inside `.conda-env`. Linux/macOS retain their platform-specific GDAL installation contract.

## License and attribution

This repository is distributed under the BSD 3-Clause License. Adapted UC Davis / AM2 / automate-metashape components retain their original notices in [LICENSE](LICENSE); project-specific attribution is in [NOTICE.md](NOTICE.md).
