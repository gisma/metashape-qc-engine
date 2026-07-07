#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STUDY_CONFIG="${1:-$REPO_ROOT/config/sensitivity/level1ab_sensitivity.yaml}"
STAGE="${2:-plan}"

cd "$REPO_ROOT"
if [[ -f "$REPO_ROOT/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.venv/bin/activate"
fi

python3 -m metashape_qc_engine.level1ab_sensitivity_runner \
  --study "$STUDY_CONFIG" \
  --stage "$STAGE"
