# Metashape runtime setup

This workflow is executed inside the Agisoft Metashape Python runtime. The system Python is not sufficient, because the `Metashape` module is only available when the script is launched through `metashape.sh`.

The repository therefore separates three things:

1. the workflow code in `python/`,
2. external Python dependencies in `requirements-metashape.txt`,
3. a local, non-committed dependency directory in `python/vendor/`.

`python/vendor/` is generated locally and must not be committed.

## Required files

The repository contains the following helper files:

```text
requirements-metashape.txt
scripts/bootstrap_metashape_deps.sh
scripts/run_metashape_workflow.sh
```

The repository `.gitignore` must contain:

```gitignore
# Local Python dependencies for Agisoft Metashape runtime
python/vendor/
```

## Why this is needed

Metashape provides its own Python environment and the `Metashape` module. However, this environment does not necessarily include additional Python packages used by the workflow, for example `PyYAML`.

The workflow reads YAML configuration files. Therefore `PyYAML` is required. Because the Metashape-internal `pip` installation can be incomplete or broken on some installations, dependencies are installed into a local repository directory:

```text
python/vendor/
```

The workflow script adds this directory to `sys.path` before importing workflow modules. This makes the dependencies available inside the Metashape runtime without modifying the Metashape installation itself.

## One-time dependency setup

From the repository root:

```bash
cd ~/dev/automate-metashape-2
scripts/bootstrap_metashape_deps.sh
```

This installs the packages listed in:

```text
requirements-metashape.txt
```

into:

```text
python/vendor/
```

At minimum, the requirements file contains:

```text
PyYAML>=6.0
```

## Running the workflow

Metashape is launched through the wrapper script:

```bash
scripts/run_metashape_workflow.sh config/test_mesh_ortho_franzosenwiese.yml
```

If `metashape.sh` is not available in `PATH`, set `METASHAPE_DIR` explicitly:

```bash
METASHAPE_DIR="/home/creu/apps/metashape-pro" \
scripts/run_metashape_workflow.sh config/test_mesh_ortho_franzosenwiese.yml
```

For other users, the path must be adapted to their local Metashape installation, for example:

```bash
METASHAPE_DIR="/opt/metashape-pro" \
scripts/run_metashape_workflow.sh config/my_config.yml
```

## Expected launcher behavior

The runner searches for Metashape in this order:

1. `METASHAPE_DIR/metashape.sh`, if `METASHAPE_DIR` is set,
2. `metashape.sh` from `PATH`,
3. otherwise it stops with a clear error message.

The workflow is then executed with:

```bash
metashape.sh -r python/metashape_workflow.py <config.yml>
```

## Local dependency path inside the workflow

The workflow script must add the repository root and the local vendor directory to `sys.path` before importing workflow modules.

The relevant logic in `python/metashape_workflow.py` is:

```python
# Make repo-local vendored dependencies available inside the Metashape runtime.
from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parents[1]
_VENDOR_DIR = _REPO_ROOT / "python" / "vendor"

if _VENDOR_DIR.is_dir():
    sys.path.insert(0, str(_VENDOR_DIR))

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
```

This avoids two common runtime errors:

```text
ModuleNotFoundError: No module named 'yaml'
```

and, depending on the launch context:

```text
ModuleNotFoundError: No module named 'python'
```

## Do not commit generated dependencies

The following directory is local runtime state:

```text
python/vendor/
```

It is created by:

```bash
scripts/bootstrap_metashape_deps.sh
```

and must not be committed. The repository should only track:

```text
requirements-metashape.txt
scripts/bootstrap_metashape_deps.sh
scripts/run_metashape_workflow.sh
.gitignore
```

## Minimal test

After bootstrapping dependencies, run:

```bash
METASHAPE_DIR="/home/creu/apps/metashape-pro" \
scripts/run_metashape_workflow.sh config/test_mesh_ortho_franzosenwiese.yml
```

A successful start should print the Metashape version and continue into the workflow without failing on missing Python modules.

Typical successful startup begins like this:

```text
Agisoft Metashape Professional Version: 2.3.1 ...
Platform: Linux
CPU: ...
RAM: ...
```

If the workflow stops after that, the Metashape runtime setup is working and the next error belongs to the actual photogrammetry workflow or configuration.
