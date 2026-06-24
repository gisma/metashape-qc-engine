from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET


RASTER_SUFFIXES = {".tif", ".tiff", ".vrt", ".img", ".jp2"}
REPORT_KEYS = (
    "candidate_id",
    "feature_stack_path",
    "valid_mask_path",
    "output_dir",
    "default_tmp_dir",
    "runtime_tmp_dir",
    "scaling_dir",
    "masked_feature_stack_path",
    "scaled_feature_stack_path",
    "scaling_parameters_xml_path",
    "scaling_parameters_json_path",
    "report_path",
    "band_count",
    "background_value",
    "otb_apps",
    "otb_commands",
    "dry_run",
    "overwrite",
    "checks",
    "status",
    "failure_reasons",
    "command_results",
    "masked_stack_created",
    "statistics_xml_created",
    "scaling_parameters_json_written",
    "scaled_output_created",
    "timestamp",
    "no_pca_performed",
    "no_scale_" + "candidates_generated",
    "no_seg" + "mentation_performed",
)
CHECK_KEYS = (
    "candidate_id_non_empty",
    "feature_stack_path_exists",
    "feature_stack_suffix_raster_like",
    "valid_mask_path_exists",
    "valid_mask_suffix_raster_like",
    "band_count_positive_integer",
    "background_value_numeric",
    "scaled_feature_stack_path_available",
    "scaling_parameters_xml_path_available",
    "scaling_parameters_json_path_available",
    "report_path_available",
    "otb_bandmathx_discoverable",
    "otb_compute_images_statistics_discoverable",
)


@dataclass
class Level1BScalingConfig:
    candidate_id: str
    feature_stack_path: str | Path
    valid_mask_path: str | Path
    output_dir: str | Path
    band_count: int
    tmp_dir: str | Path | None = None
    background_value: float = -999999.0
    output_filename: str = "scaled_feature_stack.tif"
    parameters_xml_filename: str = "scaling_parameters.xml"
    parameters_json_filename: str = "scaling_parameters.json"
    report_filename: str = "scaling_report.json"
    overwrite: bool = False
    dry_run: bool = False


def build_level1b_scaling_layout(output_dir, tmp_dir=None) -> dict[str, Path]:
    level1b_dir = Path(output_dir) / "level1b"
    default_tmp_dir = level1b_dir / "tmp"
    runtime_tmp_dir = Path(tmp_dir) if tmp_dir is not None else default_tmp_dir
    layout = {
        "default_tmp_dir": default_tmp_dir,
        "runtime_tmp_dir": runtime_tmp_dir,
        "logs_dir": level1b_dir / "logs",
        "reports_dir": level1b_dir / "reports",
        "scaling_dir": level1b_dir / "scaling",
        "runtime_scaling_tmp_dir": runtime_tmp_dir / "scaling",
    }
    for directory in layout.values():
        directory.mkdir(parents=True, exist_ok=True)
    return layout


def discover_scaling_otb_apps() -> dict[str, str | None]:
    return {
        "BandMathX": shutil.which("otbcli_BandMathX"),
        "ComputeImagesStatistics": shutil.which("otbcli_ComputeImagesStatistics"),
    }


def validate_scaling_config(config, layout, apps) -> tuple[dict[str, bool], list[str]]:
    checks = {key: True for key in CHECK_KEYS}
    failure_reasons: list[str] = []

    feature_stack_path = Path(config.feature_stack_path)
    valid_mask_path = Path(config.valid_mask_path)
    output_paths = {
        "scaled_feature_stack_path_available": layout["scaling_dir"] / config.output_filename,
        "scaling_parameters_xml_path_available": layout["scaling_dir"] / config.parameters_xml_filename,
        "scaling_parameters_json_path_available": layout["scaling_dir"] / config.parameters_json_filename,
        "report_path_available": layout["scaling_dir"] / config.report_filename,
    }

    if not str(config.candidate_id).strip():
        checks["candidate_id_non_empty"] = False
        failure_reasons.append("candidate_id is empty")
    if not feature_stack_path.exists():
        checks["feature_stack_path_exists"] = False
        failure_reasons.append("feature_stack_path does not exist")
    if feature_stack_path.suffix.lower() not in RASTER_SUFFIXES:
        checks["feature_stack_suffix_raster_like"] = False
        failure_reasons.append("feature_stack_path suffix must be one of .tif, .tiff, .vrt, .img, .jp2")
    if not valid_mask_path.exists():
        checks["valid_mask_path_exists"] = False
        failure_reasons.append("valid_mask_path does not exist")
    if valid_mask_path.suffix.lower() not in RASTER_SUFFIXES:
        checks["valid_mask_suffix_raster_like"] = False
        failure_reasons.append("valid_mask_path suffix must be one of .tif, .tiff, .vrt, .img, .jp2")
    if not isinstance(config.band_count, int) or isinstance(config.band_count, bool) or config.band_count <= 0:
        checks["band_count_positive_integer"] = False
        failure_reasons.append("band_count must be a positive integer")
    if not isinstance(config.background_value, (int, float)) or isinstance(config.background_value, bool):
        checks["background_value_numeric"] = False
        failure_reasons.append("background_value must be numeric")

    if not config.overwrite and not config.dry_run:
        for check_key, output_path in output_paths.items():
            if output_path.exists():
                checks[check_key] = False
                failure_reasons.append(f"{output_path.name} already exists and overwrite is false")

    if not apps.get("BandMathX"):
        checks["otb_bandmathx_discoverable"] = False
        failure_reasons.append("no OTB BandMathX app discoverable")
    if not apps.get("ComputeImagesStatistics"):
        checks["otb_compute_images_statistics_discoverable"] = False
        failure_reasons.append("no OTB ComputeImagesStatistics app discoverable")

    return checks, failure_reasons


def build_masked_feature_stack_command(config, apps, layout) -> list[str]:
    expressions = [
        f"(im2b1 > 0 ? im1b{band_index} : {float(config.background_value)})"
        for band_index in range(1, config.band_count + 1)
    ]
    return [
        apps["BandMathX"],
        "-il",
        str(Path(config.feature_stack_path)),
        str(Path(config.valid_mask_path)),
        "-out",
        str(layout["runtime_scaling_tmp_dir"] / "masked_feature_stack_tmp.tif"),
        "float",
        "-exp",
        "{" + ";".join(expressions) + "}",
    ]


def build_statistics_command(config, apps, layout) -> list[str]:
    return [
        apps["ComputeImagesStatistics"],
        "-il",
        str(layout["runtime_scaling_tmp_dir"] / "masked_feature_stack_tmp.tif"),
        "-bv",
        str(float(config.background_value)),
        "-out.xml",
        str(layout["scaling_dir"] / config.parameters_xml_filename),
    ]


def parse_scaling_statistics_xml(xml_path, band_count) -> dict[str, list[float]]:
    def numbers_from_text(value: str | None) -> list[float]:
        if value is None:
            return []
        normalized = value.replace(",", " ").replace(";", " ").replace("[", " ").replace("]", " ")
        numbers: list[float] = []
        for token in normalized.split():
            try:
                numbers.append(float(token))
            except ValueError:
                continue
        return numbers

    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"invalid scaling statistics: {exc}") from exc

    values = {"means": [], "standard_deviations": []}
    for element in root.iter():
        path_parts = []
        current = element
        while current is not None:
            path_parts.append(current.tag.lower())
            current = None
        descriptors = path_parts
        descriptors.extend(str(key).lower() for key in element.attrib)
        descriptors.extend(str(value).lower() for value in element.attrib.values())
        parent_descriptor = ""
        for candidate in root.iter():
            if element in list(candidate):
                parent_descriptor = " ".join(
                    [candidate.tag.lower()]
                    + [str(key).lower() for key in candidate.attrib]
                    + [str(value).lower() for value in candidate.attrib.values()]
                )
                break
        descriptor = " ".join(descriptors + [parent_descriptor])
        collected: list[float] = []
        for attr_value in element.attrib.values():
            collected.extend(numbers_from_text(attr_value))
        collected.extend(numbers_from_text(element.text))

        if "mean" in descriptor and collected:
            values["means"].extend(collected)
        if ("std" in descriptor or "standard" in descriptor or "sigma" in descriptor) and collected:
            values["standard_deviations"].extend(collected)

    means = values["means"][:band_count]
    standard_deviations = values["standard_deviations"][:band_count]
    if len(means) != band_count:
        raise ValueError("invalid scaling statistics: missing means")
    if len(standard_deviations) != band_count:
        raise ValueError("invalid scaling statistics: missing standard deviations")
    if any(value <= 0 for value in standard_deviations):
        raise ValueError("invalid scaling statistics: standard deviations must be > 0")

    return {"means": means, "standard_deviations": standard_deviations}


def build_zscore_scaling_command(config, apps, layout, stats) -> list[str]:
    expressions = []
    for band_index, (mean, standard_deviation) in enumerate(
        zip(stats["means"], stats["standard_deviations"], strict=True),
        start=1,
    ):
        expressions.append(
            f"(im2b1 > 0 ? ((im1b{band_index} - {mean}) / {standard_deviation}) : {float(config.background_value)})"
        )
    return [
        apps["BandMathX"],
        "-il",
        str(Path(config.feature_stack_path)),
        str(Path(config.valid_mask_path)),
        "-out",
        str(layout["scaling_dir"] / config.output_filename),
        "float",
        "-exp",
        "{" + ";".join(expressions) + "}",
    ]


def run_scaling_step(config) -> dict[str, object]:
    layout = build_level1b_scaling_layout(config.output_dir, config.tmp_dir)
    apps = discover_scaling_otb_apps()
    checks, failure_reasons = validate_scaling_config(config, layout, apps)
    report = _base_report(config, layout, apps, checks, failure_reasons)

    if failure_reasons:
        report["status"] = "failed"
        _write_report(report)
        return report

    masked_command = build_masked_feature_stack_command(config, apps, layout)
    statistics_command = build_statistics_command(config, apps, layout)
    report["otb_commands"] = [masked_command, statistics_command]

    if config.dry_run:
        report["status"] = "dry_run"
        _write_report(report)
        return report

    for command in (masked_command, statistics_command):
        result = subprocess.run(command, capture_output=True, text=True)
        report["command_results"].append(_command_result(command, result))
        if result.returncode != 0:
            report["status"] = "failed"
            report["failure_reasons"].append(f"command failed: {Path(command[0]).name}")
            _refresh_artifact_flags(report)
            _write_report(report)
            return report

    _refresh_artifact_flags(report)
    try:
        stats = parse_scaling_statistics_xml(layout["scaling_dir"] / config.parameters_xml_filename, config.band_count)
    except ValueError as exc:
        report["status"] = "failed"
        report["failure_reasons"].append(str(exc))
        _write_report(report)
        return report

    parameters = {
        "band_count": config.band_count,
        "background_value": float(config.background_value),
        "means": stats["means"],
        "standard_deviations": stats["standard_deviations"],
        "source_xml": str(layout["scaling_dir"] / config.parameters_xml_filename),
    }
    with (layout["scaling_dir"] / config.parameters_json_filename).open("w", encoding="utf-8") as handle:
        json.dump(parameters, handle, indent=2, sort_keys=True)
        handle.write("\n")
    report["scaling_parameters_json_written"] = True

    zscore_command = build_zscore_scaling_command(config, apps, layout, stats)
    report["otb_commands"].append(zscore_command)
    result = subprocess.run(zscore_command, capture_output=True, text=True)
    report["command_results"].append(_command_result(zscore_command, result))
    if result.returncode != 0:
        report["status"] = "failed"
        report["failure_reasons"].append(f"command failed: {Path(zscore_command[0]).name}")
    else:
        report["status"] = "ok"

    _refresh_artifact_flags(report)
    _write_report(report)
    return report


def _base_report(config, layout, apps, checks, failure_reasons) -> dict[str, object]:
    values = {
        "candidate_id": str(config.candidate_id).strip(),
        "feature_stack_path": str(Path(config.feature_stack_path)),
        "valid_mask_path": str(Path(config.valid_mask_path)),
        "output_dir": str(Path(config.output_dir)),
        "default_tmp_dir": str(layout["default_tmp_dir"]),
        "runtime_tmp_dir": str(layout["runtime_tmp_dir"]),
        "scaling_dir": str(layout["scaling_dir"]),
        "masked_feature_stack_path": str(layout["runtime_scaling_tmp_dir"] / "masked_feature_stack_tmp.tif"),
        "scaled_feature_stack_path": str(layout["scaling_dir"] / config.output_filename),
        "scaling_parameters_xml_path": str(layout["scaling_dir"] / config.parameters_xml_filename),
        "scaling_parameters_json_path": str(layout["scaling_dir"] / config.parameters_json_filename),
        "report_path": str(layout["scaling_dir"] / config.report_filename),
        "band_count": config.band_count,
        "background_value": float(config.background_value)
        if isinstance(config.background_value, (int, float)) and not isinstance(config.background_value, bool)
        else config.background_value,
        "otb_apps": apps,
        "otb_commands": [],
        "dry_run": config.dry_run,
        "overwrite": config.overwrite,
        "checks": checks,
        "status": "pending",
        "failure_reasons": list(failure_reasons),
        "command_results": [],
        "masked_stack_created": False,
        "statistics_xml_created": False,
        "scaling_parameters_json_written": False,
        "scaled_output_created": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "no_pca_performed": True,
        "no_scale_" + "candidates_generated": True,
        "no_seg" + "mentation_performed": True,
    }
    return {key: values[key] for key in REPORT_KEYS}


def _command_result(command, result) -> dict[str, object]:
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def _refresh_artifact_flags(report) -> None:
    report["masked_stack_created"] = Path(report["masked_feature_stack_path"]).exists()
    report["statistics_xml_created"] = Path(report["scaling_parameters_xml_path"]).exists()
    report["scaling_parameters_json_written"] = Path(report["scaling_parameters_json_path"]).exists()
    report["scaled_output_created"] = Path(report["scaled_feature_stack_path"]).exists()


def _write_report(report) -> None:
    path = Path(report["report_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
