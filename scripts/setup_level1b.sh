#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$REPO_ROOT/.venv"
PYTHON_VENV_STATUS="OK"
PYTHON_IMPORTS_STATUS="OK"
GDAL_PYTHON_STATUS="MISSING"
OTB_STATUS="OK"
SAGA_STATUS="MISSING"
GDAL_CLI_STATUS="OK"
RSCRIPT_STATUS="MISSING"
R_PACKAGES_STATUS="MISSING"

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
  PYTHON_VENV_STATUS="MISSING"
  missing "pip upgrade failed in $VENV_DIR"
fi
if [[ "$PYTHON_VENV_STATUS" == "OK" ]] && ! python -m pip install -e .; then
  PYTHON_VENV_STATUS="MISSING"
  missing "editable project installation failed"
fi
if [[ "$PYTHON_VENV_STATUS" == "OK" ]] && ! python -m pip install matplotlib; then
  PYTHON_VENV_STATUS="MISSING"
  missing "matplotlib installation failed"
fi

if python - <<'PYIMPORT'
import matplotlib
import numpy
import rasterio
import yaml
PYIMPORT
then
  ok "Python imports: numpy, yaml, rasterio, matplotlib"
else
  PYTHON_IMPORTS_STATUS="MISSING"
  missing "one or more Python imports failed: numpy, yaml, rasterio, matplotlib"
fi

if python - <<'PYGDAL'
from osgeo import gdal, ogr, osr
PYGDAL
then
  GDAL_PYTHON_STATUS="OK"
  ok "GDAL Python bindings: osgeo.gdal, osgeo.ogr, osgeo.osr"
elif command -v gdal-config >/dev/null 2>&1; then
  GDAL_VERSION="$(gdal-config --version)"
  printf 'GDAL Python bindings unavailable; trying GDAL==%s from gdal-config.\n' "$GDAL_VERSION"
  if python -m pip install "GDAL==$GDAL_VERSION" && python - <<'PYGDAL'
from osgeo import gdal, ogr, osr
PYGDAL
  then
    GDAL_PYTHON_STATUS="OK"
    ok "GDAL Python bindings installed for GDAL $GDAL_VERSION"
  else
    missing "GDAL Python binding installation failed for GDAL $GDAL_VERSION"
  fi
else
  missing "GDAL Python bindings unavailable and gdal-config was not found"
fi

OTB_TOOLS=(
  otbcli_BandMathX
  otbcli_DimensionalityReduction
  otbcli_HaralickTextureExtraction
  otbcli_ComputeImagesStatistics
)
MISSING_OTB=()
for tool in "${OTB_TOOLS[@]}"; do
  if command -v "$tool" >/dev/null 2>&1; then
    ok "$tool: $(command -v "$tool")"
  else
    OTB_STATUS="MISSING"
    MISSING_OTB+=("$tool")
    missing "$tool"
  fi
done

if command -v saga_cmd >/dev/null 2>&1; then
  SAGA_STATUS="OK"
  ok "saga_cmd: $(command -v saga_cmd)"
else
  missing "saga_cmd"
fi

GDAL_CLI_TOOLS=(gdal_edit.py ogr2ogr)
MISSING_GDAL_CLI=()
for tool in "${GDAL_CLI_TOOLS[@]}"; do
  if command -v "$tool" >/dev/null 2>&1; then
    ok "$tool: $(command -v "$tool")"
  else
    GDAL_CLI_STATUS="MISSING"
    MISSING_GDAL_CLI+=("$tool")
    missing "$tool"
  fi
done

R_PACKAGES=(sf terra exactextractr jsonlite readr)
MISSING_R_PACKAGES=()
if command -v Rscript >/dev/null 2>&1; then
  RSCRIPT_STATUS="OK"
  ok "Rscript: $(command -v Rscript)"
  for package in "${R_PACKAGES[@]}"; do
    if Rscript -e "quit(status=if (requireNamespace('$package', quietly=TRUE)) 0 else 1)"; then
      ok "R package: $package"
    else
      MISSING_R_PACKAGES+=("$package")
      missing "R package: $package"
    fi
  done
  if [[ "${#MISSING_R_PACKAGES[@]}" -eq 0 ]]; then
    R_PACKAGES_STATUS="OK"
  else
    printf '%s\n' "Rscript -e 'install.packages(c(\"sf\",\"terra\",\"exactextractr\",\"jsonlite\",\"readr\"))'"
  fi
else
  missing "Rscript"
  printf '%s\n' "Rscript -e 'install.packages(c(\"sf\",\"terra\",\"exactextractr\",\"jsonlite\",\"readr\"))'"
fi

printf '\nLevel-1B setup summary\n'
printf '  Python venv/package: %s\n' "$PYTHON_VENV_STATUS"
printf '  Python imports: %s\n' "$PYTHON_IMPORTS_STATUS"
printf '  GDAL Python bindings: %s\n' "$GDAL_PYTHON_STATUS"
printf '  OTB CLI tools: %s' "$OTB_STATUS"
if [[ "${#MISSING_OTB[@]}" -gt 0 ]]; then printf ' (%s)' "${MISSING_OTB[*]}"; fi
printf '\n'
printf '  SAGA Seeded Region Growing: %s\n' "$SAGA_STATUS"
printf '  GDAL CLI tools: %s' "$GDAL_CLI_STATUS"
if [[ "${#MISSING_GDAL_CLI[@]}" -gt 0 ]]; then printf ' (%s)' "${MISSING_GDAL_CLI[*]}"; fi
printf '\n'
printf '  Rscript: %s\n' "$RSCRIPT_STATUS"
printf '  R packages: %s' "$R_PACKAGES_STATUS"
if [[ "${#MISSING_R_PACKAGES[@]}" -gt 0 ]]; then printf ' (%s)' "${MISSING_R_PACKAGES[*]}"; fi
printf '\n'
printf '  Note: this script does not install SAGA, OTB, GDAL CLI tools, R, or Agisoft Metashape.\n'

if [[ "$PYTHON_VENV_STATUS" != "OK" || "$PYTHON_IMPORTS_STATUS" != "OK" ]]; then
  exit 1
fi
