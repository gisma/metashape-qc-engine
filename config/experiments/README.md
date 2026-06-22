# Product Analysis Presets and Matrices

This directory contains preset JSON files, template configs, and template variant CSV files used by `metashape-qc prepare`.

## Prepare input contract

`metashape-qc prepare` requires:

- `--image-dir`: directory containing the input images Metashape should load.
- `--product-id`: logical product identifier used in generated names.
- `--preset`: preset JSON file.
- `--reps`: replicate count for the later product-analysis run.
- `--output-root`: parent directory where run directories are created.

The command writes run-local artifacts:

- `<run_dir>/config.yml`
- `<run_dir>/variants.csv`

It prints the concrete `metashape-qc run-analysis` command and does not start Metashape.

## Preset JSON fields

Each preset JSON must define:

- `template_config`: source YAML config template copied and adjusted for the run directory.
- `template_variants_csv`: source CSV whose first data row is used as the base variant row.
- `experiment_dir_template`: internal field name for rendering the output run directory.
- `variant_id_template`: template for generated `variant_id` values.
- `factors`: mapping from CSV/config factor column to values used for Cartesian expansion.

`experiment_dir_template` is an internal preset field name retained by the implementation. User-facing docs should describe the rendered path as the run directory.

## Template variants CSV expansion

Prepare reads the first data row of `template_variants_csv` as the base row, computes the Cartesian product of `factors`, replaces the factor columns for each combination, renders a sanitized `variant_id`, and writes the generated rows with the original CSV header.

Factor columns must exist in the template variants CSV. Values are later applied by the runner as dotted YAML-key overrides.

## Starter/example preset

`config/experiments/presets/mesh_facecount_smoothing_3x3.json` is a small starter/example preset. It varies:

- `buildModel.face_count_custom`
- `buildModel.noiterations`

It is useful for exercising the preparation and runner contract, but it is not the current reference benchmark.

## Current MOF reference benchmark

The current reference benchmark preset is:

```text
config/experiments/presets/mof_alignment_mesh_ortho_reference_v1.json
```

It defines the MOF Alignment-Mesh-Ortho reference matrix. The reference image directory used in current local benchmark instructions is:

```text
/datadisk/data/uav/MOF_repro_test_recovered/input-images
```

Prepare command:

```bash
metashape-qc prepare \
  --image-dir "/datadisk/data/uav/MOF_repro_test_recovered/input-images" \
  --product-id "mof_alignment_mesh_ortho_reference_v1" \
  --preset "config/experiments/presets/mof_alignment_mesh_ortho_reference_v1.json" \
  --reps 5 \
  --output-root "/datadisk/data/uav/MOF_repro_reference/runs"
```

MOF matrix factor columns:

- `alignPhotos.downscale`: `1`, `2`
- `alignPhotos.adaptive_fitting`: `true`, `false`
- `buildModel.face_count_custom`: `50000`, `100000`, `250000`
- `buildModel.noiterations`: `5`, `35`
- `buildOrthomosaic.orthoRes`: `0.03`, `0.05`

This expands to:

```text
2 x 2 x 3 x 2 x 2 = 48 processing candidates
```

With `--reps 5`, the expected workload is:

```text
48 x 5 = 240 Metashape runs
```

## MOF fixed controls and non-varied settings

The MOF template disables:

- `buildDepthMaps.enabled`
- `buildPointCloud.enabled`
- `buildDem.enabled`

The matrix enables mesh-based orthomosaic production and does not benchmark Dense Cloud, Depth Maps, Point Cloud, DEM/DSM, or 3D reconstruction quality.

Generic and reference preselection are present as fixed template/CSV controls, but they are not varied in MOF v1. Keypoint limit, tiepoint limit, and guided matching are not part of MOF v1 unless they are implemented as active factor controls in the preset and generated variants CSV.

`buildOrthomosaic.orthoRes` is the requested orthomosaic pixel size / sampling resolution. It is a product-generation factor, not a guarantee of geometric accuracy or true detail.

## Non-scope

The current MOF reference benchmark does not establish:

- product suitability for change detection;
- platform comparison;
- GCP/checkpoint validation;
- cross-date accuracy;
- absolute geometric accuracy;
- Dense/Depth/PointCloud/DEM quality.
