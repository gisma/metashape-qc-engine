#!/usr/bin/env bash
# Copyright (c) 2026 Chris Reudenbach, Lars Opgenoorth, Christian Mestre Runge
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
METASHAPE_DIR="${METASHAPE_DIR:-/home/creu/apps/metashape-pro}"
VENDOR_DIR="$REPO_ROOT/metashape_qc_engine/level1a/vendor"

mkdir -p "$VENDOR_DIR"

python3 -m pip install \
  --upgrade \
  --target "$VENDOR_DIR" \
  -r "$REPO_ROOT/requirements-metashape.txt"

echo "Installed Metashape workflow dependencies into:"
echo "$VENDOR_DIR"
