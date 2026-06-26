# Level-1b user manual

## Purpose

Level-1b turns one orthomosaic into a set of candidate segmentation stability results. It does not yet choose a final ecological object layer and it does not create vector final products. Its job is to create valid support, feature proxies, sampling-regime-adaptive scale candidates, feature-space ranger values, local perturbations, and then raster-only stability comparisons.

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

OTB_ROOT="$HOME/apps/otb911" RUN_ROOT="/datadisk/data/uav/MOF_repro_test_recovered/level1b_runs/mof_rep004_fc050k_smooth5_clean_$(date +%Y%m%dT%H%M%S)" /home/creu/tmp/run_level1b_mof_rep004_chain_clean.sh
```

The Step-6 block in the driver must pass the Step-4 proxy stack into Step 6:

```python
proxy_stack_path=feature_stack,
valid_mask_path=valid_mask,
proxy_structure_mode="texture_preferred",
sampling_regime="auto",
infer_structure_support_from_proxy=True,
infer_texture_support_from_proxy=True,
upper_radius_factor=2.5,
```

This is required so that Step 6 uses the texture bands of the proxy stack as structure evidence instead of asking for manual radius lists.

## What happens during a run

| step | name | what it does | main outputs |
|---:|---|---|---|
| 1 | preflight | Checks input contract, expected layout and OTB availability. | `level1b/reports/preflight.json` |
| 3 | valid mask | Creates valid observation support. Rejects RGB `(0,0,0)` and `(255,255,255)` by default and keeps nodata/alpha logic when supplied. | `level1b/mask/valid_mask.tif`, `valid_mask_report.json` |
| 4 | channels/proxy | Builds the default RGB proxy stack: VIG, DRY, BRI, TEX_100M, TEX_200M, mask-gated. | `level1b/channels/proxy_stack.tif`, `channel_report.json` |
| 5a | scaling | Mask-aware scaling/z-score preparation. | `level1b/scaling/scaled_feature_stack.tif`, scaling reports |
| 5b | PCA | Optional PCA feature-space stack, used by default in the current driver. | `level1b/pca/pca_feature_stack.tif`, `pca_report.json` |
| 6 | scale distribution | Sampling-regime-adaptive candidate scale generation from proxy/texture patches. | `level1b/scales/scale_candidates.csv/json` |
| 7 | feature range | Derives `ranger` from feature-space kNN distances and assigns them to Step-6 candidates. | `level1b/ranger/ranger_candidates.*`, `scale_candidates_with_ranger.*` |
| 8 | perturbations | Creates local R-style perturbation sets around each coupled candidate. | `level1b/perturbations/perturbation_candidates.csv/json` |
| 9 | candidate stability | Runs one-scale raster segmentation for baseline and perturbations, then Hoover comparisons. | `level1b/stability/scale_stability.csv/json` |

## Expected Step-6 behavior in the current MOF run

The latest successful Step-6 report in the bundle shows:

```text
scale_mode: structure_derived_scale_distribution
scale_source: proxy_stack
selected texture bands: TEX_100M, TEX_200M
effective_structure_support_max_m: 2.0
structure_support_to_gsd_ratio: about 40
sampling_regime_resolved: oversample
upper_envelope_radius_m: 5.0
candidate_count: 6
```

Observed candidate scales from that run:

| scale_id | radius_m | spatialr_px | minsize_px | patch quantile |
|---|---:|---:|---:|---:|
| r0p21m_px004 | 0.205 | 4 | 53 | 0.25 |
| r0p39m_px008 | 0.390 | 8 | 192 | 0.4 |
| r0p71m_px014 | 0.714 | 14 | 641 | 0.55 |
| r1p18m_px024 | 1.180 | 24 | 1752 | 0.7 |
| r2p02m_px040 | 2.021 | 40 | 5136 | 0.85 |
| r3p87m_px078 | 3.874 | 78 | 18871 | 0.95 |

Step 6 also reported 135 patches above the 5 m envelope and `extreme_homogeneous_patch_flag=true`. Those patches are diagnostics, not candidate scales.

## Check progress

Find the latest run:

```bash
RUN_ROOT=$(ls -td /datadisk/data/uav/MOF_repro_test_recovered/level1b_runs/mof_rep004_fc050k_smooth5_clean_* | head -1)
echo "$RUN_ROOT"
```

Show completed driver steps:

```bash
find "$RUN_ROOT/_driver_reports" -maxdepth 1 -type f -printf '%f
' | sort
```

Inspect Step 6:

```bash
jq '{
  status,
  scale_source,
  selected_structure_band_indices,
  selected_structure_band_roles,
  effective_structure_support_max_m,
  structure_support_to_gsd_ratio,
  sampling_regime_resolved,
  upper_envelope_radius_m,
  candidate_count,
  patch_count_above_envelope,
  no_raster_read
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
    groups[(r.get('source_candidate_id'), r.get('scale_id'))].append(r)
baseline=[r for r in rows if r.get('is_baseline')]
pert=[r for r in rows if not r.get('is_baseline')]
print('groups:', len(groups))
print('segmentation runs:', len(rows))
print('baseline runs:', len(baseline))
print('perturbation runs:', len(pert))
print('Hoover comparisons:', len(pert))
for k, rs in sorted(groups.items()):
    b=sum(bool(r.get('is_baseline')) for r in rs)
    print(k, 'total=', len(rs), 'baseline=', b, 'perturbations=', len(rs)-b)
PY
```

For the bundled run, Step 8 produced 6 groups with 9 rows each, so Step 9 has 54 segmentation runs and 48 Hoover comparisons.

## Step-9 resume when Steps 1–8 are already complete

The bundled latest run stopped at Step 9 because the chain driver used the outdated function name `run_candidate_stability_step`. The correct exported function is `run_candidate_stability`.

Create a small resume script:

```bash
cat > /home/creu/tmp/resume_level1b_step9_candidate_stability.py <<'PY'
from __future__ import annotations
import json, os
from pathlib import Path
from metashape_qc_engine.level1b_candidate_stability import Level1BCandidateStabilityConfig, run_candidate_stability

run_root_env = os.environ.get('RUN_ROOT')
if not run_root_env:
    raise SystemExit('RUN_ROOT is not set')
RUN_ROOT = Path(run_root_env)
CANDIDATE_ID = os.environ.get('CANDIDATE_ID', 'mof_rep004_fc050k_smooth5')
OTB_BIN_DIR = os.environ.get('OTB_BIN_DIR', str(Path.home() / 'apps/otb911/bin'))
feature_space_stack = RUN_ROOT / 'level1b' / 'pca' / 'pca_feature_stack.tif'
if not feature_space_stack.exists():
    feature_space_stack = RUN_ROOT / 'level1b' / 'scaling' / 'scaled_feature_stack.tif'
perturbation_candidates_json = RUN_ROOT / 'level1b' / 'perturbations' / 'perturbation_candidates.json'
for p in [feature_space_stack, perturbation_candidates_json]:
    if not p.exists():
        raise SystemExit(f'Missing Step-9 input: {p}')

cfg = Level1BCandidateStabilityConfig(
    candidate_id=CANDIDATE_ID,
    output_dir=RUN_ROOT,
    perturbation_candidates_json_path=perturbation_candidates_json,
    feature_space_stack_path=feature_space_stack,
    otb_bin_dir=OTB_BIN_DIR,
    ram_mb=int(os.environ.get('RAM_MB', '8192')),
    overwrite=os.environ.get('OVERWRITE', '0') == '1',
    dry_run=os.environ.get('DRY_RUN', '0') == '1',
)
report = run_candidate_stability(cfg)
out = RUN_ROOT / '_driver_reports' / 'step9_candidate_stability_return_resume.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
print(f'REPORT={out}')
print(json.dumps({
    'status': report.get('status'),
    'scale_stability_csv_path': report.get('scale_stability_csv_path'),
    'scale_stability_json_path': report.get('scale_stability_json_path'),
}, indent=2, default=str))
PY
```

Run it on the existing Step-1-to-8 run:

```bash
cd /home/creu/dev/metashape-qc-engine || exit 1
OTB_ROOT="$HOME/apps/otb911"
source "$OTB_ROOT/otbenv.profile" 2>/dev/null || true
export PATH="$OTB_ROOT/bin:$PATH"
export LD_LIBRARY_PATH="$OTB_ROOT/lib:${LD_LIBRARY_PATH:-}"
export RUN_ROOT="$(ls -td /datadisk/data/uav/MOF_repro_test_recovered/level1b_runs/mof_rep004_fc050k_smooth5_clean_* | head -1)"
export CANDIDATE_ID="mof_rep004_fc050k_smooth5"
export OTB_BIN_DIR="$OTB_ROOT/bin"
python /home/creu/tmp/resume_level1b_step9_candidate_stability.py
```

## Typical failures and meanings

| symptom | likely cause | action |
|---|---|---|
| `no OTB BandMathX app discoverable` | OTB env not loaded. | Set/source `$HOME/apps/otb911/otbenv.profile`; ensure `$OTB_ROOT/bin` is in `PATH`. |
| `unexpected keyword argument` | Chain driver is out of sync with current dataclass fields. | Audit against `python_api_inventory.json`; remove/adjust only the wrong config keyword. |
| Step 6 fails with no structure/proxy input | Driver did not pass `proxy_stack_path=feature_stack`. | Patch Step 6 block as shown above. |
| Step 6 takes long | It is doing full-raster proxy/texture evidence and connected-component patch analysis. | Check CPU/RAM/swap; do not assume it is stuck. |
| Step 9 import error for `run_candidate_stability_step` | Old driver name. | Use `run_candidate_stability`. |
| Step 9 slow | It runs full segmentation per baseline and perturbation. | Count rows in `perturbation_candidates.json`; each row is one segmentation run. |

## Boundaries

Level-1b does not choose a final `selected_scale_id`. It does not create final labels, vectors, GPKG, shapefiles or zonal products. Those belong to later steps after stability analysis and scale selection.
