# Orthomosaic Stability Workflow Manual

This manual describes the standard workflow for repeatable UAV orthomosaic experiments with Metashape and stability analysis.

The workflow has three stages:

1. Single Metashape orthomosaic run
2. Variants x replicates with the reproducibility runner
3. Canonical-grid stability analysis

Full YAML and parameter details are in the appendix:
[Parameter and File Reference](orthomosaic_stability_reference.md)

## Product-oriented preparation layer

The product-oriented workflow separates dataset identity from concrete run paths:

`image directory`
is the actual directory containing the input images used by Metashape.

`product id`
is the logical dataset or product identifier used in generated names.

`output root`
is the parent directory where experiment runs are created.

`experiment directory`
is the concrete run directory for one prepared experiment.

`preset`
is an experiment-design template. It is not a dataset.

The preparation script writes the generated `config.yml` and `variants.csv` into the experiment directory. These generated files are run artifacts and should not be committed.

Example:

```bash
python3 python/prepare_product_experiment.py \
  --image-dir /data/product/images \
  --product-id product-001 \
  --preset config/experiments/presets/mesh_facecount_smoothing_3x3.json \
  --reps 10 \
  --output-root /data/metashape-qc-runs
```

This creates a product-specific experiment directory under the output root and prints the `metashape-qc experiment` command that uses the generated config and variants.

### Factor overrides

The preset defines the default factor matrix. For a prepared product experiment, the matrix can be adjusted from the command line:

```text
--factor COLUMN=VALUE1,VALUE2,...
--face-counts VALUE1,VALUE2,...
--smoothing VALUE1,VALUE2,...
--variant-id-template TEMPLATE
```

`--factor` overrides or adds one factor column and may be repeated. `--face-counts` is a shortcut for `buildModel.face_count_custom`. `--smoothing` is a shortcut for `buildModel.noiterations`. `--variant-id-template` overrides the preset template used to generate `variant_id` values.

## 1. Project Structure

Each dataset gets its own project directory.

```text
PROJECT_ROOT/
  input-images/
  runs/
```

Input imagery is stored only in:

```text
PROJECT_ROOT/input-images/
```

All generated products are written below:

```text
PROJECT_ROOT/runs/
```

Example:

```text
/datadisk/data/uav/MOF_repro_test_recovered/
  input-images/
    DJI_....JPG
    DJI_....JPG
    ...
  runs/
```

`input-images/` is the clean Metashape input folder. It contains only the images that should be processed. `runs/` contains Metashape projects, orthomosaics, logs, manifests, and stability products.

The central dataset control file is:

```text
config/experiments/test_mesh_ortho_mof_forest_knoll_rgb.yml
```

It points to `input-images/` and to output directories below `runs/`.

The variant matrix is:

```text
config/experiments/repro_variants_mesh_regularization.csv
```

It defines the three standard variants `flat_mesh`, `moderate_mesh`, and `light_mesh`.

## 2. Single Metashape Orthomosaic Run

Minimal default call:

```bash
cd ~/dev/metashape-qc-engine

METASHAPE_DIR="/home/creu/apps/metashape-pro" \
scripts/run_metashape_workflow.sh config/experiments/test_mesh_ortho_mof_forest_knoll_rgb.yml
```

This run executes exactly the base YAML. It creates one Metashape run without variants and without repeated replicates.

The single run checks whether the base workflow works: images are loaded, photos are aligned, tie points are filtered, cameras are optimized, a mesh is built from tie points, the mesh is smoothed, and that mesh is used as the orthomosaic projection surface.

The default is intentionally mesh-based:

```text
TiePointsData -> smoothed mesh -> mesh orthomosaic
```

Depth maps, dense cloud generation, and DEM/DSM generation are disabled by default. The current test is not asking for the best dense reconstruction; it evaluates the stability of orthoprojection over a regularized mesh surface.

The key default setting is:

```yaml
buildOrthomosaic:
  surface: ["Mesh"]
```

and:

```yaml
buildModel:
  source_data: Metashape.TiePointsData
```

The orthomosaic is therefore not built from a DSM. It is built from a mesh that was generated from tie points and smoothed.

The single-run output goes to the paths configured in the base YAML:

```text
PROJECT_ROOT/runs/single_run/psx/
PROJECT_ROOT/runs/single_run/output/
```

## 3. Variants x Replicates

Minimal default call:

```bash
cd ~/dev/metashape-qc-engine

EXP=/datadisk/data/uav/MOF_repro_test_recovered/runs/experiment_mesh_variants_reps5

python3 python/reproducibility_runner.py \
  config/experiments/test_mesh_ortho_mof_forest_knoll_rgb.yml \
  --variants config/experiments/repro_variants_mesh_regularization.csv \
  --reps 5 \
  --experiment-dir "$EXP" \
  --metashape-dir /home/creu/apps/metashape-pro
```

This step is the actual reproducibility experiment.

The runner takes the base YAML and creates concrete YAML files from it: one per variant and replicate. Each generated YAML has its own output directory, project directory, and `run_name`.

With the default setup this creates:

```text
3 variants x 5 replicates = 15 Metashape runs
```

The three default variants test regularization of the projection surface:

```text
flat_mesh      strongly smoothed, simple mesh
moderate_mesh  medium mesh regularization
light_mesh     more detailed, lightly smoothed mesh
```

The main parameter is:

```yaml
buildModel:
  noiterations: ...
```

It controls mesh smoothing.

The second important parameter is:

```yaml
buildModel:
  face_count: ...
```

It controls mesh complexity.

The standard variants represent a simple axis:

```text
strongly regularized -> medium regularized -> weakly regularized
```

The runner produces an experiment directory:

```text
PROJECT_ROOT/runs/experiment_mesh_variants_reps5/
  manifest.csv
  variants/
    flat_mesh/
    moderate_mesh/
    light_mesh/
```

The key file is:

```text
manifest.csv
```

The manifest is the experiment index. It records which variant and replicate correspond to which Metashape project, launcher log, and exported orthomosaic.

## 4. Stability Analysis

Minimal default call:

```bash
python3 python/ortho_stability_analyzer.py \
  "$EXP/manifest.csv" \
  --output-dir "$EXP/stability_union" \
  --grid-mode union \
  --bands 3 \
  --stable-rmse-threshold 15 \
  --overwrite
```

The analyzer reads `manifest.csv` and uses successful orthomosaic exports.

Metashape orthomosaics from repeated runs can have slightly different raster extents. Before comparison, they are warped to one shared analysis raster. This raster is the canonical grid.

The default is:

```text
--grid-mode union
```

`union` means the shared raster covers the combined extent of all orthomosaics. This preserves changing borders and variable image support.

For RGB orthomosaics the default is:

```text
--bands 3
```

The first three bands are analyzed as RGB.

The stability mask is generated with this threshold:

```text
--stable-rmse-threshold 15
```

A pixel is stable when it is valid in all replicates and its RMSE deviation from the median orthomosaic is at most 15 DN. For 8-bit RGB data, the image scale is 0-255.

The main analyzer products are:

```text
valid_count.tif
median_ortho.tif
mad_rgb.tif
rmse_to_median.tif
summary.csv
threshold_review/rmse15/variants/<variant_id>/quality_flag_rmse15.tif
```

`valid_count.tif` shows how many replicates have valid image support for each pixel.

`median_ortho.tif` is the robust median orthomosaic for one variant.

`mad_rgb.tif` shows robust deviations from the median image.

`rmse_to_median.tif` shows RMSE deviations from the median image.

`summary.csv` summarizes stability by variant.

Threshold review writes separate threshold quality flags under
`threshold_review/rmse<THR>/variants/<variant_id>/quality_flag_rmse<THR>.tif`.
These Byte GeoTIFFs use 0 for invalid/no support, 1 for stable/usable, and 2
for unstable/review or exclude under that RMSE threshold. Threshold quality
flags do not modify or clean the orthomosaic.

## 5. Reading Results

A variant is more stable when, overall, it has:

```text
more complete image support
lower MAD values
lower RMSE values
a higher stable support fraction
a lower unstable support fraction
```

The most important summary columns are:

```text
full_support_fraction
mean_mad_rgb
p95_mad_rgb
mean_rmse_to_median
p95_rmse_to_median
stable_fraction_support_rmse
unstable_fraction_support_rmse
```

These values measure reproducibility of the orthomosaic product. They do not prove absolute geometric correctness. A variant can be reproducible and still be geometrically wrong. Geometric accuracy requires separate validation.

For QGIS inspection, these layers are central:

```text
median_ortho.tif
valid_count.tif
rmse_to_median.tif
threshold_review/rmse15/variants/<variant_id>/quality_flag_rmse15.tif
```

`median_ortho.tif` is useful as a background. `rmse_to_median.tif` shows
deviation hotspots. `valid_count.tif` shows stable or unstable image support.
The threshold quality flag separates invalid/no support, stable/usable, and
unstable/review-or-exclude areas without modifying or cleaning the orthomosaic.

## 6. Changing Defaults

Most settings remain unchanged. Normally only these values are adjusted:

`photo_path`
points to the current dataset's `input-images/` folder.

`output_path` and `project_path`
point to subdirectories below `runs/`.

`run_name`
names the dataset and workflow.

`project_crs`
sets the target coordinate reference system for exports.

`orthoRes`
sets the orthomosaic resolution.

`--reps`
sets the number of replicates.

`--stable-rmse-threshold`
sets the threshold for stable pixels.

The full parameter reference is in the appendix:
[Parameter and File Reference](orthomosaic_stability_reference.md)

## Evaluation

After the Metashape replicates finish, run evaluation with one script:

```bash
cd ~/dev/metashape-qc-engine

python3 python/evaluate_ortho_stability.py \
  /datadisk/data/uav/MOF_repro_test_recovered/runs/experiment_mesh_variants_reps5
```

The script runs the stability analyzer, reads `summary.csv`, and writes a compact evaluation report.

The results are written to:

```text
PROJECT_ROOT/runs/experiment_mesh_variants_reps5/stability_union/
```

The most important files are:

```text
evaluation_report.md
summary_key_metrics.tsv
support_valid_count_histogram.tsv
qgis_layers.txt
summary.csv
../qgis_open_selected.sh
../qgis_open_selected.bat
../qgis_open_threshold_review.sh
../qgis_open_threshold_review.bat
../threshold_review/threshold_sensitivity.tsv
../threshold_review/threshold_winners.tsv
```

`evaluation_report.md` contains the compact variant evaluation.

`summary_key_metrics.tsv` contains the key metrics in a reduced table.

`support_valid_count_histogram.tsv` contains support histograms derived from `valid_count.tif`.

`qgis_layers.txt` lists the relevant raster products for spatial inspection.

`summary.csv` contains the full analyzer result table.

The evaluator also writes standard QGIS launchers at the experiment directory
root. Both POSIX `.sh` and Windows `.bat` launchers are generated. Launcher
raster arguments are relative to the experiment directory; Windows users may
set `QGIS_BIN` to override the default `qgis-bin.exe`.

`threshold_review/threshold_sensitivity.tsv` and
`threshold_review/threshold_winners.tsv` are derived from existing
`rmse_to_median.tif` rasters. This threshold review does not rerun Metashape,
does not rerun the full stability analyzer, and is a guard / sensitivity layer
rather than the primary product selector.

The compact default table is sorted by continuous image-value stability:

```text
1. lower p95 RMSE to the median orthomosaic
2. lower mean RMSE to the median orthomosaic
3. lower p95 MAD RGB
4. lower mean MAD RGB
```

The evaluator also reports separate threshold quality-flag and
support-persistence candidates. These candidate categories are not collapsed
into one canonical winner.

This evaluation describes reproducibility of the orthomosaic product. It does not replace independent geometric validation.

### Selected product trace

`selected_product.json` records the technical selection trace produced by evaluation.

Continuous stability selects the primary variant. Support persistence is feasibility and coverage context. Threshold quality-flag metrics are rejection and warning guard context.

`median_ortho` is the robust analysis product for the selected variant. `medoid_replicate` is the original Metashape orthomosaic closest to the selected variant median.

Warnings require review. The selected product trace is not an automatic scientific correctness claim.

### Evaluator dependencies

`metashape-qc evaluate` requires `numpy`, `rasterio`, and GDAL Python bindings. The project virtual environment must be able to import GDAL array support:

```bash
python3 -c "from osgeo import gdal_array"
```

Use the project helper inside the virtual environment:

```bash
scripts/install_evaluator_deps.sh
```
