#!/usr/bin/env bash
set -Eeuo pipefail

ORTHO="${ORTHO:-/home/creu/tmp/cut-ref-ortho.tif}"
REPO="${REPO:-/home/creu/dev/metashape-qc-engine}"
RUN_ROOT="${RUN_ROOT:-/home/creu/tmp/level1b_runs/level1b_$(date +%Y%m%dT%H%M%S)}"
OVERWRITE="${OVERWRITE:-0}"
OTB_ROOT="${OTB_ROOT:-$HOME/apps/otb911}"

mkdir -p "$RUN_ROOT"
SHELL_LOG="$RUN_ROOT/level1b_chain.log"
exec > >(tee -a "$SHELL_LOG") 2>&1

if [[ -f "$OTB_ROOT/otbenv.profile" ]]; then
  _NOUNSET_WAS_ON=0
  case "$-" in
    *u*) _NOUNSET_WAS_ON=1; set +u ;;
  esac
  # shellcheck disable=SC1091
  source "$OTB_ROOT/otbenv.profile"
  if [[ "$_NOUNSET_WAS_ON" == "1" ]]; then
    set -u
  fi
  unset _NOUNSET_WAS_ON
fi

if [[ -d "$OTB_ROOT/bin" ]]; then
  export PATH="$OTB_ROOT/bin:$PATH"
fi
if [[ -d "$OTB_ROOT/lib" ]]; then
  export LD_LIBRARY_PATH="$OTB_ROOT/lib:${LD_LIBRARY_PATH:-}"
fi

REAL_GDAL_EDIT="$(command -v gdal_edit.py || true)"
if [[ -n "$REAL_GDAL_EDIT" ]]; then
  RUNTIME_BIN="$(mktemp -d "${TMPDIR:-/tmp}/level1b-runtime.XXXXXX")"
  trap 'rm -f "$RUNTIME_BIN/gdal_edit.py"; rmdir "$RUNTIME_BIN" 2>/dev/null || true' EXIT
  cat > "$RUNTIME_BIN/gdal_edit.py" <<EOF
#!/usr/bin/env bash
exec python3 "$REAL_GDAL_EDIT" "\$@"
EOF
  chmod +x "$RUNTIME_BIN/gdal_edit.py"
  export PATH="$RUNTIME_BIN:$PATH"
fi

export PYTHONPATH="$REPO:${PYTHONPATH:-}"
cd "$REPO"

RUNNER_ARGS=(
  --rgb-ortho "$ORTHO"
  --out-dir "$RUN_ROOT"
)
if [[ "$OVERWRITE" == "1" ]]; then
  RUNNER_ARGS+=(--overwrite)
fi

echo "Level-1b runner"
echo "ORTHO=$ORTHO"
echo "RUN_ROOT=$RUN_ROOT"
echo "SHELL_LOG=$SHELL_LOG"
printf 'COMMAND=python3 -m metashape_qc_engine.level1b_dumb_runner'
printf ' %q' "${RUNNER_ARGS[@]}"
printf '\n'

python3 -m metashape_qc_engine.level1b_dumb_runner "${RUNNER_ARGS[@]}"
