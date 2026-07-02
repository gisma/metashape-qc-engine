# Running Level-1B

Level-1B is the candidate-scale stability and segmentation-evidence workflow. It converts one RGB orthomosaic into a scale-response analysis, a selected segmentation product for the adjacent branch, and auditable segment-level evidence.

The repository layout is historical. Processing code is mostly in `metashape_qc_engine/level1b_*.py`; the normal operational entry point is `metashape_qc_engine/run_level1b_dumb_with_user_header.sh`.

## Prerequisites

- an RGB orthomosaic readable by GDAL
- the repository's Python environment
- OTB command-line applications available through the configured OTB installation, including `DimensionalityReduction` for RGB-PC1 and `HaralickTextureExtraction` for directional GLCM Inertia
- GDAL, including `gdal_edit.py`
- `Rscript` with `sf`, `terra`, `exactextractr`, and `jsonlite`
- sufficient storage for response-surface candidate runs

The active operational defaults are loaded from:

```text
config/level1b_default.yaml
```

The resolved copy used for a run is written to:

```text
RUN_ROOT/level1b/resolved_level1b_config.yaml
```

There is no CLI option for an alternative Level-1B config path.

## Normal wrapper call

```bash
ORTHO=/path/to/ortho.tif \
RUN_ROOT=/path/to/run_root \
OVERWRITE=1 \
bash metashape_qc_engine/run_level1b_dumb_with_user_header.sh
```

The wrapper is the normal path because it:

- optionally sources `OTB_ROOT/otbenv.profile`
- prepends OTB `bin` and `lib` paths
- exports the repository through `PYTHONPATH`
- creates a temporary executable bridge when `gdal_edit.py` is discoverable
- changes to the repository root
- prints the exact Python command before executing it
- captures wrapper and runner output in `RUN_ROOT/level1b_chain.log`

| Variable | Meaning |
|---|---|
| `ORTHO` | input RGB orthomosaic |
| `RUN_ROOT` | complete run output root |
| `OVERWRITE=1` | pass `--overwrite` to the Python runner |
| `OTB_ROOT` | OTB installation root; default `$HOME/apps/otb911` |
| `REPO` | repository root used for `PYTHONPATH` and working directory |

Set `ORTHO` and `RUN_ROOT` explicitly. The wrapper contains machine-specific defaults; they are not portable run instructions.

## Direct Python call

Use this only when the same OTB/GDAL/R/Python environment is already established:

```bash
python3 -m metashape_qc_engine.level1b_dumb_runner \
  --rgb-ortho /path/to/ortho.tif \
  --out-dir /path/to/run_root \
  --overwrite
```

The Python CLI accepts only `--rgb-ortho`, `--out-dir`, and optional `--overwrite`. It does not source OTB or construct the `gdal_edit.py` bridge.

## Running, rerunning, and interruption behavior

Without `--overwrite`, the runner refuses to start if `RUN_ROOT/level1b` exists. With overwrite enabled, existing step configs receive `overwrite=True`; the runner does not delete the run root first.

There is no separate Level-1B resume command. Candidate response-surface execution has run-level reuse/completion handling, but the public operational action is still a rerun with the same `RUN_ROOT` and `OVERWRITE=1`. Inspect the chain report and shell log before rerunning.

## Status meanings

| Chain status | CLI exit | Meaning |
|---|---:|---|
| `level1b_dumb_chain_complete` | 0 | adjacent midpoint branch and all Step-10 functions completed |
| `step9b_non_adjacent_choice_required` | 2 | top two Step-9a candidates are not adjacent; alternatives were written, no choice was made, and Step 10 did not run |
| `level1b_dumb_chain_failed` | 1 | an exception or failed contract stopped the chain; the report contains `error_type` and `error` |

Step-9a must return `ok`. An incomplete or partial response surface does not continue to Step-9b or Step-10.

## Logs and chain report

- shell and runner log: `RUN_ROOT/level1b_chain.log`
- compact chain report: `RUN_ROOT/level1b_dumb_chain_report.json`
- resolved defaults: `RUN_ROOT/level1b/resolved_level1b_config.yaml`
- per-step manifests: `RUN_ROOT/level1b/manifests/<step>.json`

The wrapper prints a line beginning with `COMMAND=python3 -m metashape_qc_engine.level1b_dumb_runner`; this line and subsequent output are captured in `level1b_chain.log`.

## Locate products through the chain report

```bash
REPORT="$RUN_ROOT/level1b_dumb_chain_report.json"
```

Locate the materialized products:

```bash
MATERIALIZE_MANIFEST=$(jq -r '.step_results.step10_materialize.manifest' "$REPORT")
jq -r '.artifacts.selected_labels_tif,
       .artifacts.selected_segments_gpkg,
       .artifacts.selected_segments_manifest_json' "$MATERIALIZE_MANIFEST"
```

Locate quality evidence:

```bash
QUALITY_MANIFEST=$(jq -r '.step_results.step10_quality.manifest' "$REPORT")
jq -r '.artifacts.selected_segment_exactextractr_stats_csv,
       .artifacts.selected_segment_exactextractr_summary_json,
       .artifacts.ortho_segmentation_quality_info_json' "$QUALITY_MANIFEST"
```

Locate diagnostic figures:

```bash
FIGURE_STEP_MANIFEST=$(jq -r '.step_results.step10_figures.manifest' "$REPORT")
FIGURE_MANIFEST=$(jq -r '.artifacts.figure_manifest_json' "$FIGURE_STEP_MANIFEST")
jq -r '.figure_paths[]' "$FIGURE_MANIFEST"
```

These commands use exact manifests recorded in a successful chain report. On non-adjacent or failed branches, Step-10 keys do not exist because Step 10 was not run.

## Main intermediate evidence

Under `RUN_ROOT/level1b/`:

- `mask/valid_mask.tif`
- `channels/proxy_stack.tif` — six bands in order: `ExGR`, `ExR`, `BRI`, `DGLCM_PC1_SMALL`, `DGLCM_PC1_LARGE`, `RATIO_DGLCM_PC1`
- `channels/channel_report.json` — band order, PC1 quantization, Haralick directions/radii, aggregation, and ratio contract
- `scaling/scaled_feature_stack.tif`
- `scales/scale_candidates.json`
- `ranger/scale_candidates_with_ranger.json`
- `perturbations/perturbation_candidates.json`
- `candidate_response_surface/run_population_summary.json`
- `candidate_response_surface/candidate_group_response_summary.json`
- `candidate_response_surface/ranked_candidate_scales.json`
- `candidate_response_surface/candidate_response_surface_report.json`
- `step9b_prepare_inputs/step9b_prepare_manifest.json`
- `local_transition_refinement/step9b_interval_preflight.json`
- `local_transition_refinement/step9b_midpoint_gain_share_handoff.json` on the adjacent branch
- `local_transition_refinement/step9b_supported_scale_alternatives.json` on the non-adjacent branch

## Final products

On a complete adjacent run:

- `RUN_ROOT/level1b/step10_materialization/final_segments/selected_labels.tif`
- `RUN_ROOT/level1b/step10_materialization/final_segments/selected_segments.gpkg`
- `RUN_ROOT/level1b/step10_materialization/final_segments/selected_segments_manifest.json`

The GeoPackage layer is `selected_segments`; segment labels are stored as `segment_id`.

## Quality evidence

- `step10_materialization/decision_evidence/finalist_evidence.json`
- `step10_materialization/decision_evidence/finalist_group_summary.json`
- `step10_materialization/decision_evidence/finalist_perturbation_runs.json`
- `step10_materialization/decision_evidence/finalist_group_aggregation.json`
- `step10_materialization/decision_evidence/finalist_numeric_distribution_summary.json`
- `step10_materialization/segment_stats/selected_segment_exactextractr_stats.csv`
- `step10_materialization/segment_stats/selected_segment_exactextractr_summary.json`
- `step10_materialization/quality/ortho_segmentation_quality_info.json`

`ortho_segmentation_quality_info.json` consolidates selected-run and segment-statistics evidence. Its `quality_signal_status` is `evidence_ready`; it does not assign a final quality class.

## Diagnostic figures

The figure manifest is:

```text
RUN_ROOT/level1b/step10_materialization/figures/step10_figure_manifest.json
```

It lists six PNGs covering decision scores, stability/support distributions, segment counts, areas, parameter spread, and an aggregated numeric-field overview. Figures use finalist display order and mark the selected candidate; the lower boundary is documentation context.

## What to check after failure

1. Read `RUN_ROOT/level1b_dumb_chain_report.json` for status and exception text.
2. Read the end of `RUN_ROOT/level1b_chain.log` and identify the last completed step.
3. Inspect `RUN_ROOT/level1b/manifests/<step>.json` for that step's status, inputs, and artifacts.
4. For preflight failure, verify required OTB applications—including `DimensionalityReduction` and `HaralickTextureExtraction`—and `gdal_edit.py` in the wrapper's effective `PATH`.
5. For Step-9a failure, inspect `candidate_response_surface_report.json` and referenced per-run reports. Do not treat a partial response surface as complete.
6. For a non-adjacent exit, inspect `step9b_supported_scale_alternatives.json`; this is an analyst-choice branch, not a crash.
7. For Step-10 quality failure, verify selected segments, the selected masked value raster, `Rscript`, and required R packages.

## What Level-1B does not do

- no Level-1A Metashape reproducibility analysis
- no global best-scale search
- no extrapolation beyond the Step-9a candidate ladder
- no automatic choice between non-adjacent supported alternatives
- no final quality class
- no alternate-path search when a required artifact is missing
