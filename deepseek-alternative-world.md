# DeepSeek Alternative World: Architectural Simplification & Data Reduction Strategy

## 1. Current State Overview

The Level‑1b pipeline executes from Step‑0 (channel construction) through Step‑10 (materialization and quality).  Each step generates a rich set of artifacts: GeoTIFF rasters, JSON state dumps, CSV summaries, and GPKG vectorizations.  The total footprint for a single run can exceed 60 GB, with the vast majority produced by:

- **Per‑run segmentation rasters** (masked stack, MeanShift outputs, LSMS labels, merged labels) – retained for every evaluated candidate.
- **Repeated JSON/CSV exports** – many files are written simultaneously in both formats even though only one is consumed.
- **Nested status reports** – the Step‑9a report embeds complete one‑scale segmentation reports, and those are later copied by Step‑9b Prepare.

The audit (`implementation_audit.md`) correctly identifies these bloat sources, but it rests on several stale line references and mischaracterises some duplication.  This alternative‑world analysis builds on the **current** code base (as provided in the chat) to propose a concrete, risk‑aware simplification path.

## 2. Transient Execution Artifacts (TA)

### 2.1 Identified TA candidates

| Filename example | Producer | Consumer | Proposed lifecycle |
|---|---|---|---|
| `meanshift_smoothed.tif` | one‑scale segmentation | *none after successful run* | Delete after `merged_labels.tif` and all `run_q_*` summary files are written and validated. |
| `meanshift_position.tif` | one‑scale segmentation | *none* | Same as above. |
| `meanshift_smoothed_masked.tif` | one‑scale segmentation | *none* | Same. |
| `meanshift_position_masked.tif` | one‑scale segmentation | *none* | Same. |
| `lsms_labels.tif` | one‑scale segmentation | *none* | Same. |
| `merged_labels_unmasked.tif` | one‑scale segmentation | *none* | Same. |
| `masked_segmentation_stack.tif` | one‑scale segmentation | **Step‑10 Part 5** (exactextractr) | **Cannot delete until canonical stack is in place.** |
| `candidate_response_surface_report.json` | Step‑9a | Step‑9b Prepare (copied) | Could be replaced with a compact reference, but currently its full content is embedded in `perturbation_statuses`. |
| `analysis_matrix_summary.*` | Step‑9a | *none* | Can be omitted in non‑debug mode; they are diagnostic only. |
| `spatial_response_stability.*` | Step‑9a | *none* | Same. |
| `candidate_space_distribution_summary.*` | Step‑9a | *none* | Same. |

### 2.2 Critical observation

The `masked_segmentation_stack.tif` is the **only** transient raster that is still read after the segmentation run completes.  Deleting it without first providing a canonical shared copy (and updating all stored path references) will break the exactextractr step for *any* historical run used as a baseline.

## 3. Resume Contract Dead Ends

### 3.1 Current resume check

`_is_complete_run()` (`level1b_candidate_response_surface.py`) verifies:

- `merged_labels.tif`
- `one_scale_segmentation_report.json`
- `run_q_summary.json`
- `run_q_summary.csv`
- `run_q_segments.csv`

It does **not** verify the existence of `masked_segmentation_stack.tif`.  Therefore deleting that file does not interfere with resume.

### 3.2 The dangling pointer

`_expected_run_metadata()` **stores** the path `"masked_segmentation_stack_path"` in both the segmentation report and `run_q_summary.json`.  This path is later retrieved by Step‑10 Part 5 (`level1b_materialization.py` line ~346):

```python
value_raster = Path(selected_row["masked_segmentation_stack_path"])
```

If the file is gone, the subprocess fails silently (or with a hard error).

**Impact**: Every historical run that becomes the selected baseline will cause a pipeline failure.  The resume contract is therefore *too narrow* for safe cleanup.

### 3.3 Mitigation required before any deletion

- **Contractual guarantee**: Before any TA is removed, a **canonical masked stack** must be created once per response‑surface execution (not once per run).  All stored paths must be rewritten to point to that canonical stack.
- **Fallback logic**: Alternatively, Step‑10 Part 5 could be modified to reconstruct the stack on the fly from the unmasked stack and valid mask.  This eliminates the dependency entirely.

## 4. Serialization Overhead

### 4.1 JSON/CSV pairs

The code writes **both** JSON and CSV for:

- `run_population_summary` – JSON is used by Python, CSV is consumed by R.
- `candidate_group_response_summary` – same justification.
- `ranked_candidate_scales` – same.
- `analysis_matrix_summary` – **not** consumed by any downstream tool.
- `spatial_response_stability` – *none*.
- `candidate_space_distribution_summary` – *none*.
- `candidate_response_surface_report` – only JSON exists; no CSV.
- `finalist_group_summary`, `finalist_perturbation_runs`, etc. – both JSON and CSV are written in Step‑10.

The diagnostic CSV/JSON pairs (analysis matrix, spatial, space) can be made optional (e.g., only when `debug=True`).  Doing so removes approximately 6 redundant files per Step‑9a run.

### 4.2 Nested status reports

The `candidate_response_surface_report.json` embeds a full `perturbation_statuses` array containing every one‑scale segmentation report (including command output).  This makes the report file grow to ~57 MB.  The same information is already available in each per‑run `one_scale_segmentation_report.json`.

**Solution**: Replace the embedded reports with a compact list of `{run_id, group_id, status, report_path}` records.  Preserve the full verbose output only for failed runs or when debug mode is enabled.

### 4.3 Step‑9b Prepare copying

`run_step9b_prepare_from_existing_step9a` copies the Step‑9a report, run population, and ranked candidates into a separate directory.  This duplicates the large report (including all nested statuses).

**Solution**: Write a small Step‑9b manifest that references the original paths, rather than physically copying the files.  The manifest is already partially available via `write_step_manifest`.

### 4.4 Step‑10 evidence re‑materialization

Five separate functions each read and write intermediate JSON files.  After the first function finishes, the same data is read again for aggregation and then again for figures.

**Consolidation**: Combine the first two functions into one canonical evidence object that is stored once and then reused by the figure and materialisation steps.  This eliminates four intermediate reads and writes.

## 5. Parallel World Phased Implementation Plan

Each phase is *independently revertible* and must not alter any scientific computation.

| Phase | Action | Risk | Rationale |
|---|---|---|---|
| **0** | Create golden‑run fixture (all scientific outputs, checksums). | Low | Baseline for all subsequent validation. |
| **1** | Remove the duplicate write inside `_write_report()` (already done). | Low | Already implemented in current code. |
| **2** | Compact the `perturbation_statuses` embedded reports. | Conditional | Needs testing that Step‑9b Prepare can still run with compact references. |
| **3** | Make diagnostic CSV/JSON pairs optional (analysis_matrix, spatial, space). | Conditional | Must verify no consumer reads them. Currently none. Safe. |
| **4** | Replace Step‑9b Prepare physical copies with manifest references. | Medium | Requires refactoring of `run_step9b_midpoint_response_surface_and_handoff_from_prepare` to read from the manifest. |
| **5** | Shadow inventory for transient rasters. | Low | Write‑only logging of which files would be deleted; no actual deletion. |
| **6** | Create canonical masked stack per response‑surface execution. | High | Must prove pixel‑equality against per‑run copies. Update all path references in `run_q_summary.json`. |
| **7** | After Phase 6 validation, delete per‑run transient rasters (MeanShift, LSMS, etc.). | Dangerous | Only safe after canonical stack is deployed and all historical run summaries are updated. |
| **8** | Consolidate Step‑10 evidence: combine Parts 1‑2, reuse object for figures. | Medium | Requires changes to `run_level1b_step10_collect_finalist_evidence` and `run_level1b_step10_aggregate_finalist_evidence`. |
| **9** | Remove unnecessary CSV exports (analysis_matrix, etc.) after confirming no consumer. | Conditional | Double‑check `R/` scripts and any developer tool that may rely on them. |

### Phase dependency graph

```
Phase 0 ──► Phase 1 (already done)
   │
   ├──► Phase 2 ──► Phase 4 ──► Phase 9
   │
   ├──► Phase 3 ──► Phase 5 ──► Phase 6 ──► Phase 7 (blocked until Phase 6)
   │
   └──► Phase 8 (independent, can run after Phase 2)
```

## 6. Risk Register

| Risk | Severity | Mitigation |
|---|---|---|
| Deleting `masked_segmentation_stack.tif` before canonical stack exists | **High** | Block Phase 7 until Phase 6 is fully deployed and all historical `run_q_summary.json` paths are rewritten. |
| Changing CSV output breaks `R/level1b_run_eval_existing_stats.r` | **High** | Keep the three CSV inputs (`run_population_summary.csv`, `candidate_group_response_summary.csv`, `ranked_candidate_scales.csv`). Only remove the diagnostic CSV files. |
| Step‑9b Prepare fails to read compact references | **Medium** | Add a fallback to legacy report path in Step‑9b Prepare during migration. |
| New canonical masked stack does not produce identical values | **High** | Run pixel‑wise equivalence test against a sample of per‑run stacks. Use 64‑bit checksum comparison. |
| Historical runs become unreadable by Step‑10 after path updates | **Medium** | Store both the old per‑run path and the new canonical path for a transition period. |
| The dummy‑runner chain report grows too large due to nested statuses | **Low** | Already addressed by Phase 2. |

## 7. Conclusion

The Level‑1b pipeline can be radically simplified without altering any scientific output.  The primary bloat sources are:

1. **Per‑run transient rasters** – ~13 GB per Step‑9a run.  
2. **Nested status reports** – ~57 MB per run.  
3. **Unused diagnostic CSV/JSON pairs** – ~6 files per run.  
4. **Repeated Step‑10 evidence materialisation** – increases developer confusion and file count.

The **critical blocker** is the `masked_segmentation_stack.tif` dependency in Step‑10 Part 5.  Any deletion plan must first provide a canonical replacement and migrate all stored path references.  Once that is accomplished, the remaining phases (compact reports, optional diagnostics, consolidated evidence) can be executed safely and independently.

This alternative‑world strategy aligns with the audit’s staged approach but corrects several factual errors (the “triple copy” myth, the non‑existent double‑write, the misidentified mask‑stack build line).  It also provides a clear risk assessment for each phase and a dependency graph to avoid breaking the pipeline.

*No code was modified in the creation of this analysis.*
