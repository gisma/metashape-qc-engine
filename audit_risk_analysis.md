# Audit Risk Analysis — Adversarial Peer Review of `implementation_audit.md` Against the Current Code Base

## 1. False Assumptions & Line Drifts

The audit repeatedly cites line numbers that do **not** exist in the current version of the code.  
Because the code has evolved since the audit was written, several key observations are based on stale line references, and some factual assertions are outright wrong.

| Audit Claim | Current Reality | Impact |
|---|---|---|
| "one-scale cleanup option removes only the tmp directory (lines 587‑590)" | The cleanup block is located at roughly line 383 in `level1b_one_scale_segmentation.py`; the line range 587–590 does **not** exist. The logic description is itself correct, but the line reference misleads. | Low – the architectural observation is still valid. |
| "Step‑9a references lines 2152‑2160 and 2242‑2270" | The functions `_run_artifact_paths` and `_is_complete_run` exist but at completely different positions (approx. line 2292 and later). | Low – only a verification inconvenience. |
| "`_write_report()` writes the same report twice (lines 496‑510)" | The current `_write_report()` writes **exactly once** (see `level1b_one_scale_segmentation.py` ~line 350). The audit claims a double‑write that is **not present** in this code base. | **High** – the first proposed simplification (Phase 1, item 1) is already implemented. The audit’s justification is based on a non‑existent bug. |
| "`candidate_response_surface_summary.json` and `.csv` are byte‑identical copies of the report" | The current output files are `candidate_response_surface_report.json`, `candidate_group_response_summary.json`, and `candidate_group_response_summary.csv`. No file named `candidate_response_surface_summary.*` exists. The "three full copies" claim is false; the three files are **not** duplicates. | **High** – the audit's recommended Phase 1 item 3 (eliminate duplicate report copies) would remove **the wrong files** or break downstream readers that actually consume `candidate_group_response_summary.json`. |
| "`masked_segmentation_stack` build command lines 350‑360" | The command builder is around line 234. | Low. |

**Conclusion**: The audit is based on a **different revision** of the repository. Several of its optimisation proposals are either already done, or would target files that do not exist. Adopting the audit blindly would risk removing the **wrong** artifacts or introducing regressions.

---

## 2. The Resume-Contract Conflict

### Audit’s Claim (Section 3.2)

> "The resume contract is narrower than the produced raster set. … `masked_segmentation_stack.tif` is not part of the run‑level resume completeness check. Exception: Step‑10 Part 5 currently reads it."

The audit then proposes, as a possible Phase 5 migration, that the per‑run `masked_segmentation_stack.tif` can be deleted **provided** a canonical shared copy is created and all consumers are updated.

### What the Audit Overlooks

The resume‑readiness test `_is_complete_run()` (see `level1b_candidate_response_surface.py`) does **not** check for the existence of `masked_segmentation_stack.tif`, so deleting it would **not** cause resume to fail. **However**, the **metadata contract** stored in the run report and in the `run_q_summary.json` does contain the path to that raster.  

Specifically:

1. **`_expected_run_metadata()`** (line ~2300) includes the key `"masked_segmentation_stack_path"`. This metadata is compared by `_metadata_matches()` when deciding whether a run can be reused. The comparison is **string‑based** – it does **not** require the file to exist.  
   → Deleting the file **will not prevent reuse**. Yet the stored path becomes a **dangling pointer**.

2. **`_write_incremental_run_q_statistics_from_counts()`** writes the field `"masked_segmentation_stack_path"` into `run_q_summary.json`. That summary is read by Step‑10 Part 5 (see below).  
   → Any future run that tries to use this historical summary as a selected baseline will **fail when the value raster is missing**.

3. **Step‑10 Part 4** (`run_level1b_step10_materialize_selected_segments`) constructs the source label raster as  
   ```python
   Path(selected_row["masked_segmentation_stack_path"]).parent / "merged_labels.tif"
   ```  
   Even if the underlying `masked_segmentation_stack.tif` is deleted, the parent directory still exists (because `merged_labels.tif` is kept), so this particular call survives.  
   → A **partial** safety – but only because `merged_labels.tif` is retained.

4. **Step‑10 Part 5** (`run_level1b_step10_compute_exactextractr_segment_stats_and_quality_info`) reads  
   ```python
   value_raster = Path(selected_row["masked_segmentation_stack_path"])
   ```  
   This **will break** if the file is missing. The audit correctly identifies this as an exception, but underestimates the **number of stored references** to that path.

**Result**: If the masked‑stack is deleted **before** the canonical‑stack migration (Phase 5) is fully deployed, **any** historical run used as a Step‑10 baseline will trigger a hard failure in the exactextractr command. The resume contract is **not enough** to protect against this – the damage occurs *after* the run is accepted as complete.

The audit’s Phase 5 plan is sound in principle, but the risk of **stale historical paths** is much higher than acknowledged. A **shadow inventory** (Phase 3) would reveal exactly which runs would become broken, but only if the inventory checks *all* consumers of the path, not just the resume criteria.

---

## 3. Step‑10 Hidden Dependencies

### Exact Line Locations

**`level1b_materialization.py`:**

- **Part 4 (`run_level1b_step10_materialize_selected_segments`)** – line ~260  
  ```python
  source_label_raster = (
      Path(selected_row["masked_segmentation_stack_path"]).parent
      / "merged_labels.tif"
  )
  ```
  → Uses the directory of the masked‑stack; does not require the stack itself. **Safe** from deletion of the stack.

- **Part 5 (`run_level1b_step10_compute_exactextractr_segment_stats_and_quality_info`)** – line ~346  
  ```python
  value_raster = Path(selected_row["masked_segmentation_stack_path"])
  valid_mask_path = Path(selected_row["valid_mask_path"])
  ```
  → The `value_raster` is passed directly to an `Rscript` subprocess.  
  **If the file is gone, the subprocess fails.** This is the **sole hard dependency** on the per‑run masked stack.

### Blast Radius

- The exactextractr step is the **final** Step‑10 operation; failure there means no quality‑info JSON, no segment statistics, and ultimately a **rejected pipeline**.
- Because the `masked_segmentation_stack_path` is stored in `run_q_summary.json` (*not* just in the segmentation report), **every** historical successful run that becomes the selected baseline will trigger this failure if the file is deleted.

**Mitigation possibilities** (not explored in the audit behind a single Phase 5 line):  
- Replace the per‑run stack with a **canonical one** and update the summary fields *for all existing runs* at migration time.  
- Or, in Step‑10 Part 5, fall back to using the segmentation stack (the original unmasked stack) instead of the masked stack, and apply the valid mask inside the R script. This would remove the dependency entirely.

---

## 4. Definitive Risk Assessment

| Audit Section | Summary | Classification | Reasoning |
|---|---|---|---|
| **3.1** – Repeated per‑run raster pipeline | Each run retains ~13 GB of intermediate rasters. Audit plans to delete them in Phase 4. | **DANGEROUS** | The raster set includes `masked_segmentation_stack.tif`, which is still required by Step‑10 Part 5. Deleting before a proper migration (Phase 5) will break exactextractr. Even after migration, historical run summaries contain stale paths. |
| **3.2** – Resume contract narrower | The resume check does not include the masked stack; audit notes the Step‑10 exception. | **DANGEROUS** | As shown in Section 2, the metadata contract stores the path **everywhere**. Deleting the file would cause silent failures in Step‑10 for any selected baseline run. The audit's Phase 5 is necessary but not sufficient without path‑rewriting for historical runs. |
| **3.3** – Step‑9 report multiplication | `perturbation_statuses` embeds complete one‑scale reports; three export files are created. | **CONDITIONAL** | The audit's proposal to replace embedded reports with compact references (Phase 1) is low‑risk, but must ensure that the external consumers (Step‑9b Prepare, any external scripts) still receive the required information. The current code does **not** have a `candidate_response_surface_summary.json` – the duplicate files the audit worries about do **not exist**. |
| **3.4** – One‑scale report written twice | Claim of a duplicate write inside `_write_report()`. | **SAFE** | The alleged double‑write does **not** exist in this code. No change needed. |
| **3.5** – Parallel CSV/JSON tables | Some CSV exports are unused; audit proposes to remove them. | **CONDITIONAL** | The R script `level1b_run_eval_existing_stats.r` consumes three specific CSV files. Removing any of those will break the R evaluation. The other six CSV/JSON pairs (analysis_matrix, spatial_stability, etc.) appear to be diagnostic only – safe to remove **only** if no downstream tool (including developer ad‑hoc scripts) reads them. |
| **3.6** – Step‑9b copies Step‑9a artifacts | `run_step9b_prepare_from_existing_step9a` copies reports and run population into a new directory. | **CONDITIONAL** | The audit's Phase 6 proposes replacing copies with references. This is safe **after** manifests are authoritative and all consumers have been updated. Currently, no consumer reads the copied files from `step9b_prepare_inputs` except the Step‑9b midpoint functions themselves – which would need to be updated at the same time. |
| **3.7** – Step‑10 evidence re‑materialized | Multiple read/write cycles produce many intermediate JSON files. | **SAFE** | This is a storage concern, not a correctness risk. Optimising can wait. |
| **3.8** – Dumb‑runner report duplication | The runner result may contain nested copies of full Step returns. | **SAFE** | The dumb‑runner is operational infrastructure; compaction is fine. |
| **3.9** – Shell wrapper duplicates configuration | Variables defined in the shell wrapper are not used. | **SAFE** | Removing them cleans up without functional impact. |

### Summary of Actionable Risks

- **Sections 3.1‑3.2** must not be acted upon until the `masked_segmentation_stack.tif` dependency is removed from Step‑10 Part 5 **and** all stored path references in historical run summaries are migrated or made resilient.  
- **Section 3.3** is based on a wrong premise (non‑existent files). The audit's Phase 1 items 3 and 4 should be re‑evaluated.  
- **Section 3.4** is already solved – no work required.  
- **Section 3.5** requires careful inventory of which CSV files are read by R and by any other consumer.  

The audit's staged strategy (Phases 0‑10) is structurally sensible, but its first implementation boundary (Phase 1) should be revised to exclude the "eliminate duplicate report copies" step until the actual file set is correctly understood.

*This analysis was produced solely from the provided repository files and the audit document. No source code was modified.*
