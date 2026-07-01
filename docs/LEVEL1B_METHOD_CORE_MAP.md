# Level-1B Method Core Map

Level-1B is the candidate-scale stability and segmentation-evidence workflow. Its logical method is implemented mostly in `metashape_qc_engine/level1b_*.py`, with orchestration in `level1b_dumb_runner.py`, environment setup in one shell wrapper, and final segment statistics in one R script.

Operational commands are in [RUN_LEVEL1B.md](RUN_LEVEL1B.md). This file maps the scientific method, principal levers, and artifact contracts.

## Method core versus wrapper

| Layer | Current code | Responsibility |
|---|---|---|
| Method steps | `level1b_valid_mask.py`, `level1b_channels.py`, `level1b_scaling.py`, `level1b_scale_distribution.py`, `level1b_feature_range.py`, `level1b_perturbations.py`, `level1b_candidate_response_surface.py`, `level1b_materialization.py` | Define domain, features, scale candidates, perturbations, response evidence, handoff, and products |
| Segment statistics | `R/level1b_step10_exactextractr_segment_stats.R` | Compute exactextractr summaries for materialized selected segments |
| Contract validation | `level1b_preflight.py`, `level1b_step_manifest.py` | Validate runtime inputs/tools and expose stable per-step input/artifact keys |
| Wrapper | `level1b_dumb_runner.py`, `run_level1b_dumb_with_user_header.sh` | Establish environment, call steps in order, enforce branch/status contracts, and write a compact report |

Scientific decisions remain in step modules. The wrapper passes explicit paths and stops when a step or manifest contract fails.

## 1. Valid mask: analysis-domain contract

`level1b_valid_mask.py` creates the binary domain used by later feature and segmentation steps. Rules can use explicit nodata values, an alpha-band threshold, and black-border rejection. Current class defaults reject all-black and all-white RGB tuples.

The mask is `level1b/mask/valid_mask.tif`; later steps receive this exact path. Pixels outside it are excluded from feature statistics, segmentation evidence, and selected-run quality evidence. Changing the mask changes the analyzed population, not merely display appearance.

## 2. Proxy stack and historical texture names

For RGB input, `level1b_channels.py` builds five channels:

1. `VIG` — implemented ExGR vegetation-index expression
2. `DRY` — implemented ExR expression
3. `BRI` — RGB mean brightness
4. `TEX_100M` — local texture statistic at the first metric radius
5. `TEX_200M` — local texture statistic at the second metric radius

`TEX_100M`, `TEX_200M`, `tex_100m_radius_m`, and `tex_200m_radius_m` are historical names. They do not mean 100 m and 200 m. Active defaults in `config/level1b_default.yaml` are `0.25 m` and `0.5 m`; code converts them to pixel radii using orthomosaic pixel size.

Texture channels summarize local structure and constrain the structure-derived scale envelope. Their radii are a methodological risk: values poorly matched to target patterns bias the candidate ladder. The normal CLI does not expose overrides.

Outputs are `level1b/channels/proxy_stack.tif` and `channel_report.json`.

## 3. Robust feature scaling

`level1b_scaling.py` masks the five-band stack, derives each band's 2nd and 98th percentiles, centers on their midpoint, scales by half their range, and clips valid values to `[-1, 1]`. Background remains separate from valid scaled values.

This reduces extreme-value influence on feature-space distances, ranger derivation, and segmentation stability. It is robust-percentile scaling, not PCA and not the commented legacy z-score branch.

Outputs include `scaled_feature_stack.tif`, `scaling_parameters.json`, `scaling_parameters.xml`, and `scaling_report.json`. The JSON records quantiles, bounds, centers, and scales.

## 4. Candidate scale distribution

The active default is `structure_derived_scale_distribution`. `level1b_scale_distribution.py` uses channel metadata and texture roles to establish an explicit envelope:

- explicit `min_radius_m`, or one tenth of inferred texture support, defines the lower bound
- explicit `max_radius_m`, explicit segment-similarity maximum, or inferred texture/target support multiplied by `upper_radius_factor` defines the upper envelope
- candidate radii normally stop at `max_candidate_radius_fraction` of that envelope
- the configured number of positions comes from `patch_radius_quantiles`; deterministic radii are logarithmically spaced
- candidates collapsing to identical `(spatialr_px, minsize_px)` pairs are deduplicated

For each radius:

- `spatialr_px = round(radius_m / pixel_size_m)`, minimum 1
- `area_m2 = pi * radius_m²`
- `minsize_px = round(area_m2 / pixel_area_m2)`, minimum 1

Active defaults include `upper_radius_factor: 2.5`, `max_candidate_radius_fraction: 0.775`, and six positions. They define the tested ladder; Step-9b does not extend it.

Outputs are `level1b/scales/scale_candidates.json` and `.csv`.

## 5. Feature range (`ranger`)

`level1b_feature_range.py` samples valid vectors from the scaled stack. It computes each sampled vector's k-th-nearest-neighbor distance and uses configured quantiles of that distribution as ranger candidates.

`ranger` is the feature-space similarity range. It is distinct from spatial `spatialr_px` and minimum-size `minsize_px`.

Active defaults sample up to 50,000 vectors, limit distance calculation to 8,000, use `k=10`, and derive quantiles `0.25, 0.5, 0.75, 0.9`. Ranger candidates are assigned deterministically across ordered scale candidates.

Outputs are `ranger_candidates.json/.csv` and `scale_candidates_with_ranger.json/.csv`.

## 6. Perturbation design

`level1b_perturbations.py` writes one baseline per complete scale candidate, then a bounded local family around `spatialr_px`, `minsize_px`, and `ranger`.

Current class defaults define:

- spatial-radius delta `ds=1`, reduced to zero for baseline radii of 3 px or less
- ranger delta `max(0.005, 10% of baseline ranger)` when not explicit
- minsize delta `max(5, round(20% of baseline minsize))` when not explicit
- minsize floor at 80% of baseline
- at most `K=8` perturbations, selected deterministically with seed 1 when needed

The family measures local parameter sensitivity. It is not a global search and creates no new metric-scale anchors.

Outputs are `level1b/perturbations/perturbation_candidates.json` and `.csv`.

## 7. Step 9a response-surface evidence

`level1b_candidate_response_surface.py` runs or reuses one-scale segmentation for every planned perturbation. Each run contributes segment-area distributions, tail/central shares, spatial summaries, and run-Q evidence. Candidate families are summarized across perturbations.

Evidence has three linked views:

- **population statistics** — segment counts and areas, size-class distributions, central/tail shares, distribution distances, compatible combinations, and medoid-run context
- **spatial response** — analysis-cell dominance, pattern agreement, persistence, and spatial distribution distances
- **stability response** — edge loading, scale jumps, distribution flutter, spatial jumps, central mass, and response spread

The raw score starts at 1.0, applies fixed penalties for edge loading, scale jumps, distribution flutter, and spatial jumps, rewards mean central-area share, and penalizes response spread. `stability_score` clamps the raw score to `[0, 1]`.

True ranking is:

1. descending `stability_score_raw`
2. descending `stability_score`
3. ascending opaque `candidate_scale_group_id` only as final tie-breaker

Candidate IDs are not scale coordinates. Scale order comes from explicit numeric metadata.

Core outputs are `run_population_summary.json`, `candidate_group_response_summary.json`, `ranked_candidate_scales.json`, `candidate_response_surface_report.json`, detailed run reports, and retained segmentation products under `level1b/candidate_response_surface/`.

## 8. Step 9b adjacency and gain-share handoff

Step-9b starts from the top two true-ranked candidates but independently orders them on the numeric scale ladder.

- Non-adjacent: write both as supported alternatives, require analyst choice, and stop before Step 10.
- Adjacent: reuse lower and upper anchors by reference, construct exactly one midpoint central candidate, and execute only its perturbation family.

After midpoint-family raw support `SM` is available:

```text
midpoint_gain_share = (SM - S2) / (S1 - S2)
```

`S1` and `S2` are rank-1 and rank-2 raw supports. The midpoint is handed forward only when the share is strictly greater than `0.5`; equality retains No1. Invalid reference gain or uninterpretable midpoint support retains No1 with a warning. This is a local support handoff, not global optimization.

Key outputs include:

- `level1b/step9b_prepare_inputs/step9b_prepare_manifest.json`
- `level1b/step9b_prepare_inputs/ranked_candidate_scales_view.json`
- `level1b/local_transition_refinement/step9b_interval_preflight.json`
- midpoint probe/perturbation files on the adjacent branch
- `step9b_supported_scale_alternatives.json` on the non-adjacent branch
- nested `midpoint_response_surface_eval/` outputs
- `step9b_midpoint_gain_share_handoff.json`

## 9. Step 10 product and quality evidence

`level1b_materialization.py` first creates one canonical finalist-evidence object recording numeric boundaries, midpoint, display order, selected candidate and baseline run, group/run rows, source paths, and aggregations. Later Step-10 parts consume it without reranking.

The selected baseline labels are copied to `selected_labels.tif` without recomputing labels, then polygonized to the `selected_segments` GeoPackage layer with `segment_id` and provenance. The R script computes exactextractr named summaries as one wide row per segment against the selected run's masked feature stack.

Final products:

- `level1b/step10_materialization/final_segments/selected_labels.tif`
- `level1b/step10_materialization/final_segments/selected_segments.gpkg`
- `level1b/step10_materialization/final_segments/selected_segments_manifest.json`

Quality and plausibility evidence:

- finalist evidence and numeric aggregation under `decision_evidence/`
- six diagnostic PNGs and `figures/step10_figure_manifest.json`
- `segment_stats/selected_segment_exactextractr_stats.csv`
- `segment_stats/selected_segment_exactextractr_summary.json`
- `quality/ortho_segmentation_quality_info.json`

`ortho_segmentation_quality_info.json` is evidence, not a final quality class. It explicitly records `quality_signal_status: evidence_ready` and that no thresholded quality class is assigned.

## Artifact contracts

Every major step writes a compact manifest under:

```text
level1b/manifests/<step>.json
```

Each contains `step`, `status`, `inputs`, `artifacts`, and `provenance.candidate_id`. The runner consumes exact artifact keys and checks their paths. Scientific row data remain in canonical step outputs rather than manifests.

## Methodological levers and risks

- valid-mask rules define the population
- texture radii define structural support visible to scale generation
- robust scaling controls outlier influence
- scale-envelope controls define tested metric radii
- ranger quantiles define feature-space similarity ranges
- perturbation deltas and family size define local sensitivity evidence
- Step-9a score terms define family ranking
- Step-9b adjacency and fixed `> 0.5` rule define local handoff

The normal CLI does not expose these as ad hoc arguments. Wired operational constants are centralized in `config/level1b_default.yaml`; other method defaults remain in current config classes.

## Explicit non-scope

- no Level-1A orthomosaic reproducibility assessment
- no supervised ecological or land-cover classification
- no global scale optimization
- no scale extrapolation beyond the deterministic ladder
- no automatic resolution of non-adjacent alternatives
- no final categorical quality class
