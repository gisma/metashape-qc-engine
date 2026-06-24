from dataclasses import dataclass
import csv
import json
from math import sqrt
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET


RASTER_SUFFIXES = {".tif", ".tiff", ".vrt", ".img", ".jp2"}
FEATURE_SPACE_SOURCES = {"scaled", "pca"}
RANGER_SOURCE = "feature_std_l2_times_single_multiplier"
ASSIGNMENT_RULE = "single_feature_range_assigned_to_each_scale_candidate"
RANGER_FIELDS = (
    "ranger_id",
    "ranger_index",
    "ranger",
    "ranger_multiplier",
    "feature_std_l2",
    "feature_space_source",
    "band_count",
    "ranger_source",
)
ASSIGNED_FIELDS = (
    "candidate_id",
    "scale_id",
    "ranger_id",
    "spatialr_px",
    "minsize_px",
    "ranger",
    "ranger_source",
    "assignment_rule",
)
RANGER_JSON_KEYS = (
    "candidate_id",
    "feature_space_stack_path",
    "feature_space_source",
    "band_count",
    "background_value",
    "feature_statistics_xml_path",
    "feature_std_l2",
    "ranger_multiplier",
    "ranger_source",
    "ranger_count",
    "ranger_candidates",
)
ASSIGNED_JSON_KEYS = (
    "candidate_id",
    "scale_candidates_json_path",
    "ranger_candidates_json_path",
    "assignment_rule",
    "scale_candidate_count",
    "ranger_candidate_count",
    "assigned_candidate_count",
    "candidates",
)
CHECK_KEYS = (
    "candidate_id_non_empty",
    "feature_space_stack_path_exists",
    "feature_space_stack_suffix_raster_like",
    "feature_space_source_valid",
    "scale_candidates_json_path_exists",
    "scale_candidates_json_path_suffix_json",
    "band_count_positive_integer",
    "ranger_multiplier_numeric_positive",
    "background_value_numeric",
    "output_ranger_csv_path_available",
    "output_ranger_json_path_available",
    "output_assigned_csv_path_available",
    "output_assigned_json_path_available",
    "otb_compute_images_statistics_discoverable",
)


@dataclass
class Level1BFeatureRangeConfig:
    candidate_id: str
    output_dir: str | Path
    feature_space_stack_path: str | Path
    feature_space_source: str
    scale_candidates_json_path: str | Path
    band_count: int
    ranger_multiplier: float
    background_value: float = -999999.0
    output_ranger_csv_filename: str = "ranger_candidates.csv"
    output_ranger_json_filename: str = "ranger_candidates.json"
    output_assigned_csv_filename: str = "scale_candidates_with_ranger.csv"
    output_assigned_json_filename: str = "scale_candidates_with_ranger.json"
    overwrite: bool = False


def build_level1b_feature_range_layout(output_dir) -> dict[str, Path]:
    level1b_dir = Path(output_dir) / "level1b"
    layout = {
        "ranger_dir": level1b_dir / "ranger",
        "tmp_ranger_dir": level1b_dir / "tmp" / "ranger",
    }
    for directory in layout.values():
        directory.mkdir(parents=True, exist_ok=True)
    return layout


def discover_feature_range_otb_apps() -> dict[str, str | None]:
    return {"ComputeImagesStatistics": shutil.which("otbcli_ComputeImagesStatistics")}


def validate_feature_range_config(config, layout, apps) -> tuple[dict[str, bool], list[str]]:
    checks = {key: True for key in CHECK_KEYS}
    failure_reasons: list[str] = []
    feature_space_stack_path = Path(config.feature_space_stack_path)
    scale_candidates_json_path = Path(config.scale_candidates_json_path)
    output_paths = {
        "output_ranger_csv_path_available": layout["ranger_dir"] / config.output_ranger_csv_filename,
        "output_ranger_json_path_available": layout["ranger_dir"] / config.output_ranger_json_filename,
        "output_assigned_csv_path_available": layout["ranger_dir"] / config.output_assigned_csv_filename,
        "output_assigned_json_path_available": layout["ranger_dir"] / config.output_assigned_json_filename,
    }

    if not str(config.candidate_id).strip():
        checks["candidate_id_non_empty"] = False
        failure_reasons.append("candidate_id is empty")
    if not feature_space_stack_path.exists():
        checks["feature_space_stack_path_exists"] = False
        failure_reasons.append("feature_space_stack_path does not exist")
    if feature_space_stack_path.suffix.lower() not in RASTER_SUFFIXES:
        checks["feature_space_stack_suffix_raster_like"] = False
        failure_reasons.append("feature_space_stack_path suffix must be one of .tif, .tiff, .vrt, .img, .jp2")
    if config.feature_space_source not in FEATURE_SPACE_SOURCES:
        checks["feature_space_source_valid"] = False
        failure_reasons.append("feature_space_source must be exactly scaled or pca")
    if not scale_candidates_json_path.exists():
        checks["scale_candidates_json_path_exists"] = False
        failure_reasons.append("scale_candidates_json_path does not exist")
    if scale_candidates_json_path.suffix.lower() != ".json":
        checks["scale_candidates_json_path_suffix_json"] = False
        failure_reasons.append("scale_candidates_json_path suffix must be .json")
    if not isinstance(config.band_count, int) or isinstance(config.band_count, bool) or config.band_count <= 0:
        checks["band_count_positive_integer"] = False
        failure_reasons.append("band_count must be a positive integer")
    if (
        not isinstance(config.ranger_multiplier, (int, float))
        or isinstance(config.ranger_multiplier, bool)
        or config.ranger_multiplier <= 0
    ):
        checks["ranger_multiplier_numeric_positive"] = False
        failure_reasons.append("ranger_multiplier must be numeric and > 0")
    if not isinstance(config.background_value, (int, float)) or isinstance(config.background_value, bool):
        checks["background_value_numeric"] = False
        failure_reasons.append("background_value must be numeric")
    if not apps.get("ComputeImagesStatistics"):
        checks["otb_compute_images_statistics_discoverable"] = False
        failure_reasons.append("no OTB ComputeImagesStatistics app discoverable")
    if not config.overwrite:
        for check_key, output_path in output_paths.items():
            if output_path.exists():
                checks[check_key] = False
                failure_reasons.append(f"{output_path.name} already exists and overwrite is false")

    return checks, failure_reasons


def build_feature_statistics_command(config, apps, layout) -> list[str]:
    return [
        "otbcli_ComputeImagesStatistics",
        "-il",
        str(Path(config.feature_space_stack_path)),
        "-bv",
        str(float(config.background_value)),
        "-out.xml",
        str(layout["tmp_ranger_dir"] / "feature_statistics.xml"),
    ]


def parse_feature_statistics_xml(xml_path, band_count) -> dict[str, list[float]]:
    try:
        root = ET.parse(xml_path).getroot()
    except Exception as exc:
        raise ValueError("invalid feature statistics: XML cannot be parsed") from exc

    standard_deviations: list[float] = []
    number_pattern = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")

    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1].lower()
        attrib_text = " ".join(f"{key} {value}" for key, value in element.attrib.items()).lower()
        if "std" not in tag and "standard_deviation" not in tag and "std" not in attrib_text:
            continue
        text = " ".join(part for part in element.itertext() if part)
        for match in number_pattern.findall(text):
            standard_deviations.append(float(match))

    if len(standard_deviations) < band_count:
        raise ValueError("invalid feature statistics: standard deviations are missing")

    standard_deviations = standard_deviations[:band_count]
    if any(value <= 0 for value in standard_deviations):
        raise ValueError("invalid feature statistics: standard deviations must be > 0")

    return {"standard_deviations": standard_deviations}


def build_single_ranger_candidate(config, feature_stats) -> dict[str, object]:
    standard_deviations = feature_stats["standard_deviations"]
    feature_std_l2 = sqrt(sum(value**2 for value in standard_deviations))
    ranger = feature_std_l2 * float(config.ranger_multiplier)
    return {
        "ranger_id": f"{str(config.candidate_id).strip()}_ranger_001",
        "ranger_index": 1,
        "ranger": ranger,
        "ranger_multiplier": float(config.ranger_multiplier),
        "feature_std_l2": feature_std_l2,
        "feature_space_source": config.feature_space_source,
        "band_count": config.band_count,
        "ranger_source": RANGER_SOURCE,
    }


def read_scale_candidates(json_path) -> list[dict[str, object]]:
    with Path(json_path).open(encoding="utf-8") as file_obj:
        payload = json.load(file_obj)

    if "candidates" not in payload:
        raise ValueError("scale candidates are missing candidates")
    candidates = payload["candidates"]
    if not candidates:
        raise ValueError("scale candidates are empty")
    for candidate in candidates:
        if "candidate_id" not in candidate:
            raise ValueError("scale candidate lacks candidate_id")
        if "spatialr_px" not in candidate:
            raise ValueError("scale candidate lacks spatialr_px")
        if "minsize_px" not in candidate:
            raise ValueError("scale candidate lacks minsize_px")
    return candidates


def assign_single_ranger_to_scale_candidates(scale_candidates, ranger_candidate) -> list[dict[str, object]]:
    assigned_candidates: list[dict[str, object]] = []
    for scale_candidate in scale_candidates:
        scale_id = scale_candidate["candidate_id"]
        ranger_id = ranger_candidate["ranger_id"]
        assigned_candidates.append(
            {
                "candidate_id": f"{scale_id}__{ranger_id}",
                "scale_id": scale_id,
                "ranger_id": ranger_id,
                "spatialr_px": scale_candidate["spatialr_px"],
                "minsize_px": scale_candidate["minsize_px"],
                "ranger": ranger_candidate["ranger"],
                "ranger_source": ranger_candidate["ranger_source"],
                "assignment_rule": ASSIGNMENT_RULE,
            }
        )
    return assigned_candidates


def write_ranger_candidates_csv(candidates, csv_path) -> None:
    with Path(csv_path).open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=RANGER_FIELDS)
        writer.writeheader()
        writer.writerows({key: candidate[key] for key in RANGER_FIELDS} for candidate in candidates)


def write_ranger_candidates_json(config, layout, feature_stats, ranger_candidate, json_path) -> None:
    payload = {
        "candidate_id": str(config.candidate_id).strip(),
        "feature_space_stack_path": str(Path(config.feature_space_stack_path)),
        "feature_space_source": config.feature_space_source,
        "band_count": config.band_count,
        "background_value": float(config.background_value),
        "feature_statistics_xml_path": str(layout["tmp_ranger_dir"] / "feature_statistics.xml"),
        "feature_std_l2": ranger_candidate["feature_std_l2"],
        "ranger_multiplier": float(config.ranger_multiplier),
        "ranger_source": RANGER_SOURCE,
        "ranger_count": 1,
        "ranger_candidates": [{key: ranger_candidate[key] for key in RANGER_FIELDS}],
    }
    with Path(json_path).open("w", encoding="utf-8") as file_obj:
        json.dump({key: payload[key] for key in RANGER_JSON_KEYS}, file_obj, indent=2)


def write_assigned_candidates_csv(candidates, csv_path) -> None:
    with Path(csv_path).open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=ASSIGNED_FIELDS)
        writer.writeheader()
        writer.writerows({key: candidate[key] for key in ASSIGNED_FIELDS} for candidate in candidates)


def write_assigned_candidates_json(config, assigned_candidates, json_path) -> None:
    ranger_json_path = Path(config.output_dir) / "level1b" / "ranger" / config.output_ranger_json_filename
    payload = {
        "candidate_id": str(config.candidate_id).strip(),
        "scale_candidates_json_path": str(Path(config.scale_candidates_json_path)),
        "ranger_candidates_json_path": str(ranger_json_path),
        "assignment_rule": ASSIGNMENT_RULE,
        "scale_candidate_count": len(assigned_candidates),
        "ranger_candidate_count": 1,
        "assigned_candidate_count": len(assigned_candidates),
        "candidates": assigned_candidates,
    }
    with Path(json_path).open("w", encoding="utf-8") as file_obj:
        json.dump({key: payload[key] for key in ASSIGNED_JSON_KEYS}, file_obj, indent=2)


def run_feature_range_assignment_step(config) -> dict[str, object]:
    layout = build_level1b_feature_range_layout(config.output_dir)
    apps = discover_feature_range_otb_apps()
    checks, failure_reasons = validate_feature_range_config(config, layout, apps)
    feature_statistics_xml_path = layout["tmp_ranger_dir"] / "feature_statistics.xml"
    ranger_csv_path = layout["ranger_dir"] / config.output_ranger_csv_filename
    ranger_json_path = layout["ranger_dir"] / config.output_ranger_json_filename
    assigned_csv_path = layout["ranger_dir"] / config.output_assigned_csv_filename
    assigned_json_path = layout["ranger_dir"] / config.output_assigned_json_filename
    otb_command: list[str] = []
    command_result = None
    feature_std_l2 = None
    ranger = None
    ranger_count = 0
    scale_candidate_count = 0
    assigned_candidate_count = 0
    files_written: list[str] = []
    status = "failed"

    if not failure_reasons:
        otb_command = build_feature_statistics_command(config, apps, layout)
        result = subprocess.run(otb_command, capture_output=True, text=True)
        command_result = {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        if result.returncode != 0:
            failure_reasons.append("OTB ComputeImagesStatistics failed")
        else:
            try:
                feature_stats = parse_feature_statistics_xml(feature_statistics_xml_path, config.band_count)
                ranger_candidate = build_single_ranger_candidate(config, feature_stats)
                scale_candidates = read_scale_candidates(config.scale_candidates_json_path)
                assigned_candidates = assign_single_ranger_to_scale_candidates(scale_candidates, ranger_candidate)
            except Exception as exc:
                failure_reasons.append(str(exc))
            else:
                write_ranger_candidates_csv([ranger_candidate], ranger_csv_path)
                write_ranger_candidates_json(config, layout, feature_stats, ranger_candidate, ranger_json_path)
                write_assigned_candidates_csv(assigned_candidates, assigned_csv_path)
                write_assigned_candidates_json(config, assigned_candidates, assigned_json_path)
                feature_std_l2 = ranger_candidate["feature_std_l2"]
                ranger = ranger_candidate["ranger"]
                ranger_count = 1
                scale_candidate_count = len(scale_candidates)
                assigned_candidate_count = len(assigned_candidates)
                files_written = [
                    str(ranger_csv_path),
                    str(ranger_json_path),
                    str(assigned_csv_path),
                    str(assigned_json_path),
                ]
                status = "ok"

    return {
        "candidate_id": str(config.candidate_id).strip(),
        "output_dir": str(Path(config.output_dir)),
        "ranger_dir": str(layout["ranger_dir"]),
        "tmp_ranger_dir": str(layout["tmp_ranger_dir"]),
        "feature_space_stack_path": str(Path(config.feature_space_stack_path)),
        "feature_space_source": config.feature_space_source,
        "scale_candidates_json_path": str(Path(config.scale_candidates_json_path)),
        "feature_statistics_xml_path": str(feature_statistics_xml_path),
        "output_ranger_csv_path": str(ranger_csv_path),
        "output_ranger_json_path": str(ranger_json_path),
        "output_assigned_csv_path": str(assigned_csv_path),
        "output_assigned_json_path": str(assigned_json_path),
        "band_count": config.band_count,
        "background_value": config.background_value,
        "ranger_multiplier": config.ranger_multiplier,
        "checks": checks,
        "status": status,
        "failure_reasons": failure_reasons,
        "otb_apps": apps,
        "otb_command": otb_command,
        "command_result": command_result,
        "feature_std_l2": feature_std_l2,
        "ranger": ranger,
        "ranger_count": ranger_count,
        "scale_candidate_count": scale_candidate_count,
        "assigned_candidate_count": assigned_candidate_count,
        "files_written": files_written,
        "no_spatial_scale_candidates_created": True,
        "no_spatialr_or_minsize_modified": True,
        "no_ranger_grid_created": True,
        "no_segmentation_performed": True,
    }
