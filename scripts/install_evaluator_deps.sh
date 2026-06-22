#!/usr/bin/env bash
# Copyright (c) 2026 Chris Reudenbach, Lars Opgenoorth, Christian Mestre Runge
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -n "${PYTHON:-}" ]]; then
  PYTHON_EXE="${PYTHON}"
elif [[ -n "${VIRTUAL_ENV:-}" ]]; then
  PYTHON_EXE="${VIRTUAL_ENV}/bin/python"
elif [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  PYTHON_EXE="${REPO_ROOT}/.venv/bin/python"
else
  echo "ERROR: No project virtual environment found. Create or activate a venv, or set PYTHON=/path/to/venv/bin/python." >&2
  exit 1
fi

if ! command -v "${PYTHON_EXE}" >/dev/null 2>&1; then
  echo "ERROR: Python executable not found: ${PYTHON_EXE}" >&2
  exit 1
fi

if ! "${PYTHON_EXE}" - <<'PY'
import sys
raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)
PY
then
  echo "ERROR: Selected Python is not inside a virtual environment: ${PYTHON_EXE}" >&2
  echo "       Create or activate a venv, or set PYTHON=/path/to/venv/bin/python." >&2
  exit 1
fi

if ! command -v gdal-config >/dev/null 2>&1; then
  echo "ERROR: gdal-config is missing. Install the system GDAL development package first." >&2
  echo "       On Debian/Ubuntu this is usually: sudo apt install libgdal-dev gdal-bin" >&2
  exit 1
fi

GDAL_VERSION="$(gdal-config --version)"

echo "Using Python: $("${PYTHON_EXE}" -c 'import sys; print(sys.executable)')"
echo "Detected system GDAL version: ${GDAL_VERSION}"

"${PYTHON_EXE}" -m pip install --upgrade pip setuptools wheel

echo "Installing numpy before GDAL..."
"${PYTHON_EXE}" -m pip install --upgrade numpy

echo "Installing rasterio..."
"${PYTHON_EXE}" -m pip install --upgrade rasterio

echo "Removing any existing GDAL Python binding..."
"${PYTHON_EXE}" -m pip uninstall -y GDAL >/dev/null 2>&1 || true

echo "Installing GDAL==${GDAL_VERSION} with --no-build-isolation..."
"${PYTHON_EXE}" -m pip install --no-build-isolation "GDAL==${GDAL_VERSION}"

"${PYTHON_EXE}" - <<'PY'
import numpy
import rasterio
from osgeo import gdal
from osgeo import gdal_array

print("numpy:", numpy.__version__)
print("rasterio:", rasterio.__version__)
print("gdal:", gdal.VersionInfo())
print("gdal_array:", gdal_array.__file__)
PY
