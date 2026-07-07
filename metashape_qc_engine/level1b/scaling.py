from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

from metashape_qc_engine.level1b.otb_env import (
    discover_otb_cli,
    otb_subprocess_command,
    otb_subprocess_kwargs,
)

import numpy as np
from osgeo import gdal

from metashape_qc_engine.level1b.step_manifest import write_step_manifest


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
    "scratch_cleanup",
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
        "BandMathX": discover_otb_cli("otbcli_BandMathX"),
        "ComputeImagesStatistics": discover_otb_cli("otbcli_ComputeImagesStatistics"),
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


def compute_quantile_scaling_parameters(
    masked_stack_path,
    config,
    *,
    quantile_probs: tuple[float, float] = (0.02, 0.98),
) -> dict[str, list[float]]:
    dataset = gdal.Open(str(masked_stack_path))
    if dataset is None:
        raise ValueError(f"could not open masked feature stack: {masked_stack_path}")

    background_value = float(config.background_value)
    lower_values = []
    upper_values = []
    centers = []
    scales = []

    for band_index in range(1, config.band_count + 1):
        array = dataset.GetRasterBand(band_index).ReadAsArray().astype("float64")
        valid_values = array[(array != background_value) & np.isfinite(array)]
        if valid_values.size == 0:
            raise ValueError(f"band {band_index}: no valid pixels for robust scaling")

        lower, upper = np.quantile(valid_values, quantile_probs)
        if upper <= lower:
            raise ValueError(f"band {band_index}: robust scaling upper <= lower")

        center = (float(lower) + float(upper)) / 2.0
        scale = (float(upper) - float(lower)) / 2.0
        lower_values.append(float(lower))
        upper_values.append(float(upper))
        centers.append(center)
        scales.append(scale)

    return {
        "lower_values": lower_values,
        "upper_values": upper_values,
        "centers": centers,
        "scales": scales,
    }


def build_quantile_scaling_command(config, apps, layout, stats) -> list[str]:
    expressions = []
    for band_index, (center, scale) in enumerate(
        zip(stats["centers"], stats["scales"], strict=True),
        start=1,
    ):
        raw = f"((im1b{band_index} - {center}) / {scale})"
        clipped = f"({raw} < -1.0 ? -1.0 : ({raw} > 1.0 ? 1.0 : {raw}))"
        expressions.append(
            f"(im2b1 > 0 ? {clipped} : {float(config.background_value)})"
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


# LEGACY Z-SCORE SCALING COMMAND, intentionally commented out.
# Kept here during the robust-scaling test so the old implementation is not lost.
#
# def build_zscore_scaling_command(config, apps, layout, stats) -> list[str]:
#     expressions = []
#     for band_index, (mean, standard_deviation) in enumerate(
#         zip(stats["means"], stats["standard_deviations"], strict=True),
#         start=1,
#     ):
#         expressions.append(
#             f"(im2b1 > 0 ? ((im1b{band_index} - {mean}) / {standard_deviation}) : {float(config.background_value)})"
#         )
#     return [
#         apps["BandMathX"],
#         "-il",
#         str(Path(config.feature_stack_path)),
#         str(Path(config.valid_mask_path)),
#         "-out",
#         str(layout["scaling_dir"] / config.output_filename),
#         "float",
#         "-exp",
#         "{" + ";".join(expressions) + "}",
#     ]


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
        result = subprocess.run(
            otb_subprocess_command(command),
            capture_output=True,
            text=True,
            **otb_subprocess_kwargs(command),
        )
        report["command_results"].append(_command_result(command, result))
        if result.returncode != 0:
            report["status"] = "failed"
            report["failure_reasons"].append(f"command failed: {Path(command[0]).name}")
            _refresh_artifact_flags(report)
            _write_report(report)
            return report

    _refresh_artifact_flags(report)
    try:
        stats = compute_quantile_scaling_parameters(
            layout["runtime_scaling_tmp_dir"] / "masked_feature_stack_tmp.tif",
            config,
        )
    except ValueError as exc:
        report["status"] = "failed"
        report["failure_reasons"].append(str(exc))
        _write_report(report)
        return report

    parameters = {
        "method": "robust_percentile_clipped",
        "lower_quantile": 0.02,
        "upper_quantile": 0.98,
        "output_min": -1.0,
        "output_max": 1.0,
        "band_count": config.band_count,
        "background_value": float(config.background_value),
        "lower_values": stats["lower_values"],
        "upper_values": stats["upper_values"],
        "centers": stats["centers"],
        "scales": stats["scales"],
        "source_masked_stack": str(
            layout["runtime_scaling_tmp_dir"] / "masked_feature_stack_tmp.tif"
        ),
    }
    report.update(parameters)
    with (layout["scaling_dir"] / config.parameters_json_filename).open("w", encoding="utf-8") as handle:
        json.dump(parameters, handle, indent=2, sort_keys=True)
        handle.write("\n")
    report["scaling_parameters_json_written"] = True

    robust_command = build_quantile_scaling_command(config, apps, layout, stats)
    report["otb_commands"].append(robust_command)
    result = subprocess.run(
        otb_subprocess_command(robust_command),
        capture_output=True,
        text=True,
        **otb_subprocess_kwargs(robust_command),
    )
    report["command_results"].append(_command_result(robust_command, result))
    if result.returncode != 0:
        report["status"] = "failed"
        report["failure_reasons"].append(f"command failed: {Path(robust_command[0]).name}")
    else:
        report["status"] = "ok"

    # LEGACY Z-SCORE RUN BLOCK, intentionally commented out.
    # Kept here during the robust-scaling test so the old implementation is not lost.
    #
    # try:
    #     stats = parse_scaling_statistics_xml(
    #         layout["scaling_dir"] / config.parameters_xml_filename,
    #         config.band_count,
    #     )
    # except ValueError as exc:
    #     report["status"] = "failed"
    #     report["failure_reasons"].append(str(exc))
    #     _write_report(report)
    #     return report
    #
    # parameters = {
    #     "band_count": config.band_count,
    #     "background_value": float(config.background_value),
    #     "means": stats["means"],
    #     "standard_deviations": stats["standard_deviations"],
    #     "source_xml": str(layout["scaling_dir"] / config.parameters_xml_filename),
    # }
    # with (layout["scaling_dir"] / config.parameters_json_filename).open("w", encoding="utf-8") as handle:
    #     json.dump(parameters, handle, indent=2, sort_keys=True)
    #     handle.write("\n")
    # report["scaling_parameters_json_written"] = True
    #
    # zscore_command = build_zscore_scaling_command(config, apps, layout, stats)
    # report["otb_commands"].append(zscore_command)
    # result = subprocess.run(zscore_command, capture_output=True, text=True)
    # report["command_results"].append(_command_result(zscore_command, result))
    # if result.returncode != 0:
    #     report["status"] = "failed"
    #     report["failure_reasons"].append(f"command failed: {Path(zscore_command[0]).name}")
    # else:
    #     report["status"] = "ok"

    _refresh_artifact_flags(report)
    report["scratch_cleanup"] = _cleanup_scaling_scratch(
        layout["runtime_scaling_tmp_dir"],
        required_outputs=(
            Path(report["scaled_feature_stack_path"]),
            Path(report["scaling_parameters_xml_path"]),
            Path(report["scaling_parameters_json_path"]),
        ),
        status=str(report["status"]),
        dry_run=bool(config.dry_run),
    )
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
        "scratch_cleanup": {
            "path": str(layout["runtime_scaling_tmp_dir"]),
            "status": "skipped",
            "bytes_reclaimed": 0,
            "reason": "scaling_step_not_finished",
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "no_pca_performed": True,
        "no_scale_" + "candidates_generated": True,
        "no_seg" + "mentation_performed": True,
    }
    return {key: values[key] for key in REPORT_KEYS}


def _cleanup_scaling_scratch(
    scratch_dir: Path,
    *,
    required_outputs: tuple[Path, ...],
    status: str,
    dry_run: bool,
) -> dict[str, object]:
    """Remove scaling scratch only after every canonical output is non-empty."""

    result: dict[str, object] = {
        "path": str(scratch_dir),
        "status": "skipped",
        "bytes_reclaimed": 0,
    }
    if dry_run or status != "ok":
        result["reason"] = "scaling_step_not_successful"
        return result
    if any(not path.is_file() or path.stat().st_size == 0 for path in required_outputs):
        result["reason"] = "canonical_scaling_output_missing_or_empty"
        return result
    if not scratch_dir.exists():
        result["status"] = "complete"
        result["reason"] = "scratch_already_absent"
        return result

    bytes_reclaimed = sum(
        path.stat().st_size
        for path in scratch_dir.rglob("*")
        if path.is_file()
    )
    try:
        shutil.rmtree(scratch_dir)
    except OSError as exc:
        result["status"] = "failed"
        result["reason"] = str(exc)
        return result
    result["status"] = "complete"
    result["reason"] = "canonical_scaling_outputs_verified"
    result["bytes_reclaimed"] = bytes_reclaimed
    return result


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
    write_step_manifest(
        report["output_dir"],
        step="scaling",
        status=report["status"],
        inputs={
            "feature_stack": report["feature_stack_path"],
            "valid_mask": report["valid_mask_path"],
        },
        artifacts={
            "scaled_feature_stack": report["scaled_feature_stack_path"],
            "scaling_parameters_xml": report["scaling_parameters_xml_path"],
            "scaling_parameters_json": report["scaling_parameters_json_path"],
            "report": path,
        },
        candidate_id=report["candidate_id"],
    )
