from dataclasses import dataclass
import csv
import json
from math import pi
from pathlib import Path


SCALE_MODES = ("metric_scale_sweep", "structure_derived_scale_distribution")
COUPLING_RULE = "radius_m_to_spatialr_px__area_m2_to_minsize_px"
ROW_FIELDS = (
    "candidate_id",
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
)
JSON_FIELDS = (
    "candidate_id",
    "scale_mode",
    "scale_source",
    "pixel_size_m",
    "pixel_area_m2",
    "candidate_count",
    "candidates",
)
CHECK_KEYS = (
    "candidate_id_non_empty",
    "pixel_size_m_valid",
    "scale_mode_valid",
    "metric_radius_m_present",
    "metric_radius_m_non_empty",
    "metric_radius_m_values_valid",
    "metric_structure_radius_m_absent",
    "structure_radius_m_present",
    "structure_radius_m_non_empty",
    "structure_radius_m_values_valid",
    "structure_metric_radius_m_absent",
    "output_csv_path_available",
    "output_json_path_available",
)


@dataclass
class Level1BScaleDistributionConfig:
    candidate_id: str
    output_dir: str | Path
    pixel_size_m: float
    scale_mode: str
    metric_radius_m: tuple[float, ...] | None = None
    structure_radius_m: tuple[float, ...] | None = None
    output_csv_filename: str = "scale_candidates.csv"
    output_json_filename: str = "scale_candidates.json"
    overwrite: bool = False


def build_level1b_scale_distribution_layout(output_dir) -> dict[str, Path]:
    scales_dir = Path(output_dir) / "level1b" / "scales"
    scales_dir.mkdir(parents=True, exist_ok=True)
    return {"scales_dir": scales_dir}


def validate_scale_distribution_config(config, layout) -> tuple[dict[str, bool], list[str]]:
    checks = {key: True for key in CHECK_KEYS}
    failure_reasons: list[str] = []
    candidate_id = str(config.candidate_id).strip()
    csv_path = layout["scales_dir"] / config.output_csv_filename
    json_path = layout["scales_dir"] / config.output_json_filename

    if not candidate_id:
        checks["candidate_id_non_empty"] = False
        failure_reasons.append("candidate_id is empty")
    if not isinstance(config.pixel_size_m, (int, float)) or isinstance(config.pixel_size_m, bool) or config.pixel_size_m <= 0:
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
        elif any(not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0 for value in config.metric_radius_m):
            checks["metric_radius_m_values_valid"] = False
            failure_reasons.append("metric_radius_m values must be numeric and > 0")
        if config.structure_radius_m is not None:
            checks["metric_structure_radius_m_absent"] = False
            failure_reasons.append("structure_radius_m must be None for metric_scale_sweep")

    if config.scale_mode == "structure_derived_scale_distribution":
        if config.structure_radius_m is None:
            checks["structure_radius_m_present"] = False
            failure_reasons.append("structure_radius_m is required for structure_derived_scale_distribution")
        elif len(config.structure_radius_m) == 0:
            checks["structure_radius_m_non_empty"] = False
            failure_reasons.append("structure_radius_m must be non-empty")
        elif any(
            not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0
            for value in config.structure_radius_m
        ):
            checks["structure_radius_m_values_valid"] = False
            failure_reasons.append("structure_radius_m values must be numeric and > 0")
        if config.metric_radius_m is not None:
            checks["structure_metric_radius_m_absent"] = False
            failure_reasons.append("metric_radius_m must be None for structure_derived_scale_distribution")

    if csv_path.exists() and not config.overwrite:
        checks["output_csv_path_available"] = False
        failure_reasons.append("scale_candidates.csv already exists and overwrite is false")
    if json_path.exists() and not config.overwrite:
        checks["output_json_path_available"] = False
        failure_reasons.append("scale_candidates.json already exists and overwrite is false")

    return checks, failure_reasons


def build_scale_candidates(config) -> list[dict[str, object]]:
    if config.scale_mode == "metric_scale_sweep":
        source = "metric_radius_m"
        radii = config.metric_radius_m
    else:
        source = "structure_radius_m"
        radii = config.structure_radius_m

    pixel_size_m = float(config.pixel_size_m)
    pixel_area_m2 = pixel_size_m**2
    normalized_radii = sorted(set(float(value) for value in radii))
    candidates: list[dict[str, object]] = []

    for scale_index, radius_m in enumerate(normalized_radii, start=1):
        area_m2 = pi * radius_m**2
        candidates.append(
            {
                "candidate_id": f"{str(config.candidate_id).strip()}_scale_{scale_index:03d}",
                "scale_index": scale_index,
                "scale_mode": config.scale_mode,
                "scale_source": source,
                "radius_m": radius_m,
                "area_m2": area_m2,
                "pixel_size_m": pixel_size_m,
                "pixel_area_m2": pixel_area_m2,
                "spatialr_px": max(1, round(radius_m / pixel_size_m)),
                "minsize_px": max(1, round(area_m2 / pixel_area_m2)),
                "ranger": None,
                "coupling_rule": COUPLING_RULE,
            }
        )

    return candidates


def write_scale_candidates_csv(candidates, csv_path) -> None:
    with Path(csv_path).open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=ROW_FIELDS)
        writer.writeheader()
        for candidate in candidates:
            row = dict(candidate)
            row["ranger"] = "NA"
            writer.writerow(row)


def write_scale_candidates_json(config, candidates, json_path) -> None:
    scale_source = "metric_radius_m" if config.scale_mode == "metric_scale_sweep" else "structure_radius_m"
    pixel_size_m = float(config.pixel_size_m)
    payload = {
        "candidate_id": str(config.candidate_id).strip(),
        "scale_mode": config.scale_mode,
        "scale_source": scale_source,
        "pixel_size_m": pixel_size_m,
        "pixel_area_m2": pixel_size_m**2,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    with Path(json_path).open("w", encoding="utf-8") as file_obj:
        json.dump({key: payload[key] for key in JSON_FIELDS}, file_obj, indent=2)


def run_scale_distribution_step(config) -> dict[str, object]:
    layout = build_level1b_scale_distribution_layout(config.output_dir)
    csv_path = layout["scales_dir"] / config.output_csv_filename
    json_path = layout["scales_dir"] / config.output_json_filename
    checks, failure_reasons = validate_scale_distribution_config(config, layout)
    scale_source = "metric_radius_m" if config.scale_mode == "metric_scale_sweep" else "structure_radius_m"
    pixel_area_m2 = float(config.pixel_size_m) ** 2 if checks["pixel_size_m_valid"] else None
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

    return {
        "candidate_id": str(config.candidate_id).strip(),
        "output_dir": str(Path(config.output_dir)),
        "scales_dir": str(layout["scales_dir"]),
        "scale_mode": config.scale_mode,
        "scale_source": scale_source,
        "pixel_size_m": float(config.pixel_size_m) if checks["pixel_size_m_valid"] else config.pixel_size_m,
        "pixel_area_m2": pixel_area_m2,
        "output_csv_path": str(csv_path),
        "output_json_path": str(json_path),
        "overwrite": config.overwrite,
        "checks": checks,
        "status": status,
        "failure_reasons": failure_reasons,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "files_written": files_written,
        "no_raster_read": True,
        "no_otb_used": True,
        "no_ranger_assigned": True,
        "no_segmentation_performed": True,
    }
