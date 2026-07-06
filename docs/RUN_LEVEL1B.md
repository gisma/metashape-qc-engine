# Run Level-1B

## Purpose

Level-1B starts from one finished RGB orthomosaic and produces a selected
segmentation raster, polygonized segments, and numerical/graphical evidence.
It does not run Metashape, classify ecology, or assign a final quality class.

## Prerequisites

From the repository root, use the setup for the active platform:

- Linux or WSL2: `bash scripts/setup_level1b.sh`
- macOS: `bash scripts/setup_level1b_macos.sh`
- native Windows dependency environment: `powershell -ExecutionPolicy Bypass -File scripts/setup_level1b_windows.ps1`

The native Windows setup installs Miniforge through `winget` when needed and
uses `.conda-env` so GDAL, rasterio, and `osgeo` come from compatible
conda-forge packages. Native execution uses
`metashape_qc_engine\run_level1b_dumb_with_user_header.ps1`. Set `OTB_ROOT` to
the extracted Windows OTB package root containing `otbenv.bat`, and set
`SAGA_ROOT` when `saga_cmd.exe` is not on `PATH`. WSL2 remains an alternative;
its external dependencies must be installed inside WSL.

The workflow requires the repository Python environment plus external OTB,
SAGA, GDAL, and R/exactextractr components. The setup scripts check these
dependencies; they do not install the external system software.

The input orthomosaic must be a readable georeferenced RGB raster. The normal
runner automatically loads:

```text
config/level1b_default.yaml
```

There is no command-line option for another Level-1B config.

## Normal invocation

On native Windows PowerShell:

```powershell
$env:ORTHO = "C:\path\to\ortho.tif"
$env:RUN_ROOT = "C:\path\to\run_root"
$env:OTB_ROOT = "C:\path\to\OTB"
$env:SAGA_ROOT = "C:\path\to\SAGA"
$env:OVERWRITE = "1"
powershell -ExecutionPolicy Bypass -File metashape_qc_engine\run_level1b_dumb_with_user_header.ps1
```

On Linux, macOS, or WSL, use the Bash wrapper because it prepares the OTB CLI environment, separates it from
the Python GDAL environment, sets `PYTHONPATH`, and records the shell log.

```bash
ORTHO=/path/to/ortho.tif \
RUN_ROOT=/path/to/run_root \
OVERWRITE=1 \
bash metashape_qc_engine/run_level1b_dumb_with_user_header.sh
```

Optional environment controls accepted by the wrapper are:

- `ORTHO`: input RGB orthomosaic;
- `RUN_ROOT`: output root;
- `OVERWRITE=1`: permit execution when `RUN_ROOT/level1b` already exists;
- `OTB_ROOT`: OTB installation root containing `otbenv.profile` or `otbenv.bat`;
- `SAGA_ROOT`: native Windows SAGA installation directory when `saga_cmd.exe` is not on `PATH`;
- `REPO`: repository root used by the Bash wrapper.

Without `OVERWRITE=1`, the Python runner refuses an existing
`RUN_ROOT/level1b`. Overwrite does not mean “resume from the last failed
step”; the normal runner has no separate resume command.

The wrapper writes combined stdout/stderr to:

```text
<run_root>/level1b_chain.log
```

## Direct Python invocation

This is secondary and assumes that the required external command environments
are already correct:

```bash
python3 -m metashape_qc_engine.level1b.dumb_runner \
  --rgb-ortho /path/to/ortho.tif \
  --out-dir /path/to/run_root \
  --overwrite
```

Accepted CLI arguments are exactly `--rgb-ortho`, `--out-dir`, and optional
`--overwrite`.

## Main runtime states

### Complete

Status:

```text
level1b_dumb_chain_complete
```

CLI exit code: 0.

The adjacent Step-9 branch, midpoint handoff, centroid-seed stabilization, and
all Step-10 parts completed.

### Non-adjacent alternatives

Status:

```text
step9b_non_adjacent_choice_required
```

CLI exit code: 2.

Step 9a found two supported but non-adjacent scale families. The workflow stops
without choosing between them and does not run Step 10. Inspect:

```bash
jq . <run_root>/level1b/local_transition_refinement/step9b_supported_scale_alternatives.json
```

### Failed

Status:

```text
level1b_dumb_chain_failed
```

CLI exit code: 1.

The chain report contains `error_type` and `error`. Inspect the report, log,
and last manifests before rerunning.

## Chain report and manifests

Every known exit writes:

```text
<run_root>/level1b_dumb_chain_report.json
```

Inspect it with:

```bash
jq . <run_root>/level1b_dumb_chain_report.json
tail -n 80 <run_root>/level1b_chain.log
ls -la <run_root>/level1b/manifests
```

The chain report stores compact step status/manifest references. Canonical
artifact paths are resolved through those manifests.

## Step-9 evidence to inspect

Current Step-9a uses run-contract version 6. New rankings use four continuous
support components rather than fixed edge/jump penalties:

- robust seed-boundary support;
- robust ranger-boundary support;
- robust radius-boundary support;
- robust continuous scale-match support.

Inspect the ranking and its components:

```bash
jq '[.[] | {
  candidate_scale_group_id,
  stability_score_raw,
  ensemble_support_raw_v2,
  ensemble_support_evaluable,
  ensemble_support_missing_components,
  seed_realization_boundary_support_robust,
  ranger_boundary_support_robust,
  radius_boundary_support_robust,
  scale_match_support_raw
}]' \
  <run_root>/level1b/candidate_response_surface/ranked_candidate_scales.json
```

Relevant evidence paths:

```text
<run_root>/level1b/candidate_pre_screening/candidate_population.json
<run_root>/level1b/candidate_pre_screening/variogram_diagnostics.json
<run_root>/level1b/candidate_response_surface/run_population_summary.json
<run_root>/level1b/candidate_response_surface/candidate_group_response_summary.json
<run_root>/level1b/candidate_response_surface/ranked_candidate_scales.json
<run_root>/level1b/candidate_response_surface/boundary_support/
<run_root>/level1b/candidate_response_surface/candidate_response_surface_report.json
```

Legacy flags and the legacy weighted score can still appear for historical
interpretation. They do not rank newly generated run-contract-v6 response
surfaces.

## Final products

After `level1b_dumb_chain_complete`:

```text
<run_root>/level1b/step10_materialization/final_segments/selected_labels.tif
<run_root>/level1b/step10_materialization/final_segments/selected_segments.gpkg
<run_root>/level1b/step10_materialization/final_segments/selected_segments_manifest.json
```

The delivered labels are produced by one SAGA resegmentation using the
multiscale supported centroid seeds and handed-off `spatialr_px`/`ranger`.
They are not a pixelwise consensus merge of Step-9 labels.

## Quality evidence

```text
<run_root>/level1b/step10_materialization/decision_evidence/finalist_evidence.json
<run_root>/level1b/step10_materialization/segment_stats/selected_segment_exactextractr_stats.csv
<run_root>/level1b/step10_materialization/segment_stats/selected_segment_exactextractr_summary.json
<run_root>/level1b/step10_materialization/quality/ortho_segmentation_quality_info.json
<run_root>/level1b/step10_materialization/figures/step10_figure_manifest.json
```

`ortho_segmentation_quality_info.json` records available evidence; it does not
declare the product good, warning, or bad.

To resolve final products through the chain report:

```bash
REPORT=<run_root>/level1b_dumb_chain_report.json

MATERIALIZE_MANIFEST=$(jq -r '.step_results.step10_materialize.manifest' "$REPORT")
jq -r '.artifacts.selected_labels_tif,
       .artifacts.selected_segments_gpkg,
       .artifacts.selected_segments_manifest_json' "$MATERIALIZE_MANIFEST"

QUALITY_MANIFEST=$(jq -r '.step_results.step10_quality.manifest' "$REPORT")
jq -r '.artifacts.selected_segment_exactextractr_stats_csv,
       .artifacts.selected_segment_exactextractr_summary_json,
       .artifacts.ortho_segmentation_quality_info_json' "$QUALITY_MANIFEST"

FIGURE_STEP_MANIFEST=$(jq -r '.step_results.step10_figures.manifest' "$REPORT")
FIGURE_MANIFEST=$(jq -r '.artifacts.figure_manifest_json' "$FIGURE_STEP_MANIFEST")
jq . "$FIGURE_MANIFEST"
```

## What to inspect first after failure

1. `level1b_dumb_chain_report.json`: failing exception and completed step manifests.
2. `level1b_chain.log`: last external command and stderr.
3. `level1b/manifests/`: last successfully completed step.
4. The failing step report referenced by that manifest.
5. For Step 9, `failed_runs.json` and per-run segmentation reports.
6. For R failures, verify `Rscript` and the required packages outside the workflow.

Do not interpret a non-adjacent stop as processing failure. It is the explicit
analyst-choice branch.
