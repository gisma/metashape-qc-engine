# Level‑1B Candidate‑Stability Chain – Technical Manual

## Overview

The chain is implemented in
`metashape_qc_engine/level1b_dumb_runner.py` with `run_level1b_dumb_chain()`.
It orchestrates a fixed sequence of sub‑steps that rely on OTB command‑line
applications, Python helper modules, and one R script.  Each step writes a
manifest (via `level1b_step_manifest.py`) and the chain consumes those
manifests to verify completion.

## Entry points

| Script | Role |
|--------|------|
| `metashape_qc_engine/level1b_dumb_runner.py` | Primary entry point; exposes `--rgb-ortho`, `--out-dir`, `--overwrite`. |
| `metashape_qc_engine/cli.py` | Legacy CLI that can run the full product‑analysis experiment **but not the Level‑1B DS chain**.  Not used by this workflow. |

## Workflow step sequence (dumb runner)

1. **preflight** (`level1b_preflight.py::run_preflight`)  
   - Validates the input ortho path, candidate ID, and writes a preflight report.

2. **valid_mask** (`level1b_valid_mask.py::run_valid_mask_step`)  
   - Builds a binary mask from the input ortho using OTB `BandMathX`.  
   - Configuration: black‑border removal, alpha‑band threshold, nodata values.

3. **channels** (`level1b_channels.py::run_channel_construction_step`)  
   - Generates a 5‑band proxy stack (VIG, DRY, BRI, TEX_100M, TEX_200M) from
     the input ortho, using OTB `BandMathX` and `LocalStatisticExtraction`.  
   - The mask is applied to the intermediate ExGR band and the final stack.

4. **scaling** (`level1b_scaling.py::run_scaling_step`)  
   - Z‑score normalises the 5‑band proxy stack using OTB statistics commands.  
   - Produces `scaled_feature_stack.tif`.

5. **scale_distribution** (`level1b_scale_distribution.py::run_scale_distribution_step`)  
   - Derives candidate segmentation scales from the structure of the proxy
     stack (using `structure_derived_scale_distribution` mode).  
   - Outputs `scale_candidates.json`.

6. **feature_range** (`level1b_feature_range.py::run_feature_range_assignment_step`)  
   - Computes a feature‑space `ranger` parameter for each scale candidate
     via PCA‑based nearest‑neighbour distances.  
   - Writes `scale_candidates_with_ranger.json`.

7. **perturbations** (`level1b_perturbations.py::run_local_perturbation_step`)  
   - Generates local perturbation candidates around each scale.  
   - Creates `perturbation_candidates.json`.

8. **step9a – candidate response surface**
   (`level1b_candidate_response_surface.py::run_candidate_response_surface_step`)  
   - For every perturbation candidate, runs a “one‑scale segmentation smoke”
     (OTB MeanShift, LSMS, SmallRegionsMerging, BandMathX).  
   - Aggregates per‑run statistics (q‑based size classes), per‑group
     stability diagnostics, and produces a ranked list of candidate scales.  
   - Also computes a spatial analysis matrix and pairwise distributional
     distances.

9. **step9b – scale‑continuity handoff**  
   a. `step9b_prepare_from_existing_step9a()` examines the ranked
      results and determines whether the top two candidates are adjacent on
      the scale ladder.  
      - If **non‑adjacent**, the chain stops early with
        `step9b_non_adjacent_choice_required` and returns a list of
        supported alternatives.  
      - If **adjacent**, a midpoint probe candidate is generated and
        perturbation candidates for it are prepared.  
   b. `run_step9b_midpoint_response_surface_and_handoff_from_prepare()` runs
      a small response‑surface analysis for the midpoint family and computes
      a gain‑share handoff that selects either the midpoint candidate or the
      upper boundary.

10. **step10_collect**
    (`level1b_materialization.py::run_level1b_step10_collect_finalist_evidence`)  
    - Reads the handoff JSON and step9a/step9b summaries; annotates finalist
      rows and writes a `finalist_evidence.json`.

11. **step10_aggregate**
    (`run_level1b_step10_aggregate_finalist_evidence`)  
    - Computes per‑role numeric aggregates and stores them inside the
      evidence file.

12. **step10_figures** (`run_level1b_step10_make_finalist_figures`)  
    - Generates diagnostic PNG figures from the aggregated evidence.

13. **step10_materialize**
    (`run_level1b_step10_materialize_selected_segments`)  
    - Copies the merged‑labels raster of the selected baseline run and
      polygonizes it into a GPKG.

14. **step10_quality**
    (`run_level1b_step10_compute_exactextractr_segment_stats_and_quality_info`)  
    - Calls an R script via `subprocess.run(["Rscript", ...])`:
      `R/level1b_step10_exactextractr_segment_stats.R`.
    - Uses `exactextractr`, `terra`, `sf`, and `jsonlite` to compute
      per‑segment statistics and writes a quality‑information JSON.

## Inputs and outputs (artifact contracts)

Every step writes a **step manifest** (`<out-dir>/level1b/manifests/<step>.json`)
that records status, input paths, output paths, and a candidate ID.
The chain uses these manifests to verify that each predecessor completed
before proceeding.

| Step | Expected input manifests | Key output artifacts |
|------|--------------------------|----------------------|
| preflight | – | preflight manifest, preflight_report |
| valid_mask | preflight manifest | valid_mask.tif, valid_mask_report.json |
| channels | valid_mask manifest | proxy_stack.tif, channel_report.json |
| scaling | channels manifest | scaled_feature_stack.tif, scaling_report.json |
| scale_distribution | scaling manifest | scale_candidates.json |
| feature_range | scale_distribution manifest | scale_candidates_with_ranger.json |
| perturbations | feature_range manifest | perturbation_candidates.json |
| step9a | perturbations manifest | run_population_summary.json, group_summary.json, … |
| step9b_prepare | step9a manifest | step9b_prepare_manifest.json, ranked_candidate_scales_view.json |
| step9b_midpoint_handoff | step9b_prepare manifest | step9b_midpoint_gain_share_handoff.json |
| step10_collect | step9b_midpoint handoff manifest | finalist_evidence.json |
| step10_aggregate | step10_collect manifest | (updates finalist_evidence.json) |
| step10_figures | step10_aggregate manifest | figure_manifest.json, PNG files |
| step10_materialize | step10_aggregate manifest | selected_labels.tif, selected_segments.gpkg |
| step10_quality | step10_materialize manifest | selected_segment_exactextractr_stats.csv, … |

## Resume / rerun implementation

- The chain itself does **not** support resume.  If the output directory already
  contains a `level1b/` folder, the chain will abort unless `--overwrite` is
  specified.
- Individual steps may implement partial reuse (e.g., the step9a response
  surface has its own resume and reuse logic, but the dumb runner does not
  expose this externally).

## Dependencies and external tools

| Component | How it is called |
|-----------|------------------|
| Orfeo ToolBox | `otbcli_BandMathX`, `otbcli_LocalStatisticExtraction`, `otbcli_MeanShiftSmoothing`, `otbcli_LSMSSegmentation`, `otbcli_SmallRegionsMerging`, `otbcli_HooverCompareSegmentation` – invoked via `subprocess.run` from the Python helpers. |
| GDAL | Used by `level1b_materialization.py` for `Polygonize`, and by the `gdal_edit.py` wrapper to set nodata. |
| R | The script `R/level1b_step10_exactextractr_segment_stats.R` is called via `subprocess.run(["Rscript", ...])` in step10_quality.  It requires the R packages **`sf`**, **`terra`**, **`exactextractr`**, and **`jsonlite`** (confirmed by inspection of the script). |
| Python packages | `numpy`, `rasterio`, `json`, `pathlib`, `argparse` – all standard or easily installed. |

## Fragile contracts

- The **perturbation‑candidate table** must contain the columns expected by
  `read_perturbation_candidates` (including `perturbation_id`,
  `source_candidate_id`, `scale_id`, `spatialr_px`, `minsize_px`, `ranger`,
  `is_baseline`).  The table is produced by the `level1b_perturbations` step
  and consumed by `level1b_candidate_response_surface`.
- The **scale‑ladder identification** in step9b relies on a consistent named
  scale coordinate (e.g., `source_candidate_radius_m`) across all runs;
  inconsistent metadata will cause the step9b gate to report “cannot
  determine”.
- The **step9b_prepare** manifest must contain a complete
  `produced_branch_artifacts` dictionary; the dumb runner reads it to decide
  whether to proceed with the midpoint handoff or to return early with the
  non‑adjacent choice.
- The **step10_materialize** polygonization uses `gdal.Polygonize` and
  expects the selected baseline run to have a `merged_labels_path` field.
  The contract version (`run_contract_version`) determines how the path is
  computed; changing the contract without updating the materialization step
  could produce empty output.

## Artifact classification

- **Final artifacts** – `selected_labels.tif`, `selected_segments.gpkg`,
  `ortho_segmentation_quality_info.json`.
- **Resume artifacts** – Step manifests in `level1b/manifests/`.
- **Intermediate artifacts** – All temporary files in
  `level1b/{candidate_response_surface, segmentation_smoke, ...}`.
- **Debug artifacts** – The `level1b_dumb_chain_report.json` and all
  individual step reports.

## Files inspected

- `metashape_qc_engine/level1b_dumb_runner.py`
- `metashape_qc_engine/level1b_candidate_response_surface.py`
- `metashape_qc_engine/level1b_candidate_stability.py`
- `metashape_qc_engine/level1b_channels.py`
- `metashape_qc_engine/level1b_hoover_compare.py`
- `metashape_qc_engine/level1b_materialization.py`
- `metashape_qc_engine/level1b_one_scale_segmentation.py`
- `metashape_qc_engine/level1b_step_manifest.py`
- `metashape_qc_engine/level1b_valid_mask.py`
- `metashape_qc_engine/cli.py`
- `python/prepare_product_experiment.py`
- `python/reproducibility_runner.py`
- `python/evaluate_ortho_stability.py`
- `R/level1b_run_eval_existing_stats.r`
- `R/level1b_step10_exactextractr_segment_stats.R`
- `R/metrics-fun.R`
- `R/create_derived_configs.R`
- `R/normalize_image_intensity.R`
- `tests/test_level1b_candidate_stability.py`
- `tests/test_level1b_dumb_runner.py`
- `tests/test_level1b_hoover_compare.py`
- `tools/metashape_gui/metashape_qc_menu.py`

## Entry points found

1. `metashape_qc_engine/level1b_dumb_runner.py` – the Level‑1B DS chain.
2. `python/prepare_product_experiment.py` – (legacy) product‑analysis
   preparation.
3. `python/reproducibility_runner.py` – (legacy) product‑analysis runner.
4. `python/evaluate_ortho_stability.py` – (legacy) product‑analysis
   evaluation.
5. `metashape_qc_engine/cli.py` – CLI wrapper for the legacy product‑analysis
   scripts.
6. `R/level1b_run_eval_existing_stats.r` – diagnose existing Step‑9
   statistics.

## Documentation files created

- `docs/USER_MANUAL_LEVEL1B_DS.md`
- `docs/TECHNICAL_MANUAL_LEVEL1B_DS.md`

## Unresolved points

- A direct OTB‑bin‑dir override is not exposed on the dumb‑runner command
  line; the scripts always use PATH discovery.
- Whether the OTB `HooverCompareSegmentation` application is called anywhere
  in the dumb‑runner chain is still unclear (it appears to be part of the
  candidate‑stability logic but may not be invoked with the current
  configuration).
- The `metashape_gui` (Metashape menu launcher) assumes a specific
  repository layout that may not match the stand‑alone usage described here.
