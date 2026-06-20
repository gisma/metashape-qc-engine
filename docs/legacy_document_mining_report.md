# Legacy Document Mining Report

## Status

This file is a mining/report document. It is not an operational manual, not a replacement for the current reference layers, and not implementation truth.

It does not modify `docs/current_system_reference.md` or `docs/rationale_and_paper_argument_register.md`. It prepares later rewrite, deprecation, and archival decisions by identifying useful legacy material, contradictions, stale instructions, and content that needs human approval before being promoted.

## Reference basis

`docs/current_system_reference.md` is the code-derived technical reference for the current implementation. It summarizes the implemented CLI, preparation layer, runner, resume behavior, manifest, analyzer, evaluator, selected-product trace, QGIS review artifacts, and runtime YAML schema. Claims intended for active operational documentation should be supported by code, config, preset, CSV, or runtime behavior and should match this file unless a later code/config inspection proves it needs correction.

`docs/rationale_and_paper_argument_register.md` is the methodological and scientific argument register. It separates rationale, paper framing, interpretation limits, future work, boundary evidence, and hypotheses from implementation truth. It uses explicit status markers such as `[IMPLEMENTED]`, `[CODE-DERIVED]`, `[INFERRED]`, `[HYPOTHESIS]`, `[BOUNDARY EVIDENCE]`, `[FUTURE WORK]`, and `[NON-SCOPE]`.

## Executive diagnosis

The two current reference layers already cover the most important split: current implementation truth belongs to code/config-derived reference material, while scientific rationale and paper argument belong in a separate register with status markers. They also cover the active CLI surface, run-directory framing, manifest/status semantics, analyzer/evaluator outputs, current MOF reference preset, Dense/Depth-Map/DSM non-scope, Franzosenwiese boundary status, and the limits of selected-product interpretation.

Older documents still contain additional value. The strongest material is explanatory: why orthomosaics are synthetic products, why repeated-build stability matters, how support persistence should be read, why threshold flags are guards rather than cleaning steps, how the recovered procedural runner differs from upstream class-based assumptions, and how MetashapeTools influenced the mesh-based Ortho+ route.

Older documents are operationally dangerous where they present legacy commands, direct script calls, `--experiment-dir` terminology, `metashape-qc experiment` as the main path, historical starter matrices, Dense/DSM variants, old upstream setup instructions, or completed MOF smoothing results as if they were current benchmark truth. These should not survive into active docs without rewrite.

Before any deprecation or move, mine the methodological reasoning, recovery decisions, upstream/MetashapeTools comparison, support-aware evaluator explanations, MOF dataset framing, Franzosenwiese stress-case framing, selected-product contract language, and paper-relevant fragments.

Nothing should be automatically deleted. Audit files, upstream background, German working reports, old manuals, and stale operational instructions all contain trace evidence. Some should later get status headers or move to history/deprecated only after human approval and after useful content has been extracted.

## Document-by-document mining table

| file | current role | content status | useful content to mine | contradictions with current_system_reference.md | useful paper/rationale content | recommended later treatment | human approval required |
|---|---|---|---|---|---|---|---|
| `README.md` | Active repository overview and entry point | active but needs rewrite | High-level product-oriented workflow, repository layout, attribution, future frontend direction | Uses `mesh_facecount_smoothing_3x3.json` in primary example instead of MOF reference preset; older starter framing may be mistaken for current benchmark | Product-oriented framing and selected-product trace caveat | rewrite active | yes |
| `WORKFLOW_CHAIN.md` | Active workflow narrative | mixed | Procedural runtime order, active flat/camelCase schema explanation, upstream schema warning, YAML parser notes | Calls `mesh_facecount_smoothing_3x3.json` active starter preset; detailed function order includes steps omitted/simplified in current reference; uses legacy R/config generation as active context | Recovery logic for procedural runner and schema separation | rewrite active | yes |
| `config/README.md` | Configuration directory overview | active operational | Simple distinction between reference config, experiments, legacy config | None material; brief enough but could point to reference layers | Minimal | keep active | no |
| `config/legacy/README.md` | Legacy config status note | technical reference | Clear warning that legacy configs are reference material, not defaults | None | Historical preservation framing | keep active | no |
| `config/experiments/README.md` | Active product-analysis and MOF preset doc | active operational | Excellent MOF reference matrix summary, prepare inputs, Dense/DSM non-scope, suitability/change-detection non-scope | Still uses `mesh_facecount_smoothing_3x3.json` as current preset before MOF reference section; may imply two active defaults | MOF matrix rationale and bounded reference benchmark language | rewrite active | yes |
| `docs/quick_workflow.md` | Concise active workflow | active operational | Best concise user-facing terminology for product, product analysis, run directory, variant, replicate, selected candidate | Uses `mesh_facecount_smoothing_3x3.json` example; selected candidate wording should align with best candidate within tested space | Good product-analysis vocabulary | rewrite active | yes |
| `docs/orthomosaic_stability_manual.md` | Long workflow manual | mixed | Canonical grid explanation, metric interpretation, threshold flag language, evaluator dependency notes | Uses `experiment directory`; direct `python3` script calls; `metashape-qc experiment`; old 3-variant matrices; old MOF paths; single-run stage as standard workflow | Good explanation that stability is not geometric correctness | mine then archive or rewrite active as shorter manual | yes |
| `docs/orthomosaic_stability_manual_AI.md` | Older extended AI/manual draft | mixed | Dataset organization safety rules, no-delete rule, physical image-copy discussion, MOF/Franzosenwiese roles, crash diagnosis for polluted `photo_path`, threshold reporting | Presents old experimental axes and variants including `dense_dsm`; script-level `--experiment-dir`; historical default roles | Strong synthetic-product argument, forest regularization hypothesis, support interpretation | mine then archive | yes |
| `docs/orthomosaic_stability_reference.md` | Parameter appendix for old manual | technical reference / stale operational instruction | YAML parameter descriptions, summary column meanings, manifest status explanations | Old example config, old variant CSVs, direct analyzer calls, `experiment_dir` wording; not aligned to current MOF reference preset | Good definitions of support and RMSE/MAD columns | mine then archive | yes |
| `docs/product_manifest_contract.md` | Active contract doc | active but needs rewrite | Strong manifest/evaluator/selected-product terminology, medoid explanation, threshold review contract | Uses `<experiment_dir>` throughout where current reference prefers run directory; says stable image values are primary requirement for change detection, conflicting with change-detection non-scope | Product trace as technical review artifact | rewrite active | yes |
| `docs/metashape_runtime_setup.md` | Runtime setup note | active operational | Metashape runtime dependency separation, `python/vendor/`, evaluator dependency warnings, GDAL array troubleshooting | Old test commands use Franzosenwiese config; could imply old direct single-run path is the main workflow | Implementation warning material | add status header or rewrite active | yes |
| `docs/zwischenbericht.qmd` | Archived German working report | historical reasoning | MOF dataset description, support-aware metric interpretation, architecture shift to Python core, paper fragments | Contains completed smoothing-only MOF result claims and `noiterations=35` default interpretation; old CLI shape; must not become current MOF results | Strong paper framing, support interpretation, parameter-space limitations | keep as history after mining | yes |
| `docs/audit/AUDIT_FULL_WORKFLOW.md` | Recovery audit | audit/recovery evidence | Original recovery findings, upstream/fork comparison, MetashapeTools overlap, repair decisions | Describes an earlier broken checkout state now repaired; must not be read as current implementation truth | Code recovery story and integration rationale | keep as history with status header | yes |
| `docs/audit/REPRODUCIBILITY_STABILITY_ANALYSIS_PLAN.md` | Development plan | historical reasoning | Early repeated-build rationale, forest orthomosaic hypothesis, planned stability products | Includes `dense_dsm` as initial variant and future analyzer language that is now partly implemented or out of current MOF scope | Excellent hypothesis wording for paper register | mine then archive | yes |
| `docs/audit/UPSTREAM_AND_METASHAPETOOLS_INTEGRATION_PLAN.md` | Integration plan | audit/recovery evidence | Upstream innovations, destructive changes, MetashapeTools mapping, future GUI/diagnostics ideas | Assumes branch/state and immediate implementation targets that are no longer current active truth; says do not integrate upstream class workflow in that phase | Future-work constraints and design rationale | keep as history with status header | yes |
| `docs/upstream/README_automate_metashape_upstream.md` | Archived upstream README | upstream background | Attribution, original automate-metashape purpose, cluster/batch context, old GCP prep background | Old Python/Metashape versions, `config/example.yml`, R scripts, upstream folder rules, cluster commands; not active current workflow | Upstream comparison and provenance | keep as history | yes |

## Missing or underdeveloped content in current_system_reference.md

| source file | missing content | why it matters | code-supported | exact target section in `current_system_reference.md` | human approval required |
|---|---|---|---|---|---|
| `docs/metashape_runtime_setup.md` | Metashape runtime dependency split: Metashape runtime for workflow, local `python/vendor/`, evaluator dependency environment, GDAL array import requirement | Users need to know why system Python can run evaluator but Metashape workflow needs Metashape runtime | Partly; wrapper scripts and install scripts should be verified before adding exact commands | `Runtime workflow schema` or new `Runtime environments` | yes |
| `docs/orthomosaic_stability_manual_AI.md` | Safe input-image folder rule and no-delete rule | Prevents destructive setup patterns and polluted `photo_path` runs | Partly; prepare validates image dir and image suffixes, but no-delete is policy rather than code | `Prepare stage` or new `Operational safety boundaries` | yes |
| `docs/orthomosaic_stability_manual_AI.md` | Crash diagnostic: unexpectedly high photo numbers indicate polluted image folder | Useful implementation warning for Metashape failures | Not directly code-supported; log-pattern operational evidence | new `Troubleshooting notes` | yes |
| `WORKFLOW_CHAIN.md` | More detailed direct function order including region resets, secondary photos, report export, finish log | Current reference gives a simplified order and omits some procedural calls | Code-supported if rechecked against `python/metashape_workflow.py` | `Runtime workflow schema` | yes |
| `docs/orthomosaic_stability_reference.md` | Summary column definitions for `any_support_fraction_grid`, `full_support_fraction_grid`, `variable_support_fraction_grid`, `support_persistence_footprint`, `support_dropout_footprint` | Current reference names metrics but could define support ratios more explicitly | Code-supported by evaluator support metric computation | `Evaluation stage` or `Analyzer/stability products` | no |
| `docs/product_manifest_contract.md` | Detailed medoid mode explanation and nonfatal medoid warnings | Current reference mentions medoid but could carry the practical fallback semantics | Code-supported by evaluator | `Selection logic` | no |
| `docs/product_manifest_contract.md` | Threshold review file contract, values 0/1/2, and non-cleaning warning | Current reference lists threshold artifacts but could expose the value semantics | Code-supported by evaluator threshold review | `Evaluation stage` or `QGIS review artifacts` | no |
| `config/experiments/README.md` | Fixed columns in MOF template not varied in v1, and excluded inactive controls such as keypoint/tiepoint/guided matching | Prevents users from assuming untested sensitivity axes | Code/config-supported by preset and CSV templates | `Prepare stage` or MOF-specific note under `Scope` | yes |

Do not edit `docs/current_system_reference.md` as part of this mining report.

## Missing or underdeveloped content in rationale_and_paper_argument_register.md

| source file | missing content | why it matters | status marker it would need | exact target section in `rationale_and_paper_argument_register.md` | human approval required |
|---|---|---|---|---|---|
| `docs/orthomosaic_stability_manual_AI.md` | Orthomosaic as synthetic photogrammetric product: overlapping images, alignment, tie points, projection surface, seamlines, blending, export settings | Stronger problem statement for why repeated-build stability is needed | `[HYPOTHESIS]` or `[INFERRED]` | `Why reproducibility matters` | yes |
| `docs/audit/REPRODUCIBILITY_STABILITY_ANALYSIS_PLAN.md` | Forest regularization hypothesis: stronger projection-surface regularization may improve reproducibility while reducing local detail | Paper-relevant hypothesis that explains mesh smoothing/face-count axes | `[HYPOTHESIS]` | `MOF reference benchmark rationale` or new `Forest orthomosaic hypothesis` | yes |
| `docs/zwischenbericht.qmd` | Support-aware interpretation: grid fractions can be misleading; footprint-based dropout is clearer | Important methodological explanation for support metrics | `[INFERRED]` plus `[CODE-DERIVED]` for implemented metrics | `Evidence layers` | yes |
| `docs/zwischenbericht.qmd` | Parameter-space limitation: smoothing-only or partial matrices do not justify global optimization claims | Useful guardrail for results discussion | `[NON-SCOPE]` | `Interpretation limits` | no |
| `docs/orthomosaic_stability_manual_AI.md` | MOF as good but demanding low-budget UAV RGB/geolocation benchmark | Strengthens benchmark framing without claiming results | `[BOUNDARY EVIDENCE]` | `MOF reference benchmark rationale` | yes |
| `docs/orthomosaic_stability_manual_AI.md` | Franzosenwiese as workflow/stress/canonical-grid/mask testing dataset, not forest benchmark | Supports current boundary-case distinction | `[BOUNDARY EVIDENCE]` | `Franzosenwiese boundary-case rationale` | no |
| `docs/audit/UPSTREAM_AND_METASHAPETOOLS_INTEGRATION_PLAN.md` | MetashapeTools as algorithm/reference source, not direct dependency; GUI adapter as future frontend | Preserves integration rationale without presenting it as implemented | `[FUTURE WORK]` | `Future work` | no |
| `docs/upstream/README_automate_metashape_upstream.md` | Original upstream goal: reproducible automated Metashape batch/cluster workflows | Attribution and lineage for methods/background | `[INFERRED]` or `[BOUNDARY EVIDENCE]` | new provenance/background subsection | yes |
| `docs/product_manifest_contract.md` | Selected-product trace is a technical review artifact with warnings, not scientific correctness | Already present but can be made more paper-ready | `[IMPLEMENTED]` and `[NON-SCOPE]` | `Product analysis instead of parameter experiment` / `Interpretation limits` | no |

Do not edit `docs/rationale_and_paper_argument_register.md` as part of this mining report.

## Contradictions requiring later rewrite

| contradiction | where it appears | current reference truth | risk if left unresolved | later action required |
|---|---|---|---|---|
| Old CLI names vs current CLI | `docs/orthomosaic_stability_manual.md`, `docs/orthomosaic_stability_manual_AI.md`, `docs/orthomosaic_stability_reference.md`, `docs/zwischenbericht.qmd` | Current path is `metashape-qc prepare`, `run-analysis`, `resume-analysis`, `evaluate`; `run`, `experiment`, and `analyze` are legacy/direct wrappers | Users may run lower-level scripts or legacy wrappers and bypass current product workflow | Rewrite active docs to current CLI; keep legacy names only as compatibility notes |
| `experiment directory` vs `run directory` | `docs/orthomosaic_stability_manual.md`, `docs/product_manifest_contract.md`, older audit docs | Current user-facing term is run directory; `--experiment-dir` remains legacy alias | Confuses output container, manifests, and selected-product paths | Replace in active docs; preserve historical wording in archived docs |
| `product experiment` vs `product analysis` | README examples, config docs, old manuals | Current framing is product analysis and selected candidate within tested space | Reinforces parameter-experiment framing rather than product selection | Normalize active docs to product analysis |
| `mesh_facecount_smoothing_3x3` as starter/current preset vs MOF reference matrix | README, `WORKFLOW_CHAIN.md`, `config/experiments/README.md`, `docs/quick_workflow.md` | Current MOF reference preset is `mof_alignment_mesh_ortho_reference_v1.json`; old starter preset still exists but is not the reference benchmark | Users may run 9-candidate starter matrix and treat it as current MOF benchmark | Recast starter preset as example/legacy starter or remove from primary path after approval |
| Dense/Depth-Map/DSM assumptions vs current MOF Alignment-Mesh-Ortho scope | `REPRODUCIBILITY_STABILITY_ANALYSIS_PLAN.md`, older manuals and reference | Current MOF reference disables depth maps, point cloud, and DEM; Dense/DSM quality is non-scope | Readers may interpret Dense/DSM variants as current benchmark | Move Dense/DSM to future-work/history language |
| Change-detection or suitability implications vs explicit non-scope | `docs/product_manifest_contract.md`, older rationale/manual wording | Change-detection suitability is not established; selected product is not scientific truth | Overclaims downstream use | Rewrite to guard/review language only |
| Smaller `orthoRes` wording vs sampling/product-resolution wording | older manual/reference and MOF matrix explanations | `orthoRes` is requested product resolution, not accuracy or true detail | Could imply smaller pixel size means more accurate product | Add explicit wording in active docs and paper register |
| Selected product wording vs best-candidate-within-tested-space wording | README, quick workflow, product contract | Selected product is a trace of implemented selection policy within tested candidates | Users may treat it as global optimum or validated truth | Rewrite selected-product sections |
| Upstream/class-based workflow assumptions vs active procedural runner | upstream README, audit docs, integration plan | Active runtime is procedural flat/camelCase runner, not upstream class workflow | Wrong schema and execution assumptions | Add status headers; keep upstream docs as background only |
| Historical MOF result claims vs current no-completed-MOF-results rule | `docs/zwischenbericht.qmd` | No completed MOF result claims should be made unless current run outputs/evaluation products are present and inspected | Paper or README could cite stale/partial results | Preserve as history; require fresh result evidence before use |
| Franzosenwiese as stress case vs reference benchmark | `docs/metashape_runtime_setup.md`, old configs/manuals | Franzosenwiese is a boundary/stress case, not current reference benchmark | Users may benchmark or publish against wrong dataset | Reframe all active examples away from Franzosenwiese unless clearly marked stress/runtime test |

## Content to preserve before any archival move

| category | source file | content to preserve | target future document | reason |
|---|---|---|---|---|
| methodological reasoning | `docs/orthomosaic_stability_manual_AI.md` | Orthomosaic as synthetic product and prior question of repeated-build reproducibility | `docs/rationale_and_paper_argument_register.md` or future paper outline | Strong methods motivation |
| methodological reasoning | `docs/audit/REPRODUCIBILITY_STABILITY_ANALYSIS_PLAN.md` | Repeated builds as samples from processing pipeline | argument register / paper outline | Core thesis wording |
| code recovery decisions | `docs/audit/AUDIT_FULL_WORKFLOW.md` | Procedural runner recovery, missing parser/syntax history, schema mismatch diagnosis | future `docs/history` | Explains why current architecture exists |
| upstream comparison | `docs/audit/UPSTREAM_AND_METASHAPETOOLS_INTEGRATION_PLAN.md` | Upstream innovations and destructive changes | future `docs/history` or design note | Prevents repeating integration mistakes |
| MetashapeTools integration reasoning | `docs/audit/UPSTREAM_AND_METASHAPETOOLS_INTEGRATION_PLAN.md` | `sparse2ortho`, sparse optimization, diagnostics, GUI menu mapping | future integration design doc | Useful future-work source |
| MOF dataset framing | `docs/orthomosaic_stability_manual_AI.md`, `docs/zwischenbericht.qmd` | 48 RGB UAV images, forest knoll, beech/Douglas fir, demanding forest product | argument register / paper outline | Paper dataset framing |
| Franzosenwiese boundary/stress interpretation | `docs/orthomosaic_stability_manual_AI.md` | Development/stress/canonical-grid/mask testing role | argument register | Maintains boundary status |
| support/stability interpretation | `docs/zwischenbericht.qmd`, `docs/orthomosaic_stability_manual.md` | Footprint support vs rectangular grid support; stability is not accuracy | current reference / argument register | Prevents metric misuse |
| evaluator/manifest/selected-product contract | `docs/product_manifest_contract.md` | Manifest statuses, medoid fallback, threshold flags, warnings | rewritten product contract | Strong active contract material |
| paper argument fragments | `docs/zwischenbericht.qmd` | Python-core architecture, product analysis stages, parameter-space limitation | future paper outline | Good draft material |
| future-work constraints | `docs/audit/UPSTREAM_AND_METASHAPETOOLS_INTEGRATION_PLAN.md` | GUI adapter, AM2/R adapter, checkpoint/sparse diagnostics as future extensions | argument register / roadmap | Keeps non-scope explicit |

## Proposed future documentation rewrite plan

| stage | exact files involved | purpose | dependencies | what must not change | human approval required |
|---|---|---|---|---|---|
| A. Reference-layer corrections or additions | `docs/current_system_reference.md`, `docs/rationale_and_paper_argument_register.md` | Add verified runtime environment notes, support metric definitions, stronger methodological argument fragments | Code/config verification and human review of status markers | Do not add old result claims; do not treat policy warnings as code behavior | yes |
| B. Active operational docs rewrite | `README.md`, `WORKFLOW_CHAIN.md`, `docs/quick_workflow.md`, `docs/orthomosaic_stability_manual.md`, `config/experiments/README.md` | Align commands, terminology, and primary preset with current product-analysis workflow | Stage A reference decisions | Do not rewrite historical docs as current truth | yes |
| C. Product/manifest contract update | `docs/product_manifest_contract.md` | Replace `experiment_dir` with run directory, align selected-product and threshold language with non-scope boundaries | Stage A and evaluator verification | Do not imply change-detection suitability or global optimality | yes |
| D. Paper outline creation | future `docs/paper_outline_orthomosaic_reproducibility.md` | Convert mined rationale into paper structure with status markers and evidence needs | Argument-register updates and human paper direction | Do not claim completed MOF results without inspected outputs | yes |
| E. Status headers for historical/audit docs | `docs/zwischenbericht.qmd`, `docs/audit/*.md`, `docs/orthomosaic_stability_manual_AI.md`, `docs/orthomosaic_stability_reference.md`, `docs/upstream/README_automate_metashape_upstream.md` | Prevent stale docs from being mistaken for active instructions | Mining complete | Do not delete or silently rewrite historical evidence | yes |
| F. Optional archival move after human approval | future `docs/history` or `docs/deprecated`; candidates include old manuals, audit plans, upstream README | Reduce active-doc clutter after extraction | Stages A-E complete and approval granted | Do not create archival folders or move files automatically | yes |

## Proposed active documentation target map

| future active document | final role |
|---|---|
| `README.md` | Short repository overview, current product-analysis command path, links to quick workflow, reference layers, attribution |
| `WORKFLOW_CHAIN.md` | Technical workflow chain for current procedural runner and product-analysis stages, without stale upstream/class assumptions |
| `docs/quick_workflow.md` | Concise operational recipe for current CLI and MOF/reference or generic product-analysis use |
| `docs/orthomosaic_stability_manual.md` | Human-readable stability/evaluation interpretation manual, shortened and aligned to run-directory/product-analysis terms |
| `docs/product_manifest_contract.md` | Exact manifest, evaluator, selected-product, threshold-review, and QGIS artifact contract |
| `config/experiments/README.md` | Preset and matrix reference, including MOF Alignment-Mesh-Ortho reference preset and explicit non-scope |
| `docs/current_system_reference.md` | Code-derived implementation reference; claims must stay code/config/preset-supported |
| `docs/rationale_and_paper_argument_register.md` | Methodological and paper argument register with explicit status markers |
| future `docs/paper_outline_orthomosaic_reproducibility.md` | Paper outline and figure/table plan derived from argument register, not active operations |
| future `docs/history` or `docs/deprecated` | Human-approved location for historical reports, old manuals, audits, upstream background, and stale operational instructions after mining |

## Unsafe actions

- Broad deprecation moves without mining and human approval.
- Deleting audit files.
- Rewriting historical reports as current truth.
- Adding suitability logic before MOF reference analysis.
- Treating Dense/DSM material as current benchmark scope.
- Treating smaller `orthoRes` as accuracy.
- Presenting Franzosenwiese as reference benchmark.
- Changing code to match old docs.
- Losing paper-relevant argument material during cleanup.

## Final decision table

| file | mined value | contradiction severity | later treatment | human approval required |
|---|---|---|---|---|
| `README.md` | Overview, layout, product workflow framing | medium | rewrite active | yes |
| `WORKFLOW_CHAIN.md` | Runtime chain, schema warnings | medium | rewrite active | yes |
| `config/README.md` | Config directory status | low | keep active | no |
| `config/legacy/README.md` | Legacy config warning | low | keep active | no |
| `config/experiments/README.md` | MOF matrix and non-scope language | medium | rewrite active | yes |
| `docs/quick_workflow.md` | Concise terminology and workflow | medium | rewrite active | yes |
| `docs/orthomosaic_stability_manual.md` | Stability and evaluator explanation | high | mine then archive or rewrite | yes |
| `docs/orthomosaic_stability_manual_AI.md` | Methodological rationale and safety warnings | high | mine then archive | yes |
| `docs/orthomosaic_stability_reference.md` | Parameter/summary column definitions | high | mine then archive | yes |
| `docs/product_manifest_contract.md` | Contract and medoid/threshold language | medium | rewrite active | yes |
| `docs/metashape_runtime_setup.md` | Runtime dependency warnings | medium | add status header or rewrite active | yes |
| `docs/zwischenbericht.qmd` | Paper fragments and historical MOF interpretation | high | keep as history | yes |
| `docs/audit/AUDIT_FULL_WORKFLOW.md` | Recovery evidence | high as current truth, low as history | keep as history with status header | yes |
| `docs/audit/REPRODUCIBILITY_STABILITY_ANALYSIS_PLAN.md` | Early rationale and hypotheses | high | mine then archive | yes |
| `docs/audit/UPSTREAM_AND_METASHAPETOOLS_INTEGRATION_PLAN.md` | Integration reasoning and future-work constraints | high | keep as history with status header | yes |
| `docs/upstream/README_automate_metashape_upstream.md` | Upstream provenance | high | keep as history | yes |
