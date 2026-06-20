# Orthomosaic Reproducibility and Stability Workflow Manual

## 1. Purpose

This workflow evaluates the repeated-build stability of UAV orthomosaics produced with Agisoft Metashape.

The central idea is that a UAV orthomosaic is not a direct sensor observation. It is a synthetic photogrammetric product created from overlapping images, camera alignment, tie points, a projection surface, seamlines, blending and export settings.

The workflow therefore asks a prior question before fine-scale interpretation or change detection:

Can the image support and image values be reproduced under repeated photogrammetric processing?

This manual describes the complete current workflow, including data organization, Metashape configuration, variant experiments, repeated runs, canonical-grid analysis, stability products and basic interpretation rules.

## 2. Dataset organization rule

Each dataset must be organized as one physical project folder.

The project folder must contain:

```text
PROJECT_ROOT/
  input-images/
  runs/
```

`input-images/` contains only the physical image files that should be processed by Metashape.

`runs/` contains all generated material: Metashape projects, exported orthomosaics, logs, manifests and stability products.

The workflow must never write Metashape outputs into `input-images/`.

The workflow must never use a mixed root folder as `photo_path`.

The workflow must never use a folder as `photo_path` if that folder also contains Metashape projects, exported orthomosaics, PNGs, TIFFs, reports, logs, previous experiment outputs, ZIP files or other derived files.

## 3. No-delete rule

Setup scripts must never delete input images automatically.

This is a hard workflow rule.

Input image folders are curated data. If an `input-images/` folder already contains files, a setup script must stop and report this condition. It must not clear, overwrite or delete the folder.

Safe behavior:

```text
if input-images/ already contains files:
  stop
  print a warning
  require manual action
```

Unsafe behavior:

```text
find input-images -type f -delete
rm input-images/*
automatic cleanup of selected images
```

Old input folders should be renamed manually, not deleted automatically.

Example safe pattern:

```bash
ROOT=/path/to/project

mkdir -p "$ROOT"

if [ -d "$ROOT/input-images" ] && [ "$(find "$ROOT/input-images" -maxdepth 1 -type f | wc -l)" -gt 0 ]; then
  echo "ERROR: $ROOT/input-images already contains files."
  echo "Move or rename it manually before creating a new input set."
  exit 1
fi

mkdir -p "$ROOT/input-images"
mkdir -p "$ROOT/runs"
```

## 4. Physical image copies

For a portable and understandable workflow, `input-images/` should contain real image files, not symbolic links.

Symbolic links are useful on Linux, but they make the workflow harder to understand and less portable. For shared documentation and reproducible project folders, physical copies are preferred.

Recommended structure:

```text
/datadisk/data/uav/MOF_repro_test_recovered/
  input-images/
    DJI_....JPG
    DJI_....JPG
    ...
  runs/
```

The original archive or acquisition folder should remain unchanged.

A curated project folder may contain copied images, but those copied images are still treated as input data and must not be deleted by setup scripts.

## 5. Current dataset roles

### 5.1 Development dataset: Franzosenwiese

The Franzosenwiese dataset is a development and workflow-testing dataset.

It represents a raised bog / Hochmoor area with ditches, sparse trees and lying deadwood. It is not a forest canopy benchmark.

It is useful for:

```text
workflow development
canonical-grid testing
stability metric testing
mask logic testing
first sensitivity checks
```

It should not be presented as the main forest benchmark.

### 5.2 Real benchmark dataset: MOF forest knoll

The MOF dataset is the current real benchmark dataset.

It contains high-quality RGB UAV imagery of a forest terrain knoll with beech and Douglas fir.

It represents a strong low-budget UAV RGB/geolocation benchmark because image quality and image geolocation are unusually good for the intended use case.

It is used to test whether orthomosaic instability remains visible even under good acquisition conditions.

Recommended project structure:

```text
/datadisk/data/uav/MOF_repro_test_recovered/
  input-images/
  runs/
```

## 6. Base Metashape configuration

Each experiment starts from one base YAML configuration.

Example:

```text
config/experiments/test_mesh_ortho_mof_forest_knoll_rgb.yml
```

The base YAML defines one complete Metashape workflow.

Important top-level fields:

```yaml
load_project: ""
photo_path: "/path/to/PROJECT_ROOT/input-images/"
photo_path_secondary: ""

output_path: "/path/to/PROJECT_ROOT/runs/single_run/output/"
project_path: "/path/to/PROJECT_ROOT/runs/single_run/psx/"
run_name: "mof_forest_knoll_rgb_mesh_ortho"

project_crs: "EPSG::32632"
camera_crs: "EPSG::4326"
```

`photo_path` must point to the clean `input-images/` folder.

`output_path` and `project_path` must point below `runs/`.

`project_crs` is the target CRS for exported geospatial products.

`camera_crs` is the CRS of the camera reference positions, normally WGS84 for DJI/EXIF geotags.

## 7. Core Metashape modules

The base YAML contains the main Metashape workflow blocks.

### 7.1 `addPhotos`

Controls image loading and camera reference handling.

Important fields:

```yaml
addPhotos:
  enabled: True
  separate_calibration_per_path: False
  multispectral: False
  use_rtk: True
  fix_accuracy: 0.000001
  nofix_accuracy: 0.0001
```

For RGB benchmark runs, `multispectral` should remain `False`.

`use_rtk` should reflect the intended handling of accurate camera positions. For datasets with strong image geolocation, this should be explicitly documented.

### 7.2 `alignPhotos`

Controls image matching and camera alignment.

Important fields:

```yaml
alignPhotos:
  enabled: True
  downscale: 1
  adaptive_fitting: True
  keep_keypoints: True
  reset_alignment: True
  generic_preselection: True
  reference_preselection: True
  reference_preselection_mode: Metashape.ReferencePreselectionSource
  export: True
```

`downscale: 1` gives high-quality matching, but increases computation.

`keep_keypoints: True` is useful for diagnostics, but can increase memory use.

If memory or GPU problems occur during matching, this block is one of the first places to check.

### 7.3 `filterPointsUSGS`

Controls sparse point filtering.

Important fields:

```yaml
filterPointsUSGS:
  enabled: True
  rec_thresh_percent: 20
  rec_thresh_absolute: 15
  proj_thresh_percent: 30
  proj_thresh_absolute: 2
  reproj_thresh_percent: 5
  reproj_thresh_absolute: 0.3
```

This is part of the current inherited automate-metashape workflow. It should not be confused with the future checkpoint-aware sparse-cloud optimization axis.

### 7.4 `optimizeCameras`

Controls camera optimization after sparse point filtering.

Important fields:

```yaml
optimizeCameras:
  enabled: True
  adaptive_fitting: True
  export: True
```

Camera optimization remains part of the base workflow.

### 7.5 `buildDepthMaps` and `buildPointCloud`

For the current mesh-orthomosaic regularization tests, these are disabled.

```yaml
buildDepthMaps:
  enabled: False

buildPointCloud:
  enabled: False
```

This is intentional. The current experiment axis is mesh-based projection-surface regularization from tie points, not dense DSM generation.

### 7.6 `buildModel`

This block creates the mesh used as orthomosaic projection surface.

Important fields:

```yaml
buildModel:
  enabled: True
  source_data: Metashape.TiePointsData
  face_count: Metashape.LowFaceCount
  face_count_custom: 100000
  noiterations: 35
```

`source_data` defines what the mesh is built from.

For the current Ortho+ style route:

```yaml
source_data: Metashape.TiePointsData
```

`face_count` controls mesh complexity.

`noiterations` controls smoothing strength through `smoothModel()`.

Together, these parameters define the projection-surface regularization axis.

### 7.7 `buildDem`

For the current mesh-orthomosaic tests, DEM generation is disabled.

```yaml
buildDem:
  enabled: False
```

Dense DSM/DEM routes are computationally heavier and should be treated as separate benchmark experiments, not part of the default mesh-regularization test.

### 7.8 `buildOrthomosaic`

This block creates and exports the orthomosaic.

Important fields:

```yaml
buildOrthomosaic:
  enabled: True
  orthoRes: 0.05
  surface: ["Mesh"]
  blending: Metashape.MosaicBlending
  fill_holes: True
  refine_seamlines: True
  export: True
  tiff_big: True
  tiff_tiled: True
  nodata: -32767
  tiff_overviews: True
  remove_after_export: False
```

For the current workflow, `surface: ["Mesh"]` is central.

`remove_after_export: False` keeps the orthomosaic in the Metashape project after export. This is useful for inspection.

## 8. Variant table

The variant table defines controlled modifications of the base YAML.

Example:

```text
config/experiments/repro_variants_mesh_regularization.csv
```

Each row is one processing variant.

Each column after `variant_id` is a dotted YAML key.

Example:

```csv
variant_id,buildDepthMaps.enabled,buildPointCloud.enabled,buildModel.enabled,buildModel.source_data,buildModel.face_count,buildModel.noiterations,buildDem.enabled,buildDem.surface,buildOrthomosaic.enabled,buildOrthomosaic.surface,buildOrthomosaic.orthoRes
flat_mesh,False,False,True,Metashape.TiePointsData,Metashape.LowFaceCount,80,False,,True,[Mesh],0.05
moderate_mesh,False,False,True,Metashape.TiePointsData,Metashape.LowFaceCount,35,False,,True,[Mesh],0.05
light_mesh,False,False,True,Metashape.TiePointsData,Metashape.MediumFaceCount,5,False,,True,[Mesh],0.05
```

Only intentionally varied parameters should be included in the variant table.

All other settings are inherited from the base YAML.

## 9. Current experimental axis

The current experimental axis is mesh-based projection-surface regularization.

The current variants are:

```text
flat_mesh
moderate_mesh
light_mesh
```

### 9.1 `flat_mesh`

Intended role:

```text
strongly regularized projection surface
```

Typical settings:

```yaml
buildModel.face_count: Metashape.LowFaceCount
buildModel.noiterations: 80
buildOrthomosaic.surface: [Mesh]
```

### 9.2 `moderate_mesh`

Intended role:

```text
moderately regularized projection surface
```

Typical settings:

```yaml
buildModel.face_count: Metashape.LowFaceCount
buildModel.noiterations: 35
buildOrthomosaic.surface: [Mesh]
```

### 9.3 `light_mesh`

Intended role:

```text
less regularized projection surface
```

Typical settings:

```yaml
buildModel.face_count: Metashape.MediumFaceCount
buildModel.noiterations: 5
buildOrthomosaic.surface: [Mesh]
```

## 10. Reproducibility runner

The reproducibility runner is:

```text
python/reproducibility_runner.py
```

It creates independent Metashape builds from the base YAML and optional variant table.

Main call:

```bash
EXP=/path/to/PROJECT_ROOT/runs/experiment_mesh_variants_reps5

python3 python/reproducibility_runner.py \
  config/experiments/test_mesh_ortho_mof_forest_knoll_rgb.yml \
  --variants config/experiments/repro_variants_mesh_regularization.csv \
  --reps 5 \
  --experiment-dir "$EXP" \
  --metashape-dir /home/creu/apps/metashape-pro
```

With three variants and five replicates, this creates:

```text
3 variants x 5 replicates = 15 Metashape runs
```

### 10.1 `--reps`

Number of independent repeated builds per variant.

Recommended use:

```text
2 replicates
  workflow test only

5 replicates
  first useful stability diagnosis

10 or more replicates
  stronger distributional analysis
```

### 10.2 `--experiment-dir`

Root directory for all generated configs, projects, outputs, logs and the manifest.

This directory must be below `runs/`, not below `input-images/`.

### 10.3 `--variants`

Optional CSV table defining variant overrides.

If omitted, the runner repeats the base YAML only.

If provided, the runner performs all variants for all requested replicates.

### 10.4 `--metashape-dir`

Path to the Agisoft Metashape installation.

Example:

```text
/home/creu/apps/metashape-pro
```

## 11. Runner output

The runner writes:

```text
experiment_dir/
  manifest.csv
  variants/
    flat_mesh/
      configs/
      runs/
    moderate_mesh/
      configs/
      runs/
    light_mesh/
      configs/
      runs/
```

Each replicate has:

```text
runs/rep_001/
  psx/
  output/
  launcher.log
```

The replicate YAML files are written to:

```text
variants/variant_id/configs/rep_001.yml
```

These generated YAML files are important because they document the exact configuration actually used for each run.

## 12. Manifest

The manifest is:

```text
manifest.csv
```

It is the central index of the experiment.

Important columns:

```text
experiment_id
variant_id
replicate
status
return_code
config_file
project_dir
output_dir
project_file
ortho_file
launcher_log
elapsed_sec
```

Important status values:

```text
ok
  run finished and an orthomosaic TIFF was found

ok_no_ortho
  run finished but no orthomosaic TIFF was found

failed
  run returned a non-zero exit code
```

The stability analyzer only uses rows with:

```text
status = ok
```

## 13. Crash diagnosis

If a run crashes, inspect the latest log.

Example:

```bash
EXP=/path/to/experiment

LOG=$(find "$EXP" -name launcher.log -printf "%T@ %p\n" | sort -n | tail -1 | cut -d' ' -f2-)

grep -iE "error|exception|failed|traceback|aborted|killed|bad allocation|memory|cuda|gpu|tile" "$LOG" | tail -100
```

A previous critical failure mode was caused by using a mixed root folder as `photo_path`. Metashape loaded hundreds of files instead of the intended image set. The log showed image numbers far above the expected number of RGB images.

Example symptom:

```text
[GPU] photo 432
RuntimeError: Can't select tile size
```

If the dataset should contain only 48 images, log messages referring to `photo 432` indicate that the wrong folder was used as `photo_path`.

## 14. Stability analyzer

The stability analyzer is:

```text
python/ortho_stability_analyzer.py
```

It reads `manifest.csv`, aligns all orthomosaics to a canonical analysis grid, and computes stability products.

Main call:

```bash
python3 python/ortho_stability_analyzer.py \
  "$EXP/manifest.csv" \
  --output-dir "$EXP/stability_union" \
  --grid-mode union \
  --bands 3 \
  --stable-rmse-threshold 15 \
  --overwrite
```

## 15. Canonical analysis grid

Metashape orthomosaics may differ slightly in raster size, extent or support across repeated builds.

Direct pixel comparison is only valid when all rasters have the same dimensions, geotransform and projection.

The analyzer therefore warps all orthomosaics to one canonical analysis grid before computing statistics.

### 15.1 `--grid-mode union`

The grid covers the combined extent of all orthomosaics.

This preserves support instability.

Recommended for reproducibility analysis.

### 15.2 `--grid-mode intersection`

The grid covers only the common overlap of all orthomosaics.

Useful for pure pixel comparison, but it hides border/support instability.

### 15.3 `--grid-mode reference`

The grid is copied from a reference orthomosaic.

Useful for quick tests or fixed-frame comparisons.

## 16. Analyzer parameters

### 16.1 `--bands`

Number of bands analyzed.

For RGB orthomosaics:

```text
--bands 3
```

### 16.2 `--stable-rmse-threshold`

Threshold used to classify pixels as stable or unstable based on `rmse_to_median.tif`.

A pixel is stable if it is valid in all replicate orthomosaics and its RMSE to the median is less than or equal to the threshold.

For 8-bit RGB images, the threshold is expressed on the 0–255 digital number scale.

The default currently used threshold is:

```text
15
```

This threshold is a workflow parameter, not a universal physical constant. It must be reported with every analysis.

### 16.3 `--overwrite`

Recomputes outputs and aligned rasters.

Use carefully. It does not delete input images, but it can overwrite analyzer products.

## 17. Analyzer output structure

The analyzer writes:

```text
stability_union/
  canonical_grid.json
  summary.csv
  aligned/
    flat_mesh/
    moderate_mesh/
    light_mesh/
  variants/
    flat_mesh/
      valid_count.tif
      median_ortho.tif
      mad_rgb.tif
      rmse_to_median.tif
      stable_mask_rmse15.tif
      unstable_mask_rmse15.tif
    moderate_mesh/
      ...
    light_mesh/
      ...
```

## 18. Stability rasters

### 18.1 `valid_count.tif`

Number of valid orthomosaic values per canonical-grid pixel.

This measures support stability.

For five replicates, values range from 0 to 5.

### 18.2 `median_ortho.tif`

Band-wise median orthomosaic across all replicates of one variant.

This is an analysis product, not a Metashape output.

### 18.3 `mad_rgb.tif`

Robust RGB deviation from the median orthomosaic.

Lower values indicate higher repeated-build stability.

### 18.4 `rmse_to_median.tif`

RMSE of replicate values to the median orthomosaic.

Lower values indicate higher repeated-build stability.

This raster is used for threshold-based stable and unstable masks.

### 18.5 `stable_mask_rmse*.tif`

Byte mask of stable pixels.

Values:

```text
1   stable
0   valid support, but not stable
255 no valid support / NoData
```

### 18.6 `unstable_mask_rmse*.tif`

Byte mask of unstable pixels.

Values:

```text
1   unstable
0   valid support, but not unstable
255 no valid support / NoData
```

Inside valid support, `stable_mask` and `unstable_mask` form a complete partition.

## 19. Summary table

The analyzer writes:

```text
summary.csv
```

One row per variant.

Important columns:

```text
variant_id
n_orthos
grid_mode
xsize
ysize
any_support_fraction
full_support_fraction
mean_valid_count
min_valid_count
max_valid_count
mean_mad_rgb
p95_mad_rgb
mean_rmse_to_median
p95_rmse_to_median
stable_rmse_threshold
valid_pixels
nodata_pixels
stable_pixels_rmse
unstable_pixels_rmse
stable_fraction_support_rmse
unstable_fraction_support_rmse
```

### 19.1 Support metrics

`any_support_fraction` is the fraction of the canonical grid where at least one orthomosaic has valid data.

`full_support_fraction` is the fraction of the canonical grid where all replicate orthomosaics have valid data.

A large difference between both values indicates support instability.

### 19.2 Deviation metrics

`mean_mad_rgb` and `mean_rmse_to_median` summarize repeated-build pixel deviation.

Lower values indicate more stable orthomosaic products.

The 95th percentile values describe the upper tail of local instability.

### 19.3 Stable / unstable fractions

`stable_fraction_support_rmse` is the fraction of the valid support classified as stable.

`unstable_fraction_support_rmse` is the fraction of the valid support classified as unstable.

Within the valid support, these fractions should sum to 1.

## 20. Mask validation

For Byte masks, `0` is a valid class value.

Therefore, `0` must not be used as NoData.

The analyzer uses:

```text
255 = NoData
```

for mask rasters.

`gdalinfo -stats` can be misleading if statistics are cached or NoData is set incorrectly.

Pixel counting is safer.

Example validation:

```bash
python3 - <<'PY'
from pathlib import Path
import numpy as np
from osgeo import gdal

gdal.UseExceptions()

EXP = Path("/path/to/experiment")

def read_band(path):
    ds = gdal.Open(str(path), gdal.GA_ReadOnly)
    arr = ds.ReadAsArray()
    if arr.ndim == 3:
        arr = arr[0]
    return arr.copy()

for V in ["flat_mesh", "moderate_mesh", "light_mesh"]:
    DIR = EXP / "stability_union" / "variants" / V

    stable = read_band(DIR / "stable_mask_rmse15.tif")
    unstable = read_band(DIR / "unstable_mask_rmse15.tif")

    valid = stable != 255

    print("-----", V)
    print("valid pixels:", int(np.sum(valid)))
    print("stable pixels:", int(np.sum((stable == 1) & valid)))
    print("unstable pixels:", int(np.sum((unstable == 1) & valid)))
    print("both stable and unstable:", int(np.sum((stable == 1) & (unstable == 1) & valid)))
    print("neither stable nor unstable:", int(np.sum((stable == 0) & (unstable == 0) & valid)))
PY
```

Expected logic inside valid support:

```text
both stable and unstable = 0
neither stable nor unstable = 0
```

## 21. Interpretation rules

A variant is more stable when it shows:

```text
higher full_support_fraction
lower mean_mad_rgb
lower p95_mad_rgb
lower mean_rmse_to_median
lower p95_rmse_to_median
higher stable_fraction_support_rmse
lower unstable_fraction_support_rmse
```

These metrics must be interpreted together.

A low RMSE does not prove ecological correctness.

A high stable fraction does not prove geometric accuracy.

The workflow measures repeated-build stability of the exported orthomosaic product.

It does not yet validate whether the product represents the true ground or canopy geometry.

## 22. Relation to change detection

The stability workflow acts as a doorkeeper for change detection.

Fine-scale change detection should not be performed on the entire orthomosaic by default.

The stable mask identifies areas where the orthomosaic product is reproducible under repeated processing.

Potential use:

```text
stable areas
  eligible for fine-scale interpretation or change detection

unstable areas
  mask, flag or interpret separately

no-support areas
  outside valid orthomosaic support
```

For forest and terrain-knoll datasets, instability may occur around:

```text
tree crowns
canopy edges
deadwood
shadows
steep microrelief
seamline boundaries
low-overlap areas
orthomosaic borders
```

For raised-bog datasets, instability may occur around:

```text
ditch edges
wet/dry transitions
lying deadwood
sparse shrubs
isolated trees
shadow boundaries
microtopographic edges
```

## 23. What this workflow does not yet do

The current analyzer does not yet compute local texture correlation or normalized cross-correlation.

It does not yet compare variants directly on a combined stability score.

It does not yet integrate tiepoint density, marker errors, checkpoint errors, seamlines or Metashape internal diagnostics.

It does not yet perform change detection.

It only quantifies repeated-build stability of exported orthomosaic products.

## 24. Planned extensions

Planned additions:

```text
local correlation / NCC
support-instability map
combined stability score
cross-variant comparison
stable-support-only change detection masks
diagnostic overlays from tiepoint and marker error exports
separate dense DSM benchmark
report generator
```

## 25. Recommended working sequence

### Step 1: Create physical project folder

```text
PROJECT_ROOT/
  input-images/
  runs/
```

### Step 2: Place selected images in `input-images/`

Use physical image copies.

Do not use mixed root folders.

Do not store outputs in `input-images/`.

### Step 3: Verify input folder

```bash
find PROJECT_ROOT/input-images -maxdepth 1 -type f | wc -l

find PROJECT_ROOT/input-images -maxdepth 1 -type f \
  | sed 's/.*\.//' \
  | tr '[:upper:]' '[:lower:]' \
  | sort \
  | uniq -c
```

### Step 4: Run reproducibility experiment

```bash
EXP=PROJECT_ROOT/runs/experiment_mesh_variants_reps5

python3 python/reproducibility_runner.py \
  config/experiments/test_mesh_ortho_mof_forest_knoll_rgb.yml \
  --variants config/experiments/repro_variants_mesh_regularization.csv \
  --reps 5 \
  --experiment-dir "$EXP" \
  --metashape-dir /home/creu/apps/metashape-pro
```

### Step 5: Inspect manifest

```bash
column -s, -t "$EXP/manifest.csv" | less -S
```

### Step 6: Run stability analyzer

```bash
python3 python/ortho_stability_analyzer.py \
  "$EXP/manifest.csv" \
  --output-dir "$EXP/stability_union" \
  --grid-mode union \
  --bands 3 \
  --stable-rmse-threshold 15 \
  --overwrite
```

### Step 7: Inspect summary

```bash
column -s, -t "$EXP/stability_union/summary.csv" | less -S
```

### Step 8: Inspect rasters in GIS

Recommended layers:

```text
median_ortho.tif
valid_count.tif
rmse_to_median.tif
stable_mask_rmse15.tif
unstable_mask_rmse15.tif
```

Use transparent styling for masks.
