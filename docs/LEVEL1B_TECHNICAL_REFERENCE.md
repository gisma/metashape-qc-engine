# Level-1b technical reference
Generated from `python_api_inventory.json` in `level1_doc_bundle`.
## Repository state from bundle
```text
M metashape_qc_engine/level1b_scale_distribution.py
 M tests/test_level1b_scale_distribution.py
?? metashape_qc_engine/level1b_candidate_stability.py
?? tests/test_level1b_candidate_stability.py
```
Changed tracked files:

```text
metashape_qc_engine/level1b_scale_distribution.py
tests/test_level1b_scale_distribution.py
```
## Module overview
| step | module | main config | main run function |
|---|---|---|---|
| 1 | `metashape_qc_engine.level1b_preflight` | `Level1BPreflightConfig` | `run_preflight` |
| 2 | `metashape_qc_engine.level1b_valid_mask` | `Level1BValidMaskConfig` | `run_valid_mask_step` |
| 3 | `metashape_qc_engine.level1b_channels` | `Level1BChannelConfig` | `run_channel_construction_step` |
| 4 | `metashape_qc_engine.level1b_scaling` | `Level1BScalingConfig` | `run_scaling_step` |
| 5 | `metashape_qc_engine.level1b_pca` | `Level1BPCAConfig` | `run_pca_step` |
| 6 | `metashape_qc_engine.level1b_scale_distribution` | `Level1BScaleDistributionConfig` | `run_scale_distribution_step` |
| 7 | `metashape_qc_engine.level1b_feature_range` | `Level1BFeatureRangeConfig` | `run_feature_range_assignment_step` |
| 8 | `metashape_qc_engine.level1b_perturbations` | `Level1BPerturbationConfig` | `run_local_perturbation_step` |
| 9 | `metashape_qc_engine.level1b_one_scale_segmentation` | `Level1BOneScaleSegmentationConfig` | `run_one_scale_segmentation_smoke` |
| 10 | `metashape_qc_engine.level1b_hoover_compare` | `Level1BHooverCompareConfig` | `run_hoover_compare` |
| 11 | `metashape_qc_engine.level1b_candidate_stability` | `Level1BCandidateStabilityConfig` | `run_candidate_stability` |

## Output layout

```text
RUN_ROOT/
  _driver_logs/
  _driver_reports/
  level1b/
    reports/preflight.json
    mask/valid_mask.tif
    mask/valid_mask_report.json
    channels/proxy_stack.tif
    channels/channel_report.json
    scaling/scaled_feature_stack.tif
    scaling/scaling_report.json
    pca/pca_feature_stack.tif
    pca/pca_report.json
    scales/scale_candidates.csv
    scales/scale_candidates.json
    ranger/ranger_candidates.csv
    ranger/ranger_candidates.json
    ranger/scale_candidates_with_ranger.csv
    ranger/scale_candidates_with_ranger.json
    perturbations/perturbation_candidates.csv
    perturbations/perturbation_candidates.json
    stability/scale_stability.csv
    stability/scale_stability.json
```
## Dataclasses and functions

### Preflight

Module: `metashape_qc_engine.level1b_preflight`

Constructor: `Level1BPreflightConfig(candidate_id: 'str', input_path: 'str | Path', output_dir: 'str | Path', tmp_dir: 'str | Path | None' = None, input_type: 'str' = 'rgb', valid_mask_path: 'str | Path | None' = None, band_roles: 'Iterable[str] | None' = None, declared_channels: 'Iterable[str] | None' = None, mask_contract: 'str' = 'optional', candidate_state: 'Any' = None, required_otb_apps: 'Iterable[str] | None' = None) -> None`

| field | required | default | type |
|---|---:|---|---|
| `candidate_id` | yes | `—` | `str` |
| `input_path` | yes | `—` | `str | Path` |
| `output_dir` | yes | `—` | `str | Path` |
| `tmp_dir` | no | `None` | `str | Path | None` |
| `input_type` | no | `'rgb'` | `str` |
| `valid_mask_path` | no | `None` | `str | Path | None` |
| `band_roles` | no | `None` | `Iterable[str] | None` |
| `declared_channels` | no | `None` | `Iterable[str] | None` |
| `mask_contract` | no | `'optional'` | `str` |
| `candidate_state` | no | `None` | `Any` |
| `required_otb_apps` | no | `None` | `Iterable[str] | None` |

Functions:

- `discover_otb_app(app_name: 'str') -> 'str | None'`
- `discover_required_otb_apps(required_apps: 'Iterable[str] | None' = None) -> 'tuple[dict[str, dict[str, str | bool | None]], str | None]'`
- `build_level1b_layout(output_dir: 'str | Path', tmp_dir: 'str | Path | None' = None) -> 'dict[str, Path]'`
- `validate_input_contract(input_type: 'str', band_roles: 'Iterable[str] | None', declared_channels: 'Iterable[str] | None') -> 'tuple[str, list[str] | None, list[str] | None, dict[str, bool], list[str]]'`
- `validate_mask_contract(mask_contract: 'str', valid_mask_path: 'Path | None') -> 'tuple[str, str, dict[str, bool], list[str]]'`
- `run_preflight(config: 'Level1BPreflightConfig') -> 'dict[str, Any]'`

### Valid mask

Module: `metashape_qc_engine.level1b_valid_mask`

Constructor: `Level1BValidMaskConfig(candidate_id: str, input_path: str | pathlib.Path, output_dir: str | pathlib.Path, tmp_dir: str | pathlib.Path | None = None, nodata_values: dict[int, float] | None = None, alpha_band_index: int | None = None, alpha_valid_min: float = 1.0, black_border_enabled: bool = True, black_border_band_indices: tuple[int, ...] = (1, 2, 3), invalid_rgb_tuples: tuple[tuple[float, float, float], ...] = ((0.0, 0.0, 0.0), (255.0, 255.0, 255.0)), black_border_invalid_values: tuple[float, ...] | None = None, otb_bin_dir: str | pathlib.Path | None = None, output_filename: str = 'valid_mask.tif', report_filename: str = 'valid_mask_report.json', ram_mb: int | None = None, overwrite: bool = False, dry_run: bool = False) -> None`

| field | required | default | type |
|---|---:|---|---|
| `candidate_id` | yes | `—` | `<class 'str'>` |
| `input_path` | yes | `—` | `str | pathlib.Path` |
| `output_dir` | yes | `—` | `str | pathlib.Path` |
| `tmp_dir` | no | `None` | `str | pathlib.Path | None` |
| `nodata_values` | no | `None` | `dict[int, float] | None` |
| `alpha_band_index` | no | `None` | `int | None` |
| `alpha_valid_min` | no | `1.0` | `<class 'float'>` |
| `black_border_enabled` | no | `True` | `<class 'bool'>` |
| `black_border_band_indices` | no | `(1, 2, 3)` | `tuple[int, ...]` |
| `invalid_rgb_tuples` | no | `((0.0, 0.0, 0.0), (255.0, 255.0, 255.0))` | `tuple[tuple[float, float, float], ...]` |
| `black_border_invalid_values` | no | `None` | `tuple[float, ...] | None` |
| `otb_bin_dir` | no | `None` | `str | pathlib.Path | None` |
| `output_filename` | no | `'valid_mask.tif'` | `<class 'str'>` |
| `report_filename` | no | `'valid_mask_report.json'` | `<class 'str'>` |
| `ram_mb` | no | `None` | `int | None` |
| `overwrite` | no | `False` | `<class 'bool'>` |
| `dry_run` | no | `False` | `<class 'bool'>` |

Functions:

- `build_level1b_mask_layout(output_dir: str | pathlib.Path, tmp_dir: str | pathlib.Path | None = None) -> dict[str, pathlib.Path]`
- `discover_bandmathx(otb_bin_dir: str | pathlib.Path | None = None) -> tuple[str | None, str | None]`
- `validate_valid_mask_config(config: metashape_qc_engine.level1b_valid_mask.Level1BValidMaskConfig, layout: dict[str, pathlib.Path]) -> tuple[dict[str, bool], list[str]]`
- `build_valid_mask_expression(config: metashape_qc_engine.level1b_valid_mask.Level1BValidMaskConfig) -> tuple[str | None, list[str]]`
- `build_valid_mask_command(config: metashape_qc_engine.level1b_valid_mask.Level1BValidMaskConfig, otb_app_path: str, valid_mask_path: pathlib.Path) -> list[str]`
- `run_valid_mask_step(config: metashape_qc_engine.level1b_valid_mask.Level1BValidMaskConfig) -> dict[str, object]`

### Channels/proxy stack

Module: `metashape_qc_engine.level1b_channels`

Constructor: `Level1BChannelConfig(candidate_id: 'str', input_path: 'str | Path', output_dir: 'str | Path', input_type: 'str', valid_mask_path: 'str | Path', pixel_size_m: 'float', tmp_dir: 'str | Path | None' = None, rgb_band_indices: 'tuple[int, int, int]' = (1, 2, 3), declared_channels: 'tuple[str, ...] | None' = None, declared_band_indices: 'tuple[int, ...] | None' = None, tex_100m_radius_m: 'float' = 1.0, tex_200m_radius_m: 'float' = 2.0, output_filename: 'str | None' = None, report_filename: 'str' = 'channel_report.json', overwrite: 'bool' = False, dry_run: 'bool' = False) -> None`

| field | required | default | type |
|---|---:|---|---|
| `candidate_id` | yes | `—` | `str` |
| `input_path` | yes | `—` | `str | Path` |
| `output_dir` | yes | `—` | `str | Path` |
| `input_type` | yes | `—` | `str` |
| `valid_mask_path` | yes | `—` | `str | Path` |
| `pixel_size_m` | yes | `—` | `float` |
| `tmp_dir` | no | `None` | `str | Path | None` |
| `rgb_band_indices` | no | `(1, 2, 3)` | `tuple[int, int, int]` |
| `declared_channels` | no | `None` | `tuple[str, ...] | None` |
| `declared_band_indices` | no | `None` | `tuple[int, ...] | None` |
| `tex_100m_radius_m` | no | `1.0` | `float` |
| `tex_200m_radius_m` | no | `2.0` | `float` |
| `output_filename` | no | `None` | `str | None` |
| `report_filename` | no | `'channel_report.json'` | `str` |
| `overwrite` | no | `False` | `bool` |
| `dry_run` | no | `False` | `bool` |

Functions:

- `build_level1b_channel_layout(output_dir, tmp_dir=None) -> 'dict[str, Path]'`
- `discover_channel_otb_apps(input_type) -> 'dict[str, str | None]'`
- `validate_channel_config(config, layout) -> 'tuple[dict[str, bool], list[str], dict[str, object]]'`
- `build_rgb_proxy_commands(config, apps, layout, output_path) -> 'tuple[list[list[str]], dict[str, object]]'`
- `build_multichannel_stack_command(config, apps, output_path, normalized_declared_channels, normalized_declared_band_indices) -> 'tuple[list[str], dict[str, object]]'`
- `run_channel_construction_step(config) -> 'dict[str, object]'`

### Scaling

Module: `metashape_qc_engine.level1b_scaling`

Constructor: `Level1BScalingConfig(candidate_id: 'str', feature_stack_path: 'str | Path', valid_mask_path: 'str | Path', output_dir: 'str | Path', band_count: 'int', tmp_dir: 'str | Path | None' = None, background_value: 'float' = -999999.0, output_filename: 'str' = 'scaled_feature_stack.tif', parameters_xml_filename: 'str' = 'scaling_parameters.xml', parameters_json_filename: 'str' = 'scaling_parameters.json', report_filename: 'str' = 'scaling_report.json', overwrite: 'bool' = False, dry_run: 'bool' = False) -> None`

| field | required | default | type |
|---|---:|---|---|
| `candidate_id` | yes | `—` | `str` |
| `feature_stack_path` | yes | `—` | `str | Path` |
| `valid_mask_path` | yes | `—` | `str | Path` |
| `output_dir` | yes | `—` | `str | Path` |
| `band_count` | yes | `—` | `int` |
| `tmp_dir` | no | `None` | `str | Path | None` |
| `background_value` | no | `-999999.0` | `float` |
| `output_filename` | no | `'scaled_feature_stack.tif'` | `str` |
| `parameters_xml_filename` | no | `'scaling_parameters.xml'` | `str` |
| `parameters_json_filename` | no | `'scaling_parameters.json'` | `str` |
| `report_filename` | no | `'scaling_report.json'` | `str` |
| `overwrite` | no | `False` | `bool` |
| `dry_run` | no | `False` | `bool` |

Functions:

- `build_level1b_scaling_layout(output_dir, tmp_dir=None) -> 'dict[str, Path]'`
- `discover_scaling_otb_apps() -> 'dict[str, str | None]'`
- `validate_scaling_config(config, layout, apps) -> 'tuple[dict[str, bool], list[str]]'`
- `build_masked_feature_stack_command(config, apps, layout) -> 'list[str]'`
- `build_statistics_command(config, apps, layout) -> 'list[str]'`
- `parse_scaling_statistics_xml(xml_path, band_count) -> 'dict[str, list[float]]'`
- `build_zscore_scaling_command(config, apps, layout, stats) -> 'list[str]'`
- `run_scaling_step(config) -> 'dict[str, object]'`

### PCA

Module: `metashape_qc_engine.level1b_pca`

Constructor: `Level1BPCAConfig(candidate_id: 'str', scaled_feature_stack_path: 'str | Path', valid_mask_path: 'str | Path', output_dir: 'str | Path', band_count: 'int', pca_components: 'int', tmp_dir: 'str | Path | None' = None, background_value: 'float' = -999999.0, output_filename: 'str' = 'pca_feature_stack.tif', report_filename: 'str' = 'pca_report.json', overwrite: 'bool' = False, dry_run: 'bool' = False) -> None`

| field | required | default | type |
|---|---:|---|---|
| `candidate_id` | yes | `—` | `str` |
| `scaled_feature_stack_path` | yes | `—` | `str | Path` |
| `valid_mask_path` | yes | `—` | `str | Path` |
| `output_dir` | yes | `—` | `str | Path` |
| `band_count` | yes | `—` | `int` |
| `pca_components` | yes | `—` | `int` |
| `tmp_dir` | no | `None` | `str | Path | None` |
| `background_value` | no | `-999999.0` | `float` |
| `output_filename` | no | `'pca_feature_stack.tif'` | `str` |
| `report_filename` | no | `'pca_report.json'` | `str` |
| `overwrite` | no | `False` | `bool` |
| `dry_run` | no | `False` | `bool` |

Functions:

- `build_level1b_pca_layout(output_dir, tmp_dir=None) -> 'dict[str, Path]'`
- `discover_pca_otb_apps() -> 'dict[str, str | None]'`
- `validate_pca_config(config, layout, apps) -> 'tuple[dict[str, bool], list[str]]'`
- `build_pca_command(config, apps, layout) -> 'list[str]'`
- `build_pca_remask_command(config, apps, layout) -> 'list[str]'`
- `run_pca_step(config) -> 'dict[str, object]'`

### Scale distribution

Module: `metashape_qc_engine.level1b_scale_distribution`

Constructor: `Level1BScaleDistributionConfig(candidate_id: 'str', output_dir: 'str | Path', pixel_size_m: 'float | None', scale_mode: 'str', metric_radius_m: 'tuple[float, ...] | None' = None, structure_radius_m: 'tuple[float, ...] | None' = None, proxy_stack_path: 'Path | None' = None, feature_stack_path: 'Path | None' = None, feature_space_stack_path: 'Path | None' = None, valid_mask_path: 'Path | None' = None, proxy_structure_mode: 'str' = 'texture_preferred', proxy_band_indices: 'tuple[int, ...] | None' = None, texture_band_indices: 'tuple[int, ...] | None' = None, infer_texture_bands_from_metadata: 'bool' = True, infer_texture_support_from_proxy: 'bool' = True, sampling_regime: 'str' = 'auto', sampling_regime_method: 'str' = 'structure_support_to_gsd_ratio', structure_support_max_m: 'float | None' = None, infer_structure_support_from_proxy: 'bool' = True, undersample_support_px_max: 'float' = 3.0, balanced_support_px: 'float' = 10.0, oversample_support_px_min: 'float' = 30.0, oversample_default_upper_radius_factor: 'float' = 2.5, balanced_default_upper_radius_factor: 'float | None' = None, undersample_default_upper_radius_factor: 'float | None' = None, enforce_oversample_envelope: 'bool' = True, report_sampling_memberships: 'bool' = True, texture_band_name_patterns: 'tuple[str, ...]' = ('TEX', 'texture', 'TEXTURE'), fallback_standard_proxy_texture_band_indices: 'tuple[int, ...] | None' = None, structure_mask_path: 'Path | None' = None, structure_raster_path: 'Path | None' = None, structure_band_index: 'int' = 1, structure_threshold: 'float | None' = None, structure_threshold_operator: 'str' = 'gt', chm_p95_path: 'Path | None' = None, canopy_fraction_path: 'Path | None' = None, chm_thr_m: 'float' = 2.0, evidence_quantiles: 'tuple[float, ...]' = (0.6, 0.7, 0.8), patch_radius_quantiles: 'tuple[float, ...]' = (0.25, 0.4, 0.55, 0.7, 0.85, 0.95), min_radius_m: 'float | None' = None, min_spatialr_px: 'int' = 1, min_patch_px: 'int' = 4, min_patch_area_m2: 'float | None' = None, texture_support_max_m: 'float | None' = None, segment_similarity_radius_max_m: 'float | None' = None, target_structure_max_m: 'float | None' = None, upper_radius_factor: 'float' = 2.5, max_radius_m: 'float | None' = None, output_csv_filename: 'str' = 'scale_candidates.csv', output_json_filename: 'str' = 'scale_candidates.json', overwrite: 'bool' = False) -> None`

| field | required | default | type |
|---|---:|---|---|
| `candidate_id` | yes | `—` | `str` |
| `output_dir` | yes | `—` | `str | Path` |
| `pixel_size_m` | yes | `—` | `float | None` |
| `scale_mode` | yes | `—` | `str` |
| `metric_radius_m` | no | `None` | `tuple[float, ...] | None` |
| `structure_radius_m` | no | `None` | `tuple[float, ...] | None` |
| `proxy_stack_path` | no | `None` | `Path | None` |
| `feature_stack_path` | no | `None` | `Path | None` |
| `feature_space_stack_path` | no | `None` | `Path | None` |
| `valid_mask_path` | no | `None` | `Path | None` |
| `proxy_structure_mode` | no | `'texture_preferred'` | `str` |
| `proxy_band_indices` | no | `None` | `tuple[int, ...] | None` |
| `texture_band_indices` | no | `None` | `tuple[int, ...] | None` |
| `infer_texture_bands_from_metadata` | no | `True` | `bool` |
| `infer_texture_support_from_proxy` | no | `True` | `bool` |
| `sampling_regime` | no | `'auto'` | `str` |
| `sampling_regime_method` | no | `'structure_support_to_gsd_ratio'` | `str` |
| `structure_support_max_m` | no | `None` | `float | None` |
| `infer_structure_support_from_proxy` | no | `True` | `bool` |
| `undersample_support_px_max` | no | `3.0` | `float` |
| `balanced_support_px` | no | `10.0` | `float` |
| `oversample_support_px_min` | no | `30.0` | `float` |
| `oversample_default_upper_radius_factor` | no | `2.5` | `float` |
| `balanced_default_upper_radius_factor` | no | `None` | `float | None` |
| `undersample_default_upper_radius_factor` | no | `None` | `float | None` |
| `enforce_oversample_envelope` | no | `True` | `bool` |
| `report_sampling_memberships` | no | `True` | `bool` |
| `texture_band_name_patterns` | no | `('TEX', 'texture', 'TEXTURE')` | `tuple[str, ...]` |
| `fallback_standard_proxy_texture_band_indices` | no | `None` | `tuple[int, ...] | None` |
| `structure_mask_path` | no | `None` | `Path | None` |
| `structure_raster_path` | no | `None` | `Path | None` |
| `structure_band_index` | no | `1` | `int` |
| `structure_threshold` | no | `None` | `float | None` |
| `structure_threshold_operator` | no | `'gt'` | `str` |
| `chm_p95_path` | no | `None` | `Path | None` |
| `canopy_fraction_path` | no | `None` | `Path | None` |
| `chm_thr_m` | no | `2.0` | `float` |
| `evidence_quantiles` | no | `(0.6, 0.7, 0.8)` | `tuple[float, ...]` |
| `patch_radius_quantiles` | no | `(0.25, 0.4, 0.55, 0.7, 0.85, 0.95)` | `tuple[float, ...]` |
| `min_radius_m` | no | `None` | `float | None` |
| `min_spatialr_px` | no | `1` | `int` |
| `min_patch_px` | no | `4` | `int` |
| `min_patch_area_m2` | no | `None` | `float | None` |
| `texture_support_max_m` | no | `None` | `float | None` |
| `segment_similarity_radius_max_m` | no | `None` | `float | None` |
| `target_structure_max_m` | no | `None` | `float | None` |
| `upper_radius_factor` | no | `2.5` | `float` |
| `max_radius_m` | no | `None` | `float | None` |
| `output_csv_filename` | no | `'scale_candidates.csv'` | `str` |
| `output_json_filename` | no | `'scale_candidates.json'` | `str` |
| `overwrite` | no | `False` | `bool` |

Functions:

- `build_level1b_scale_distribution_layout(output_dir) -> 'dict[str, Path]'`
- `validate_scale_distribution_config(config, layout) -> 'tuple[dict[str, bool], list[str]]'`
- `build_scale_candidates(config) -> 'list[dict[str, object]]'`
- `run_scale_distribution_step(config) -> 'dict[str, object]'`

### Feature range/ranger

Module: `metashape_qc_engine.level1b_feature_range`

Constructor: `Level1BFeatureRangeConfig(candidate_id: str, output_dir: str | pathlib.Path, feature_space_stack_path: str | pathlib.Path, valid_mask_path: str | pathlib.Path, scale_candidates_json_path: str | pathlib.Path, feature_space_source: str, band_count: int, sample_n: int = 50000, knn_k: int = 10, quantile_probs: tuple[float, ...] = (0.25, 0.5, 0.75, 0.9), seed: int = 1, max_distance_sample_n: int = 8000, output_ranger_csv_filename: str = 'ranger_candidates.csv', output_ranger_json_filename: str = 'ranger_candidates.json', output_assigned_csv_filename: str = 'scale_candidates_with_ranger.csv', output_assigned_json_filename: str = 'scale_candidates_with_ranger.json', overwrite: bool = False) -> None`

| field | required | default | type |
|---|---:|---|---|
| `candidate_id` | yes | `—` | `<class 'str'>` |
| `output_dir` | yes | `—` | `str | pathlib.Path` |
| `feature_space_stack_path` | yes | `—` | `str | pathlib.Path` |
| `valid_mask_path` | yes | `—` | `str | pathlib.Path` |
| `scale_candidates_json_path` | yes | `—` | `str | pathlib.Path` |
| `feature_space_source` | yes | `—` | `<class 'str'>` |
| `band_count` | yes | `—` | `<class 'int'>` |
| `sample_n` | no | `50000` | `<class 'int'>` |
| `knn_k` | no | `10` | `<class 'int'>` |
| `quantile_probs` | no | `(0.25, 0.5, 0.75, 0.9)` | `tuple[float, ...]` |
| `seed` | no | `1` | `<class 'int'>` |
| `max_distance_sample_n` | no | `8000` | `<class 'int'>` |
| `output_ranger_csv_filename` | no | `'ranger_candidates.csv'` | `<class 'str'>` |
| `output_ranger_json_filename` | no | `'ranger_candidates.json'` | `<class 'str'>` |
| `output_assigned_csv_filename` | no | `'scale_candidates_with_ranger.csv'` | `<class 'str'>` |
| `output_assigned_json_filename` | no | `'scale_candidates_with_ranger.json'` | `<class 'str'>` |
| `overwrite` | no | `False` | `<class 'bool'>` |

Functions:

- `build_level1b_feature_range_layout(output_dir) -> dict[str, pathlib.Path]`
- `validate_feature_range_config(config, layout, apps=None) -> tuple[dict[str, bool], list[str]]`
- `sample_valid_feature_vectors(config) -> tuple[numpy.ndarray, int]`
- `read_feature_stack_and_mask(feature_space_stack_path, valid_mask_path, band_count: int) -> tuple[numpy.ndarray, numpy.ndarray]`
- `compute_knn_distances(vectors, knn_k: int) -> numpy.ndarray`
- `build_ranger_candidates_from_knn_distances(candidate_id: str, distances, quantile_probs, knn_k: int, sample_n_requested: int, sample_n_used: int, distance_sample_n: int, feature_space_source: str, band_count: int) -> list[dict[str, object]]`
- `read_scale_candidates(json_path) -> list[dict[str, object]]`
- `assign_ranger_candidates_to_scale_candidates(scale_candidates, ranger_candidates) -> list[dict[str, object]]`
- `run_feature_range_assignment_step(config) -> dict[str, object]`

### Perturbations

Module: `metashape_qc_engine.level1b_perturbations`

Constructor: `Level1BPerturbationConfig(candidate_id: str, output_dir: str | pathlib.Path, scale_candidates_with_ranger_json_path: str | pathlib.Path | None, dr: float | None = None, ds: int = 1, dm: int | None = None, K: int = 8, minsize_floor_frac: float = 0.8, seed: int = 1, output_csv_filename: str = 'perturbation_candidates.csv', output_json_filename: str = 'perturbation_candidates.json', overwrite: bool = False) -> None`

| field | required | default | type |
|---|---:|---|---|
| `candidate_id` | yes | `—` | `<class 'str'>` |
| `output_dir` | yes | `—` | `str | pathlib.Path` |
| `scale_candidates_with_ranger_json_path` | yes | `—` | `str | pathlib.Path | None` |
| `dr` | no | `None` | `float | None` |
| `ds` | no | `1` | `<class 'int'>` |
| `dm` | no | `None` | `int | None` |
| `K` | no | `8` | `<class 'int'>` |
| `minsize_floor_frac` | no | `0.8` | `<class 'float'>` |
| `seed` | no | `1` | `<class 'int'>` |
| `output_csv_filename` | no | `'perturbation_candidates.csv'` | `<class 'str'>` |
| `output_json_filename` | no | `'perturbation_candidates.json'` | `<class 'str'>` |
| `overwrite` | no | `False` | `<class 'bool'>` |

Functions:

- `build_level1b_perturbation_layout(output_dir) -> dict[str, pathlib.Path]`
- `validate_perturbation_config(config, layout) -> tuple[dict[str, bool], list[str]]`
- `read_scale_candidates_with_ranger(json_path) -> list[dict[str, object]]`
- `build_perturbation_candidates(config, complete_candidates) -> list[dict[str, object]]`
- `run_local_perturbation_step(config) -> dict[str, object]`

### One-scale segmentation

Module: `metashape_qc_engine.level1b_one_scale_segmentation`

Constructor: `Level1BOneScaleSegmentationConfig(candidate_id: str, output_dir: str | pathlib.Path, feature_space_stack_path: str | pathlib.Path, perturbation_candidates_json_path: str | pathlib.Path, perturbation_id: str, tilesizex: int = 512, tilesizey: int = 512, ram_mb: int = 1024, cleanup: bool = True, overwrite: bool = False) -> None`

| field | required | default | type |
|---|---:|---|---|
| `candidate_id` | yes | `—` | `<class 'str'>` |
| `output_dir` | yes | `—` | `str | pathlib.Path` |
| `feature_space_stack_path` | yes | `—` | `str | pathlib.Path` |
| `perturbation_candidates_json_path` | yes | `—` | `str | pathlib.Path` |
| `perturbation_id` | yes | `—` | `<class 'str'>` |
| `tilesizex` | no | `512` | `<class 'int'>` |
| `tilesizey` | no | `512` | `<class 'int'>` |
| `ram_mb` | no | `1024` | `<class 'int'>` |
| `cleanup` | no | `True` | `<class 'bool'>` |
| `overwrite` | no | `False` | `<class 'bool'>` |

Functions:

- `build_level1b_one_scale_segmentation_layout(output_dir, perturbation_id) -> dict[str, pathlib.Path]`
- `discover_one_scale_segmentation_otb_apps() -> dict[str, str | None]`
- `validate_one_scale_segmentation_config(config, layout, apps) -> tuple[dict[str, bool], list[str]]`
- `read_perturbation_candidates(json_path) -> list[dict[str, object]]`
- `build_meanshift_smoothing_command(config, apps, layout, selected_candidate) -> list[str]`
- `build_lsms_segmentation_command(config, apps, layout, selected_candidate) -> list[str]`
- `build_small_regions_merging_command(config, apps, layout, selected_candidate) -> list[str]`
- `run_one_scale_segmentation_smoke(config) -> dict[str, object]`

### Hoover compare

Module: `metashape_qc_engine.level1b_hoover_compare`

Constructor: `Level1BHooverCompareConfig(candidate_id: str, comparison_id: str, baseline_labels_path: str | pathlib.Path, perturbation_labels_path: str | pathlib.Path, output_dir: str | pathlib.Path, otb_bin_dir: str | pathlib.Path | None = None, report_filename: str = 'hoover_report.json', raw_output_filename: str = 'hoover_raw.txt', ram_mb: int = 4096, overwrite: bool = False, dry_run: bool = False) -> None`

| field | required | default | type |
|---|---:|---|---|
| `candidate_id` | yes | `—` | `<class 'str'>` |
| `comparison_id` | yes | `—` | `<class 'str'>` |
| `baseline_labels_path` | yes | `—` | `str | pathlib.Path` |
| `perturbation_labels_path` | yes | `—` | `str | pathlib.Path` |
| `output_dir` | yes | `—` | `str | pathlib.Path` |
| `otb_bin_dir` | no | `None` | `str | pathlib.Path | None` |
| `report_filename` | no | `'hoover_report.json'` | `<class 'str'>` |
| `raw_output_filename` | no | `'hoover_raw.txt'` | `<class 'str'>` |
| `ram_mb` | no | `4096` | `<class 'int'>` |
| `overwrite` | no | `False` | `<class 'bool'>` |
| `dry_run` | no | `False` | `<class 'bool'>` |

Functions:

- `build_level1b_hoover_compare_layout(config: metashape_qc_engine.level1b_hoover_compare.Level1BHooverCompareConfig) -> dict[str, pathlib.Path]`
- `discover_hoover_compare_app(otb_bin_dir=None) -> str | None`
- `validate_hoover_compare_config(config: metashape_qc_engine.level1b_hoover_compare.Level1BHooverCompareConfig, layout: dict[str, pathlib.Path], app_path: str | None) -> tuple[dict[str, bool], list[str]]`
- `build_hoover_compare_command(config: metashape_qc_engine.level1b_hoover_compare.Level1BHooverCompareConfig, app_path: str, layout: dict[str, pathlib.Path]) -> list[str]`
- `parse_hoover_numeric_metrics(output_text: str) -> tuple[dict[str, float], str]`
- `run_hoover_compare(config: metashape_qc_engine.level1b_hoover_compare.Level1BHooverCompareConfig) -> dict[str, object]`

### Candidate stability

Module: `metashape_qc_engine.level1b_candidate_stability`

Constructor: `Level1BCandidateStabilityConfig(candidate_id: str, output_dir: str | pathlib.Path, perturbation_candidates_json_path: str | pathlib.Path, feature_space_stack_path: str | pathlib.Path, otb_bin_dir: str | pathlib.Path | None = None, ram_mb: int = 4096, overwrite: bool = False, dry_run: bool = False) -> None`

| field | required | default | type |
|---|---:|---|---|
| `candidate_id` | yes | `—` | `<class 'str'>` |
| `output_dir` | yes | `—` | `str | pathlib.Path` |
| `perturbation_candidates_json_path` | yes | `—` | `str | pathlib.Path` |
| `feature_space_stack_path` | yes | `—` | `str | pathlib.Path` |
| `otb_bin_dir` | no | `None` | `str | pathlib.Path | None` |
| `ram_mb` | no | `4096` | `<class 'int'>` |
| `overwrite` | no | `False` | `<class 'bool'>` |
| `dry_run` | no | `False` | `<class 'bool'>` |

Functions:

- `build_level1b_candidate_stability_layout(output_dir) -> dict[str, pathlib.Path]`
- `read_perturbation_candidates(json_path) -> list[dict[str, object]]`
- `validate_candidate_stability_config(config: metashape_qc_engine.level1b_candidate_stability.Level1BCandidateStabilityConfig) -> tuple[list[dict[str, object]], list[str]]`
- `run_candidate_stability(config: metashape_qc_engine.level1b_candidate_stability.Level1BCandidateStabilityConfig) -> dict[str, object]`

## Current known API caveat

`metashape_qc_engine.level1b_candidate_stability` exports `run_candidate_stability`, not `run_candidate_stability_step`. Chain drivers and resume scripts must call the exported function name.
