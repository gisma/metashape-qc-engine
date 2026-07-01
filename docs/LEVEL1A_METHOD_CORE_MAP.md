# Level-1A Method Core Map

Level-1A is the Metashape product-analysis and reproducibility workflow. The repository layout is historical: the method is implemented across `python/`, `scripts/`, and `metashape_qc_engine/cli.py`, rather than in files named `level1a_*`.

This map separates methodological decisions from execution infrastructure. Operational commands are in [RUN_LEVEL1A.md](RUN_LEVEL1A.md).

## Method core versus wrapper

| Layer | Current code | Responsibility |
|---|---|---|
| Preparation | `python/prepare_product_experiment.py` | Materialize one run config and parameter-variant table from an explicit preset |
| Repeated builds | `python/reproducibility_runner.py` | Execute variant/replicate combinations and record attempts in `manifest.csv` |
| Metashape processing | `python/metashape_workflow.py` | Execute configured Metashape build and export operations |
| Stability analyzer | `python/ortho_stability_analyzer.py` | Align successful orthomosaics to a canonical grid and compute spatial stability evidence |
| Evaluation | `python/evaluate_ortho_stability.py` | Rank distinct evidence dimensions and write the selected-product trace |
| User wrapper | `metashape_qc_engine/cli.py`, `scripts/run_metashape_workflow.sh` | Parse commands, resolve Metashape, pass paths, and launch method code |

The wrapper does not define the continuous-stability ranking. The evaluation module does.

## Method sequence

1. Define parameter variants and replicate count.
2. Build each variant repeatedly with Metashape.
3. Record run status and orthomosaic paths in `manifest.csv`.
4. Accept only successful rows with existing orthomosaics for analysis.
5. Verify compatible raster resolution and construct a canonical grid.
6. Align each accepted orthomosaic to that grid.
7. Compute support, median, MAD, RMSE, and threshold masks by variant.
8. Rank continuous stability, threshold behavior, and support persistence separately.
9. Record the primary variant, median product, and closest observed replicate in `selected_product.json`.

## Canonical grid concept

Repeated orthomosaics may have different extents. The analyzer first checks resolution compatibility, then uses one explicit grid mode:

- `union` — union of orthomosaic extents; the default
- `intersection` — common extent only
- `reference` — grid of a named orthomosaic in the manifest set

Aligned rasters are written under `stability_union/aligned/`. Nodata, raster masks, and all-zero RGB pixels are excluded from valid support. Extent instability remains visible as support variation rather than being hidden by comparing only universal overlap.

For each variant and grid cell, the analyzer derives:

- `valid_count.tif` — supporting replicate count
- `median_ortho.tif` — per-band median across valid replicate values
- `mad_rgb.tif` — median absolute deviation summarized across RGB
- `rmse_to_median.tif` — replicate deviation from the per-cell median
- stable and unstable masks at the configured RMSE threshold

## Three separate rankings

### Continuous stability ranking

This is the primary variant ranking. Lower values are preferred in this order:

1. `p95_rmse_to_median`
2. `mean_rmse_to_median`
3. `p95_mad_rgb`
4. `mean_mad_rgb`

It uses continuous deviations and does not depend on a pass/fail threshold.

### Threshold guard ranking

The threshold view prefers higher `stable_fraction_support_rmse`, then lower `unstable_fraction_support_rmse`. It is separate because its result depends on the selected threshold. In `selected_product.json` it is rejection/warning context, not the primary rule.

### Support persistence ranking

Support persistence asks whether the product footprint remains available across replicates. Ordering prefers:

1. lower `support_dropout_footprint`
2. lower `variable_support_fraction_grid`
3. higher `support_persistence_footprint`

`support_persistence_footprint = full_support / any_support`; `support_dropout_footprint = variable_support / any_support`. This separates rectangular-grid occupancy from genuine replicate-to-replicate support loss. Its winner does not automatically replace the continuous-stability winner.

## Median orthomosaic versus medoid replicate

These are distinct:

- The selected variant's `median_ortho.tif` is a pixel-wise statistical composite on the canonical grid. It may not be any individual Metashape build.
- The medoid replicate is the observed successful replicate whose aligned raster has the lowest RGB RMSE to that selected median over common valid pixels.

`selected_product.json` records both modes. The median represents the repeated-build center; the medoid points to a real exported orthomosaic closest to it. Failure to identify a medoid is recorded as a warning.

## Main artifact contract

| Artifact | Method role |
|---|---|
| `config.yml` | concrete Metashape run configuration |
| `variants.csv` | parameter combinations to repeat |
| `manifest.csv` | attempt ledger and orthomosaic source paths |
| `variants/<variant_id>/runs/<run_label>/launcher.log` | per-attempt execution evidence |
| `stability_union/summary.csv` | complete per-variant numeric stability summary |
| `stability_union/summary_key_metrics.tsv` | compact continuously ranked evidence |
| `stability_union/support_valid_count_histogram.tsv` | spatial support-count evidence |
| `stability_union/variants/<variant_id>/*.tif` | median, support, MAD, RMSE, and mask rasters |
| `stability_union/evaluation_report.md` | readable comparison and interpretation |
| `selected_product.json` | primary variant, median/medoid modes, contexts, warnings |
| `qgis_open_selected.*` | launch available selected-product inspection layers |

## Methodological levers

- prepared variant factors and replicate count
- canonical grid mode
- analyzed band count
- stable RMSE threshold
- threshold-review values
- selected Metashape configuration and variant overrides

Changing those controls changes the experiment or its interpretation. The primary continuous ranking itself is fixed in the current evaluator.

## Explicit non-scope

Level-1A does not establish:

- absolute geometric accuracy
- GCP or independent checkpoint validation
- cross-date accuracy or temporal consistency
- ecological, vegetation, habitat, or land-cover classification
- Level-1B segmentation-scale stability
- a final categorical quality class

It measures repeated-build orthomosaic stability under the configured experiment. External accuracy evidence remains **UNRESOLVED** unless supplied outside this workflow.
