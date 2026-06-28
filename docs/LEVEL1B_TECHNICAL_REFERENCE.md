# Level-1b technical reference

Updated after the active Step-9 response-surface implementation.

## Repository state relevant to this documentation update

This manual describes the current documentation target:

```text
Step 6 remains as implemented.
Active Step 9 is metashape_qc_engine.level1b_candidate_response_surface.
Hoover-based candidate stability is archived as legacy/audit logic.
```

## Module overview

| workflow role | module | main config | main run function |
|---|---|---|---|
| Preflight | `metashape_qc_engine.level1b_preflight` | `Level1BPreflightConfig` | `run_preflight` |
| Valid mask | `metashape_qc_engine.level1b_valid_mask` | `Level1BValidMaskConfig` | `run_valid_mask_step` |
| Channels/proxy stack | `metashape_qc_engine.level1b_channels` | `Level1BChannelConfig` | `run_channel_construction_step` |
| Scaling | `metashape_qc_engine.level1b_scaling` | `Level1BScalingConfig` | `run_scaling_step` |
| PCA | `metashape_qc_engine.level1b_pca` | `Level1BPCAConfig` | `run_pca_step` |
| Scale distribution | `metashape_qc_engine.level1b_scale_distribution` | `Level1BScaleDistributionConfig` | `run_scale_distribution_step` |
| Feature range/ranger | `metashape_qc_engine.level1b_feature_range` | `Level1BFeatureRangeConfig` | `run_feature_range_assignment_step` |
| Perturbations | `metashape_qc_engine.level1b_perturbations` | `Level1BPerturbationConfig` | `run_local_perturbation_step` |
| One-scale segmentation backend | `metashape_qc_engine.level1b_one_scale_segmentation` | `Level1BOneScaleSegmentationConfig` | `run_one_scale_segmentation_smoke` |
| Active candidate response surface | `metashape_qc_engine.level1b_candidate_response_surface` | `Level1BCandidateResponseSurfaceConfig` | `run_candidate_response_surface_step` |
| Hoover compare helper | `metashape_qc_engine.level1b_hoover_compare` | `Level1BHooverCompareConfig` | `run_hoover_compare` |
| Legacy Hoover candidate stability | `metashape_qc_engine.legacy.level1b_candidate_stability_hoover_archive` | legacy config | legacy/audit only |

## Output layout

```text
RUN_ROOT/
  _driver_logs/
  _driver_reports/
  level1b/
    reports/preflight.json
    mask/valid_mask.tif
    mask/valid_mask_report.json
    channels/proxy_stack.tif
    channels/channel_report.json
    scaling/scaled_feature_stack.tif
    scaling/scaling_report.json
    pca/pca_feature_stack.tif
    pca/pca_report.json
    scales/scale_candidates.csv
    scales/scale_candidates.json
    ranger/ranger_candidates.csv
    ranger/ranger_candidates.json
    ranger/scale_candidates_with_ranger.csv
    ranger/scale_candidates_with_ranger.json
    perturbations/perturbation_candidates.csv
    perturbations/perturbation_candidates.json
    candidate_response_surface/
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

## Step-6 reference

Step 6 remains the currently implemented `metashape_qc_engine.level1b_scale_distribution` module. This documentation update does not require any Step-6 code change.

The current technical check for Step 6 should be generated from the repository before changing drivers:

```bash
python - <<'PY'
import dataclasses
from metashape_qc_engine.level1b_scale_distribution import Level1BScaleDistributionConfig
print([f.name for f in dataclasses.fields(Level1BScaleDistributionConfig)])
PY
```

Driver calls must use only actual dataclass fields. Do not add dynamic filtering of config arguments.

## Active Step 9: candidate response surface

Module:

```text
metashape_qc_engine.level1b_candidate_response_surface
```

Public API:

```python
Level1BCandidateResponseSurfaceConfig
run_candidate_response_surface_step(cfg)
```

The implementation report for the active Step 9 states that the module implements:

```text
Step-8 table reading
candidate-scale grouping
one-scale segmentation orchestration through the existing backend
sparse segment-size counting without dense-label assumptions
equivalent-radius calculation
primary q_i = r_eq_i / r_candidate_source
diagnostic class assignment: micro, small, in_scale, large, oversize
run-level population summaries
ordered cumulative distribution distance
q-histogram distance
candidate-group normal-response diagnostics
scale-jump and flurry diagnostics
raster/block analysis-matrix aggregation
spatial dominance and stability summaries
medoid representative run selection
full candidate-space distribution summary
ranked, accepted, removed and failed-run outputs
```

### `Level1BCandidateResponseSurfaceConfig`

Core fields documented by the current implementation report:

| field | purpose |
|---|---|
| `candidate_id` | candidate/run identifier |
| `output_dir` | `RUN_ROOT` |
| `perturbation_candidates_json_path` | Step-8 candidate table |
| `feature_space_stack_path` | PCA or scaled feature-space stack used for one-scale segmentation |
| `valid_mask_path` | valid support mask |
| `otb_bin_dir` | OTB binary directory |
| `ram_mb` | OTB memory hint passed to backend where used |
| `overwrite` | overwrite existing outputs |
| `dry_run` | report commands without real execution where supported |
| `run_hoover_audit` | optional audit flag; default is `False` |

The default active path must use:

```python
run_hoover_audit=False
```

### Driver Step-9 block

The active driver Step-9 block should be:

```python
def step9():
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

run_step("step9_candidate_response_surface", step9)
```

### Active Step-9 output contract

The active Step 9 writes under:

```text
<output_dir>/level1b/candidate_response_surface/
```

Required files:

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

### Active Step-9 report fields

The top-level report includes:

```text
input paths
config values
thresholds
diagnostic class definitions
analysis-cell derivation
candidate group count
planned run count
successful run count
failed run count
omitted run count
run-level summary overview
candidate-group summary overview
full candidate-space summary
Hoover audit status
runtime metadata
```

## One-scale segmentation backend

The response-surface module reuses the existing one-scale segmentation backend. It does not replace MeanShift/LSMS behaviour.

Module:

```text
metashape_qc_engine.level1b_one_scale_segmentation
```

Main config and function:

```python
Level1BOneScaleSegmentationConfig
run_one_scale_segmentation_smoke
```

This backend reads one row from `perturbation_candidates.json`, runs smoothing, segmentation and small-region merging, and writes the resulting label raster and report.

## Hoover compare and legacy candidate stability

Hoover remains available only as helper/audit logic.

Helper module:

```text
metashape_qc_engine.level1b_hoover_compare
```

Legacy archive module:

```text
metashape_qc_engine.legacy.level1b_candidate_stability_hoover_archive
```

The active response-surface module contains no default call to `HooverCompareSegmentation`. The archived implementation may still import and preserve Hoover comparison for explicit audit use.

## Test commands

Active Step 9:

```bash
PYTHONPATH="$PWD/.venv/lib/python3.12/site-packages:$PYTHONPATH" \
pytest -q tests/test_level1b_candidate_response_surface.py
```

Step 6–8 regression checks:

```bash
PYTHONPATH="$PWD/.venv/lib/python3.12/site-packages:$PYTHONPATH" \
pytest -q tests/test_level1b_scale_distribution.py tests/test_level1b_feature_range.py tests/test_level1b_perturbations.py
```

Hoover evidence:

```bash
rg -n "HooverCompareSegmentation" metashape_qc_engine/level1b_candidate_response_surface.py tests/test_level1b_candidate_response_surface.py || true
rg -n "HooverCompareSegmentation" metashape_qc_engine/legacy || true
```

Expected: the active module has no default Hoover call; the legacy archive may contain Hoover references.
