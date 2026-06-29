#!/usr/bin/env bash
set -Eeuo pipefail

ORTHO="${ORTHO:-/home/creu/tmp/cut-ref-ortho.tif}"
REPO="${REPO:-/home/creu/dev/metashape-qc-engine}"
CANDIDATE_ID="${CANDIDATE_ID:-cutref_fullrange}"
RUN_ROOT="${RUN_ROOT:-/home/creu/tmp/level1b_runs/${CANDIDATE_ID}_clean_$(date +%Y%m%dT%H%M%S)}"

USE_PCA="${USE_PCA:-0}"
PCA_COMPONENTS="${PCA_COMPONENTS:-3}"
RAM_MB="${RAM_MB:-8192}"
OVERWRITE="${OVERWRITE:-0}"
DRY_RUN="${DRY_RUN:-0}"
REQUIRE_STEP9="${REQUIRE_STEP9:-1}"

OTB_ROOT="${OTB_ROOT:-$HOME/apps/otb911}"

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
  OTB_BIN_DIR="${OTB_BIN_DIR:-$OTB_ROOT/bin}"
else
  OTB_BIN_DIR="${OTB_BIN_DIR:-}"
fi

if [[ -d "$OTB_ROOT/lib" ]]; then
  export LD_LIBRARY_PATH="$OTB_ROOT/lib:${LD_LIBRARY_PATH:-}"
fi

export ORTHO REPO RUN_ROOT CANDIDATE_ID USE_PCA PCA_COMPONENTS RAM_MB OVERWRITE DRY_RUN REQUIRE_STEP9 OTB_ROOT OTB_BIN_DIR

if [[ ! -f "$ORTHO" ]]; then
  echo "ERROR: ORTHO not found: $ORTHO" >&2
  exit 2
fi

if [[ ! -d "$REPO" ]]; then
  echo "ERROR: REPO not found: $REPO" >&2
  exit 3
fi

mkdir -p "$RUN_ROOT/_driver_logs" "$RUN_ROOT/_driver_reports"

DRIVER_LOG="$RUN_ROOT/_driver_logs/driver_$(date +%Y%m%dT%H%M%S).log"
exec > >(tee -a "$DRIVER_LOG") 2>&1

echo "============================================================"
echo "Level-1b clean chain driver"
echo "============================================================"
echo "ORTHO=$ORTHO"
echo "REPO=$REPO"
echo "RUN_ROOT=$RUN_ROOT"
echo "CANDIDATE_ID=$CANDIDATE_ID"
echo "USE_PCA=$USE_PCA"
echo "PCA_COMPONENTS=$PCA_COMPONENTS"
echo "OTB_ROOT=$OTB_ROOT"
echo "OTB_BIN_DIR=$OTB_BIN_DIR"
echo "RAM_MB=$RAM_MB"
echo "DRY_RUN=$DRY_RUN"
echo "OVERWRITE=$OVERWRITE"
echo "REQUIRE_STEP9=$REQUIRE_STEP9"
echo "DRIVER_LOG=$DRIVER_LOG"
echo "============================================================"

echo "OTB executables:"
command -v otbcli_BandMathX || true
command -v otbcli_MeanShiftSmoothing || true
command -v otbcli_LSMSSegmentation || true
command -v otbcli_LSMSSmallRegionsMerging || true
command -v otbcli_HooverCompareSegmentation || true
echo "============================================================"
echo "GDAL Python utility wrapper:"
REAL_GDAL_EDIT="$(command -v gdal_edit.py || true)"
if [[ -n "$REAL_GDAL_EDIT" ]]; then
  mkdir -p "$RUN_ROOT/_runtime_bin"
  cat > "$RUN_ROOT/_runtime_bin/gdal_edit.py" <<EOF
#!/usr/bin/env bash
exec python3 "$REAL_GDAL_EDIT" "\$@"
EOF
  chmod +x "$RUN_ROOT/_runtime_bin/gdal_edit.py"
  export PATH="$RUN_ROOT/_runtime_bin:$PATH"
  echo "REAL_GDAL_EDIT=$REAL_GDAL_EDIT"
  echo "WRAPPED_GDAL_EDIT=$RUN_ROOT/_runtime_bin/gdal_edit.py"
else
  echo "WARNING: gdal_edit.py not found on PATH before wrapper"
fi
export PYTHONPATH="$REPO:${PYTHONPATH:-}"
echo "PYTHON=$(command -v python3 || true)"
python3 --version || true
echo "============================================================"

echo "Running Level-1b dumb runner"
echo "============================================================"

cd "$REPO"

DUMB_ARGS=(
  --rgb-ortho "$ORTHO"
  --out-dir "$RUN_ROOT"
)

if [[ "$OVERWRITE" == "1" ]]; then
  DUMB_ARGS+=(--overwrite)
fi

echo "DUMB RUNNER COMMAND:"
printf 'python3 -m metashape_qc_engine.level1b_dumb_runner'
printf ' %q' "${DUMB_ARGS[@]}"
printf '\n'
echo "============================================================"

if [[ "$DRY_RUN" == "1" ]]; then
  echo "DRY_RUN=1, not executing dumb runner."
  exit 0
fi

python3 -m metashape_qc_engine.level1b_dumb_runner "${DUMB_ARGS[@]}"
