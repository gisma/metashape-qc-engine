# Level-1A/Level-1B Sensitivity Study: Methods

## Study objective

The sensitivity study quantifies how upstream photogrammetric processing and downstream segmentation controls affect the reproducibility of orthomosaic products and the stability of segmentation evidence. It does not optimize parameters automatically and does not define a final ecological or quality class. Its purpose is to expose parameter-sensitive conclusions, failed parameter regions, and the propagation of upstream image-product variation into Level-1B segmentation.

The study uses the existing workflows without replacing their scientific methods:

- **Level-1A** repeatedly constructs and evaluates Metashape orthomosaic candidates.
- **Level-1B** derives a valid analysis domain, a deterministic six-band RGB/DGLCM-PC1 proxy stack, scene-adaptive scale/ranger candidates, segmentation ensembles, Step-9 stability evidence, and Step-10 materialized products and quality evidence.

The meta-runner only materializes an explicit experiment table, calls these workflows, and collects their existing numeric outputs. It contains no winner-selection rule.

## Experimental organization

The experiment is defined in `config/sensitivity/level1ab_sensitivity.yaml`. Every planned run is written to `study_design.csv` before processing. The current reference design contains three complementary blocks.

### Level-1A processing sensitivity

The Level-1A block uses a balanced (2 \times 2 \times 2) factorial screening design with the following factors:

| Factor | Levels |
|---|---|
| Alignment downscale | 1, 2 |
| Custom mesh face count | 50,000; 100,000 |
| Mesh smoothing iterations | 5, 35 |
| Orthomosaic resolution | fixed at 0.05 m |

Each of the eight parameter combinations is executed three times, giving 24 Metashape runs. Repeated builds separate variation caused by processing configuration from variation among repeated executions of the same configuration.

Level-1A evaluates successful orthomosaics on a canonical raster grid. Existing workflow outputs provide, among other quantities, valid support counts, pixel-wise median orthomosaics, median absolute deviation, RMSE to the median, support persistence, and support dropout. The primary Level-1A ranking remains the existing continuous-stability ranking. The sensitivity meta-runner does not alter that ranking.

### Level-1B parameter sensitivity

The Level-1B parameter block is conditional on the orthomosaic selected by the existing Level-1A continuous-stability procedure. Seven pre-registered profiles are evaluated:

| Profile | Difference from active Level-1B baseline | Scientific question |
|---|---|---|
| `baseline` | none | Reference result |
| `radius_domain_narrow` | maximum admissible radius 2.0 m | Does the upper spatial domain control the selected scale or segmentation? |
| `radius_domain_wide` | maximum admissible radius 6.0 m | Does additional coarse-scale support alter the result? |
| `dglcm_finer` | DGLCM radii 0.1/0.3 m | Sensitivity to finer directional structure support |
| `dglcm_coarser` | DGLCM radii 0.3/0.8 m | Sensitivity to coarser directional structure support |
| `ranger_plateau_strict` | HSM plateau relative tolerance 0.05 | Sensitivity of feature-range estimation to a stricter stability definition |
| `centroid_support_strict` | stronger run/phase/ranger support requirements | Sensitivity of stabilized seeds to stricter ensemble support |

All profiles retain the implemented six-band stack:

1. ExGR
2. ExR
3. BRI
4. DGLCM_PC1_SMALL
5. DGLCM_PC1_LARGE
6. RATIO_DGLCM_PC1

The design therefore tests interpretable controls without searching arbitrary channel subsets. The DGLCM profiles vary metric support radii but do not change channel identity or formula. A future proxy-stack ablation would require separately pre-registered recipes and should not be mixed silently into this experiment.

Each profile is created from `config/level1b_default.yaml` by replacing only explicitly listed existing keys. The resulting complete YAML is stored with the study. Unknown override paths or incompatible value types fail during planning.

### Upstream-to-downstream propagation

A limited propagation block applies the unchanged Level-1B baseline to four corners of the Level-1A factorial design:

- fine alignment / low face count / low smoothing;
- fine alignment / high face count / high smoothing;
- coarse alignment / low face count / low smoothing;
- coarse alignment / high face count / high smoothing.

This block tests whether plausible upstream processing contrasts propagate into the Level-1B result. It deliberately avoids a full Cartesian product between all Level-1A variants and all Level-1B profiles. Consequently, it supports a targeted propagation assessment, not a complete estimate of all Level-1A × Level-1B interactions.

## Response variables

### Level-1A evidence

The collector imports the existing `summary_key_metrics.tsv` rows. Principal response variables include:

- number of successful orthomosaics per variant;
- valid-support and support-dropout measures;
- mean and 95th-percentile MAD;
- mean and 95th-percentile RMSE to the median orthomosaic;
- stable and unstable fractions at the configured RMSE guard threshold;
- identity and stability context of the selected Level-1A product.

These quantities measure repeatability and spatial support. They do not establish absolute geometric accuracy because no independent GCP/checkpoint accuracy test is introduced by this study.

### Level-1B evidence

For each Level-1B run, the collector records:

- chain status and Step-9b branch;
- selected candidate, selected source, and representative run;
- available selected-run segment statistics from Step 10;
- Step-9b values `S1`, `S2`, `SM`, and midpoint gain share when an adjacent midpoint handoff exists;
- the complete per-run Level-1B artifacts at their normal locations.

Scientific review should additionally compare the existing segmentation products spatially. Relevant descriptive responses include segment count, area-distribution quantiles, maximum-to-median area ratio, large-segment share, boundary persistence, and within-segment feature dispersion where available. The current collector preserves existing numeric outputs; it does not invent missing metrics or compute inferential statistics.

## Analysis strategy

The primary analysis is effect-oriented rather than winner-oriented.

1. **Level-1A main effects:** compare stability and support responses across the balanced factorial levels while retaining replicate-level variation.
2. **Level-1B profile contrasts:** compare each pre-registered profile against the Level-1B baseline on the selected Level-1A product.
3. **Propagation contrasts:** compare the baseline Level-1B response among the four named Level-1A corner variants.
4. **Failure-domain evidence:** retain explicit workflow failures and non-adjacent Step-9b outcomes rather than excluding them silently.
5. **Spatial review:** inspect selected labels, polygons, figures, and quality evidence for chain growth, fragmented support, implausibly large segments, and changes in boundary location.

For a study extended to several independent scenes, a suitable model for a numeric response (y) is

\[
y = \mu + A + B + A\!:\!B + u_{scene} + \varepsilon,
\]

where (A) represents Level-1A controls, (B) represents Level-1B controls, and (u_{scene}) is a scene-level random effect. That model is not identifiable from the single-scene reference YAML alone. The current design supports within-scene sensitivity and reproducibility assessment; population-level generalization requires several independent scenes or acquisition campaigns.

## Reproducibility and audit trail

The following artifacts define the study audit trail:

| Artifact | Role |
|---|---|
| `config/sensitivity/level1ab_sensitivity.yaml` | pre-registered design and explicit parameter values |
| `study_design.csv` | materialized list of planned Level-1A and Level-1B runs |
| `level1b/configs/<profile>.yaml` | complete resolved config for each Level-1B profile |
| Level-1A `manifest.csv` | replicate execution status and orthomosaic paths |
| Level-1A `selected_product.json` | selected product and median/medoid context |
| Level-1B `level1b_dumb_chain_report.json` | chain status and artifact references |
| `study_results.csv` | collected existing Level-1A and Level-1B scalar evidence |
| `sensitivity_study_report.json` | collection status and row counts |

The study YAML, source revision, and result directory should be archived together when results are reported. The workflow does not assign a final quality class, and the quality JSON remains evidence rather than a thresholded decision.

## Scope limitations

The current reference design has the following explicit limits:

- one image dataset and scene;
- one fixed orthomosaic output resolution in the Level-1A screening block;
- Level-1B profile contrasts on one selected Level-1A product;
- only four targeted Level-1A variants in the propagation block;
- no complete Level-1A × Level-1B factorial crossing;
- no arbitrary proxy-band search;
- no independent geometric ground truth;
- no ecological reference labels and no ecological classification;
- no population-level inference across landscapes or acquisition conditions.
