# Level-1B Method Core Map

## Purpose and scope

Level-1B starts from one finished RGB orthomosaic and produces a selected
segmentation raster, a polygon product, and reviewable numerical evidence. It
does not run Metashape, create an ecological classification, establish external
accuracy, or assign a final quality class.

The Level-1B method is implemented in the `metashape_qc_engine/level1b/`
subpackage. The normal environment wrapper is
`metashape_qc_engine/run_level1b_dumb_with_user_header.sh`, and Step-10
segment statistics use
`R/level1b_step10_exactextractr_segment_stats.R`.

## Current chain

```text
RGB orthomosaic
  -> preflight
  -> valid analysis mask
  -> six-band RGB/DGLCM-PC1 proxy stack
  -> robust per-band scaling
  -> scene-adaptive candidate pre-screening
  -> scale x ranger x seed-phase SAGA ensemble
  -> Step 9a continuous ensemble support and ranking
  -> Step 9b adjacency / midpoint handoff
  -> finalist evidence
  -> multiscale centroid-seed stabilization
  -> Step 10 materialization, figures, and exactextractr evidence
```

The active default parameter file is `config/level1b_default.yaml`. It defines
an admissible radius domain and method policies. It does not define the concrete
Step-9 scale ladder. Pre-screening materializes that ladder from the current
scene.

## 1. Valid analysis domain

The valid mask is a binary raster in which valid analysis pixels are one and
invalid/background pixels are zero. It is consumed by channel construction,
scaling, pre-screening, segmentation, Step 9, and Step 10.

The mask is a scientific domain contract: feature distributions and all later
statistics refer only to this support. Incorrect border, nodata, or alpha
handling propagates through the complete chain.

Principal artifact:

```text
<run_root>/level1b/mask/valid_mask.tif
```

## 2. Six-band proxy stack

The active normal RGB stack has exactly this order:

1. `ExGR`
2. `ExR`
3. `BRI`
4. `DGLCM_PC1_SMALL`
5. `DGLCM_PC1_LARGE`
6. `RATIO_DGLCM_PC1`

The first three bands are deterministic RGB proxies. The structure bands are
directional Haralick simple Inertia responses on RGB-PC1. RGB is masked before
the repository PCA implementation is called. PC1 is clipped at configured valid
pixel quantiles, rescaled to the configured Haralick range, and evaluated for
the configured directions and small/large metric radii. Directional Inertia is
aggregated by pixelwise maximum.

The ratio band is

[
RATIO = \frac{DGLCM_{small}}{DGLCM_{large}+\varepsilon}.
]

Bands 4 and 5 are structure-support bands. Band 6 is a feature-space ratio and
is not a source for the candidate radius ladder.

The historical five-band ExGR local-variance stack is not the active normal
path.

Principal artifact:

```text
<run_root>/level1b/channels/proxy_stack.tif
```

## 3. Robust scaling

For each valid proxy band, the active scaler computes the 2nd and 98th
percentiles, maps their midpoint to zero, scales their half-distance to one,
and clips valid values to `[-1, 1]`. Invalid pixels retain the configured
background value.

This gives all six channels a common bounded numerical range. It does not make
the bands statistically independent or equally informative.

Principal artifacts:

```text
<run_root>/level1b/scaling/scaled_feature_stack.tif
<run_root>/level1b/scaling/scaling_parameters.json
```

## 4. Scene-adaptive candidate pre-screening

The normal runner does not call the historical
`scale_distribution -> feature_range -> perturbations` sequence. It calls
`run_candidate_prescreening_step()` and passes its candidate population
directly to Step 9a.

### Spatial support

The configured `radius_min_m` and `radius_max_m` define the admissible
metric domain. A robust multiband empirical variogram is sampled from valid,
scaled feature vectors over logarithmic lags and configured directions. Stable
first crossings of configured sill fractions materialize scene-specific radius
support points. Knees, plateaus, and anisotropy are diagnostics; they are not
separate candidate classes and do not receive different Step-9 rules.

### Feature-space range

The same scaled valid feature vectors provide empirical k-nearest-neighbour
distance distributions. For every configured candidate k, the Half-Sample Mode
(HSM) is computed. The smallest k in the first configured stable HSM plateau is
selected. The candidate population uses the HSM mode and the positive unique
bounds of its main modal interval as bounded ranger positions. No tail-quantile
ranger ladder is used.

### Seed realizations and minsize metadata

Each scale/ranger combination is crossed with the configured translations of a
metric hexagonal seed lattice. Nominal seed centres snap within a
radius-relative neighbourhood to local multiband-variance minima while
respecting radius-relative spacing and coverage rules.

`minsize_px` is common technical scale metadata derived from
`radius_min_m`; the active SAGA backend does not perform a later OTB
small-region merge. It is not an independent candidate axis.

Principal artifacts:

```text
<run_root>/level1b/candidate_pre_screening/candidate_population.json
<run_root>/level1b/candidate_pre_screening/variogram_diagnostics.json
<run_root>/level1b/candidate_pre_screening/candidate_pre_screening_report.json
```

## 5. Ensemble segmentation

Every materialized scale x ranger x seed-phase row is one planned SAGA Seeded
Region Growing realization. The segmentation consumes the same scaled proxy
stack used for pre-screening. Candidate `ranger` is passed as feature
variance and `spatialr_px` as position variance and seed-support scale.

Step 9a may reuse a run only when its run contract and required artifacts match.
The continuous-support implementation uses run-contract version 6. Historical
summaries without scale-match evidence are not current reusable run summaries.

Principal per-run evidence includes:

- merged labels;
- run-level segment-size and q statistics;
- exact parameters and seed realization;
- segmentation report.

## 6. Step 9a: continuous ensemble support

Step 9a groups runs by candidate scale, computes per-run population evidence,
compares boundary persistence across controlled variations, selects an actual
boundary-medoid run, and ranks candidate families.

### 6.1 Continuous scale match

For segment (i) in candidate family (g),

[
q_i = \frac{r_{segment,i}}{r_{candidate,g}},
qquad
m_i = \min(q_i, q_i^{-1}).
]

The run-level scale-match support is area weighted:

[
M_{gj} =
\frac{\sum_i A_i m_i}{\sum_i A_i}.
]

It is one when segment and candidate radii agree and decreases continuously and
symmetrically for smaller or larger segments. It replaces the former binary
edge-loaded penalty in current-run ranking.

Across perturbation runs, repeated support is summarized conservatively as

[
R(x) =
\operatorname{clip}
\left(
\operatorname{median}(x)
-1.4826\,MAD(x),
0,1
\right).
]

Thus

[
S_{scale,g}=R(\{M_{gj}\}).
]

The factor 1.4826 is the normal-consistency scaling of MAD, not a fitted
candidate weight.

### 6.2 Scale-relative boundary agreement

The previous fixed one-pixel matching tolerance is not used by the current
score. For a boundary pixel at distance (d) from the nearest comparison
boundary and reference radius (r) in pixels,

[
b(d,r)=\max\left(0,1-\frac{d}{r}\right).
]

Agreement is evaluated symmetrically in both directions. Within one candidate
family, the reference radius is the geometric mean of the two run radii. For
adjacent candidate families, the geometric mean of their representative radii
is used. Boundary localization is therefore normalized by the tested spatial
scale rather than by one raster pixel.

Pairwise agreements are separated into:

- seed-realization agreement;
- ranger agreement;
- radius agreement.

Each set is aggregated with the same robust median-minus-MAD operator:

[
S_{seed,g},\quad S_{ranger,g},\quad S_{radius,g}.
]

### 6.3 Final raw support and ranking

The current raw support score is

[
S_g =
\left(
S_{seed,g}
S_{ranger,g}
S_{radius,g}
S_{scale,g}
\right)^{1/4}.
]

The four components are bounded, empirical support dimensions. No additive
penalties or compensating bonuses are used. A required component that cannot be
computed is recorded in `ensemble_support_missing_components`; the family is
marked `ensemble_support_not_evaluable` rather than receiving an implicit
support value of one.

Current candidate groups are ranked by `stability_score_raw`, which equals
`ensemble_support_raw_v2`, then by the bounded score and deterministic group
ID tie-breaking.

### 6.4 Legacy diagnostics

Size classes, central/tail shares, response spread, flutter, scale-jump, and
spatial-jump flags remain in the reports for interpretation. The historical
fixed coefficients

```text
edge 0.35
scale jump 0.35
distribution flutter 0.20
spatial jump 0.20
central-mass bonus 0.50
response-spread penalty 0.10
```

do not influence ranking of newly generated run-contract-v6 response surfaces.
The legacy calculation remains only to explain completed historical artifacts.

`candidate_outcome` now states whether the four-component ensemble support is
evaluable. It is not a quality class and no score threshold such as 0.75
accepts or rejects scientific quality.

Principal artifacts:

```text
<run_root>/level1b/candidate_response_surface/run_population_summary.json
<run_root>/level1b/candidate_response_surface/candidate_group_response_summary.json
<run_root>/level1b/candidate_response_surface/ranked_candidate_scales.json
<run_root>/level1b/candidate_response_surface/boundary_support/
<run_root>/level1b/candidate_response_surface/candidate_response_surface_report.json
```

## 7. Step 9b: adjacency and midpoint support

Step 9b uses the Step-9a ranking and explicit numeric scale ladder.

If No. 1 and No. 2 are not adjacent, both are written as supported alternatives
and the runner stops for analyst choice. Non-adjacency is not an error.

If they are adjacent, Step 9b constructs exactly one midpoint family inside
that interval, evaluates it with the same Step-9a support method, and computes

[
gain\_share =
\frac{S_M-S_2}{S_1-S_2}.
]

The midpoint is handed off only when `gain_share > 0.5`; at exactly 0.5 the
No. 1 candidate is retained. This threshold defines the question “does the
midpoint deliver more than half the reference gain?” It is not a fitted score
weight and does not extend the scale domain.

Principal artifacts:

```text
<run_root>/level1b/local_transition_refinement/step9b_supported_scale_alternatives.json
<run_root>/level1b/local_transition_refinement/step9b_midpoint_probe_candidate.json
<run_root>/level1b/local_transition_refinement/midpoint_response_surface_eval/
<run_root>/level1b/local_transition_refinement/step9b_midpoint_gain_share_handoff.json
```

Only the artifacts for the branch taken are expected.

## 8. Multiscale centroid-seed stabilization

After adjacent handoff and finalist-evidence collection, centroids from the
initial Step-9a label population are accumulated per scale. Density peaks must
satisfy configured support across runs, seed phases, and ranger positions.
Mutual-nearest tracks across adjacent scales identify persistent centres.
Tracks present at the handed-off scale provide one stabilized seed scaffold.

SAGA then runs once at the handed-off `spatialr_px` and `ranger` using those
seeds. This is a single evidence-derived resegmentation, not recursive centroid
feedback and not a consensus boundary merge.

Principal artifacts:

```text
<run_root>/level1b/step10_materialization/centroid_seed_stabilization/stabilized_seeds.csv
<run_root>/level1b/step10_materialization/centroid_seed_stabilization/stabilized_labels.tif
<run_root>/level1b/step10_materialization/centroid_seed_stabilization/centroid_seed_stabilization_report.json
```

## 9. Step 10 products and evidence

Step 10:

1. collects finalist roles, selected candidate, and selected representative run;
2. aggregates existing numeric evidence;
3. writes diagnostic figures;
4. copies the stabilized label raster and polygonizes it;
5. calls the R exactextractr script for per-segment feature statistics;
6. writes run-level quality information.

Final product paths:

```text
<run_root>/level1b/step10_materialization/final_segments/selected_labels.tif
<run_root>/level1b/step10_materialization/final_segments/selected_segments.gpkg
<run_root>/level1b/step10_materialization/final_segments/selected_segments_manifest.json
```

Quality-evidence paths:

```text
<run_root>/level1b/step10_materialization/segment_stats/selected_segment_exactextractr_stats.csv
<run_root>/level1b/step10_materialization/segment_stats/selected_segment_exactextractr_summary.json
<run_root>/level1b/step10_materialization/quality/ortho_segmentation_quality_info.json
<run_root>/level1b/step10_materialization/figures/step10_figure_manifest.json
```

`ortho_segmentation_quality_info.json` is evidence. It deliberately contains
no thresholded traffic-light or final quality class.

## Methodological controls that remain explicit

The method is scene-adaptive but not assumption-free. Important explicit
controls remain in `config/level1b_default.yaml`:

- valid RGB band mapping;
- DGLCM radii, directions, clipping, and quantization;
- admissible radius domain;
- variogram lag sampling and sill-fraction support points;
- HSM k candidates and plateau tolerance;
- ranger modal-interval policy;
- seed-phase translations and candidate budget;
- centroid-support minima.

These settings define the experiment. They should be reported with results and
tested for sensitivity when transferring the workflow to substantially
different GSDs, landscapes, or image qualities.
