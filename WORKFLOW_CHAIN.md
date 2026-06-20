# Recovered Fork Workflow Chain

## Active Workflow

The active workflow is the recovered fork-style procedural runner:

- `python/metashape_workflow.py`
- `python/metashape_workflow_functions.py`
- `python/read_yaml.py`
- flat/camelCase YAML configs such as `config/base.yml` and `config/legacy/base2_pre_migration_franzosenwiese.yml`

The runner loads one YAML config, converts Metashape object strings, then calls module-level functions in a fixed order. The workflow is not step-isolated and does not use an object-oriented workflow class.

## Upstream Workflow Not Active

The upstream class-based `MetashapeWorkflow` architecture is not active in this recovered chain. The nested snake_case config schema in `config/config-example.yml` is not the active runtime schema for `python/metashape_workflow.py`.

Do not treat upstream `project:`, `add_photos`, `build_point_cloud`, or `build_orthomosaic` keys as active for this runner unless the workflow is deliberately migrated later.

## R and Config Generation Chain

`R/prep_configs.R` is the restored batch config generator. It expects a directory containing:

- `base.yml`
- `derived.yml`

The script reads `base.yml`, reads config fragments from `derived.yml`, merges each fragment into the base config with `modifyList()`, writes generated `cfg_<run_name>.yml` files, and writes a `config_batch.sh` script that runs `python/metashape_workflow.py` once per generated config.

`R/create_derived_configs.R` provides a function-based helper for generating derived YAML files from a base config and a replacement data frame. It preserves the same flat/camelCase schema when the replacement keys match that schema.

## Config Files

`config/base.yml` is the restored example/default flat-schema config. It is the expected input shape for the active Python runner and the default filename expected by `R/prep_configs.R`.

`config/legacy/base2_pre_migration_franzosenwiese.yml` is a separate/manual fork config with project-specific paths and Ortho+ oriented settings. It uses the same active flat/camelCase schema, including `buildModel.noiterations` and `buildOrthomosaic.orthoRes`.

`config/derived.yml` contains partial config fragments for `R/prep_configs.R`. These fragments are merged into `base.yml` to produce full generated configs. They must target active paths such as `addPhotos.multispectral` and `buildPointCloud`.

`config/config-example.yml` is an upstream reference config. It uses the upstream nested snake_case schema and is not the active schema for the recovered procedural runner.

## YAML Parser

`python/read_yaml.py` loads YAML with `yaml.SafeLoader`, then walks the resulting dictionary and converts string values containing `Metashape` into live Metashape objects with `eval()`.

This is why active configs can contain values such as:

- `Metashape.ReferencePreselectionSource`
- `Metashape.ModerateFiltering`
- `Metashape.MosaicBlending`

The parser is imported by `python/metashape_workflow.py` as either `from python import read_yaml` or `import read_yaml`, depending on how the script is launched.

## Runner Startup

`python/metashape_workflow.py` starts the chain.

Config selection is:

```python
if len(sys.argv) > 1:
    config_file = sys.argv[1]
else:
    config_file = manual_config_file
```

Then it calls:

```python
cfg = read_yaml.read_yaml(config_file)
```

The parsed config is passed into the procedural functions in `python/metashape_workflow_functions.py`.

## Function Order

The runner calls the workflow functions in this order:

1. `project_setup(cfg, config_file)`
2. `enable_and_log_gpu(log, cfg)`
3. `add_photos(doc, cfg)` when `photo_path` is non-empty and `addPhotos.enabled` is true
4. `calibrate_reflectance(doc, cfg)` when enabled
5. `align_photos(doc, log, run_id, cfg)` when enabled
6. `reset_region(doc)` after alignment
7. `filter_points_usgs_part1(doc, log, cfg)` when enabled
8. `reset_region(doc)` after filtering part 1
9. `add_gcps(doc, cfg)` when enabled
10. `reset_region(doc)` after GCP import
11. `optimize_cameras(doc, log, run_id, cfg)` when enabled
12. `reset_region(doc)` after camera optimization
13. `filter_points_usgs_part2(doc, log, cfg)` when enabled
14. `reset_region(doc)` after filtering part 2
15. `build_depth_maps(doc, log, cfg)` when enabled
16. `build_point_cloud(doc, log, run_id, cfg)` when enabled
17. `build_model(doc, log, run_id, cfg)` when enabled
18. `build_dem_orthomosaic(doc, log, run_id, cfg)` always called; internal config flags decide DEM and orthomosaic work
19. `add_align_secondary_photos(doc, log, run_id, cfg)` when `photo_path_secondary` is non-empty
20. `export_report(doc, run_id, cfg)`
21. `finish_run(log, config_file)`

Helper functions used inside those steps include `export_cameras()`, `classify_ground_points()`, and `build_export_orthomosaic()`.

## Ortho, DEM, and Orthomosaic Logic

DEM and orthomosaic behavior is concentrated in:

- `build_model()`
- `build_dem_orthomosaic()`
- `build_export_orthomosaic()`

`build_model()` builds and exports the model/mesh according to `buildModel` settings.

`build_dem_orthomosaic()` handles DEM surfaces from `buildDem.surface`, including `DSM-ptcloud`, `DTM-ptcloud`, and `DSM-mesh`. It exports DEM rasters when `buildDem.export` is true.

`build_export_orthomosaic()` builds an orthomosaic from either mesh/model data or active elevation data. It uses the active fork key `buildOrthomosaic.orthoRes` for orthomosaic resolution and exports raster output when `buildOrthomosaic.export` is true.

## Manual Run

Run with an explicit config path so the old local fallback path is not used:

```bash
python python/metashape_workflow.py config/base.yml
```

or:

```bash
python python/metashape_workflow.py config/legacy/base2_pre_migration_franzosenwiese.yml
```

In production, run this with the Python interpreter provided by Agisoft Metashape or an environment where the `Metashape` module is installed.

## Known Caveats

- The Agisoft `Metashape` Python module is required. Ordinary system Python can parse the files but cannot execute the real workflow.
- The no-argument fallback path is old/local: `~/dev/metashape-qc-engine/config/base.yml`.
- `config/config-example.yml` is an upstream reference file, not the active schema for this recovered workflow.
