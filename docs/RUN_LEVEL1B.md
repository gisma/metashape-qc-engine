# Running Level-1B

Level-1B is the candidate-scale stability and segmentation-evidence workflow. It converts one RGB orthomosaic into a scale-response analysis, a selected segmentation product for the adjacent branch, and auditable segment-level evidence.

The repository layout is historical. Processing code is mostly in `metashape_qc_engine/level1b_*.py`; the normal operational entry point is `metashape_qc_engine/run_level1b_dumb_with_user_header.sh`.

## Prerequisites

- an RGB orthomosaic readable by GDAL
- the repository's Python environment
- OTB command-line applications available through the configured OTB installation, including `DimensionalityReduction` for RGB-PC1 and `HaralickTextureExtraction` for directional GLCM Inertia
- SAGA GIS with `saga_cmd` and the `imagery_segmentation` tools
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

### Scene-adaptive scale and ranger pre-screening

The YAML block `candidate_pre_screening` defines an admissible radius domain,
not concrete scale anchors. The active bounds are `radius_min_m: 0.1` and
`radius_max_m: 1.0` metres.

Before segmentation, the workflow samples valid pixel pairs from the scaled
six-band stack over logarithmic lags and four directions. It computes a robust
multiband empirical variogram and estimates its sill from the tail. Stable
first crossings of the configured sill fractions `0.25, 0.50, 0.75, 0.95`
materialize the actual scene-specific scale families. Knee, plateau, saturation,
and directional-anisotropy values are diagnostics only; they never change how
Step 9 evaluates a family.

For each selected radius, `spatialr_px` is the selected raster lag. A common
technical `minsize_px` is recorded from the lower domain radius as
`(2 * round_half_up(radius_min_m / pixel_size_m))²`. Under the active SAGA
backend this value is provenance only: SAGA does not perform a later
minimum-size merge, and Step-9b does not perturb minsize independently.

One-scale execution uses SAGA's multiband local-variance surface followed by a
controlled seed construction and SAGA Seeded Region Growing. The old
unconstrained set of all variance minima is not used as the region-growing seed
set. For every candidate radius, four deterministic translations of the same
metric hexagonal lattice are evaluated (`[0,0]`, `[0.5,0]`, `[0,0.5]`, and
`[0.5,0.5]` in lattice coordinates). A support cell has area
`pi * radius_px^2`. Each centre can snap at most `0.45 * radius_px` to a valid
local variance minimum, seeds remain at least `radius_px` apart, and exact SAGA
proximity must show every valid pixel within `2 * radius_px` of a seed. Any
uncovered support receives deterministic farthest-point completion seeds.
`spatialr_px` also supplies positional variance; `ranger` controls feature-space
variance. The similarity threshold is zero, four-neighbour connectivity is
used, and label zero remains invalid support. Canonical SAGA feature grids are
reused by all runs; radius/phase seed scaffolds are reused across ranger levels
when their exact provenance matches.

The same pre-screen evaluates kNN ranks
`[8, 10, 13, 16, 21, 27, 34, 44, 55]` on valid scaled feature vectors. The
first stable HSM-ranger plateau supplies the central ranger. Candidate rows use
that mode and the positive unique lower/upper bounds of its shortest
half-sample interval. These are controlled positions in the plausible main
interval, not tail quantiles.

Pre-screening performs no segmentation, ranking, or final selection. It
materializes the factorial population `scale family × ranger level × seed
phase`; the current four scale supports, three ranger positions, and four seed
phases require a budget of 48. It fails rather than restoring fixed YAML
anchors when fewer than two stable spatial support points are available or
when the configured candidate budget is insufficient.

### Multiscale centroid-seed stabilization

The Step-9 population is also the bootstrap evidence for the final seed
realization. After the adjacent Step-9b handoff and Step-10 finalist collection,
the runner reads all initial Step-9a label rasters. For every spatial scale it
forms a centroid-density surface from the twelve `ranger × seed phase` runs.
A local maximum is retained only when it is supported by at least six runs,
three of the four phases, and two ranger positions. Mutually nearest supported
maxima are tracked between adjacent scales; a usable track must occur at two or
more scales.

Tracks present at the selected scale—or at the nearest initial scale when the
handoff selected the midpoint—supply the final seed scaffold. Their locations
are the median positions of their multiscale tracks. Seeds are separated by at
least the selected `spatialr_px`.

SAGA seeded region growing then runs once with the handed-off `spatialr_px` and
`ranger` and this multiscale-supported seed scaffold. This stage does not merge
boundaries and does not invent a consensus polygon. It converts the complete
Step-9 ensemble into one reproducible seed realization at the already selected
parameter pair. The active support controls are in the
`centroid_seed_stabilization` YAML block.

There is no CLI option for an alternative Level-1B config path.
### Proxy-stack parameters

The active RGB proxy-stack parameters are in the `channels` block:

- `rgb_band_indices`
- `dglcm_pc1_small_radius_m` and `dglcm_pc1_large_radius_m`
- `pc1_clip_quantiles`
- `pc1_output_min` and `pc1_output_max`
- `glcm_nbbin`
- `glcm_directions`
- `ratio_eps`
- `background_value`

`feature_band_count` is intentionally not a YAML setting. The active proxy-stack recipe derives `band_count` from its ordered band-definition list, and the runner passes that result to scaling and candidate pre-screening. Adding or removing a recipe band therefore does not require a second band-count edit.

The scientific RGB recipe is implemented in:

```text
metashape_qc_engine/level1b_proxy_stack_rgb_dglcm.py
```

`level1b_channels.py` validates paths and parameters, calls that recipe, and writes the existing `proxy_stack.tif` and `channel_report.json` artifacts.

## Normal wrapper call

```bash
ORTHO=/path/to/ortho.tif \
RUN_ROOT=/path/to/run_root \
OVERWRITE=1 \
bash metashape_qc_engine/run_level1b_dumb_with_user_header.sh
```

The wrapper is the normal path because it:

- optionally sources `OTB_ROOT/otbenv.profile` and records its CLI runtime
- keeps OTB CLI tools discoverable through `PATH`
- removes OTB Python and library paths plus OTB `GDAL_DATA`/`PROJ_LIB` from the Python runner environment
- restores the recorded OTB runtime only for `otbcli_*` subprocesses
- exports the repository through the sanitized `PYTHONPATH`
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
| `level1b_dumb_chain_complete` | 0 | adjacent midpoint branch, centroid-seed stabilization, and all Step-10 functions completed |
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
- `candidate_pre_screening/candidate_population.json` — complete Step-9a rows grouped by scene-adaptive scale support
- `candidate_pre_screening/variogram_diagnostics.json` — sill crossings, knee/plateau and directional diagnostics
- `candidate_pre_screening/candidate_pre_screening_report.json`
- `candidate_response_surface/run_population_summary.json`
- `candidate_response_surface/candidate_group_response_summary.json`
- `candidate_response_surface/ranked_candidate_scales.json`
- `candidate_response_surface/candidate_response_surface_report.json`
- `step9b_prepare_inputs/step9b_prepare_manifest.json`
- `local_transition_refinement/step9b_interval_preflight.json`
- `local_transition_refinement/step9b_midpoint_gain_share_handoff.json` on the adjacent branch
- `local_transition_refinement/step9b_supported_scale_alternatives.json` on the non-adjacent branch
- `step10_materialization/centroid_seed_stabilization/centroid_seed_stabilization_report.json`
- `step10_materialization/centroid_seed_stabilization/stabilized_seeds.csv`
- `step10_materialization/centroid_seed_stabilization/stabilized_seeds.sgrd`
- `step10_materialization/centroid_seed_stabilization/stabilized_labels.tif`

## Final products

On a complete adjacent run:

- `RUN_ROOT/level1b/step10_materialization/final_segments/selected_labels.tif`
- `RUN_ROOT/level1b/step10_materialization/final_segments/selected_segments.gpkg`
- `RUN_ROOT/level1b/step10_materialization/final_segments/selected_segments_manifest.json`

The GeoPackage layer is `selected_segments`; segment labels are stored as `segment_id`.

`selected_labels.tif` is copied from the multiscale-seeded
`centroid_seed_stabilization/stabilized_labels.tif`, not from the Step-9
boundary-medoid run. The medoid remains selection and stability evidence.

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
4. For preflight failure, verify required OTB applications—including `DimensionalityReduction` and `HaralickTextureExtraction`—plus `saga_cmd` and `gdal_edit.py` in the wrapper's effective `PATH`.
5. For Step-9a failure, inspect `candidate_response_surface_report.json` and referenced per-run reports. Do not treat a partial response surface as complete.
6. For a non-adjacent exit, inspect `step9b_supported_scale_alternatives.json`; this is an analyst-choice branch, not a crash.
7. For stabilization failure, inspect `centroid_seed_stabilization_report.json`, its support counts, selected parameters, seed count, and output segment count.
8. For Step-10 quality failure, verify selected segments, the selected masked value raster, `Rscript`, and required R packages.

## What Level-1B does not do

- no Level-1A Metashape reproducibility analysis
- no global best-scale search
- no extrapolation beyond the Step-9a candidate ladder
- no automatic choice between non-adjacent supported alternatives
- no final quality class
- no alternate-path search when a required artifact is missing
- no consensus boundary merge after Step 9
