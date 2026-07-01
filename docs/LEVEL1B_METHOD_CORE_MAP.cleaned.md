# Level-1b Method Core Map

## Purpose

Level-1b processes an orthomosaic to select a segmentation scale and materialize a final segmentation product, accompanied by quality evidence. It does not assign a final quality class. It produces evidence such as stability scores, selected-scale evidence, segment statistics, and diagnostic figures for later interpretation.

This document separates the methodological core from the technical wrapper. The scientific method is the small set of decisions that shape the segmentation result; the wrapper is the file handling, OTB/R execution, manifests, reports, and traceability layer around it.

## Workflow in one line

Orthomosaic → Valid Mask → Proxy Stack → Scaling → Scale Candidates → Ranger Assignment → Perturbations → Step 9a Response Surface → Step 9b Handoff → Step 10 Materialized Product + Quality Evidence

## Critical methodological levers

- Valid analysis mask (`valid_mask.tif`).
- Proxy channels: vegetation, dryness, brightness, and two texture bands.
- Texture radii: configurable radii in metres; the historical config names `tex_100m_radius_m` and `tex_200m_radius_m` do not mean literal 100 m / 200 m radii.
- Feature scaling: robust percentile clipping in the current robust-scaling working branch.
- Candidate scale generation: radius / `spatialr_px` / `minsize_px` derived from texture support and pixel size.
- Ranger assignment: feature-space k-NN distance quantiles.
- Perturbation design: local parameter variation around baseline segmentation settings.
- Response-surface stability scoring: distributional and spatial response metrics.
- Step 9b midpoint / handoff rule: gain-share decision between boundary and midpoint candidates.
- Selected segment materialization: final label raster and vector product.
- Segment-level quality evidence: per-segment band statistics from the selected product.

## Step-by-step map

### Step 1 – Preflight

**Inputs:** `candidate_id`, input orthomosaic path, `output_dir`, declared input type, optional mask-related settings, and the required OTB CLI applications.

**Scientific core:** None. This is a validation step. It checks whether the input file exists, whether it has a raster-like suffix, whether the declared input contract is plausible, and whether required command-line tools can be found.

**Technical wrapper:** Creates the output layout and locates external tools with `shutil.which`.

**Outputs:** `preflight.json` and a step manifest.

**Consumed by:** Not consumed downstream; it is recorded for traceability.

**Quality relevance:** None directly. Failure prevents the pipeline from starting.

**Artifact contract:** Manifest step `preflight` with artifact `preflight_report`.

**UNRESOLVED:** None identified from inspected code.

---

### Step 2 – Valid Mask

**Inputs:** Orthomosaic, optional nodata values per band, optional alpha band settings, and black/white border exclusion settings.

**Scientific core:** Builds a binary validity mask where valid analysis pixels are `1` and invalid/background pixels are `0`. The mask can exclude nodata values, low-alpha pixels, and RGB border/background tuples such as black or white borders. This mask defines the analysis domain for the rest of the chain.

**Technical wrapper:** Constructs and runs an OTB `BandMathX` expression and writes a single-band uint8 raster.

**Outputs:** `valid_mask.tif`, `valid_mask_report.json`, and a step manifest.

**Consumed by:** Channels, Scaling, Feature Range, and Step 9a.

**Quality relevance:** Very high. If the valid mask includes border/background pixels or excludes real image content, all downstream feature statistics, segmentation results, and stability metrics are biased.

**Artifact contract:** Manifest step `valid_mask` with artifacts `valid_mask` and `report`.

**UNRESOLVED:** Behaviour outside the expected RGB/orthomosaic contract is not documented here.

---

### Step 3 – Channel Construction (Proxy Stack)

**Inputs:** Orthomosaic, `valid_mask`, `pixel_size_m`, `rgb_band_indices`, and two configurable texture radii in metres (`tex_100m_radius_m`, `tex_200m_radius_m`). These names are historical and must not be read as literal 100 m / 200 m radii.

**Scientific core:** For RGB input, builds a 5-band proxy stack:

1. `VIG`: vegetation proxy, based on ExGR.
2. `DRY`: dryness / redness proxy, based on ExR.
3. `BRI`: brightness proxy, based on RGB average.
4. Texture band 1: local standard deviation of the vegetation proxy at radius 1.
5. Texture band 2: local standard deviation of the vegetation proxy at radius 2.

All channels are masked to the valid analysis area. For multichannel input, the step reorders and masks the supplied channels rather than deriving RGB proxies.

**Technical wrapper:** Uses OTB `BandMathX` and `LocalStatisticExtraction` to compute and assemble the stack.

**Outputs:** `proxy_stack.tif`, `channel_report.json`, and a step manifest.

**Consumed by:** Scaling and Scale Distribution.

**Quality relevance:** Very high. The proxy stack defines the feature space used for segmentation. Texture radii are especially critical: if the texture support is too coarse for the GSD and object scale, segmentation can be pulled toward large mixed texture regions.

**Artifact contract:** Manifest step `channels` with artifacts `proxy_stack` and `report`.

**UNRESOLVED:** The best texture radii are landscape- and GSD-dependent. The current values must be checked in `config/level1b_default.yaml` for the active run.

---

### Step 4 – Scaling (Feature Normalization)

**Inputs:** `proxy_stack`, `valid_mask`, `band_count`, and `background_value`.

**Scientific core:** In the robust-scaling working branch, each band is scaled by robust percentile clipping:

1. Mask the proxy stack using the valid mask.
2. For each band, compute the 2nd and 98th percentile over valid pixels only.
3. Derive `center = (lower + upper) / 2` and `scale = (upper - lower) / 2`.
4. Transform valid pixels with `(value - center) / scale`.
5. Clip valid output values to `[-1, 1]`.
6. Keep invalid/background pixels at `background_value`.

This is intended to make the feature space more robust against extreme texture outliers than mean/std z-score scaling.

**Technical wrapper:** Uses OTB `BandMathX` for masking and final raster writing. The robust parameters are computed from the masked raster with Python/GDAL/numpy in the robust-scaling patch. If legacy z-score code or `ComputeImagesStatistics` calls still exist in the file, they are wrapper/legacy artefacts and not the active method unless the current checked-in code calls them for the final scaling expression.

**Outputs:** `scaled_feature_stack.tif`, `scaling_parameters.xml` if still produced by the legacy wrapper, `scaling_parameters.json`, `scaling_report.json`, and a step manifest.

**Consumed by:** Feature Range and Step 9a.

**Quality relevance:** Very high. Scaling controls whether single bands or outlier-heavy texture values dominate the mean-shift feature space. Robust clipping should reduce outlier-driven overmerging.

**Artifact contract:** Manifest step `scaling` with artifacts `scaled_feature_stack`, `scaling_parameters_xml`, `scaling_parameters_json`, and `report`.

**UNRESOLVED:** The robust implementation reads full bands into memory. This may become a limitation on very large rasters.

---

### Step 5 – Scale Distribution (Candidate Scales)

**Inputs:** `pixel_size_m`, `scale_mode`, channel report, texture support metadata, `upper_radius_factor`, `max_candidate_radius_fraction`, `patch_radius_quantiles`, optional manual limits, and output filenames.

**Scientific core:** Generates candidate segmentation scales. In structure-derived mode, the step reads or infers the maximum texture support radius, derives an upper envelope, and creates a small ladder of candidate radii. The lower bound is derived from texture support or from pixel size. The upper candidate radius is constrained by the upper envelope and `max_candidate_radius_fraction`.

The number of `patch_radius_quantiles` controls how many candidate radii are generated. The candidate radii are placed evenly in log-space between lower and upper bounds; the quantile values are recorded with the candidates as metadata rather than directly placing radii at those quantile positions.

For each radius, the code derives integer `spatialr_px` from `radius_m / pixel_size_m` by rounding to a pixel radius, and derives `minsize_px` from the area-equivalent circle size.

**Technical wrapper:** Pure Python. Reads channel metadata, computes candidate rows, and writes CSV/JSON.

**Outputs:** `scale_candidates.csv`, `scale_candidates.json`, and a step manifest.

**Consumed by:** Feature Range.

**Quality relevance:** Very high. This step defines which object-size range can be selected later. If the texture support or upper envelope is too coarse, the chain can prefer large mixed segments.

**Artifact contract:** Manifest step `scale_distribution` with artifact `scale_candidates_json`.

**UNRESOLVED:** The lower/upper envelope heuristic is not validated across landscapes.

---

### Step 6 – Feature Range (Ranger Assignment)

**Inputs:** `scaled_feature_stack`, `valid_mask`, `scale_candidates_json`, `band_count`, `sample_n`, `knn_k`, `quantile_probs`, and `max_distance_sample_n`.

**Scientific core:** Estimates feature-space density and derives mean-shift range (`ranger`) values. The step samples valid pixel vectors from the scaled stack, computes k-nearest-neighbour distances in feature space, derives quantiles of those distances, and assigns ranger candidates to the ordered scale candidates. If there are more scale candidates than ranger candidates, the last ranger is reused for the remaining scale candidates (tail padding).

**Technical wrapper:** Python/numpy distance computation and raster reading.

**Outputs:** `ranger_candidates.csv`, `ranger_candidates.json`, `scale_candidates_with_ranger.csv`, `scale_candidates_with_ranger.json`, and a step manifest.

**Consumed by:** Perturbations.

**Quality relevance:** High. Ranger values define feature-space merging tolerance. Too large a ranger can merge spectrally different areas; too small a ranger can fragment the segmentation.

**Artifact contract:** Manifest step `feature_range` with artifact `scale_candidates_with_ranger_json`.

**UNRESOLVED:** The manual k-NN computation has not been validated here against an external implementation.

---

### Step 7 – Perturbations

**Inputs:** `scale_candidates_with_ranger_json` and perturbation settings for spatial radius, ranger, minsize, number of perturbations, minsize floor, and seed.

**Scientific core:** For each source scale candidate, creates a local perturbation family around the baseline segmentation parameters. The family contains the baseline and a bounded set of nearby parameter variants. Duplicate and baseline-identical perturbations are removed.

**Technical wrapper:** Pure Python, with seeded random selection if more perturbations are available than requested.

**Outputs:** `perturbation_candidates.csv`, `perturbation_candidates.json`, and a step manifest.

**Consumed by:** Step 9a.

**Quality relevance:** High. This step defines the local sensitivity test. Too narrow a perturbation family can hide instability; too wide a family can test a different regime rather than local robustness.

**Artifact contract:** Manifest step `perturbations` with artifact `perturbation_candidates_json`.

**UNRESOLVED:** The perturbation design is heuristic.

---

### Step 8 – One-Scale Segmentation (executed many times)

**Inputs:** `scaled_feature_stack`, `valid_mask`, one perturbation record, `spatialr`, `ranger`, `minsize`, tile size, and RAM settings.

**Scientific core:** Runs one segmentation realization with the OTB mean-shift / LSMS / small-region-merging chain:

1. Mask the scaled stack and ensure nodata/background handling.
2. Run MeanShiftSmoothing with `spatialr` and `ranger`.
3. Run LSMSSegmentation on the smoothed image.
4. Merge regions smaller than `minsize`.
5. Post-mask labels so background remains background.

**Technical wrapper:** Subprocess calls to OTB and GDAL tools, temporary files, completion detection, and optional cleanup.

**Outputs:** Per-run `merged_labels.tif`, segmentation report, and intermediate rasters.

**Consumed by:** Step 9a.

**Quality relevance:** High. Each run is one realization used to assess sensitivity and stability.

**Artifact contract:** Not a top-level manifest step on its own in the runner. Step 9a manages the response-surface artefact contract and reuse detection for completed runs.

**UNRESOLVED:** OTB algorithm internals and defaults beyond the explicitly passed parameters are not validated here.

---

### Step 9a – Candidate-Scale Response Surface

**Inputs:** `perturbation_candidates_json`, `scaled_feature_stack`, `valid_mask`, candidate metadata, and stability thresholds.

**Scientific core:** This is the main stability analysis. For each candidate scale group, Step 9a runs or reuses segmentation replicates, computes segment-size population statistics, summarizes relative size classes, builds spatial response summaries, measures distributional and spatial variation across perturbations, selects representative medoid runs, computes a stability score, classifies groups, ranks candidate groups, and checks scale adjacency among the top candidates.

**Technical wrapper:** Python orchestration, raster/window reading, many CSV/JSON summaries, and manifest writing. OTB is invoked indirectly through repeated one-scale segmentation runs.

**Outputs:** `run_population_summary`, `candidate_group_response_summary`, spatial response summaries, ranked candidate scales, accepted/removed lists, `candidate_response_surface_report.json`, and a step manifest.

**Consumed by:** Step 9b and Step 10.

**Quality relevance:** Very high. This is the core stability evidence used for final scale selection.

**Artifact contract:** Manifest step `candidate_response_surface` with artifacts `run_population_json`, `group_json`, and `report`.

**UNRESOLVED:** Stability thresholds and penalties are heuristic and may not generalize.

---

### Step 9b – Scale Gating & Handoff

#### 9b-Prepare

**Inputs:** Step 9a outputs, `candidate_id`, and perturbation configuration.

**Scientific core:** Re-ranks candidate groups, checks whether the two best candidates are adjacent on the scale ladder, and either requests manual/user choice for non-adjacent alternatives or constructs a midpoint probe candidate between adjacent boundary candidates.

**Technical wrapper:** Pure Python. Writes a prepare manifest and either alternative-scale files or midpoint-probe files.

**Outputs:** `step9b_prepare_manifest.json`, `ranked_candidate_scales_view.json`, and either supported alternatives or midpoint perturbation files.

**Consumed by:** Step 9b-Midpoint Handoff, or by the user if non-adjacent alternatives require manual selection.

**Quality relevance:** High. This controls whether local refinement proceeds automatically or requires a choice.

**Artifact contract:** Manifest step `step9b_prepare` with branch-dependent artefacts.

**UNRESOLVED:** None identified from inspected code.

#### 9b-Midpoint Response Surface & Handoff

**Inputs:** Midpoint perturbation candidates and the candidate response surface configuration.

**Scientific core:** Runs a small response surface on the midpoint candidate, compares the midpoint stability score against the two boundary candidate scores, and applies the gain-share rule. If the midpoint gain exceeds half of the boundary gain interval, the midpoint is selected; otherwise the No. 1 boundary candidate is retained.

**Technical wrapper:** Reuses Step 9a machinery and writes handoff files.

**Outputs:** `step9b_midpoint_gain_share_handoff.json`, midpoint summaries, and a step manifest.

**Consumed by:** Step 10.

**Quality relevance:** Very high. This step selects the final scale used for materialization.

**Artifact contract:** Manifest step `step9b_midpoint_handoff` with artifact `step9b_midpoint_gain_share_handoff_json`.

**UNRESOLVED:** The 50% gain-share threshold is heuristic.

---

### Step 10 – Materialization & Quality Evidence

#### 10a – Collect Finalist Evidence

**Scientific core:** Collects the handoff decision and earlier summaries into a structured finalist-evidence object.

**Technical wrapper:** Reads JSON/CSV artefacts and writes evidence tables.

**Outputs:** `finalist_evidence.json` and accompanying CSV/JSON files.

**Artifact contract:** Manifest step `step10_collect` with artifact `finalist_evidence_json`.

#### 10b – Aggregate Finalist Evidence

**Scientific core:** Computes summary statistics over finalist evidence fields.

**Technical wrapper:** Python aggregation and table writing.

**Outputs:** Aggregated finalist evidence tables.

**Artifact contract:** Manifest step `step10_aggregate`.

#### 10c – Figures

**Scientific core:** Produces diagnostic visualizations of the decision and evidence structure.

**Technical wrapper:** Matplotlib figure generation and figure manifest writing.

**Outputs:** Diagnostic figures and a figure manifest.

**Artifact contract:** Manifest step `step10_figures` with artifact `figure_manifest_json`.

#### 10d – Materialize Selected Segments

**Scientific core:** Takes the selected representative segmentation and makes it the delivered product.

**Technical wrapper:** Copies the selected `merged_labels.tif` to `selected_labels.tif`, polygonizes labels into `selected_segments.gpkg`, and drops the background segment.

**Outputs:** `selected_labels.tif`, `selected_segments.gpkg`, `selected_segments_manifest.json`.

**Artifact contract:** Manifest step `step10_materialize` with artifacts `selected_segments_manifest_json`, `selected_segments_gpkg`, and `selected_labels_tif`.

#### 10e – Exactextractr Segment Stats & Quality Evidence

**Inputs:** `selected_segments.gpkg`, selected/masked segmentation stack, and related run metadata.

**Scientific core:** Computes per-segment band statistics from the selected segmentation product. The output is evidence, not a final quality class.

**Technical wrapper:** Runs an R script using `exactextractr` and writes CSV/JSON summaries.

**Outputs:** `selected_segment_exactextractr_stats.csv`, `selected_segment_exactextractr_summary.json`, and `ortho_segmentation_quality_info.json`.

**Quality relevance:** Very high for post-hoc assessment. This step provides segment-level evidence but does not decide whether the final product is good or bad.

**Artifact contract:** Manifest step `step10_quality` with artifacts `selected_segment_exactextractr_stats_csv`, `selected_segment_exactextractr_summary_json`, and `ortho_segmentation_quality_info_json`.

**UNRESOLVED:** The R environment and `exactextractr` behaviour are assumed rather than fully validated by the Python runner.

## Final product handoff

The final product handoff is not just the top-level chain report. The useful deliverables are produced in Step 10 and are referenced through the Step 10 manifests:

- `selected_labels.tif` — final selected label raster.
- `selected_segments.gpkg` — polygonized final segments.
- `selected_segments_manifest.json` — materialization metadata.
- `selected_segment_exactextractr_stats.csv` — per-segment band statistics.
- `selected_segment_exactextractr_summary.json` — summary of extracted segment statistics.
- `ortho_segmentation_quality_info.json` — quality evidence summary; not a quality class.
- Diagnostic figure manifest and figures — useful for inspection, not required for downstream processing.

## Method vs wrapper summary

| Step | Scientific core | Technical wrapper | Main artifact contract |
|---|---|---|---|
| Preflight | Input validation and OTB discovery | Directory creation, `shutil.which` | `preflight_report` |
| Valid Mask | Valid analysis domain | `otbcli_BandMathX` expression | `valid_mask.tif` |
| Channels | Vegetation, dryness, brightness, texture proxies | OTB BandMathX and LocalStatisticExtraction | `proxy_stack.tif` |
| Scaling | Robust percentile clipping to `[-1, 1]` in the robust-scaling branch | Masking, parameter computation, BandMathX output | `scaled_feature_stack.tif` |
| Scale Distribution | Candidate radii and minsize from texture support | Python metadata calculations | `scale_candidates.json` |
| Feature Range | k-NN feature-space distance quantiles | Numpy/raster reading | `scale_candidates_with_ranger.json` |
| Perturbations | Local parameter family around each candidate | Python random/grid construction | `perturbation_candidates.json` |
| One-scale Segmentation | Mean-shift + LSMS + small-region merging | OTB/GDAL subprocess chain | per-run `merged_labels.tif` |
| Step 9a Response Surface | Stability analysis and ranking | Python orchestration and summaries | `run_population_json`, `group_json`, `report` |
| Step 9b Prepare | Scale adjacency gating and midpoint construction | Python branch handling | `step9b_prepare_manifest.json` |
| Step 9b Handoff | Gain-share final scale selection | Re-runs response surface for midpoint | `step9b_midpoint_gain_share_handoff.json` |
| Step 10 Collect/Aggregate/Figures | Finalist evidence and diagnostics | Python aggregation and matplotlib | `finalist_evidence_json`, `figure_manifest_json` |
| Step 10 Materialize | Delivered selected segmentation | GDAL copy/polygonize | `selected_labels.tif`, `selected_segments.gpkg` |
| Step 10 Quality | Segment-level evidence | Rscript / exactextractr | `selected_segment_exactextractr_stats.csv`, `ortho_segmentation_quality_info.json` |

## Do-not-break artefact contracts

The following names and manifest keys are operational contracts. Renaming them breaks the runner or downstream handoff unless the consuming code is changed at the same time:

- `valid_mask.tif`
- `proxy_stack.tif`
- `scaled_feature_stack.tif`
- `scale_candidates.json`
- `scale_candidates_with_ranger.json`
- `perturbation_candidates.json`
- `candidate_response_surface_report.json`
- `step9b_midpoint_gain_share_handoff.json`
- `finalist_evidence.json`
- `selected_labels.tif`
- `selected_segments.gpkg`
- `selected_segment_exactextractr_stats.csv`
- `selected_segment_exactextractr_summary.json`
- `ortho_segmentation_quality_info.json`
- manifest artifact keys read by `level1b_dumb_runner.py`

## Current methodological risk focus

The most sensitive methodological coupling is:

Texture radii → texture support metadata → candidate scale envelope → robust scaling / ranger → mean-shift segmentation behaviour.

If texture radii are too coarse for the GSD, and feature scaling is outlier-sensitive, the segmentation can be pulled toward large mixed texture regions. Robust percentile clipping reduces the outlier part of this risk, but the texture radius / scale-envelope coupling remains a separate methodological control point.
