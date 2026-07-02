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

# Preserve the complete OTB CLI runtime before sanitizing the Python process.
export LEVEL1B_OTB_PYTHONPATH_ORIG="${PYTHONPATH:-}"
export LEVEL1B_OTB_LD_LIBRARY_PATH_ORIG="${LD_LIBRARY_PATH:-}"
export LEVEL1B_OTB_APPLICATION_PATH_ORIG="${OTB_APPLICATION_PATH:-}"
export LEVEL1B_OTB_PATH_ORIG="$PATH"
export LEVEL1B_OTB_GDAL_DATA_ORIG="${GDAL_DATA:-}"
export LEVEL1B_OTB_PROJ_LIB_ORIG="${PROJ_LIB:-}"

export PYTHONPATH="$REPO:${PYTHONPATH:-}"

# OTB CLI tools run as external commands. Do not let OTB's Python bindings
# shadow the active venv GDAL bindings, which are compatible with NumPy 2.
IFS=':' read -r -a _PYTHONPATH_ENTRIES <<< "${PYTHONPATH:-}"
_SANITIZED_PYTHONPATH_ENTRIES=()
for _PYTHONPATH_ENTRY in "${_PYTHONPATH_ENTRIES[@]}"; do
  case "$_PYTHONPATH_ENTRY" in
    "$OTB_ROOT"/lib/python*/dist-packages|\
    "$OTB_ROOT"/lib/python*/site-packages|\
    "$OTB_ROOT"/lib/otb/python)
      continue
      ;;
  esac
  _SANITIZED_PYTHONPATH_ENTRIES+=("$_PYTHONPATH_ENTRY")
done
if (( ${#_SANITIZED_PYTHONPATH_ENTRIES[@]} > 0 )); then
  PYTHONPATH="$(IFS=:; printf '%s' "${_SANITIZED_PYTHONPATH_ENTRIES[*]}")"
  export PYTHONPATH
else
  unset PYTHONPATH
fi
unset _PYTHONPATH_ENTRIES _SANITIZED_PYTHONPATH_ENTRIES _PYTHONPATH_ENTRY

IFS=':' read -r -a _LD_LIBRARY_PATH_ENTRIES <<< "${LD_LIBRARY_PATH:-}"
_SANITIZED_LD_LIBRARY_PATH_ENTRIES=()
for _LD_LIBRARY_PATH_ENTRY in "${_LD_LIBRARY_PATH_ENTRIES[@]}"; do
  case "$_LD_LIBRARY_PATH_ENTRY" in
    "$OTB_ROOT"/lib|"$OTB_ROOT"/lib/*)
      continue
      ;;
  esac
  _SANITIZED_LD_LIBRARY_PATH_ENTRIES+=("$_LD_LIBRARY_PATH_ENTRY")
done
if (( ${#_SANITIZED_LD_LIBRARY_PATH_ENTRIES[@]} > 0 )); then
  LD_LIBRARY_PATH="$(IFS=:; printf '%s' "${_SANITIZED_LD_LIBRARY_PATH_ENTRIES[*]}")"
  export LD_LIBRARY_PATH
else
  unset LD_LIBRARY_PATH
fi
unset _LD_LIBRARY_PATH_ENTRIES _SANITIZED_LD_LIBRARY_PATH_ENTRIES _LD_LIBRARY_PATH_ENTRY

echo "PYTHONPATH sanitized for Python runner"
echo "LD_LIBRARY_PATH sanitized for Python runner"

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
python3 -c 'import osgeo; print(f"OSGEO_IMPORT_PATH={osgeo.__file__}")'

python3 -m metashape_qc_engine.level1b_dumb_runner "${RUNNER_ARGS[@]}"
