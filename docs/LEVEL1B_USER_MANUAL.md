# Level-1b user manual

## Purpose

Level-1b turns one orthomosaic into a raster-only candidate-scale evidence space. It does not choose a final ecological object layer and it does not create vector final products.

Its job is to create valid support, feature proxies, candidate scale candidates, feature-space `ranger` values, local perturbation combinations, and then analyze the candidate-scale response surface produced by those combinations.

The active Step 9 now evaluates the distributional and spatial response of the candidate scale groups. It does not run full OTB Hoover comparisons by default.

## Inputs

Minimum input for the current MOF test run:

```bash
ORTHO=/datadisk/data/uav/MOF_repro_test_recovered/runs/experiment_mesh_facecount_smoothing_reps5/variants/fc050k_smooth_5/runs/rep_004/output/mof_forest_knoll_rgb_mesh_ortho_fc050k_smooth_5_rep_004_20260620T1211_ortho_mesh.tif
REPO=/home/creu/dev/metashape-qc-engine
OTB_ROOT=$HOME/apps/otb911
```

The driver assumes that OTB 9.1.1 is installed under `$HOME/apps/otb911` unless `OTB_ROOT` is overridden. The driver sources `otbenv.profile`, prepends `$OTB_ROOT/bin` to `PATH`, and sets `LD_LIBRARY_PATH` when `$OTB_ROOT/lib` exists.

## Start a clean run

Use a fresh timestamped `RUN_ROOT`. Do not overwrite a failed run unless you are deliberately debugging the same folder.

```bash
cd /home/creu/dev/metashape-qc-engine || exit 1

OTB_ROOT="$HOME/apps/otb911" \
RUN_ROOT="/datadisk/data/uav/MOF_repro_test_recovered/level1b_runs/mof_rep004_fc050k_smooth5_clean_$(date +%Y%m%dT%H%M%S)" \
/home/creu/tmp/run_level1b_mof_rep004_chain_clean.sh
```

The Step-6 block is not changed by this manual update. It must match the currently implemented `Level1BScaleDistributionConfig` in the repository.

The current active Step-9 block must import and call the response-surface module:

```python
from metashape_qc_engine.level1b_candidate_response_surface import (
    Level1BCandidateResponseSurfaceConfig,
    run_candidate_response_surface_step,
)

cfg = Level1BCandidateResponseSurfaceConfig(
    candidate_id=CANDIDATE_ID,
    output_dir=RUN_ROOT,
    perturbation_candidates_json_path=perturbation_candidates_json,
    feature_space_stack_path=feature_space_stack,
    valid_mask_path=valid_mask,
    otb_bin_dir=OTB_BIN_DIR,
    ram_mb=RAM_MB,
    overwrite=OVERWRITE,
    dry_run=DRY_RUN,
    run_hoover_audit=False,
)
return run_candidate_response_surface_step(cfg)
```

## What happens during a run

| step | name | what it does | main outputs |
|---:|---|---|---|
| 1 | preflight | Checks input contract, expected layout and OTB availability. | `level1b/reports/preflight.json` |
| 3 | valid mask | Creates valid observation support. Rejects RGB `(0,0,0)` and `(255,255,255)` by default and keeps nodata/alpha logic when supplied. | `level1b/mask/valid_mask.tif`, `valid_mask_report.json` |
| 4 | channels/proxy | Builds the default RGB proxy stack: VIG, DRY, BRI, TEX_100M, TEX_200M, mask-gated. | `level1b/channels/proxy_stack.tif`, `channel_report.json` |
| 5a | scaling | Mask-aware scaling/z-score preparation. | `level1b/scaling/scaled_feature_stack.tif`, scaling reports |
| 5b | PCA | Optional PCA feature-space stack, used by default in the current driver. | `level1b/pca/pca_feature_stack.tif`, `pca_report.json` |
| 6 | scale distribution | Builds the candidate scale distribution according to the current Step-6 implementation. | `level1b/scales/scale_candidates.csv/json` |
| 7 | feature range | Derives `ranger` from feature-space kNN distances and assigns them to Step-6 candidates. | `level1b/ranger/ranger_candidates.*`, `scale_candidates_with_ranger.*` |
| 8 | perturbations | Creates local R-style perturbation sets around each coupled candidate. | `level1b/perturbations/perturbation_candidates.csv/json` |
| 9 | candidate response surface | Runs/reuses one-scale raster segmentations for planned Step-8 rows and analyzes segment-population distributions, spatial analysis-matrix patterns, scale jumps, flurry behavior, medoids and full candidate-space distributions. | `level1b/candidate_response_surface/*` |

## Expected Step-6 behavior

Step 6 remains as implemented in the repository. This manual update does not change Step 6 and does not instruct another Step-6 refinement.

When checking a run, always inspect the actual Step-6 return JSON and candidate JSON rather than assuming an external matrix:

```bash
jq '{
  status,
  scale_mode,
  scale_source,
  candidate_count,
  output_json_path,
  output_csv_path
}' "$RUN_ROOT/_driver_reports/step6_scale_distribution_return.json"
```

## Check progress

Find the latest run:

```bash
RUN_ROOT=$(ls -td /datadisk/data/uav/MOF_repro_test_recovered/level1b_runs/mof_rep004_fc050k_smooth5_clean_* | head -1)
echo "$RUN_ROOT"
```

Show completed driver steps:

```bash
find "$RUN_ROOT/_driver_reports" -maxdepth 1 -type f -printf '%f\n' | sort
```

Inspect Step 6:

```bash
jq '{
  status,
  scale_mode,
  scale_source,
  candidate_count,
  output_json_path,
  output_csv_path
}' "$RUN_ROOT/_driver_reports/step6_scale_distribution_return.json"
```

Count Step-9 work from Step-8 candidates:

```bash
P="$RUN_ROOT/level1b/perturbations/perturbation_candidates.json"
python - "$P" <<'PY'
import json, sys
from pathlib import Path
from collections import defaultdict

p=Path(sys.argv[1])
obj=json.loads(p.read_text())
rows=obj if isinstance(obj, list) else next(obj[k] for k in ('candidates','perturbations','rows','data') if k in obj)
groups=defaultdict(list)
for r in rows:
    key = (
        r.get('candidate_scale_group_id')
        or r.get('source_candidate_id')
        or r.get('source_scale_id')
        or r.get('scale_id')
        or r.get('candidate_id')
    )
    groups[key].append(r)

print('candidate-scale groups:', len(groups))
print('planned Step-9 runs:', len(rows))
for k, rs in sorted(groups.items()):
    print(k, 'runs=', len(rs))
PY
```

Monitor the new active Step 9:

```bash
pgrep -af "candidate_response_surface|one_scale|MeanShift|LSMS|otbcli" | sed -n '1,30p'

find "$RUN_ROOT/level1b/candidate_response_surface" -maxdepth 2 -type f \
  -printf '%TY-%Tm-%Td %TH:%TM:%TS %s %p\n' 2>/dev/null | sort | tail -30
```

The active Step 9 should not show `HooverCompareSegmentation` unless an explicit Hoover audit mode was enabled:

```bash
pgrep -af "HooverCompareSegmentation"
```

## Step-9 resume when Steps 1–8 are already complete

Use this when Steps 1–8 already produced `perturbation_candidates.json` and you want to run only the active response-surface Step 9.

```bash
cd /home/creu/dev/metashape-qc-engine || exit 1

export RUN_ROOT="/datadisk/data/uav/MOF_repro_test_recovered/level1b_runs/mof_rep004_fc050k_smooth5_clean_20260626T154455"
export OTB_ROOT="$HOME/apps/otb911"

source "$OTB_ROOT/otbenv.profile" 2>/dev/null || true
export PATH="$OTB_ROOT/bin:$PATH"
export LD_LIBRARY_PATH="$OTB_ROOT/lib:${LD_LIBRARY_PATH:-}"
export OTB_BIN_DIR="$OTB_ROOT/bin"

python - <<'PY'
from pathlib import Path
import json
import os

from metashape_qc_engine.level1b_candidate_response_surface import (
    Level1BCandidateResponseSurfaceConfig,
    run_candidate_response_surface_step,
)

RUN_ROOT = Path(os.environ["RUN_ROOT"])

feature_space_stack = RUN_ROOT / "level1b" / "pca" / "pca_feature_stack.tif"
if not feature_space_stack.exists():
    feature_space_stack = RUN_ROOT / "level1b" / "scaling" / "scaled_feature_stack.tif"

valid_mask = RUN_ROOT / "level1b" / "mask" / "valid_mask.tif"
perturbation_candidates_json = RUN_ROOT / "level1b" / "perturbations" / "perturbation_candidates.json"

for p in [feature_space_stack, valid_mask, perturbation_candidates_json]:
    if not p.exists():
        raise SystemExit(f"missing input: {p}")

cfg = Level1BCandidateResponseSurfaceConfig(
    candidate_id="mof_rep004_fc050k_smooth5",
    output_dir=RUN_ROOT,
    perturbation_candidates_json_path=perturbation_candidates_json,
    feature_space_stack_path=feature_space_stack,
    valid_mask_path=valid_mask,
    otb_bin_dir=os.environ.get("OTB_BIN_DIR"),
    ram_mb=8192,
    overwrite=False,
    dry_run=False,
    run_hoover_audit=False,
)

report = run_candidate_response_surface_step(cfg)

out = RUN_ROOT / "_driver_reports" / "step9_candidate_response_surface_return_resume.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

print(f"REPORT={out}")
print(json.dumps({
    "status": report.get("status"),
    "output_dir": report.get("output_dir"),
    "candidate_group_count": report.get("candidate_group_count"),
    "planned_run_count": report.get("planned_run_count"),
    "successful_run_count": report.get("successful_run_count"),
    "failed_run_count": report.get("failed_run_count"),
    "omitted_run_count": report.get("omitted_run_count"),
    "hoover_audit_ran": report.get("hoover_audit_ran"),
}, indent=2, default=str))
PY
```

## Main Step-9 outputs

The active Step 9 writes under:

```text
RUN_ROOT/level1b/candidate_response_surface/
```

Important files:

```text
candidate_response_surface_report.json
candidate_response_surface_summary.csv
candidate_response_surface_summary.json
run_population_summary.csv
run_population_summary.json
candidate_group_response_summary.csv
candidate_group_response_summary.json
analysis_matrix_summary.csv
analysis_matrix_summary.json
spatial_response_stability.csv
spatial_response_stability.json
candidate_space_distribution_summary.csv
candidate_space_distribution_summary.json
ranked_candidate_scales.csv
ranked_candidate_scales.json
stable_representative_combinations.json
accepted_scale_candidates.json
removed_scale_candidates.json
failed_runs.json
```

Quick report check:

```bash
jq '{
  status,
  candidate_group_count,
  planned_run_count,
  successful_run_count,
  failed_run_count,
  omitted_run_count,
  hoover_audit_ran
}' "$RUN_ROOT/level1b/candidate_response_surface/candidate_response_surface_report.json"
```

## Typical failures and meanings

| symptom | likely cause | action |
|---|---|---|
| `no OTB BandMathX app discoverable` | OTB env not loaded. | Set/source `$HOME/apps/otb911/otbenv.profile`; ensure `$OTB_ROOT/bin` is in `PATH`. |
| `unexpected keyword argument` | Chain driver is out of sync with current dataclass fields. | Audit the actual dataclass fields and change only the wrong keyword. Do not add silent filtering. |
| Step 6 config error | Driver does not match current Step-6 dataclass. | Keep Step 6 as implemented and align only the driver call to actual fields. |
| Step 9 reports failed runs because source radius is missing | Step-8 rows did not carry a usable candidate/source radius. | Inspect `perturbation_candidates.json` and Step-8 metadata; Step 9 needs a source candidate radius to compute `q_i`. |
| `HooverCompareSegmentation` appears during normal Step 9 | Wrong legacy Step-9 path or explicit audit accidentally enabled. | Stop the run and use `level1b_candidate_response_surface` with `run_hoover_audit=False`. |
| Step 9 creates many segmentation outputs | Normal. Each Step-8 row is one planned response-surface sample. | Count rows/groups in `perturbation_candidates.json` and monitor `candidate_response_surface` outputs. |

## Boundaries

Level-1b does not choose a final `selected_scale_id`. It does not create final labels, vectors, GPKG, shapefiles or zonal products. Those belong to later steps after response-surface evidence is interpreted.

Hoover comparison remains archived/audit logic. It is not the default active Level-1b Step-9 criterion.
