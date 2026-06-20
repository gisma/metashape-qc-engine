# Orthomosaic Stability Workflow — Parameter and File Reference

This file is the technical appendix for the main manual:

[Orthomosaic Stability Workflow — Manual](orthomosaic_stability_manual.md)

## Appendix A: Base YAML

Default base YAML:

```yaml
load_project: ""
photo_path: "/datadisk/data/uav/MOF_repro_test_recovered/input-images/"
photo_path_secondary: ""

output_path: "/datadisk/data/uav/MOF_repro_test_recovered/runs/single_run/output/"
project_path: "/datadisk/data/uav/MOF_repro_test_recovered/runs/single_run/psx/"
run_name: "mof_forest_knoll_rgb_mesh_ortho"

project_crs: "EPSG::32632"
camera_crs: "EPSG::4326"

subdivide_task: False
use_cuda: True
gpu_multiplier: 2

addPhotos:
  enabled: True
  separate_calibration_per_path: False
  multispectral: False
  use_rtk: True
  fix_accuracy: 0.000001
  nofix_accuracy: 0.0001

calibrateReflectance:
  enabled: False
  panel_filename: "RP04-1923118-OB.csv"
  use_reflectance_panels: True
  use_sun_sensor: True

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

addGCPs:
  enabled: False
  gcp_crs: "EPSG::32632"
  marker_location_accuracy: 0.1
  marker_projection_accuracy: 8
  optimize_w_gcps_only: True

filterPointsUSGS:
  enabled: True
  rec_thresh_percent: 20
  rec_thresh_absolute: 15
  proj_thresh_percent: 30
  proj_thresh_absolute: 2
  reproj_thresh_percent: 5
  reproj_thresh_absolute: 0.3

optimizeCameras:
  enabled: True
  adaptive_fitting: True
  export: True

buildDepthMaps:
  enabled: False
  downscale: 4
  filter_mode: Metashape.ModerateFiltering
  reuse_depth: False
  max_neighbors: 60

buildPointCloud:
  enabled: False
  keep_depth: True
  max_neighbors: 60
  classify_ground_points: False
  export: False
  classes: "ALL"
  remove_after_export: False

classifyGroundPoints:
  max_angle: 15.0
  max_distance: 1.0
  cell_size: 50.0

buildModel:
  enabled: True
  source_data: Metashape.TiePointsData
  face_count: Metashape.LowFaceCount
  face_count_custom: 100000
  export_local: True
  export_transform: False
  export_georeferenced: True
  export_extension: "obj"
  noiterations: 35

buildDem:
  enabled: False
  classify_ground_points: False
  surface: ["DTM-ptcloud", "DSM-ptcloud", "DSM-mesh"]
  resolution: 0
  export: True
  tiff_big: True
  tiff_tiled: False
  nodata: -32767
  tiff_overviews: True

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

exportReport:
  enabled: False
```

## Appendix B: Variant table

Default file:

```text
config/experiments/repro_variants_mesh_regularization.csv
```

Content:

```csv
variant_id,buildDepthMaps.enabled,buildPointCloud.enabled,buildModel.enabled,buildModel.source_data,buildModel.face_count,buildModel.noiterations,buildDem.enabled,buildDem.surface,buildOrthomosaic.enabled,buildOrthomosaic.surface,buildOrthomosaic.orthoRes
flat_mesh,False,False,True,Metashape.TiePointsData,Metashape.LowFaceCount,80,False,,True,[Mesh],0.05
moderate_mesh,False,False,True,Metashape.TiePointsData,Metashape.LowFaceCount,35,False,,True,[Mesh],0.05
light_mesh,False,False,True,Metashape.TiePointsData,Metashape.MediumFaceCount,5,False,,True,[Mesh],0.05
```

Column logic:

```text
variant_id
  variant name used in folder names and manifest rows

buildModel.face_count
  mesh complexity

buildModel.noiterations
  mesh smoothing strength

buildOrthomosaic.surface
  orthomosaic projection surface

buildOrthomosaic.orthoRes
  orthomosaic export resolution
```

## Appendix C: Core parameter reference

### `photo_path`

Input image folder used by Metashape.

Must point to `PROJECT_ROOT/input-images/`.

### `output_path`

Output folder for direct single-run exports.

The Reproducibility Runner overrides this path per variant and replicate.

### `project_path`

Project folder for a direct single run.

The Reproducibility Runner overrides this path per variant and replicate.

### `run_name`

Base name for output files.

The Reproducibility Runner appends variant and replicate labels.

### `project_crs`

Target CRS for exported geodata.

### `camera_crs`

CRS of camera reference coordinates.

### `use_cuda`

Enables GPU processing in Metashape.

### `addPhotos.multispectral`

Set `False` for standard RGB orthomosaic workflows.

### `addPhotos.use_rtk`

Controls whether accurate camera positions are treated as high-confidence input.

### `alignPhotos.downscale`

Image matching scale.

Lower values are higher quality and more expensive.

### `alignPhotos.keep_keypoints`

Keeps keypoints for diagnostics.

### `filterPointsUSGS`

Sparse point filtering block.

Uses Reconstruction Uncertainty, Projection Accuracy and Reprojection Error thresholds.

### `optimizeCameras`

Optimizes camera parameters after sparse point filtering.

### `buildDepthMaps.enabled`

Disabled in the default mesh workflow.

### `buildPointCloud.enabled`

Disabled in the default mesh workflow.

### `buildModel.source_data`

Default:

```yaml
source_data: Metashape.TiePointsData
```

Builds mesh from tie points.

### `buildModel.face_count`

Controls mesh complexity.

### `buildModel.noiterations`

Controls mesh smoothing.

### `buildOrthomosaic.surface`

Default:

```yaml
surface: ["Mesh"]
```

Uses mesh as orthomosaic projection surface.

### `buildOrthomosaic.orthoRes`

Orthomosaic export resolution.

## Appendix D: Runner manifest columns

`manifest.csv` columns:

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

`status` values:

```text
ok
  run finished and ortho TIFF was found

ok_no_ortho
  run finished but no ortho TIFF was found

failed
  run returned a non-zero code
```

The analyzer uses only rows with `status = ok`.

## Appendix E: Analyzer outputs

Default output folder:

```text
stability_union/
```

Core files:

```text
canonical_grid.json
summary.csv
aligned/
variants/
```

Per-variant rasters:

```text
valid_count.tif
median_ortho.tif
mad_rgb.tif
rmse_to_median.tif
stable_mask_rmse15.tif
unstable_mask_rmse15.tif
```

## Appendix F: Summary columns

Important `summary.csv` columns:

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

Meaning:

```text
full_support_fraction
  fraction of canonical grid valid in all replicates

mean_mad_rgb
  mean robust RGB deviation from median orthomosaic

p95_mad_rgb
  95th percentile of RGB deviation

mean_rmse_to_median
  mean RMSE deviation from median orthomosaic

p95_rmse_to_median
  95th percentile of RMSE deviation

stable_fraction_support_rmse
  fraction of valid support classified as stable

unstable_fraction_support_rmse
  fraction of valid support classified as unstable
```

## Appendix G: Minimal command block

```bash
cd ~/dev/metashape-qc-engine

EXP=/datadisk/data/uav/MOF_repro_test_recovered/runs/experiment_mesh_variants_reps5

METASHAPE_DIR="/home/creu/apps/metashape-pro" \
scripts/run_metashape_workflow.sh config/experiments/test_mesh_ortho_mof_forest_knoll_rgb.yml

python3 python/reproducibility_runner.py \
  config/experiments/test_mesh_ortho_mof_forest_knoll_rgb.yml \
  --variants config/experiments/repro_variants_mesh_regularization.csv \
  --reps 5 \
  --experiment-dir "$EXP" \
  --metashape-dir /home/creu/apps/metashape-pro

python3 python/ortho_stability_analyzer.py \
  "$EXP/manifest.csv" \
  --output-dir "$EXP/stability_union" \
  --grid-mode union \
  --bands 3 \
  --stable-rmse-threshold 15 \
  --overwrite
```
