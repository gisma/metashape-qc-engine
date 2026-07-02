from dataclasses import dataclass
import csv
import json
import math
from pathlib import Path

from metashape_qc_engine.level1b_step_manifest import write_step_manifest


SCALE_MODE = "explicit_baseline_candidates"
SCALE_SOURCE = "config.baseline_candidate_radii_m"
RADIUS_UNIT = "m"
COUPLING_RULE = "radius_m_to_spatialr_px__area_m2_to_minsize_px"

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
)
JSON_FIELDS = (
    "candidate_id",
    "scale_mode",
    "scale_source",
    "baseline_candidate_radii_m",
    "radius_unit",
    "pixel_size_m",
    "pixel_area_m2",
    "candidate_count",
    "candidates",
    "no_raster_read",
    "no_otb_used",
    "no_ranger_assigned",
    "no_segmentation_performed",
)
CHECK_KEYS = (
    "candidate_id_non_empty",
    "pixel_size_m_valid",
    "baseline_candidate_radii_m_present",
    "baseline_candidate_radii_m_non_empty",
    "baseline_candidate_radii_m_values_valid",
    "baseline_candidate_radii_m_strictly_increasing",
    "output_csv_path_available",
    "output_json_path_available",
)


@dataclass
class Level1BScaleDistributionConfig:
    candidate_id: str
    output_dir: str | Path
    pixel_size_m: float | None
    baseline_candidate_radii_m: tuple[float, ...] | None
    output_csv_filename: str = "scale_candidates.csv"
    output_json_filename: str = "scale_candidates.json"
    overwrite: bool = False


def build_level1b_scale_distribution_layout(output_dir) -> dict[str, Path]:
    scales_dir = Path(output_dir) / "level1b" / "scales"
    scales_dir.mkdir(parents=True, exist_ok=True)
    return {"scales_dir": scales_dir}


def _is_positive_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0
    )


def validate_scale_distribution_config(config, layout) -> tuple[dict[str, bool], list[str]]:
    checks = {key: True for key in CHECK_KEYS}
    failure_reasons: list[str] = []
    csv_path = layout["scales_dir"] / config.output_csv_filename
    json_path = layout["scales_dir"] / config.output_json_filename

    if not str(config.candidate_id).strip():
        checks["candidate_id_non_empty"] = False
        failure_reasons.append("candidate_id is empty")
    if not _is_positive_number(config.pixel_size_m):
        checks["pixel_size_m_valid"] = False
        failure_reasons.append("pixel_size_m must be numeric and > 0")

    radii = config.baseline_candidate_radii_m
    if radii is None:
        checks["baseline_candidate_radii_m_present"] = False
        failure_reasons.append("baseline_candidate_radii_m is required")
    elif len(radii) == 0:
        checks["baseline_candidate_radii_m_non_empty"] = False
        failure_reasons.append("baseline_candidate_radii_m must be non-empty")
    elif any(not _is_positive_number(value) for value in radii):
        checks["baseline_candidate_radii_m_values_valid"] = False
        failure_reasons.append(
            "baseline_candidate_radii_m values must be finite numeric metre values > 0"
        )
    else:
        normalized = tuple(float(value) for value in radii)
        if any(
            current <= previous
            for previous, current in zip(normalized, normalized[1:])
        ):
            checks["baseline_candidate_radii_m_strictly_increasing"] = False
            failure_reasons.append(
                "baseline_candidate_radii_m must be strictly increasing with no duplicates"
            )

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


def _candidate_row(
    config: Level1BScaleDistributionConfig,
    scale_index: int,
    radius_m: float,
    pixel_size_m: float,
) -> dict[str, object]:
    area_m2 = math.pi * radius_m**2
    pixel_area_m2 = pixel_size_m**2
    spatialr_px = max(1, round(radius_m / pixel_size_m))
    scale_id = _scale_id(radius_m, spatialr_px)
    return {
        "candidate_id": f"{str(config.candidate_id).strip()}_{scale_id}",
        "scale_id": scale_id,
        "scale_index": scale_index,
        "scale_mode": SCALE_MODE,
        "scale_source": SCALE_SOURCE,
        "radius_m": radius_m,
        "area_m2": area_m2,
        "pixel_size_m": pixel_size_m,
        "pixel_area_m2": pixel_area_m2,
        "spatialr_px": spatialr_px,
        "minsize_px": max(1, round(area_m2 / pixel_area_m2)),
        "ranger": None,
        "coupling_rule": COUPLING_RULE,
    }


def build_scale_candidates(
    config: Level1BScaleDistributionConfig,
) -> list[dict[str, object]]:
    pixel_size_m = float(config.pixel_size_m)
    radii = tuple(float(value) for value in config.baseline_candidate_radii_m or ())
    return [
        _candidate_row(config, index, radius_m, pixel_size_m)
        for index, radius_m in enumerate(radii, start=1)
    ]


def write_scale_candidates_csv(candidates, csv_path) -> None:
    with Path(csv_path).open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(
            file_obj,
            fieldnames=list(ROW_FIELDS),
            extrasaction="ignore",
        )
        writer.writeheader()
        for candidate in candidates:
            row = dict(candidate)
            row["ranger"] = "NA"
            writer.writerow(row)


def _payload(config, candidates) -> dict[str, object]:
    pixel_size_m = (
        float(config.pixel_size_m)
        if _is_positive_number(config.pixel_size_m)
        else config.pixel_size_m
    )
    return {
        "candidate_id": str(config.candidate_id).strip(),
        "scale_mode": SCALE_MODE,
        "scale_source": SCALE_SOURCE,
        "baseline_candidate_radii_m": [
            float(value) for value in config.baseline_candidate_radii_m or ()
        ],
        "radius_unit": RADIUS_UNIT,
        "pixel_size_m": pixel_size_m,
        "pixel_area_m2": pixel_size_m**2 if pixel_size_m is not None else None,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "no_raster_read": True,
        "no_otb_used": True,
        "no_ranger_assigned": True,
        "no_segmentation_performed": True,
    }


def write_scale_candidates_json(config, candidates, json_path) -> None:
    payload = _payload(config, candidates)
    with Path(json_path).open("w", encoding="utf-8") as file_obj:
        json.dump({key: payload[key] for key in JSON_FIELDS}, file_obj, indent=2)


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
    write_step_manifest(
        config.output_dir,
        step="scale_distribution",
        status=status,
        inputs={},
        artifacts={
            "scale_candidates_csv": csv_path,
            "scale_candidates_json": json_path,
        },
        candidate_id=str(config.candidate_id).strip(),
    )
    return report
