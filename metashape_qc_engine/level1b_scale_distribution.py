from dataclasses import dataclass
import csv
import json
import math
import re
from pathlib import Path
from typing import Any

from metashape_qc_engine.level1b_step_manifest import write_step_manifest


SCALE_MODES = ("metric_scale_sweep", "structure_derived_scale_distribution")
METRIC_COUPLING_RULE = "radius_m_to_spatialr_px__area_m2_to_minsize_px"
STRUCTURE_COUPLING_RULE = "metadata_texture_support_radius_m_to_spatialr_px__area_m2_to_minsize_px"
STRUCTURE_RADIUS_DEPRECATED_REASON = (
    "structure_radius_m is deprecated/manual input and must not be supplied for "
    "structure_derived_scale_distribution"
)
DEFAULT_PATCH_RADIUS_QUANTILES = (0.25, 0.4, 0.55, 0.7, 0.85, 0.95)
TEXTURE_BAND_PATTERNS = ("TEX", "texture", "TEXTURE")
DGLCM_STRUCTURE_BAND_ROLES = ("DGLCM_PC1_SMALL", "DGLCM_PC1_LARGE")

ROW_FIELDS = (
    "candidate_id",
    "scale_id",
    "scale_index",
    "scale_mode",
    "scale_source",
    "radius_m",
    "area_m2",
    "pixel_size_m",
    "pixel_area_m2",
    "spatialr_px",
    "minsize_px",
    "ranger",
    "coupling_rule",
    "evidence_quantile",
    "patch_radius_quantile",
    "texture_support_max_m",
    "target_structure_max_m",
    "upper_radius_factor",
    "upper_envelope_radius_m",
    "max_radius_m",
    "selected_structure_band_indices",
    "selected_structure_band_roles",
    "selected_structure_band_source",
    "texture_support_inference_method",
    "proxy_structure_mode",
    "envelope_source",
    "inside_uav_segment_similarity_envelope",
    "gsd_mapping_rule",
)
JSON_FIELDS = (
    "candidate_id",
    "scale_mode",
    "scale_source",
    "pixel_size_m",
    "raster_pixel_size_m",
    "pixel_area_m2",
    "candidate_count",
    "candidates",
    "proxy_structure_mode",
    "selected_structure_band_indices",
    "selected_structure_band_roles",
    "selected_structure_band_source",
    "texture_support_max_m",
    "target_structure_max_m",
    "upper_radius_factor",
    "upper_envelope_radius_m",
    "max_radius_m",
    "envelope_source",
    "no_raster_read",
    "no_otb_used",
    "no_ranger_assigned",
    "no_segmentation_performed",
)
CHECK_KEYS = (
    "candidate_id_non_empty",
    "pixel_size_m_valid",
    "scale_mode_valid",
    "metric_radius_m_present",
    "metric_radius_m_non_empty",
    "metric_radius_m_values_valid",
    "metric_structure_radius_m_absent",
    "structure_radius_m_absent",
    "structure_proxy_or_metadata_available",
    "structure_texture_support_available",
    "structure_upper_envelope_available",
    "structure_candidate_radii_available",
    "output_csv_path_available",
    "output_json_path_available",
)


@dataclass
class Level1BScaleDistributionConfig:
    candidate_id: str
    output_dir: str | Path
    pixel_size_m: float | None
    scale_mode: str
    metric_radius_m: tuple[float, ...] | None = None
    structure_radius_m: tuple[float, ...] | None = None
    proxy_stack_path: str | Path | None = None
    feature_stack_path: str | Path | None = None
    feature_space_stack_path: str | Path | None = None
    valid_mask_path: str | Path | None = None
    channel_report_path: str | Path | None = None
    proxy_structure_mode: str = "texture_preferred"
    proxy_band_indices: tuple[int, ...] | None = None
    texture_band_indices: tuple[int, ...] | None = None
    infer_texture_support_from_proxy: bool = True
    infer_structure_support_from_proxy: bool = True
    sampling_regime: str = "auto"
    structure_support_max_m: float | None = None
    texture_support_max_m: float | None = None
    target_structure_max_m: float | None = None
    segment_similarity_radius_max_m: float | None = None
    upper_radius_factor: float = 2.5
    max_radius_m: float | None = None
    patch_radius_quantiles: tuple[float, ...] = DEFAULT_PATCH_RADIUS_QUANTILES
    min_radius_m: float | None = None
    max_candidate_radius_fraction: float = 0.775
    output_csv_filename: str = "scale_candidates.csv"
    output_json_filename: str = "scale_candidates.json"
    overwrite: bool = False


def build_level1b_scale_distribution_layout(output_dir) -> dict[str, Path]:
    scales_dir = Path(output_dir) / "level1b" / "scales"
    scales_dir.mkdir(parents=True, exist_ok=True)
    return {"scales_dir": scales_dir}


def _is_positive_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and float(value) > 0


def _channel_report_path(config: Level1BScaleDistributionConfig) -> Path:
    if config.channel_report_path is not None:
        return Path(config.channel_report_path)
    return Path(config.output_dir) / "level1b" / "channels" / "channel_report.json"


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _read_channel_metadata(config: Level1BScaleDistributionConfig) -> dict[str, Any]:
    path = _channel_report_path(config)
    if path.exists():
        metadata = _read_json(path)
        metadata["_metadata_path"] = str(path)
        return metadata
    return {"_metadata_path": str(path)}


def _texture_radius_from_role(role: object) -> float | None:
    text = str(role)
    match = re.search(r"(?:TEX|texture|TEXTURE)[_\- ]*(\d+(?:\.\d+)?)(?:M|m)?", text)
    if match:
        value = float(match.group(1))
        if value > 20:
            value = value / 100.0
        return value
    match = re.search(r"(\d+(?:\.\d+)?)\s*m", text, flags=re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def _selected_proxy_bands(config: Level1BScaleDistributionConfig, metadata: dict[str, Any]) -> tuple[list[int], list[str], str, list[int]]:
    channel_names = [str(value) for value in metadata.get("channel_names") or []]
    if config.proxy_band_indices:
        indices = [int(value) for value in config.proxy_band_indices]
        roles = [channel_names[i - 1] if 1 <= i <= len(channel_names) else f"band_{i}" for i in indices]
        return indices, roles, "selected_bands", []
    if config.texture_band_indices:
        indices = [int(value) for value in config.texture_band_indices]
        roles = [channel_names[i - 1] if 1 <= i <= len(channel_names) else f"band_{i}" for i in indices]
        return indices, roles, "selected_texture_bands", []
    if config.proxy_structure_mode == "all_bands":
        count = len(channel_names) or 1
        return list(range(1, count + 1)), channel_names or ["band_1"], "all_bands_explicit", []
    dglcm_indices = [
        index
        for index, name in enumerate(channel_names, start=1)
        if name in DGLCM_STRUCTURE_BAND_ROLES
    ]
    if dglcm_indices:
        excluded = [
            index
            for index in range(1, len(channel_names) + 1)
            if index not in dglcm_indices
        ]
        return (
            dglcm_indices,
            [channel_names[index - 1] for index in dglcm_indices],
            "metadata_dglcm_structure_roles",
            excluded,
        )
    texture_indices = [
        index
        for index, name in enumerate(channel_names, start=1)
        if any(pattern.lower() in name.lower() for pattern in TEXTURE_BAND_PATTERNS)
    ]
    if texture_indices:
        excluded = [index for index in range(1, len(channel_names) + 1) if index not in texture_indices]
        return texture_indices, [channel_names[index - 1] for index in texture_indices], "metadata_texture_roles", excluded
    if len(channel_names) == 5 or not channel_names:
        return [4, 5], ["TEX_100M", "TEX_200M"], "standard_5_band_proxy_texture_fallback", [1, 2, 3]
    return [], [], "no_texture_band_identified", list(range(1, len(channel_names) + 1))


def _infer_texture_support_max_m(config: Level1BScaleDistributionConfig, metadata: dict[str, Any], roles: list[str]) -> tuple[float | None, str]:
    if _is_positive_number(config.texture_support_max_m):
        return float(config.texture_support_max_m), "config.texture_support_max_m"
    values: list[float] = []
    for key in (
        "dglcm_pc1_small_radius_m",
        "dglcm_pc1_large_radius_m",
        "texture_support_max_m",
        "effective_structure_support_max_m",
    ):
        value = metadata.get(key)
        if _is_positive_number(value):
            values.append(float(value))
    if config.infer_texture_support_from_proxy:
        for role in roles:
            value = _texture_radius_from_role(role)
            if _is_positive_number(value):
                values.append(float(value))
    if values:
        return max(values), "channel_metadata_or_selected_texture_roles"
    return None, "not_available"


def _resolve_pixel_size(config: Level1BScaleDistributionConfig, metadata: dict[str, Any]) -> tuple[float | None, float | None]:
    raster_px = metadata.get("pixel_size_m")
    raster_px = float(raster_px) if _is_positive_number(raster_px) else None
    config_px = float(config.pixel_size_m) if _is_positive_number(config.pixel_size_m) else None
    return config_px or raster_px, raster_px


def _resolve_upper_envelope(config: Level1BScaleDistributionConfig, texture_support_max_m: float | None) -> tuple[float | None, str]:
    if _is_positive_number(config.max_radius_m):
        return float(config.max_radius_m), "max_radius_m"
    if _is_positive_number(config.segment_similarity_radius_max_m):
        return float(config.segment_similarity_radius_max_m), "segment_similarity_radius_max_m"
    if _is_positive_number(texture_support_max_m):
        return float(texture_support_max_m) * float(config.upper_radius_factor), "inferred_texture_support_x_upper_radius_factor"
    if _is_positive_number(config.target_structure_max_m):
        return float(config.target_structure_max_m) * float(config.upper_radius_factor), "target_structure_max_m_x_upper_radius_factor"
    return None, "not_available"


def _deterministic_metadata_radii(config: Level1BScaleDistributionConfig, pixel_size_m: float, texture_support_max_m: float | None, upper_envelope: float) -> list[float]:
    count = len(tuple(config.patch_radius_quantiles or DEFAULT_PATCH_RADIUS_QUANTILES))
    lower = config.min_radius_m
    if not _is_positive_number(lower):
        lower = float(texture_support_max_m) / 10.0 if _is_positive_number(texture_support_max_m) else pixel_size_m * 4.0
    upper = min(upper_envelope * float(config.max_candidate_radius_fraction), upper_envelope)
    if upper <= float(lower):
        upper = upper_envelope
    if count <= 1:
        return [float(lower)]
    log_lower = math.log(float(lower))
    log_upper = math.log(float(upper))
    return [math.exp(log_lower + (log_upper - log_lower) * index / (count - 1)) for index in range(count)]


def validate_scale_distribution_config(config, layout) -> tuple[dict[str, bool], list[str]]:
    checks = {key: True for key in CHECK_KEYS}
    failure_reasons: list[str] = []
    candidate_id = str(config.candidate_id).strip()
    csv_path = layout["scales_dir"] / config.output_csv_filename
    json_path = layout["scales_dir"] / config.output_json_filename
    metadata = _read_channel_metadata(config)
    selected_indices, selected_roles, _selected_source, _excluded = _selected_proxy_bands(config, metadata)
    texture_support_max_m, _texture_source = _infer_texture_support_max_m(config, metadata, selected_roles)
    pixel_size_m, _raster_pixel_size_m = _resolve_pixel_size(config, metadata)
    upper_envelope, _envelope_source = _resolve_upper_envelope(config, texture_support_max_m)

    if not candidate_id:
        checks["candidate_id_non_empty"] = False
        failure_reasons.append("candidate_id is empty")
    if not _is_positive_number(pixel_size_m):
        checks["pixel_size_m_valid"] = False
        failure_reasons.append("pixel_size_m must be numeric and > 0")
    if config.scale_mode not in SCALE_MODES:
        checks["scale_mode_valid"] = False
        failure_reasons.append("scale_mode must be exactly metric_scale_sweep or structure_derived_scale_distribution")

    if config.scale_mode == "metric_scale_sweep":
        if config.metric_radius_m is None:
            checks["metric_radius_m_present"] = False
            failure_reasons.append("metric_radius_m is required for metric_scale_sweep")
        elif len(config.metric_radius_m) == 0:
            checks["metric_radius_m_non_empty"] = False
            failure_reasons.append("metric_radius_m must be non-empty")
        elif any(not _is_positive_number(value) for value in config.metric_radius_m):
            checks["metric_radius_m_values_valid"] = False
            failure_reasons.append("metric_radius_m values must be numeric and > 0")
        if config.structure_radius_m is not None:
            checks["metric_structure_radius_m_absent"] = False
            failure_reasons.append("structure_radius_m must be None for metric_scale_sweep")

    if config.scale_mode == "structure_derived_scale_distribution":
        if config.structure_radius_m is not None:
            checks["structure_radius_m_absent"] = False
            failure_reasons.append(STRUCTURE_RADIUS_DEPRECATED_REASON)
        if not (config.proxy_stack_path or config.feature_stack_path or config.feature_space_stack_path or metadata.get("output_path")):
            checks["structure_proxy_or_metadata_available"] = False
            failure_reasons.append("structure_derived_scale_distribution requires proxy/feature stack metadata")
        if not selected_indices:
            checks["structure_proxy_or_metadata_available"] = False
            failure_reasons.append("no texture/structure proxy bands selected; use texture metadata or proxy_structure_mode='all_bands'")
        if not _is_positive_number(texture_support_max_m):
            checks["structure_texture_support_available"] = False
            failure_reasons.append("texture_support_max_m could not be inferred from metadata or config")
        if not _is_positive_number(upper_envelope):
            checks["structure_upper_envelope_available"] = False
            failure_reasons.append("upper envelope radius could not be derived")
        if _is_positive_number(pixel_size_m) and _is_positive_number(texture_support_max_m) and _is_positive_number(upper_envelope):
            if not _deterministic_metadata_radii(config, float(pixel_size_m), float(texture_support_max_m), float(upper_envelope)):
                checks["structure_candidate_radii_available"] = False
                failure_reasons.append("no metadata-derived candidate radii available")
        if config.metric_radius_m is not None:
            checks["metric_radius_m_present"] = False
            failure_reasons.append("metric_radius_m must be None for structure_derived_scale_distribution")

    if csv_path.exists() and not config.overwrite:
        checks["output_csv_path_available"] = False
        failure_reasons.append("scale_candidates.csv already exists and overwrite is false")
    if json_path.exists() and not config.overwrite:
        checks["output_json_path_available"] = False
        failure_reasons.append("scale_candidates.json already exists and overwrite is false")

    return checks, failure_reasons


def _scale_id(radius_m: float, spatialr_px: int) -> str:
    text = f"{radius_m:.2f}".rstrip("0").rstrip(".").replace(".", "p")
    return f"r{text}m_px{spatialr_px:03d}"


def _candidate_row(config, scale_index, radius_m, source, pixel_size_m, metadata=None, patch_quantile=None) -> dict[str, object]:
    area_m2 = math.pi * radius_m**2
    pixel_area_m2 = pixel_size_m**2
    spatialr_px = max(1, round(radius_m / pixel_size_m))
    row = {
        "candidate_id": f"{str(config.candidate_id).strip()}_{_scale_id(radius_m, spatialr_px)}",
        "scale_id": _scale_id(radius_m, spatialr_px),
        "scale_index": scale_index,
        "scale_mode": config.scale_mode,
        "scale_source": source,
        "radius_m": radius_m,
        "area_m2": area_m2,
        "pixel_size_m": pixel_size_m,
        "pixel_area_m2": pixel_area_m2,
        "spatialr_px": spatialr_px,
        "minsize_px": max(1, round(area_m2 / pixel_area_m2)),
        "ranger": None,
        "coupling_rule": METRIC_COUPLING_RULE if config.scale_mode == "metric_scale_sweep" else STRUCTURE_COUPLING_RULE,
    }
    if metadata:
        row.update(metadata)
    if patch_quantile is not None:
        row["patch_radius_quantile"] = float(patch_quantile)
    return row


def _structure_metadata(config: Level1BScaleDistributionConfig) -> dict[str, object]:
    metadata = _read_channel_metadata(config)
    selected_indices, selected_roles, selected_source, excluded = _selected_proxy_bands(config, metadata)
    texture_support_max_m, texture_source = _infer_texture_support_max_m(config, metadata, selected_roles)
    upper_envelope, envelope_source = _resolve_upper_envelope(config, texture_support_max_m)
    target_structure_max_m = config.target_structure_max_m or config.structure_support_max_m or texture_support_max_m
    return {
        "channel_metadata_path": metadata.get("_metadata_path"),
        "proxy_structure_mode": config.proxy_structure_mode,
        "selected_structure_band_indices": selected_indices,
        "selected_structure_band_roles": selected_roles,
        "selected_structure_band_source": selected_source,
        "excluded_proxy_band_indices": excluded,
        "texture_support_max_m": texture_support_max_m,
        "texture_support_inference_method": texture_source,
        "target_structure_max_m": target_structure_max_m,
        "upper_radius_factor": float(config.upper_radius_factor),
        "upper_envelope_radius_m": upper_envelope,
        "max_radius_m": config.max_radius_m,
        "envelope_source": envelope_source,
        "all_bands_used_explicitly": config.proxy_structure_mode == "all_bands",
        "color_index_bands_excluded_by_default": excluded,
        "envelope_is_not_candidate": True,
        "candidates_are_metadata_derived": True,
        "gsd_mapping_rule": "metadata_radius_m_to_pixel_radius_and_area",
    }


def build_scale_candidates(config) -> list[dict[str, object]]:
    metadata = _read_channel_metadata(config)
    pixel_size_m, _raster_pixel_size_m = _resolve_pixel_size(config, metadata)
    if not _is_positive_number(pixel_size_m):
        pixel_size_m = float(config.pixel_size_m)
    pixel_size_m = float(pixel_size_m)

    if config.scale_mode == "metric_scale_sweep":
        radii = sorted(set(float(value) for value in config.metric_radius_m or ()))
        return [_candidate_row(config, index, radius_m, "metric_radius_m", pixel_size_m) for index, radius_m in enumerate(radii, start=1)]

    structure_meta = _structure_metadata(config)
    texture_support_max_m = structure_meta["texture_support_max_m"]
    upper_envelope = structure_meta["upper_envelope_radius_m"]
    radii = _deterministic_metadata_radii(config, pixel_size_m, float(texture_support_max_m), float(upper_envelope))
    quantiles = tuple(config.patch_radius_quantiles or DEFAULT_PATCH_RADIUS_QUANTILES)
    candidates: list[dict[str, object]] = []
    for index, (radius_m, quantile) in enumerate(zip(radii, quantiles), start=1):
        if radius_m > float(upper_envelope):
            continue
        row_meta = dict(structure_meta)
        row_meta["inside_uav_segment_similarity_envelope"] = True
        row_meta["evidence_quantile"] = None
        candidates.append(_candidate_row(config, index, float(radius_m), "proxy_stack", pixel_size_m, row_meta, quantile))
    unique: list[dict[str, object]] = []
    seen: set[tuple[int, int]] = set()
    for candidate in candidates:
        key = (int(candidate["spatialr_px"]), int(candidate["minsize_px"]))
        if key in seen:
            continue
        seen.add(key)
        candidate["scale_index"] = len(unique) + 1
        unique.append(candidate)
    return unique


def write_scale_candidates_csv(candidates, csv_path) -> None:
    fieldnames = list(ROW_FIELDS)
    for candidate in candidates:
        for key in candidate:
            if key not in fieldnames:
                fieldnames.append(key)
    with Path(csv_path).open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for candidate in candidates:
            row = dict(candidate)
            row["ranger"] = "NA"
            for key, value in list(row.items()):
                if isinstance(value, (list, tuple, dict)):
                    row[key] = json.dumps(value, separators=(",", ":"), sort_keys=True)
            writer.writerow(row)


def _payload(config, candidates) -> dict[str, object]:
    metadata = _read_channel_metadata(config)
    pixel_size_m, raster_pixel_size_m = _resolve_pixel_size(config, metadata)
    pixel_area_m2 = float(pixel_size_m) ** 2 if _is_positive_number(pixel_size_m) else None
    scale_source = "metric_radius_m" if config.scale_mode == "metric_scale_sweep" else "proxy_stack"
    payload: dict[str, object] = {
        "candidate_id": str(config.candidate_id).strip(),
        "scale_mode": config.scale_mode,
        "scale_source": scale_source,
        "pixel_size_m": float(pixel_size_m) if _is_positive_number(pixel_size_m) else pixel_size_m,
        "raster_pixel_size_m": raster_pixel_size_m,
        "pixel_area_m2": pixel_area_m2,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "no_raster_read": True,
        "no_otb_used": True,
        "no_ranger_assigned": True,
        "no_segmentation_performed": True,
    }
    if config.scale_mode == "structure_derived_scale_distribution":
        payload.update(_structure_metadata(config))
    return payload


def write_scale_candidates_json(config, candidates, json_path) -> None:
    payload = _payload(config, candidates)
    keys = list(JSON_FIELDS)
    for key in payload:
        if key not in keys:
            keys.append(key)
    with Path(json_path).open("w", encoding="utf-8") as file_obj:
        json.dump({key: payload.get(key) for key in keys}, file_obj, indent=2)


def run_scale_distribution_step(config) -> dict[str, object]:
    layout = build_level1b_scale_distribution_layout(config.output_dir)
    csv_path = layout["scales_dir"] / config.output_csv_filename
    json_path = layout["scales_dir"] / config.output_json_filename
    checks, failure_reasons = validate_scale_distribution_config(config, layout)
    candidates: list[dict[str, object]] = []
    files_written: list[str] = []

    if failure_reasons:
        status = "failed"
    else:
        candidates = build_scale_candidates(config)
        write_scale_candidates_csv(candidates, csv_path)
        write_scale_candidates_json(config, candidates, json_path)
        files_written = [str(csv_path), str(json_path)]
        status = "ok"

    report = _payload(config, candidates)
    report.update(
        {
            "output_dir": str(Path(config.output_dir)),
            "scales_dir": str(layout["scales_dir"]),
            "output_csv_path": str(csv_path),
            "output_json_path": str(json_path),
            "scale_candidates_csv_path": str(csv_path),
            "scale_candidates_json_path": str(json_path),
            "overwrite": config.overwrite,
            "checks": checks,
            "status": status,
            "failure_reasons": failure_reasons,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "files_written": files_written,
        }
    )
    manifest_inputs = {
        name: value
        for name, value in {
            "proxy_stack": config.proxy_stack_path,
            "valid_mask": config.valid_mask_path,
            "channel_report": config.channel_report_path,
        }.items()
        if value is not None
    }
    write_step_manifest(
        config.output_dir,
        step="scale_distribution",
        status=status,
        inputs=manifest_inputs,
        artifacts={
            "scale_candidates_csv": csv_path,
            "scale_candidates_json": json_path,
        },
        candidate_id=str(config.candidate_id).strip(),
    )
    return report
