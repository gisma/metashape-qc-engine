# Rationale and Paper Argument Register

## Status

[DESIGN DECISION] This file is an argument register. It is not the operational manual and not implementation truth. Implementation truth belongs to the code, config, presets, runner, analyzer, and evaluator. This file separates paper-relevant rationale from the technical reference.

## Core thesis

[HYPOTHESIS] A single successful Metashape orthomosaic run is not enough evidence for difficult UAV RGB products. Product selection should be based on repeated processing, support persistence, continuous stability, threshold-based quality flags, and an explicit selected-product trace.

[IMPLEMENTED] The current workflow implements repeated product analysis, manifest history, orthomosaic stability analysis, support diagnostics, threshold review, and `selected_product.json`.

## Why reproducibility matters

[HYPOTHESIS] Photogrammetric orthomosaics can look complete after one run while still containing processing-dependent artifacts, variable spatial support, seamline instability, or projection-surface effects. A single successful export proves that one processing path completed; it does not prove that the product is stable, accurate, or suitable for downstream interpretation.

[CODE-DERIVED] The analyzer treats repeated outputs as comparable samples from the processing procedure. It aligns successful orthomosaics to a canonical grid and measures support persistence and image-value deviation from the per-variant median orthomosaic.

## Product analysis instead of parameter experiment

[DESIGN DECISION] The workflow is framed as product analysis and candidate selection rather than only as a parameter experiment. The practical question is which tested candidate should be carried forward for review and use, not whether one parameter is universally optimal.

[IMPLEMENTED] The evaluator ranks candidates, writes compact TSVs, writes an evaluation report, and records a selected-product trace. The selected product is the best available candidate under the implemented ranking within the tested parameter space.

## Evidence layers

[IMPLEMENTED] Repeated runs provide replicate evidence for each candidate.

[IMPLEMENTED] Manifest history records every candidate/replicate execution with status, paths, return code, and elapsed time.

[CODE-DERIVED] Support persistence measures whether valid orthomosaic support is retained across replicates inside the actual supported footprint.

[CODE-DERIVED] Continuous stability is represented by MAD and RMSE-to-median metrics, including mean and 95th percentile summaries.

[CODE-DERIVED] RMSE/MAD to the median orthomosaic gives an internal repeated-build consistency measure, not an external accuracy measure.

[IMPLEMENTED] Threshold quality flags convert RMSE-to-median rasters into review masks for configured thresholds.

[IMPLEMENTED] `selected_product.json` records the selected continuous-stability candidate, support-persistence context, threshold-guard context, product modes, source files, and warnings.

[IMPLEMENTED] QGIS launchers collect key raster review layers for selected-product and threshold review.

## MOF reference benchmark rationale

[DESIGN DECISION] MOF is the current reference benchmark because it is controlled enough for implementation development and demanding enough for forest orthomosaic products.

[BOUNDARY EVIDENCE] Existing project notes describe the MOF RGB dataset as 48 UAV RGB images of a forest terrain knoll with beech and Douglas fir. The local reference image directory contains 48 supported images.

[IMPLEMENTED] The current MOF reference preset is `config/experiments/presets/mof_alignment_mesh_ortho_reference_v1.json`.

[CODE-DERIVED] The MOF reference matrix tests Alignment-Mesh-Ortho sensitivity by varying alignment downscale, adaptive fitting, mesh face count, mesh smoothing iterations, and requested orthomosaic pixel size.

[CODE-DERIVED] The matrix expands to 48 candidates. With 5 replicates, it implies 240 Metashape runs.

[NON-SCOPE] No completed MOF result claims should be made unless run outputs and evaluation products are present and inspected.

## Franzosenwiese boundary-case rationale

[BOUNDARY EVIDENCE] Franzosenwiese is useful as a boundary/stress case. It can illustrate where the procedure produces warnings, candidate disagreement, or high review burden.

[NON-SCOPE] Franzosenwiese is not the current reference benchmark and should not be converted into change-detection suitability logic.

[HYPOTHESIS] A boundary case may still produce a selected candidate, but the selected candidate can carry high warning conditions and require stronger domain review.

## Requested orthomosaic pixel size

[CODE-DERIVED] `buildOrthomosaic.orthoRes` is passed into Metashape as the requested orthomosaic build resolution.

[DESIGN DECISION] In the paper argument, requested pixel size should be treated as a sampling or product-resolution choice. It should not be described as a direct measure of geometric accuracy or true scene detail.

[NON-SCOPE] The workflow does not prove that smaller `orthoRes` is more accurate.

## Why Dense/Depth-Map/DSM are excluded here

[CODE-DERIVED] The current MOF reference variant template disables `buildDepthMaps.enabled`, `buildPointCloud.enabled`, and `buildDem.enabled`, while enabling mesh-based orthomosaic production.

[DESIGN DECISION] The current MOF reference matrix is Orthomosaic/Alignment-Mesh-Ortho only. Excluding Dense/Depth-Map/DSM products is scope control for this benchmark, not a universal claim that those products are never useful.

[NON-SCOPE] Dense-cloud quality, depth-map quality, DSM/DEM quality, 3D reconstruction quality, and building reconstruction quality are not evaluated in this benchmark.

## Interpretation limits

[NON-SCOPE] Selected product means best available candidate within the tested parameter space and implemented selection policy.

[NON-SCOPE] Stability is not absolute accuracy.

[NON-SCOPE] Internal reproducibility is not external truth.

[NON-SCOPE] Quality flags are interpretation guards, not image cleaning.

[NON-SCOPE] Change-detection suitability is not established yet.

[NON-SCOPE] Cross-date accuracy is not established yet.

[NON-SCOPE] Platform comparison is not established yet.

## Paper direction

[INFERRED] Possible title directions:

- Repeated-build orthomosaic product selection for UAV forest RGB imagery
- Support-aware reproducibility analysis for Metashape orthomosaic candidates
- From single export to selected product: reproducible UAV orthomosaic candidate selection

[INFERRED] Problem statement: difficult forest UAV orthomosaics can be sensitive to processing choices and repeated-build variability; a single successful export hides support loss and image-value instability.

[IMPLEMENTED] Contribution: a practical workflow that prepares candidate matrices, runs repeated Metashape builds, records manifest history, computes support and stability products, ranks candidates, writes threshold review layers, and emits a selected-product trace.

[INFERRED] Expected methods section structure:

1. Dataset and benchmark scope.
2. Candidate matrix and replicate design.
3. Metashape mesh orthomosaic processing path.
4. Manifest and execution tracking.
5. Canonical-grid stability analysis.
6. Support persistence and threshold flags.
7. Candidate ranking and selected-product trace.
8. Interpretation limits.

[INFERRED] Expected results types:

- Manifest completion table.
- Candidate stability summary.
- Support valid-count histograms.
- Median orthomosaic, RMSE-to-median, and valid-count maps.
- Threshold sensitivity table.
- Candidate disagreement warnings.
- Selected-product JSON trace examples.

[INFERRED] Possible figures/tables:

- Workflow diagram from prepare to selected-product trace.
- MOF candidate matrix table.
- Stability metric ranking table.
- Support-persistence comparison table.
- Example raster panels: median orthomosaic, valid count, RMSE-to-median, quality flag.
- Threshold sensitivity plot or table.
- Selected-product trace excerpt.

[INFERRED] Candidate abstract skeleton:

Single-run UAV orthomosaics can conceal processing-dependent variability, especially in forest imagery where projection surfaces and alignment settings affect support and local image values. We present a product-analysis workflow for Agisoft Metashape that evaluates candidate orthomosaic products using repeated processing, manifest-tracked execution, canonical-grid stability analysis, support persistence, and threshold-based quality flags. The workflow ranks candidates by continuous stability while preserving support and threshold diagnostics as interpretation guards, and writes an explicit selected-product trace. The current MOF reference benchmark tests an Alignment-Mesh-Ortho matrix for RGB forest imagery without claiming absolute geometric accuracy or change-detection suitability. This separates internal reproducibility evidence from external validation needs.

## Future work

[FUTURE WORK] Add platform comparison after the MOF reference analysis is complete.

[FUTURE WORK] Add GCP/checkpoint and cross-date validation as separate evidence layers.

[FUTURE WORK] Add suitability and change-detection guards only after the MOF reference analysis establishes the internal reproducibility baseline.

[FUTURE WORK] Consider Dense/Depth-Map/DSM benchmark extensions when the orthomosaic reference benchmark is stable.

[FUTURE WORK] Consider a Metashape GUI/menu adapter around the existing CLI and file contract.

[FUTURE WORK] Consider an AM2/R adapter later around the same contract, rather than changing the core implementation first.

## Material to mine from existing docs

[INFERRED] `README.md`: mine current high-level framing, active command sequence, repository layout, and frontend direction. Do not treat it as implementation truth without code confirmation.

[INFERRED] `WORKFLOW_CHAIN.md`: mine current workflow narrative, runtime order, active schema explanation, and known caveats. Do not treat it as implementation truth without code confirmation.

[INFERRED] `docs/quick_workflow.md`: mine user-facing terminology and concise product workflow language. Do not treat it as implementation truth without code confirmation.

[INFERRED] `docs/orthomosaic_stability_manual.md`: mine explanation of stability metrics, support interpretation, threshold flags, and selected-product review. Do not treat it as implementation truth without code confirmation.

[INFERRED] `docs/product_manifest_contract.md`: mine manifest, selected-product, threshold-review, and medoid terminology. Do not treat it as implementation truth without code confirmation.

[INFERRED] `config/experiments/README.md`: mine preset rationale, MOF matrix description, and explicit non-scope boundaries. Confirm matrix details against preset and CSV files.

[INFERRED] `docs/audit/REPRODUCIBILITY_STABILITY_ANALYSIS_PLAN.md`: mine rationale for repeated-build stability and forest orthomosaic hypotheses. Keep hypothesis language explicit.

[INFERRED] `docs/audit/UPSTREAM_AND_METASHAPETOOLS_INTEGRATION_PLAN.md`: mine future-work context for GUI, upstream integration, and MetashapeTools-related ideas. Do not present planned items as implemented.

[INFERRED] `docs/zwischenbericht.qmd`: mine paper framing, MOF dataset description, and candidate figure/table ideas. Do not claim completed results from it unless corresponding run outputs are present and inspected.

[INFERRED] `docs/upstream/README_automate_metashape_upstream.md`: mine attribution and upstream workflow background only. Do not treat upstream behavior as active current implementation.
