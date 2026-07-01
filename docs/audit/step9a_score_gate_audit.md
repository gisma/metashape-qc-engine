# Step-9a Score Gate Audit

## 1. Scope

This is an audit only. No repository code or source-level configuration was changed. The audit used current source code and existing Step-9a CSV/JSON outputs from `/home/creu/tmp/level1b_runs/ref_fullrange_clean_20260627T213220/level1b/candidate_response_surface`. No candidate parameter was inferred from an identifier string; every reported parameter value was read from an output field. Evidence: `metashape_qc_engine/level1b_candidate_response_surface.py`, functions cited below; existing output files listed in section 3.

## 2. Repository State

- Current branch: `level1b-step9a-score-gate-audit`, checked with read-only command `git symbolic-ref --short HEAD`.
- Current HEAD: `22127cf3a9e50847dddab84517dc48872d2c6bbc`, checked with read-only command `git rev-parse HEAD`.
- No Git history was inspected.

## 3. Files Inspected

Current source:

- `/home/creu/dev/metashape-qc-engine/metashape_qc_engine/level1b_candidate_response_surface.py` — Step-9a input grouping, run metrics, group metrics, scoring, outcome classification, ranking, and output writes (`read_step8_local_parameter_combinations`, `group_rows_by_candidate_scale`, `compute_run_population_summary_from_counts`, `compute_normal_response_diagnostics`, `compute_candidate_group_response_summary`, `stability_score`, `classify_candidate_outcome`, `run_candidate_response_surface_step`, `_write_outputs`; lines 115-166, 203-505, 728-818, 817-990, 1210-1288, 1338-1365).
- `/home/creu/dev/metashape-qc-engine/metashape_qc_engine/level1b_perturbations.py` — input candidate validation, baseline/local parameter rows, passthrough fields, and Step-8 export (`REQUIRED_CANDIDATE_FIELDS`, `OPTIONAL_PASSTHROUGH_FIELDS`, `read_scale_candidates_with_ranger`, `build_perturbation_candidates`, `_candidate_row`, `_deltas`, writers; lines 9-24, 134-255, 324-382).
- `/home/creu/dev/metashape-qc-engine/metashape_qc_engine/level1b_feature_range.py` — ranger assignment and assigned-candidate export (`ASSIGNED_FIELDS`, `assign_ranger_candidates_to_scale_candidates`, `write_assigned_candidates_csv`, `write_assigned_candidates_json`; lines 28-65, 378-450).
- `/home/creu/dev/metashape-qc-engine/metashape_qc_engine/level1b_scale_distribution.py` — initial scale-candidate fields, generation, and export (`ROW_FIELDS`, `_candidate_row`, `build_scale_candidates`, `write_scale_candidates_csv`, `write_scale_candidates_json`; lines 20-73, 318-346, 377-462).

Existing Step-9a outputs:

- `/home/creu/tmp/level1b_runs/ref_fullrange_clean_20260627T213220/level1b/candidate_response_surface/run_population_summary.csv` — run-level metrics and real parameter fields; header line 1, baseline rows at lines 2, 11, 20, 29, 38, and 47.
- `/home/creu/tmp/level1b_runs/ref_fullrange_clean_20260627T213220/level1b/candidate_response_surface/run_population_summary.json` — JSON form of the 54 run summaries; objects contain the same run metric/parameter fields written by `_write_outputs` (`level1b_candidate_response_surface.py:1350-1351`).
- `/home/creu/tmp/level1b_runs/ref_fullrange_clean_20260627T213220/level1b/candidate_response_surface/candidate_group_response_summary.csv` — six group summaries; header line 1 and rows 2-7.
- `/home/creu/tmp/level1b_runs/ref_fullrange_clean_20260627T213220/level1b/candidate_response_surface/candidate_group_response_summary.json` — JSON form of the six group summaries, written with the CSV by `_write_outputs` (`level1b_candidate_response_surface.py:1352-1353`).
- `/home/creu/tmp/level1b_runs/ref_fullrange_clean_20260627T213220/level1b/candidate_response_surface/ranked_candidate_scales.csv` — six ranked group summaries; header line 1 and ranked rows 2-7.
- `/home/creu/tmp/level1b_runs/ref_fullrange_clean_20260627T213220/level1b/candidate_response_surface/ranked_candidate_scales.json` — JSON form of the ranked summaries, written with the CSV by `_write_outputs` (`level1b_candidate_response_surface.py:1360-1361`).
- `/home/creu/tmp/level1b_runs/ref_fullrange_clean_20260627T213220/level1b/candidate_response_surface/candidate_response_surface_report.json` — actual run configuration and counts; thresholds at lines 56-66 and counts at lines 80-84.

No other source or output file was used as evidence.

## 4. Step-9a Candidate Group Generation

Step-9a does not create a new candidate parameter grid. It reads the existing Step-8 perturbation rows from `cfg.perturbation_candidates_json_path` in `read_step8_local_parameter_combinations`, which requires a nonempty `candidates` list or a top-level list (`level1b_candidate_response_surface.py:115-121`). `run_candidate_response_surface_step` immediately passes those rows to `group_rows_by_candidate_scale` (`level1b_candidate_response_surface.py:823-825`).

The Step-9a group key is chosen by `candidate_scale_group_key` from the first nonempty field in this exact order: `candidate_scale_group_id`, `source_scale_id`, `scale_id`, `source_candidate_id`; absence of all four raises `ValueError` (`level1b_candidate_response_surface.py:124-129`). `group_rows_by_candidate_scale` copies each row, adds `_step8_row_index` only if absent, groups by that key, sorts group IDs, sorts each group's rows by `perturbation_id` (falling back to row index), and returns dictionaries containing `candidate_scale_group_id` and `rows` (`level1b_candidate_response_surface.py:132-142`). No parameter is parsed from the group ID.

Upstream candidate rows are generated in two source stages:

1. `build_scale_candidates` produces scale candidates. In metric mode it uses the explicit configured radii; in structure mode it uses the computed `radii` sequence, then `_candidate_row` stores `radius_m`, `area_m2`, `pixel_size_m`, `pixel_area_m2`, `spatialr_px`, and `minsize_px` as actual fields (`level1b_scale_distribution.py:323-346,377-410`).
2. `assign_ranger_candidates_to_scale_candidates` copies each scale-candidate dictionary and adds `ranger_id`, `ranger`, `ranger_source`, and `assignment_rule` (`level1b_feature_range.py:378-397`). `build_perturbation_candidates` then creates one baseline row and local perturbation rows from the actual `spatialr_px`, `minsize_px`, and `ranger` fields (`level1b_perturbations.py:168-238`).

The existing report records six candidate groups, 54 successful runs, and zero failed runs (`candidate_response_surface_report.json:80-84`).

## 5. Candidate Parameter Export

### Source export chain

The initial scale candidate schema declares `candidate_id`, `scale_id`, `scale_index`, `scale_mode`, `scale_source`, `radius_m`, `area_m2`, `pixel_size_m`, `pixel_area_m2`, `spatialr_px`, `minsize_px`, `ranger`, `coupling_rule`, and structure metadata fields (`level1b_scale_distribution.py`, `ROW_FIELDS`, lines 20-49). `_candidate_row` assigns the core numeric fields; the scale CSV/JSON writers export the candidate dictionaries (`level1b_scale_distribution.py:323-346,413-462`).

The ranger-assigned schema explicitly contains `candidate_id`, `scale_id`, `radius_m`, `area_m2`, `spatialr_px`, `minsize_px`, `ranger_id`, `ranger`, `ranger_source`, and `assignment_rule`; the assigned writers preserve extra fields as well (`level1b_feature_range.py:28-39,428-450`).

The perturbation stage requires `candidate_id`, `scale_id`, `spatialr_px`, `minsize_px`, and `ranger`; it optionally passes through only `radius_m`, `area_m2`, `ranger_id`, `ranger_source`, and `assignment_rule` (`level1b_perturbations.py:9-11,134-163`). `_candidate_row` exports `perturbation_id`, `source_candidate_id`, `scale_id`, actual `spatialr_px`, `minsize_px`, `ranger`, offsets, baseline status, rule, and those passthrough values (`level1b_perturbations.py:346-369`).

### Step-9a exports

`compute_run_population_summary_from_counts` stores the source fields as `source_candidate_id`, `source_scale_id`, `source_candidate_radius_m`, `source_spatial_radius`, `source_minsize`, and `source_ranger`; it also stores actual run fields as `run_spatial_radius_m`, `run_minsize`, `run_ranger`, `parameter_offsets`, and the complete `original_row_metadata` dictionary (`level1b_candidate_response_surface.py:274-309`). `_write_incremental_run_q_statistics_from_counts` additionally writes `scale_id`, `candidate_id`, `perturbation_id`, `radius_m`, `spatialr_px`, `minsize_px`, and `ranger` into each run summary (`level1b_candidate_response_surface.py:1228-1261`). `_write_outputs` exports these summaries to `run_population_summary.csv` and `.json` (`level1b_candidate_response_surface.py:1338-1351`).

The group and ranked files do not contain the source candidate's `candidate_id`, `radius_m`, `spatialr_px`, `minsize_px`, or source `ranger`. They contain `candidate_scale_group_id` and the selected medoid's `medoid_run_id` plus `medoid_parameters` (`candidate_group_response_summary.csv:1`; `ranked_candidate_scales.csv:1`). `select_medoid_run` defines `medoid_parameters` as the medoid run's `spatial_radius_m`, `minsize`, `ranger`, and `parameter_offsets`; these are medoid-run values, not a substitute for the baseline/source candidate fields (`level1b_candidate_response_surface.py:459-502`).

## 6. Metric Computation Locations

| requested field | exact computation / assignment | export location |
|---|---|---|
| `lower_tail_area_share` | `compute_class_summaries`: `lower = micro.area_share + small.area_share`, then `summary["lower_tail_area_share"] = lower` (`level1b_candidate_response_surface.py:238-258`) | copied into each run summary by `compute_run_population_summary_from_counts` (`350-351`), then written by `_write_outputs` (`1350-1351`) |
| `central_area_share` | `compute_class_summaries`: `central = in_scale.area_share`, then assignment to `summary` (`level1b_candidate_response_surface.py:252-257`) | same run-summary copy/write path (`350-351,1350-1351`) |
| `upper_tail_area_share` | `compute_class_summaries`: `upper = large.area_share + oversize.area_share`, then assignment to `summary` (`level1b_candidate_response_surface.py:252-258`) | same run-summary copy/write path (`350-351,1350-1351`) |
| `response_center_q` | `compute_normal_response_diagnostics`: median of run `area_weighted_q_median` values: `statistics.median(centers) if centers else 0.0` (`level1b_candidate_response_surface.py:391-408`) | merged into group summary with `**diagnostics` (`764-768`) and written to group/ranked files (`1352-1353,1360-1361`) |
| `response_spread_q` | median of each run's `area_weighted_q_q90 - area_weighted_q_q10`: `statistics.median(spreads) if spreads else 0.0` (`level1b_candidate_response_surface.py:391-408`) | same group/ranked path (`764-768,1352-1361`) |
| `lower_tail_area_share_mean` | `_mean(lower)` over run `lower_tail_area_share` values (`level1b_candidate_response_surface.py:394-415`) | same group/ranked path (`764-768,1352-1361`) |
| `central_area_share_mean` | `_mean(central)` over run `central_area_share` values (`level1b_candidate_response_surface.py:395-415`) | same group/ranked path (`764-768,1352-1361`) |
| `upper_tail_area_share_mean` | `_mean(upper)` over run `upper_tail_area_share` values (`level1b_candidate_response_surface.py:396-415`) | same group/ranked path (`764-768,1352-1361`) |
| `medoid_run_id` | `select_medoid_run` evaluates every run, minimizes `mean_distance_to_medoid`, and assigns `candidate["run_id"]`; empty input falls back to `""` (`level1b_candidate_response_surface.py:459-502`) | merged with `**medoid` (`737-776`) and written to group/ranked files (`1352-1361`) |
| `stability_score` | `compute_candidate_group_response_summary`: `summary["stability_score"] = stability_score(summary)` (`level1b_candidate_response_surface.py:782`) | group/ranked writers (`1352-1361`) |
| `candidate_outcome` | immediately after scoring: `summary["candidate_outcome"] = classify_candidate_outcome(summary)` (`level1b_candidate_response_surface.py:783`) | group/ranked writers (`1352-1361`) |

`classify_candidate_outcome` checks `scale_jump_flag` first, then `spatial_scale_jump_flag`, distribution/edge flags, centered status plus score, and finally returns `unstable_distribution_response` (`level1b_candidate_response_surface.py:965-976`). Thus `candidate_outcome` and `stability_score` are related outputs but are not the same rule.

## 7. stability_score Logic

The exact source expression is (`level1b_candidate_response_surface.py`, `stability_score`, lines 954-962):

```python
score = 1.0
score -= 0.35 * float(summary.get("edge_loaded_flag", False))
score -= 0.35 * float(summary.get("scale_jump_flag", False))
score -= 0.2 * float(summary.get("distribution_flutter_flag", False))
score -= 0.2 * float(summary.get("spatial_scale_jump_flag", False))
score += 0.5 * float(summary.get("central_area_share_mean", 0.0))
score -= 0.1 * float(summary.get("response_spread_q", 0.0))
return max(0.0, min(1.0, score))
```

Therefore:

- `stability_score` is exactly zero when the pre-clamp expression is less than or equal to zero; `max(0.0, ...)` clamps it to zero (`level1b_candidate_response_surface.py:954-962`).
- A candidate retains a positive score when that pre-clamp expression is greater than zero. If it is between zero and one, that value is retained; if it is at least one, `min(1.0, score)` caps it at one (`level1b_candidate_response_surface.py:954-962`).
- `scale_jump_flag == True` subtracts `0.35`; it does not independently force the score to zero (`level1b_candidate_response_surface.py:957,962`). Separately, it forces `candidate_outcome = "scale_jump_detected"` because outcome classification checks it first (`level1b_candidate_response_surface.py:965-967`).
- Ranking sorts by descending `stability_score`, then lexically by the already-exported `candidate_scale_group_id` as a tie-breaker; it does not parse parameters from the ID (`level1b_candidate_response_surface.py:911-914`).

For this run, the report records the score-related thresholds used by diagnostic flags, including `min_central_area_share=0.5`, `max_edge_loaded_area_share=0.5`, `max_response_spread_q=1.5`, `max_distribution_flutter=1.0`, `max_scale_jump_distance=1.5`, and `max_spatial_pattern_distance=1.0` (`candidate_response_surface_report.json:56-66`). The arithmetic weights themselves are fixed in `stability_score`, not read from that threshold object (`level1b_candidate_response_surface.py:954-962`).

## 8. Candidate-by-Candidate Diagnosis

The table is in the exact order of `ranked_candidate_scales.csv`; candidate IDs and parameter values come from each group's baseline row in `run_population_summary.csv`, not from parsing group IDs. The baseline fields `source_candidate_radius_m/source_spatial_radius/source_minsize/source_ranger` and `radius_m/spatialr_px/minsize_px/ranger` agree within each listed row (`run_population_summary.csv:1-2,11,20,29,38,47`). `area_m2`, `ranger_id`, `ranger_source`, and `assignment_rule` are available in that row's `original_row_metadata` (`run_population_summary.csv:2,11,20,29,38,47`; source storage at `level1b_candidate_response_surface.py:296-309`).

| rank | candidate_id | real baseline/source parameters exported by Step-9a | medoid parameters exported in ranked row |
|---:|---|---|---|
| 1 | `ref_fullrange_r3p88m_px078` | `scale_id=r3p88m_px078`; `radius_m=3.875`; `area_m2=47.17297718905924`; `spatialr_px=78`; `minsize_px=18884`; `ranger=0.7050695405472065`; `ranger_id=ref_fullrange_ranger_004`; `ranger_source=knn_distance_quantile`; `assignment_rule=ordered_scale_candidates_assigned_ordered_knn_distance_quantiles_with_tail_padding`; baseline offsets all zero; baseline `run_spatial_radius_m=3.898464625649877` (`run_population_summary.csv:47`) | `medoid_run_id=ref_fullrange_r3p88m_px078__baseline`; `spatial_radius_m=3.898464625649877`; `minsize=18884`; `ranger=0.7050695405472065`; offsets all zero (`ranked_candidate_scales.csv:2`) |
| 2 | `ref_fullrange_r0p2m_px004` | `scale_id=r0p2m_px004`; `radius_m=0.2`; `area_m2=0.12566370614359174`; `spatialr_px=4`; `minsize_px=50`; `ranger=0.3540343190487846`; `ranger_id=ref_fullrange_ranger_001`; same exported ranger source/assignment rule; baseline offsets all zero; baseline `run_spatial_radius_m=0.19992126285383985` (`run_population_summary.csv:2`) | `medoid_run_id=ref_fullrange_r0p2m_px004__perturb_001`; `spatial_radius_m=0.1499409471403799`; `minsize=50`; `ranger=0.3540343190487846`; `spatialr_px_delta=-1`, other offsets zero (`ranked_candidate_scales.csv:3`) |
| 3 | `ref_fullrange_r0p36m_px007` | `scale_id=r0p36m_px007`; `radius_m=0.3618081437156948`; `area_m2=0.41125060370702043`; `spatialr_px=7`; `minsize_px=165`; `ranger=0.43154683209316597`; `ranger_id=ref_fullrange_ranger_002`; same exported ranger source/assignment rule; baseline offsets all zero; baseline `run_spatial_radius_m=0.34986220999421974` (`run_population_summary.csv:11`) | `medoid_run_id=ref_fullrange_r0p36m_px007__perturb_001`; `spatial_radius_m=0.2998818942807598`; `minsize=165`; `ranger=0.43154683209316597`; `spatialr_px_delta=-1`, other offsets zero (`ranked_candidate_scales.csv:4`) |
| 4 | `ref_fullrange_r0p65m_px013` | `scale_id=r0p65m_px013`; `radius_m=0.6545256642949843`; `area_m2=1.3458703729152541`; `spatialr_px=13`; `minsize_px=539`; `ranger=0.5469669888407498`; `ranger_id=ref_fullrange_ranger_003`; same exported ranger source/assignment rule; baseline offsets all zero; baseline `run_spatial_radius_m=0.6497441042749795` (`run_population_summary.csv:20`) | `medoid_run_id=ref_fullrange_r0p65m_px013__perturb_001`; `spatial_radius_m=0.5997637885615196`; `minsize=539`; `ranger=0.5469669888407498`; `spatialr_px_delta=-1`, other offsets zero (`ranked_candidate_scales.csv:5`) |
| 5 | `ref_fullrange_r1p18m_px024` | `scale_id=r1p18m_px024`; `radius_m=1.1840635780642512`; `area_m2=4.404533499436473`; `spatialr_px=24`; `minsize_px=1763`; `ranger=0.7050695405472065`; `ranger_id=ref_fullrange_ranger_004`; same exported ranger source/assignment rule; baseline offsets all zero; baseline `run_spatial_radius_m=1.1995275771230391` (`run_population_summary.csv:29`) | `medoid_run_id=ref_fullrange_r1p18m_px024__baseline`; `spatial_radius_m=1.1995275771230391`; `minsize=1763`; `ranger=0.7050695405472065`; offsets all zero (`ranked_candidate_scales.csv:6`) |
| 6 | `ref_fullrange_r2p14m_px043` | `scale_id=r2p14m_px043`; `radius_m=2.142019226103952`; `area_m2=14.414401073140846`; `spatialr_px=43`; `minsize_px=5770`; `ranger=0.7050695405472065`; `ranger_id=ref_fullrange_ranger_004`; same exported ranger source/assignment rule; baseline offsets all zero; baseline `run_spatial_radius_m=2.1491535756787785` (`run_population_summary.csv:38`) | `medoid_run_id=ref_fullrange_r2p14m_px043__perturb_001`; `spatial_radius_m=2.0991732599653186`; `minsize=5770`; `ranger=0.7050695405472065`; `spatialr_px_delta=-1`, other offsets zero (`ranked_candidate_scales.csv:7`) |

The scoring diagnosis uses the exact formula in section 7. Boolean values below are output fields, not inferred conditions (`ranked_candidate_scales.csv:1-7`).

| rank | candidate_id | center | spread | lower mean | central mean | upper mean | outcome | score | source-rule diagnosis |
|---:|---|---:|---:|---:|---:|---:|---|---:|---|
| 1 | `ref_fullrange_r3p88m_px078` | 1.7903489623997577 | 2.1842483147742042 | 0.0 | 0.580621862450601 | 0.41937813754939923 | `scale_jump_detected` | 0.3218860997478801 | Output flags are edge=false, scale-jump=true, flutter=true, spatial-jump=true. Pre-clamp score is `1 - 0 - .35 - .2 - .2 + .5*0.580621862450601 - .1*2.1842483147742042 = 0.3218860997478801`, so it remains positive. Outcome is scale-jump because that check precedes score-based outcome checks (`ranked_candidate_scales.csv:2`; `level1b_candidate_response_surface.py:954-976`). |
| 2 | `ref_fullrange_r0p2m_px004` | 1.8437079074013365 | 36.577057322942444 | 0.0 | 0.5217826243673241 | 0.47821737563267575 | `scale_jump_detected` | 0.0 | Flags edge=false, scale-jump=true, flutter=true, spatial-jump=true yield pre-clamp `-3.1468144201105828`; `max(0, ...)` sets zero (`ranked_candidate_scales.csv:3`; `level1b_candidate_response_surface.py:954-967`). |
| 3 | `ref_fullrange_r0p36m_px007` | 3.007412979659883 | 87.05980837973527 | 0.00000045944123384669055 | 0.3941496703105736 | 0.6058498702481927 | `scale_jump_detected` | 0.0 | All four penalty flags are true; pre-clamp score is `-8.608906002818241`, so it clamps to zero (`ranked_candidate_scales.csv:4`; `level1b_candidate_response_surface.py:954-967`). |
| 4 | `ref_fullrange_r0p65m_px013` | 5.522587324593782 | 63.389690358249574 | 0.00000019050002379009123 | 0.2896806674995328 | 0.7103191420004435 | `scale_jump_detected` | 0.0 | All four penalty flags are true; pre-clamp score is `-6.2941287020751915`, so it clamps to zero (`ranked_candidate_scales.csv:5`; `level1b_candidate_response_surface.py:954-967`). |
| 5 | `ref_fullrange_r1p18m_px024` | 4.676160296448773 | 25.313637312105875 | 0.0 | 0.24103228421832584 | 0.7589677157816741 | `scale_jump_detected` | 0.0 | Edge, scale-jump, and spatial-jump are true; flutter is false. Pre-clamp score is `-2.310847589101425`, so it clamps to zero (`ranked_candidate_scales.csv:6`; `level1b_candidate_response_surface.py:954-967`). |
| 6 | `ref_fullrange_r2p14m_px043` | 2.059248719757732 | 3.1243806202662174 | 0.000010298207168417284 | 0.45933087830349734 | 0.5406588234893343 | `scale_jump_detected` | 0.0 | All four penalty flags are true; pre-clamp score is `-0.1827726228748731`, so it clamps to zero (`ranked_candidate_scales.csv:7`; `level1b_candidate_response_surface.py:954-967`). |

## 9. Candidate Regime Evidence

The existing outputs show these data regimes without implying any later selection:

- Two candidates have `central_area_share_mean > 0.5` and `response_center_q` between 0.5 and 2.0: the rows ranked first and second. Their upper-tail means are 0.41937813754939923 and 0.47821737563267575, respectively (`ranked_candidate_scales.csv:2-3`). The source's `centered` definition requires both conditions (`level1b_candidate_response_surface.py:416`).
- Four candidates have central mean below 0.5 and upper-tail mean above central mean; their output fields mark `upper_tail_dominated=True` (`ranked_candidate_scales.csv:4-7`; source definition at `level1b_candidate_response_surface.py:417-418`).
- Lower-tail means are zero or near zero across all six candidates, while the central/upper allocation changes materially across rows (`ranked_candidate_scales.csv:2-7`).
- Response spread separates into two comparatively small observed values (2.1842483147742042 and 3.1243806202662174) and four much larger observed values (25.313637312105875 through 87.05980837973527) (`ranked_candidate_scales.csv:2-7`). All six exceed this run's `max_response_spread_q=1.5`, and all rows record `unstably_spread=True` (`candidate_response_surface_report.json:61`; `ranked_candidate_scales.csv:2-7`; flag expression at `level1b_candidate_response_surface.py:425`).
- Every candidate records `scale_jump_flag=True` and `candidate_outcome=scale_jump_detected`; only one retains a positive arithmetic score (`ranked_candidate_scales.csv:2-7`). This follows the distinct scoring and outcome rules in `stability_score` and `classify_candidate_outcome` (`level1b_candidate_response_surface.py:954-976`).

No anchor, interval, fallback, transition, or later-run decision is made by this description.

## 10. Parameter Completeness for Possible Future Step-9b

For every existing candidate group, the collective Step-9a outputs contain the complete real parameter tuple consumed by the Step-8 perturbation/Step-9a segmentation rows: `candidate_id`/`source_candidate_id`, `scale_id`, `radius_m`, `spatialr_px`, `minsize_px`, and `ranger`; they also preserve `area_m2`, `ranger_id`, `ranger_source`, `assignment_rule`, baseline status, perturbation ID, and parameter offsets in `original_row_metadata` (`run_population_summary.csv:1-2,11,20,29,38,47`; construction at `level1b_perturbations.py:134-190`; Step-9a export at `level1b_candidate_response_surface.py:274-309,1228-1261`). Thus these fields do not have to be recovered from candidate names.

The ranked and group files are not self-contained parameter tables. Specifically, both omit source `candidate_id`, `source_candidate_id`, `source_scale_id`, `radius_m`, `area_m2`, `spatialr_px`, `minsize_px`, source `ranger`, `ranger_id`, `ranger_source`, `assignment_rule`, baseline status, baseline perturbation ID, and baseline offsets; their only parameter object is `medoid_parameters`, which describes the selected medoid run (`candidate_group_response_summary.csv:1`; `ranked_candidate_scales.csv:1`; `level1b_candidate_response_surface.py:459-502`). Those omitted source fields are present in `run_population_summary.csv`, so a source-key join is required to associate a ranked group with its baseline/source parameters (`run_population_summary.csv:1-2,11,20,29,38,47`).

Fields generated earlier but not passed through to the Step-8/Step-9a run summaries are `scale_index`, `scale_mode`, `scale_source`, `pixel_size_m`, `pixel_area_m2`, `coupling_rule`, and the optional structure-specific metadata declared in `ROW_FIELDS` (`level1b_scale_distribution.py:20-49`). The reason is explicit: the perturbation reader preserves required fields plus only `radius_m`, `area_m2`, `ranger_id`, `ranger_source`, and `assignment_rule` (`level1b_perturbations.py:9-11,134-163`). Consequently, those earlier fields are missing from all three inspected Step-9a CSVs (`run_population_summary.csv:1`; `candidate_group_response_summary.csv:1`; `ranked_candidate_scales.csv:1`).

Whether any of those missing earlier-stage fields would be required by a future Step-9b is not determinable: no Step-9b source or parameter contract was inspected or present in the allowed evidence. This audit therefore makes no Step-9b selection or execution decision.

## 11. Missing Information

- No source-level Step-9b parameter contract exists in the inspected allowed source, so the exact fields a possible future Step-9b would require are not determinable from this audit (`metashape_qc_engine/level1b_candidate_response_surface.py` ends its active workflow by writing Step-9a outputs at lines 911-938).
- `ranked_candidate_scales.csv` and `candidate_group_response_summary.csv` do not state the source candidate's baseline parameter tuple; it must be obtained from `run_population_summary.csv` as described in section 10 (`ranked_candidate_scales.csv:1`; `candidate_group_response_summary.csv:1`; `run_population_summary.csv:1`).
- Direct `pixel_size_m`, `pixel_area_m2`, `scale_index`, `scale_mode`, `scale_source`, `coupling_rule`, and structure-specific generation metadata are not present in the three inspected Step-9a CSV schemas (`run_population_summary.csv:1`; `candidate_group_response_summary.csv:1`; `ranked_candidate_scales.csv:1`).
- The outputs establish observed metrics and the current source establishes their computation, but neither establishes whether a later refinement should run; no such decision is made here (`level1b_candidate_response_surface.py:911-938`).

## 12. No-Change Confirmation

No repository file was modified by this audit. No file was staged or committed, and no branch was created. No workflow, test, segmentation, OTB command, or raster-processing command was run. The only created file is this required audit report at `/home/creu/tmp/step9a_score_gate_audit.md`, outside the repository.
