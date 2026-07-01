#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$REPO_ROOT/.venv"
PYTHON_STATUS="OK"
IMPORT_STATUS="OK"
GDAL_PYTHON_STATUS="OK"
METASHAPE_STATUS="MISSING"

ok() {
  printf 'OK: %s\n' "$1"
}

missing() {
  printf 'MISSING: %s\n' "$1" >&2
}

cd "$REPO_ROOT"

if [[ ! -d "$VENV_DIR" ]]; then
  if python3 -m venv "$VENV_DIR"; then
    ok "created Python venv at $VENV_DIR"
  else
    missing "could not create Python venv at $VENV_DIR"
    exit 1
  fi
else
  ok "using existing Python venv at $VENV_DIR"
fi

# shellcheck disable=SC1091
if ! source "$VENV_DIR/bin/activate"; then
  missing "could not activate Python venv at $VENV_DIR"
  exit 1
fi

if ! python -m pip install --upgrade pip; then
  PYTHON_STATUS="MISSING"
  missing "pip upgrade failed in $VENV_DIR"
fi
if [[ "$PYTHON_STATUS" == "OK" ]] && ! python -m pip install -e .; then
  PYTHON_STATUS="MISSING"
  missing "editable project installation failed"
fi

if [[ "$PYTHON_STATUS" == "OK" ]] && command -v metashape-qc >/dev/null 2>&1; then
  ok "metashape-qc is available at $(command -v metashape-qc)"
else
  PYTHON_STATUS="MISSING"
  missing "metashape-qc is not available in the venv"
fi

if python - <<'PYIMPORT'
import numpy
import rasterio
import yaml
PYIMPORT
then
  ok "Python imports: numpy, yaml, rasterio"
else
  IMPORT_STATUS="MISSING"
  missing "one or more Python imports failed: numpy, yaml, rasterio"
fi

# The Level-1A analyzer/evaluator imports osgeo.gdal, but GDAL installation is system-specific.
if python - <<'PYGDAL'
from osgeo import gdal
PYGDAL
then
  ok "Level-1A analyzer import: osgeo.gdal"
else
  GDAL_PYTHON_STATUS="MISSING"
  missing "osgeo.gdal is unavailable; analysis/evaluation cannot run"
fi

if [[ -n "${METASHAPE_DIR:-}" ]]; then
  if [[ -x "$METASHAPE_DIR/metashape.sh" ]]; then
    METASHAPE_STATUS="OK"
    ok "Metashape launcher: $METASHAPE_DIR/metashape.sh"
  else
    missing "METASHAPE_DIR is set but does not contain executable metashape.sh: $METASHAPE_DIR"
  fi
elif command -v metashape.sh >/dev/null 2>&1; then
  METASHAPE_STATUS="OK"
  ok "Metashape launcher: $(command -v metashape.sh)"
else
  missing "metashape.sh not found; set METASHAPE_DIR to an existing Agisoft Metashape installation"
fi

printf '\nLevel-1A setup summary\n'
printf '  Python venv/package: %s\n' "$PYTHON_STATUS"
printf '  Base Python imports: %s\n' "$IMPORT_STATUS"
printf '  GDAL Python bindings: %s\n' "$GDAL_PYTHON_STATUS"
printf '  Agisoft Metashape: %s\n' "$METASHAPE_STATUS"
printf '  Note: this script does not install Agisoft Metashape or GDAL system software.\n'

if [[ "$PYTHON_STATUS" != "OK" || "$IMPORT_STATUS" != "OK" ]]; then
  exit 1
fi
