#!/usr/bin/env bash
# Copyright (c) 2026 Chris Reudenbach, Lars Opgenoorth, Christian Mestre Runge
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="${1:?Usage: scripts/run_metashape_workflow.sh <config.yml>}"

if [[ -n "${METASHAPE_DIR:-}" ]]; then
  METASHAPE_BIN="$METASHAPE_DIR/metashape.sh"
elif command -v metashape.sh >/dev/null 2>&1; then
  METASHAPE_BIN="$(command -v metashape.sh)"
else
  echo "ERROR: Could not find metashape.sh." >&2
  echo "Set METASHAPE_DIR to your Agisoft Metashape installation directory, e.g.:" >&2
  echo "  METASHAPE_DIR=/path/to/metashape-pro scripts/run_metashape_workflow.sh <config.yml>" >&2
  exit 1
fi

if [[ ! -x "$METASHAPE_BIN" ]]; then
  echo "ERROR: Metashape launcher is not executable: $METASHAPE_BIN" >&2
  exit 1
fi

PYTHONPATH="$REPO_ROOT/python/vendor${PYTHONPATH:+:$PYTHONPATH}" \
"$METASHAPE_BIN" -r \
"$REPO_ROOT/python/metashape_workflow.py" \
"$CONFIG_FILE"
