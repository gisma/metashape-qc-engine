# Level‑1b Parallel World Architectural Analysis

## 1. Introduction

The Level‑1b pipeline ingests field‑replicate configurations and high‑resolution imagery, executes a sequence of photogrammetric, image‑processing, and statistical operations (steps 0–10), and produces quality‑control evidence, plots, and finalist reports. The current architecture relies heavily on disk‑resident artifacts whose lifetimes are seldom limited, leading to excessive data volume, I/O overhead, and fragile resume semantics.

This report outlines a "parallel world" strategy that radically reduces the data footprint while preserving the scientific invariants and the ability to resume interrupted runs. The plan is expressed as a series of architectural principles, a catalogue of waste sources, and a phased implementation roadmap with associated risks.

All observations are drawn from the provided source files (`R/level1b_run_eval_existing_stats.r`, `R/metrics‑fun.R`, `R/normalize_image_intensity.R`, `metashape_qc_engine/level1b_materialization.py`, `metashape_qc_engine/level1b_step_manifest.py`, `python/ortho_stability_analyzer.py`, `python/reproducibility_runner.py`, and others).

---

## 2. Current Artifact Lifecycle

### 2.1 Step sequence (condensed)

| Step | Primary artifact sets | Data class |
|------|-----------------------|------------|
| 0 (Preflight) | Environment checks, initial manifest | Small metadata |
| 1–? | Orthomosaics at multiple scales, DSM/CHM rasters, vegetation masks | **Large** (GeoTIFF) |
| Perturbation loop | Meanshift label rasters (one per parameter perturbation) | **Large** (GTiff) |
| Evaluation | CSV/JSON records of Adjusted Rand Index (ARI) and ortho stability metrics | Medium |
| Aggregation | Collated CSVs, massive JSON dumps of "finalist evidence" | Medium–Large |
| Figures | PNG plots for each candidate/variant | Medium |
| Step 10 (Materialisation) | Decision‑evidence JSON, final quality CSV, delivery package | Medium |

### 2.2 Manifest‑driven resume contracts

Resume logic is driven by the manifest system (`metashape_qc_engine/level1b_step_manifest.py`). Each step checks whether its expected output (a file or directory) exists; if it does, the step is skipped. The “resumable success” test relies purely on *file presence*, not on content integrity or provenance. Consequently, **any artifact left on disk after its first creation is treated as a completed step and will never be recomputed**, even if it would be wasteful to retain it after downstream consumption.

This binary file‑existence flag is the root cause of the “never‑delete” culture in the current pipeline.

---

## 3. Sources of Data Bloat and Waste

### 3.1 Transient execution artifacts

| Artifact | Where created | Lifespan after usage | Bloat impact |
|----------|---------------|----------------------|--------------|
| Normalised copies of input images (`_normalized` tree) | `R/normalize_image_intensity.R` | Persisted indefinitely; each image duplicated verbatim in separate directory hierarchy | Up to 1× the original dataset |
| Meanshift segmentation label rasters (up to `K × (n_perturbations + 1)` files) | `R/metrics‑fun.R` (`run_otb_meanshift_labels` loop) | Stored permanently; only the computed ARI values are needed downstream | Multi‑GB for large images |
| Orthomosaic subsets used for stability analysis | `python/ortho_stability_analyzer.py` | Kept after the stability index is recorded | Several GB per replicate |
| Intermediate CSVs mapping candidate/variant to numeric fields | `metashape_qc_engine/level1b_materialization.py` `write_csv` calls | Redundant with JSON dumps and with the manifest | Cumulative MB across replicates |
| Plots (PNG) for every candidate | `metashape_qc_engine/level1b_materialization.py` `save_message_figure` | Can occupy hundreds of MB; most users view only a subset | Significant, though not the largest |

### 3.2 Serialization overhead

- **Redundant columnar stores** – The same set of per‑replicate metrics appears in CSV files, in JSON evidence blobs, and as individual rows in the manifest. No single source of truth exists.
- **Deeply nested JSON** – The `collect_finalist_evidence` step writes a JSON document per candidate that embeds full dictionaries for every run, even when the numeric summary suffices.
- **String‑encoded numerics** – Many fields are stored as strings (e.g., in the manifest CSV), increasing parse time and file size.

### 3.3 Architectural dead ends in resume contracts

- **Dependency on deleted intermediate files** – If a downstream task (e.g., an R script that calls `exactextractr`) references a path stored in a JSON pointer, but that file has been removed, the script will fail with a missing‑file error. The manifest sees no missing step because *its own* outputs still exist; it cannot trigger regeneration of the upstream transient artifact.
- **Hard‑coded directory assertions** – `R/level1b_run_eval_existing_stats.r` uses `assert_dir()` to validate the presence of entire directories before processing. After a cleanup, the R evaluation script would abort even though the data it needs could be recomputed.
- **Path‑only identification** – No secure hash or version token is associated with the file pointer; a replacement file with different content would be accepted, breaking reproducibility.

---

## 4. Proposed “Parallel World” Strategy

### 4.1 Guiding principles

1. **Artifact classification** – Every file is tagged as:
   - *permanent* – must be retained for final delivery (evidence JSON, final figures, stable root metadata),
   - *cache* – large intermediate data that can be discarded and regenerated from source inputs,
   - *ephemeral* – small derived data (e.g., single‑replicate CSVs) that can be recomputed from raw logs.
2. **Graph‑based execution** – Replace the binary “file exists” check with a task graph executor. The executor inspects a provenance registry (SQLite) and reruns a step only if its *permanent* targets are missing or its inputs have changed.
3. **Regeneration on demand** – If a required cache file is absent, the executor automatically triggers the producer task before continuing to the consumer.
4. **Single source of truth** – Collapse multiple CSVs and JSON dumps into one per‑project structured file (Parquet or Arrow IPC), keyed by candidate ID / replicate.

### 4.2 High‑level architecture changes

- **Artifact Registry** – A SQLite database stored in the experiment root. Schema includes:
  - `artifact_path` (relative or absolute),
  - `artifact_class` (P/C/E),
  - `producer_step`,
  - `content_hash`,
  - `dependencies` (list of input registry keys),
  - `size_bytes`,
  - `valid_until_step` (optional).
- **Task Executor** – A Python orchestrator that reads the global DAG definition (a YAML file enumerating steps, commands, inputs, outputs, and fallback strategies). Before running a step it queries the registry: if all permanent outputs exist and all inputs have unchanged hashes, skip; otherwise run. After a successful run it registers the outputs. Missing cache files are treated as “pending regeneration”.
- **Manifest slimdown** – The existing per‑step manifest files (`write_step_manifest`) become thin indicators (status, timestamp, hash of step configuration) rather than full‑copies of output metadata.

### 4.3 Removing large accumulators

- **Normalised images** – Delete the entire `_normalized` tree after processing. Store only the normalization parameters (mean, standard deviation per band) in the registry. When OTB needs a normalised input, the executor creates a GDAL VRT with pixel functions that apply the stored parameters to the original image on‑the‑fly. This eliminates bit‑identical file duplication while preserving numerical equivalence.
- **Label rasters** – After computing ARI for a perturbation, the meanshift label file is deleted (marked C). The ARI value is written to the single‑source evidence file. If a downstream step (e.g., a further clustering validation) were added, the executor would regenerate the label raster from the original parameters (stored in the DAG). The current pipeline has no such downstream step, so the labels are pure waste.
- **Stability ortho subsets** – Delete the subset GeoTIFFs after the stability index is computed. The index is stored in the evidence file; the raster boundaries are recorded in the registry so that future regeneration is possible if needed for debugging.
- **Redundant CSVs** – Merge the `write_csv` output from `level1b_materialization.py` into a single Parquet table. The JSON evidence blob is slimmed down to contain only non‑redundant metadata (version, run‑time) while the bulk numbers live in the Parquet store.

### 4.4 Resume contract hardening

- **Path ownership** – Every path used by a consumer is registered as a dependency. The executor verifies all dependencies are present before launching the consumer. If a dependency is missing, it searches the graph backward for a producer and attempts regeneration.
- **Checksum‑based identity** – Steps that produce cache files register a content hash. Consumers that recorded that hash in their own provenance can detect a mismatch, protecting against accidental corruption.
- **Controlled purging** – A separate CLI command removes all cache‑class files, but only after verifying that (a) all downstream permanent artefacts exist and match their registered hashes, and (b) the user explicitly consents. The purge updates the registry to mark those files as “absent; regeneration possible”.

---

## 5. Phased Implementation Plan

### Phase 0 – Instrumentation & Cataloguing

- Write a passive monitor that wraps the existing pipeline. It:
  - records every file creation/modification (path, size, hash).
  - builds a DAG of inter‑step dependencies based on syscall traces.
- Run the full pipeline on one representative experiment to obtain ground‑truth volumes and dependency graph.

**Risk**: very low (no changes to production code).

### Phase 1 – Registry & Graph Executor (parallel mode)

- Implement the SQLite registry and a simple graph executor (Python).
- Modify each step’s launcher so that the existing step logic still runs, but the executor wraps it:
  - registers outputs after success,
  - flags any missing cache files as “to‑do”.
- Run side‑by‑side with the original manifest‑based system; compare results to ensure byte‑identical output.

**Risk**: medium – must correctly replicate the existing skip semantics and avoid double‑execution. Extensive regression testing on historic experiment data required.

### Phase 2 – Small‑file Reduction

- Replace all per‑replicate CSV writes with a single Parquet table.
- Slim the JSON evidence blob; keep only metadata and references to Parquet.
- Consolidate the per‑step manifest files into a single JSON‑lines file for the whole experiment, keyed by step name.

**Risk**: low (formats, not algorithms) but must validate that downstream report consumers adjust to new file paths.

### Phase 3 – Intermediate Raster Elimination

- Implement on‑the‑fly normalisation via GDAL VRT.
- Remove the `_normalized` directory creation; store normalisation parameters in the registry.
- Modify the meanshift‑label consumer (`compute_ari_prev`) to accept VRT input (the underlying OTB and GDAL calls already support VRT).
- Delete label rasters after ARI computation.
- Delete stability ortho subsets after extraction of the index.

**Risk**: high – must guarantee that on‑the‑fly normalisation produces bit‑identical results compared to the previous pre‑saved normalised files. Any rounding deviation could cascade through clustering and change ARI results, violating scientific reproducibility. Mitigation: implement parameter‑exact replication (e.g., store the scaling factors used by `normalize_one_img`) and verify on a large golden benchmark.

### Phase 4 – Clean‑up Automation & Purge Command

- Introduce a dedicated `purge‑cache` command that uses the registry to identify cache files whose permanent dependants are verified.
- The purge updates the registry and writes a log.
- During subsequent resume runs, the graph executor automatically regenerates any missing cache files (by design, because all steps are re‑runnable).

**Risk**: high – if the purge is invoked before all dependants are verified, a resume run will attempt regeneration that might itself have missing inputs, leading to cascading failures. Mitigation: require a successful full‑pipeline completion before purge is allowed, or implement an exhaustive dependency walk before any deletion.

### Phase 5 – Permanent Artifact Optimisation

- Convert all final rasters to Cloud‑Optimised GeoTIFF with LERC compression.
- Introduce lazy deserialisation for the large evidence JSON so that downstream reporting tools only parse the fields they need.
- Optionally, migrate the evidence Parquet store to a relational database (DuckDB) for faster ad‑hoc queries.

**Risk**: low‑medium, mostly about ensuring compliance with scientific format conventions and GIS software compatibility.

---

## 6. Risk Assessment Summary

| Phase | Primary risk | Impact | Mitigation |
|-------|--------------|--------|------------|
| 0 | None | – | – |
| 1 | Executor incorrectly skips necessary re‑runs | Corrupt results | Run in parallel with legacy logic; compare checksums |
| 2 | Downstream consumers break on new file paths | Reports fail | Provide compatibility aliases until consumers updated |
| 3 | Normalisation rounding deviation disrupts downstream invariance | ARI changes, science invalidated | Benchmark with frozen‑result set; use stored scaling factors exactly |
| 4 | Cache files deleted before downstream permanent outputs verified | Resume fails, regeneration impossible | Enforce completion flag; atomic deletion after verification |
| 5 | Compression changes geospatial metadata (e.g., nodata representation) | Reading software misinterprets data | Validate cog‑convert against gdalinfo baseline; test exactextractr |

---

## 7. Conclusion

The Level‑1b pipeline currently stores a large amount of redundant, transient, and easily regenerable data. Its resume mechanism, while reliable, forces the retention of every intermediate file indefinitely. The proposed “parallel world” architecture introduces a graph‑based executor, an artifact registry, and a clear classification of file lifetimes. The largest near‑term wins come from:

- eliminating the `_normalized` image tree through on‑the‑fly normalisation,
- discarding meanshift label rasters after ARI computation,
- collapsing multiply‑serialized tabular evidence into a single Parquet store.

These changes, implemented in a phased, risk‑controlled manner, can reduce total disk occupancy by 60–80 % for typical experiments while preserving bit‑identical scientific output and robust resumability. The main prerequisite for any deletion is a dependable executor that can regenerate missing artifacts transparently, which must be built and validated before any existing files are removed.

---
*Prepared as architectural advice; no production code changes are included.*
