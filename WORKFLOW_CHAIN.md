# Workflow Chain

This repository contains two logical workflows. The physical source layout is historical and is not divided into `level1a/` and `level1b/` trees.

- Level-1A code is split across `python/`, `scripts/`, and `metashape_qc_engine/cli.py`.
- Level-1B code is mostly in `metashape_qc_engine/level1b_*.py`, with `metashape_qc_engine/run_level1b_dumb_with_user_header.sh` and `R/level1b_step10_exactextractr_segment_stats.R`.

Operational and methodological details are maintained in the four active documents:

- [docs/RUN_LEVEL1A.md](docs/RUN_LEVEL1A.md)
- [docs/LEVEL1A_METHOD_CORE_MAP.md](docs/LEVEL1A_METHOD_CORE_MAP.md)
- [docs/RUN_LEVEL1B.md](docs/RUN_LEVEL1B.md)
- [docs/LEVEL1B_METHOD_CORE_MAP.md](docs/LEVEL1B_METHOD_CORE_MAP.md)

## Environment setup

```bash
bash scripts/setup_level1a.sh
bash scripts/setup_level1b.sh
```

Run only the setup script for the workflow being prepared. Both use the repository `.venv`; Level-1B adds checks and Python packages beyond the base install. External system applications remain separately installed.

## Level-1A: product-analysis and reproducibility chain

```text
prepare -> run-analysis / resume-analysis -> evaluate -> review
```

### Prepare

`metashape-qc prepare` consumes an image directory, product ID, preset JSON, replicate count, and output root. It writes run-local `config.yml` and `variants.csv`, then prints the concrete follow-up commands.

### Run or resume

`metashape-qc run-analysis` expands the variant/replicate matrix, writes per-run configs, invokes `scripts/run_metashape_workflow.sh`, captures `launcher.log`, and appends each attempt to `manifest.csv`.

`metashape-qc resume-analysis` uses the same run contract. It skips latest manifest rows considered successful and reruns failed or missing variant/replicate combinations.

The shell bridge locates `metashape.sh` through `METASHAPE_DIR` or `PATH` and launches `python/metashape_workflow.py` inside the Metashape runtime.

### Evaluate and review

`metashape-qc evaluate` analyzes successful orthomosaics on a canonical grid, then writes continuous-stability, threshold-guard, and support-persistence evidence. Principal outputs are:

- `<run_dir>/manifest.csv`
- `<run_dir>/stability_union/summary.csv`
- `<run_dir>/stability_union/evaluation_report.md`
- `<run_dir>/selected_product.json`
- `<run_dir>/qgis_open_selected.sh` and `.bat`

Level-1A produces and reviews orthomosaic product candidates. It does not run Step 9/10 segmentation and does not convert internal reproducibility into external accuracy.

## Level-1B: candidate-scale stability and segmentation evidence

```text
orthomosaic
  -> valid mask
  -> six-band proxy stack
  -> robust scaling
  -> scene-adaptive multiband variogram pre-screening
  -> stable sill-fraction spatial support points
  -> HSM main-interval ranger levels
  -> materialized Step-9a candidate families
  -> controlled hex/variance-minimum seeds per candidate
  -> SAGA seeded region growing per candidate
  -> Step 9a response surface
  -> Step 9b adjacency/midpoint handoff
  -> Step 10 materialization and quality evidence
```

### Analysis domain and features

The runner derives orthomosaic pixel size, creates `valid_mask.tif`, builds the deterministic six-band RGB proxy stack, and robustly scales the proxy features. Bands 4–5 measure fine and coarse directional structure; band 6 is their ratio. These features enter the variogram, ranger diagnostic, and segmentation, but their names and DGLCM measurement radii do not define the candidate ladder. Domain and policy defaults come from `config/level1b_default.yaml`.

### Candidate population

`candidate_pre_screening` reads the valid scaled feature stack and the YAML
parameter domain. It computes a robust multiband empirical variogram over
logarithmic lags and configured directions. Stable first crossings of the
configured sill fractions materialize the scene-specific spatial ladder inside
`radius_min_m` and `radius_max_m`.

For each selected radius, `spatialr_px` is the selected raster lag and
`minsize_px` is deterministically coupled through the circular footprint
area. The pre-screen reuses the k-to-HSM plateau diagnostic and materializes
the central ranger plus the positive unique bounds of its main modal interval.
It writes one Step-9a-compatible population and performs no segmentation,
ranking, or final selection.

### Step 9a and Step 9b

Step 9a executes or reuses every materialized candidate run, writes run/group
response summaries, computes raw/clamped stability scores, ranks candidate
families, and diagnoses numeric scale adjacency and boundaries.

Step 9b either:

- writes two non-adjacent supported alternatives and stops for analyst choice, or
- evaluates one midpoint family inside an adjacent interval and applies the fixed gain-share handoff.

No scale outside the pre-screened ladder is introduced.
### Step 10

On the adjacent handoff branch, Step 10 collects finalist evidence, aggregates it, writes diagnostic figures, materializes selected labels and polygons, and computes exactextractr segment statistics plus run-level quality information.

Principal outputs are:

- `<run_root>/level1b_dumb_chain_report.json`
- `<run_root>/level1b/step10_materialization/final_segments/selected_labels.tif`
- `<run_root>/level1b/step10_materialization/final_segments/selected_segments.gpkg`
- `<run_root>/level1b/step10_materialization/segment_stats/selected_segment_exactextractr_summary.json`
- `<run_root>/level1b/step10_materialization/quality/ortho_segmentation_quality_info.json`

Level-1B starts from one finished orthomosaic. It does not run Metashape reproducibility, create an ecological classification, or assign a final quality class.

### Operational follow-up commands

After every exit, inspect the chain report and wrapper log:

```bash
jq . <run_root>/level1b_dumb_chain_report.json
tail -n 80 <run_root>/level1b_chain.log
```

For a rerun through the normal wrapper:

```bash
ORTHO=<input_ortho> RUN_ROOT=<run_root> OVERWRITE=1 bash metashape_qc_engine/run_level1b_dumb_with_user_header.sh
```

If the runner cannot find that wrapper next to `level1b_dumb_runner.py`, it prints `UNRESOLVED` and the direct fallback command instead:

```bash
python3 -m metashape_qc_engine.level1b_dumb_runner --rgb-ortho <input_ortho> --out-dir <run_root> --overwrite
```

For a complete run, resolve Step-10 outputs through the manifests recorded in the chain report:

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

For the non-adjacent analyst-choice branch:

```bash
jq . <run_root>/level1b/local_transition_refinement/step9b_supported_scale_alternatives.json
```

For a failed run, list the manifests that were written before failure:

```bash
ls -la <run_root>/level1b/manifests
```

## Relationship between the chains

A reviewed Level-1A orthomosaic may be supplied as the Level-1B input, but the code does not automatically chain Level-1A into Level-1B. The handoff is an explicit orthomosaic path chosen by the operator.

Level-1A asks whether Metashape product candidates are reproducible. Level-1B asks which segmentation-scale response is locally supported for one finished orthomosaic and records the resulting segmentation evidence.
