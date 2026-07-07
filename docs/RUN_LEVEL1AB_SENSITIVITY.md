# Run the Level-1A/Level-1B Sensitivity Study

## Purpose

This guide runs the joint sensitivity experiment defined in:

```text
config/sensitivity/level1ab_sensitivity.yaml
```

The current design plans:

- 8 Level-1A variants × 3 replicates = 24 Metashape runs;
- 7 Level-1B profiles on the selected Level-1A orthomosaic;
- 4 additional Level-1B baseline runs for Level-1A propagation.

That is a substantial computation. The shell script defaults to `plan`; it does not start processing unless a processing stage is explicitly supplied.

## Prerequisites

From the repository root, prepare both environments as documented for the normal workflows:

```bash
bash scripts/setup_level1a.sh
bash scripts/setup_level1b.sh
```

Before running, verify these YAML values:

```yaml
study.output_root
level1a.image_dir
level1a.product_id
level1a.project_crs
level1a.metashape_dir
level1b.otb_root
```

The current example contains machine-specific paths for the MOF reference dataset. Change them before using another machine or dataset.

The normal Level-1A and Level-1B default files are not modified by the study. Complete Level-1B profile YAML files are written under the study output root.

## 1. Inspect and materialize the plan

The shortest safe command is:

```bash
bash scripts/run_level1ab_sensitivity.sh
```

This is equivalent to:

```bash
bash scripts/run_level1ab_sensitivity.sh \
  config/sensitivity/level1ab_sensitivity.yaml \
  plan
```

It validates the YAML, checks all Level-1B override paths, materializes the complete profile configs, and writes:

```text
<study.output_root>/study_design.csv
<study.output_root>/level1b/configs/baseline.yaml
<study.output_root>/level1b/configs/<profile_id>.yaml
```

Inspect the design before processing:

```bash
column -s, -t < /home/creu/tmp/level1ab_sensitivity/mof_v1/study_design.csv | less -S
```

For the supplied YAML, `study_design.csv` should contain 24 Level-1A rows and 11 Level-1B rows.

## 2. Run Level-1A

```bash
bash scripts/run_level1ab_sensitivity.sh \
  config/sensitivity/level1ab_sensitivity.yaml \
  level1a
```

The meta-runner calls the existing operations in this order:

```text
metashape-qc prepare
metashape-qc run-analysis
metashape-qc evaluate
```

For the supplied YAML, the experiment directory is:

```text
/home/creu/tmp/level1ab_sensitivity/mof_v1/level1a/
  mof_level1a_sensitivity_rgb_mesh_ortho_fast_screening_reps3/
```

Check first:

```bash
RUN=/home/creu/tmp/level1ab_sensitivity/mof_v1/level1a/mof_level1a_sensitivity_rgb_mesh_ortho_fast_screening_reps3

column -s, -t < "$RUN/manifest.csv" | less -S
jq . "$RUN/selected_product.json"
column -s $'\t' -t < "$RUN/stability_union/summary_key_metrics.tsv" | less -S
```

Level-1B must not be started until `selected_product.json` and the requested variant median orthomosaics exist.

## 3. Run Level-1B

```bash
bash scripts/run_level1ab_sensitivity.sh \
  config/sensitivity/level1ab_sensitivity.yaml \
  level1b
```

For every planned Level-1B row, the meta-runner:

1. chooses the exact Level-1A orthomosaic declared by the source block;
2. passes the corresponding resolved profile YAML as `LEVEL1B_CONFIG`;
3. invokes the existing Level-1B environment wrapper;
4. writes the normal Level-1B outputs under a separate run directory.

Run roots are located at:

```text
<study.output_root>/level1b/runs/selected_product__<profile_id>/
<study.output_root>/level1b/runs/variant_<variant_id>__baseline/
```

A Step-9b non-adjacent result returns code 2 and is retained as a valid study outcome requiring human choice. Other failed Level-1B runs are recorded; the meta-runner continues through the planned Level-1B rows and returns nonzero after collection.

Inspect statuses:

```bash
find /home/creu/tmp/level1ab_sensitivity/mof_v1/level1b/runs \
  -name level1b_dumb_chain_report.json -print0 \
  | xargs -0 -n1 jq -r '[.output_dir, .status, (.branch // "")] | @tsv'
```

Inspect one completed profile:

```bash
RUN=/home/creu/tmp/level1ab_sensitivity/mof_v1/level1b/runs/selected_product__baseline

jq . "$RUN/level1b_dumb_chain_report.json"
jq . "$RUN/level1b/step10_materialization/quality/ortho_segmentation_quality_info.json"
```

Principal geospatial outputs are:

```text
<run>/level1b/step10_materialization/final_segments/selected_labels.tif
<run>/level1b/step10_materialization/final_segments/selected_segments.gpkg
<run>/level1b/step10_materialization/figures/
```

## 4. Collect existing evidence

```bash
bash scripts/run_level1ab_sensitivity.sh \
  config/sensitivity/level1ab_sensitivity.yaml \
  collect
```

This reads existing workflow results only. It writes:

```text
<study.output_root>/study_results.csv
<study.output_root>/sensitivity_study_report.json
```

Inspect them with:

```bash
ROOT=/home/creu/tmp/level1ab_sensitivity/mof_v1

jq . "$ROOT/sensitivity_study_report.json"
column -s, -t < "$ROOT/study_results.csv" | less -S
```

`study_results.csv` combines the existing Level-1A key metrics with available Level-1B status, selection, selected-run, and Step-9b handoff fields. It is not an automatic statistical verdict.

## Run all stages

After reviewing the plan, the complete sequence can be started with:

```bash
bash scripts/run_level1ab_sensitivity.sh \
  config/sensitivity/level1ab_sensitivity.yaml \
  all
```

This can be computationally expensive. Running the stages separately is preferable because it allows Level-1A products and the Level-1B run count to be inspected before segmentation begins.

## Change the experiment

### Change Level-1A factors

Edit only the explicit lists under:

```yaml
level1a.factors
```

The Level-1A prepare step forms the Cartesian product of those lists. Check the resulting number of rows with the `plan` stage before processing.

### Add a Level-1B profile

A profile must contain exactly an ID and existing dotted YAML paths relative to the `level1b` object:

```yaml
- id: "example_profile"
  overrides:
    candidate_pre_screening.radius_max_m: 3.0
```

Then reference the profile explicitly in one of:

```yaml
level1b.sources.selected_product.profile_ids
level1b.sources.level1a_variants.profile_ids
```

Unknown paths and incompatible value types fail during planning. The active `config/level1b_default.yaml` is never edited.

### Change propagation variants

Edit:

```yaml
level1b.sources.level1a_variants.variant_ids
```

Every ID must be generated by the current Level-1A factor design. The `plan` stage fails if an ID is not part of that design.

## Overwrite behavior

The supplied YAML uses:

```yaml
study:
  overwrite: false
```

This prevents an existing named study from being silently reused as a new run. Setting it to `true` passes overwrite to the existing workflows. It does not change scientific parameters and should be used only when the complete named study output may be replaced.

For a new experiment, prefer a new `study.id`, `product_id`, and `study.output_root` instead of overwriting an earlier result.

## Failure checks

### Level-1A failure

Check:

```text
<Level-1A experiment>/manifest.csv
<Level-1A experiment>/variants/<variant>/runs/<replicate>/launcher.log
```

The Level-1A stage stops if prepare, run-analysis, or evaluate returns nonzero.

### Missing Level-1B source

The Level-1B stage fails if `selected_product.json` is missing or if an explicitly requested median orthomosaic does not exist. It does not search for substitutes.

### Level-1B processing failure

Check:

```text
<Level-1B run>/level1b_chain.log
<Level-1B run>/level1b_dumb_chain_report.json
<Level-1B run>/level1b/manifests/
```

A profile such as `ranger_plateau_strict` may fail scientifically when no stable plateau satisfies its stricter criterion. Such a failure is study evidence and must not be silently replaced by the baseline result.

## Interpretation boundary

The supplied design measures within-scene sensitivity. It does not by itself establish general robustness across landscapes, dates, sensors, flight conditions, or ecological classes. Multi-scene inference requires repeating the pre-registered design on independent scenes and analyzing scene as an explicit grouping factor.
