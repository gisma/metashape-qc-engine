# Dataset-neutral orthomosaic presets

## Concept

A preset is a reusable analysis profile. It defines the processing factors and defaults that should be applied to a product analysis, without naming a dataset.

A dataset is the user-selected image directory supplied at prepare time.

A run is the concrete application of a preset to a dataset. A run has its own run directory, generated config, variants table when applicable, Metashape products, analyzer outputs, evaluator outputs, and reports.

A workflow profile is orchestration around one or more `prepare`, `run-analysis`, and `evaluate` calls. It can describe how to repeat a base preset across related runs, such as sensitivity checks, without being a single normal prepare preset.

## Current profiles

### `rgb_mesh_ortho_fast_screening_v1.json`

Type: normal prepare preset.

Question answered: whether a dataset and chosen project CRS can complete a compact RGB mesh and orthomosaic stability run with enough signal to justify a larger reference run.

Expected run logic: prepare one run directory from the preset, pass the image directory, product id, output root, reps, and `project_crs`, then run and evaluate that directory.

Recommended reps: low replicate count for screening, commonly `2` or `3`, chosen by the user to balance runtime and early stability signal.

Factor strategy: compact factor matrix focused on fast coverage of core alignment, mesh, and orthomosaic behavior.

Interpretation: use the result to detect obvious processing failures, unstable settings, missing inputs, or unsuitable runtime assumptions before committing to a larger run.

Non-claims: does not establish external accuracy, checkpoint validation, cross-date accuracy, change-detection suitability, platform comparison, or true scene detail.

### `rgb_mesh_ortho_reference_v1.json`

Type: normal prepare preset.

Question answered: what internal repeatability and product-selection behavior is observed for the selected dataset under the reference RGB mesh and orthomosaic factor matrix.

Expected run logic: prepare one run directory from the preset with a user-supplied `project_crs`, run all generated variants for the selected reps, then evaluate the completed or partially completed run directory.

Recommended reps: `5` or more when runtime allows; use fewer only when treating the output as preliminary.

Factor strategy: broader reference matrix covering the main processing factors intended for product comparison inside one dataset and one project CRS.

Interpretation: compare variants by internal stability metrics, support counts, and generated evaluation reports. Treat the selected product trace as the implemented selection procedure for that run, not as external truth.

Non-claims: does not establish external accuracy, checkpoint validation, cross-date accuracy, change-detection suitability, platform comparison, or true scene detail.

### `rgb_mesh_ortho_alignment_sensitivity_v1.json`

Type: normal prepare preset.

Question answered: how sensitive the product analysis is to alignment-related settings while holding the rest of the processing intent close to the RGB mesh and orthomosaic baseline.

Expected run logic: prepare one run directory from the preset with user-selected dataset inputs and `project_crs`, run the generated alignment sensitivity variants, then evaluate the run directory.

Recommended reps: `3` or more for exploratory sensitivity; increase reps when alignment effects are close to the stability threshold used for review.

Factor strategy: emphasizes alignment factors while keeping unrelated factors constrained enough that alignment behavior remains interpretable.

Interpretation: inspect whether alignment choices materially change internal stability metrics, product support, or downstream evaluation flags.

Non-claims: does not establish external accuracy, checkpoint validation, cross-date accuracy, change-detection suitability, platform comparison, or true scene detail.

### `generic_ortho_resolution_probe_v1`

Type: workflow profile.

Question answered: what dataset/config-specific technical orthomosaic sampling value Metashape exports when the orthomosaic resolution is left to the generic probe behavior.

Expected run logic: run one probe execution with `reps=1`, no variants table, and its own run directory. Read the recommended numeric sampling value from the exported GeoTIFF geotransform.

Recommended reps: exactly `1`.

Factor strategy: no factor matrix. The probe exists to measure the exported technical sampling value for the selected dataset and config.

Interpretation: use the reported value as the first recommended sampling stratum for later resolution sensitivity runs.

Non-claims: does not establish an optimal resolution, external accuracy, checkpoint validation, cross-date accuracy, change-detection suitability, platform comparison, or true scene detail.

### `rgb_mesh_ortho_resolution_sensitivity_v1`

Type: workflow profile.

Question answered: how internal stability and product-selection behavior change across user-selected orthomosaic sampling strata.

Expected run logic: first run `generic_ortho_resolution_probe_v1`, then prepare separate reference-style run directories for each sampling stratum. Each run directory must contain exactly one fixed `orthoRes` value and must be run and evaluated independently.

Recommended reps: follow the reference preset guidance for each stratum, commonly `5` or more when runtime allows.

Factor strategy: vary orthomosaic sampling between run directories, not inside one mixed-resolution evaluation matrix. The first stratum should be the generic probe value; additional strata are user-configured relative or absolute choices.

Interpretation: compare independently evaluated run directories to understand internal stability changes associated with sampling choices.

Non-claims: does not establish external accuracy, checkpoint validation, cross-date accuracy, change-detection suitability, platform comparison, or true scene detail.

## CRS rule

`project_crs` is mandatory user input.

No generic projected CRS is shipped as a default. The template uses `USER_MUST_SET_PROJECT_CRS` to force an explicit choice.

`camera_crs` may remain `EPSG::4326` because it describes common EXIF/GPS camera coordinates, not the output or project CRS.

CLI users should pass `project_crs` through `--factor project_crs=EPSG::XXXXX`.

The actual EPSG code must match the project area and analysis purpose.

## Generic resolution rule

Resolution sensitivity starts with `generic_ortho_resolution_probe_v1`.

The generic probe estimates the dataset/config-specific technical sampling value from the exported GeoTIFF geotransform.

This value is the first recommended sampling stratum.

Additional strata are user-configured relative or absolute choices.

Each stratum must use its own run directory.

The normal evaluator must not be used for mixed-resolution matrices.

## CLI examples

Fast screening prepare:

```bash
metashape-qc prepare \
  --image-dir "IMAGE_DIR" \
  --product-id "PRODUCT_ID" \
  --preset "config/experiments/presets/rgb_mesh_ortho_fast_screening_v1.json" \
  --reps 3 \
  --output-root "OUTPUT_ROOT" \
  --factor project_crs=EPSG::XXXXX
```

Reference prepare with `project_crs`:

```bash
metashape-qc prepare \
  --image-dir "IMAGE_DIR" \
  --product-id "PRODUCT_ID" \
  --preset "config/experiments/presets/rgb_mesh_ortho_reference_v1.json" \
  --reps 5 \
  --output-root "OUTPUT_ROOT" \
  --factor project_crs=EPSG::XXXXX
```

Run analysis:

```bash
metashape-qc run-analysis "RUN_DIR/config.yml" \
  --variants "RUN_DIR/variants.csv" \
  --reps 5 \
  --run-dir "RUN_DIR" \
  --metashape-dir "METASHAPE_DIR"
```

Resume analysis:

```bash
metashape-qc resume-analysis "RUN_DIR/config.yml" \
  --variants "RUN_DIR/variants.csv" \
  --reps 5 \
  --run-dir "RUN_DIR" \
  --metashape-dir "METASHAPE_DIR"
```

Evaluate:

```bash
metashape-qc evaluate "RUN_DIR"
```

Generic probe:

```bash
metashape-qc run-analysis "RUN_DIR/config.yml" \
  --reps 1 \
  --run-dir "RUN_DIR" \
  --generic-ortho-resolution \
  --metashape-dir "METASHAPE_DIR"
```

Resolution sensitivity as repeated reference prepare calls with one fixed `orthoRes` per run:

```bash
metashape-qc prepare \
  --image-dir "IMAGE_DIR" \
  --product-id "PRODUCT_ID" \
  --preset "config/experiments/presets/rgb_mesh_ortho_reference_v1.json" \
  --reps 5 \
  --output-root "OUTPUT_ROOT" \
  --factor project_crs=EPSG::XXXXX \
  --factor buildOrthomosaic.orthoRes=ORTHORES_STRATUM_1
```

```bash
metashape-qc prepare \
  --image-dir "IMAGE_DIR" \
  --product-id "PRODUCT_ID" \
  --preset "config/experiments/presets/rgb_mesh_ortho_reference_v1.json" \
  --reps 5 \
  --output-root "OUTPUT_ROOT" \
  --factor project_crs=EPSG::XXXXX \
  --factor buildOrthomosaic.orthoRes=ORTHORES_STRATUM_2
```

Run and evaluate each prepared stratum in its own `RUN_DIR`.
