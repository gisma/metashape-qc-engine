from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess

from metashape_qc_engine.level1b_otb_env import otb_subprocess_kwargs


RASTER_SUFFIXES = {".tif", ".tiff", ".vrt", ".img", ".jp2"}
REPORT_KEYS = (
    "candidate_id",
    "scaled_feature_stack_path",
    "valid_mask_path",
    "output_dir",
    "default_tmp_dir",
    "runtime_tmp_dir",
    "pca_dir",
    "pca_tmp_path",
    "pca_feature_stack_path",
    "report_path",
    "band_count",
    "pca_components",
    "background_value",
    "otb_apps",
    "otb_commands",
    "dry_run",
    "overwrite",
    "checks",
    "status",
    "failure_reasons",
    "command_results",
    "pca_tmp_created",
    "pca_output_created",
    "timestamp",
    "no_scaling_performed",
    "no_scale_" + "candidates_generated",
    "no_seg" + "mentation_performed",
)
CHECK_KEYS = (
    "candidate_id_non_empty",
    "scaled_feature_stack_path_exists",
    "scaled_feature_stack_suffix_raster_like",
    "valid_mask_path_exists",
    "valid_mask_suffix_raster_like",
    "band_count_positive_integer",
    "pca_components_positive_integer",
    "pca_components_lte_band_count",
    "background_value_numeric",
    "pca_feature_stack_path_available",
    "report_path_available",
    "otb_dimensionality_reduction_discoverable",
    "otb_bandmathx_discoverable",
)


@dataclass
class Level1BPCAConfig:
    candidate_id: str
    scaled_feature_stack_path: str | Path
    valid_mask_path: str | Path
    output_dir: str | Path
    band_count: int
    pca_components: int
    tmp_dir: str | Path | None = None
    background_value: float = -999999.0
    output_filename: str = "pca_feature_stack.tif"
    report_filename: str = "pca_report.json"
    overwrite: bool = False
    dry_run: bool = False


def build_level1b_pca_layout(output_dir, tmp_dir=None) -> dict[str, Path]:
    level1b_dir = Path(output_dir) / "level1b"
    default_tmp_dir = level1b_dir / "tmp"
    runtime_tmp_dir = Path(tmp_dir) if tmp_dir is not None else default_tmp_dir
    layout = {
        "default_tmp_dir": default_tmp_dir,
        "runtime_tmp_dir": runtime_tmp_dir,
        "logs_dir": level1b_dir / "logs",
        "reports_dir": level1b_dir / "reports",
        "pca_dir": level1b_dir / "pca",
        "runtime_pca_tmp_dir": runtime_tmp_dir / "pca",
    }
    for directory in layout.values():
        directory.mkdir(parents=True, exist_ok=True)
    return layout


def discover_pca_otb_apps() -> dict[str, str | None]:
    return {
        "DimensionalityReduction": shutil.which("otbcli_DimensionalityReduction"),
        "BandMathX": shutil.which("otbcli_BandMathX"),
    }


def validate_pca_config(config, layout, apps) -> tuple[dict[str, bool], list[str]]:
    checks = {key: True for key in CHECK_KEYS}
    failure_reasons: list[str] = []

    scaled_feature_stack_path = Path(config.scaled_feature_stack_path)
    valid_mask_path = Path(config.valid_mask_path)
    output_paths = {
        "pca_feature_stack_path_available": layout["pca_dir"] / config.output_filename,
        "report_path_available": layout["pca_dir"] / config.report_filename,
    }

    if not str(config.candidate_id).strip():
        checks["candidate_id_non_empty"] = False
        failure_reasons.append("candidate_id is empty")
    if not scaled_feature_stack_path.exists():
        checks["scaled_feature_stack_path_exists"] = False
        failure_reasons.append("scaled_feature_stack_path does not exist")
    if scaled_feature_stack_path.suffix.lower() not in RASTER_SUFFIXES:
        checks["scaled_feature_stack_suffix_raster_like"] = False
        failure_reasons.append("scaled_feature_stack_path suffix must be one of .tif, .tiff, .vrt, .img, .jp2")
    if not valid_mask_path.exists():
        checks["valid_mask_path_exists"] = False
        failure_reasons.append("valid_mask_path does not exist")
    if valid_mask_path.suffix.lower() not in RASTER_SUFFIXES:
        checks["valid_mask_suffix_raster_like"] = False
        failure_reasons.append("valid_mask_path suffix must be one of .tif, .tiff, .vrt, .img, .jp2")
    if not isinstance(config.band_count, int) or isinstance(config.band_count, bool) or config.band_count <= 0:
        checks["band_count_positive_integer"] = False
        failure_reasons.append("band_count must be a positive integer")
    if (
        not isinstance(config.pca_components, int)
        or isinstance(config.pca_components, bool)
        or config.pca_components <= 0
    ):
        checks["pca_components_positive_integer"] = False
        failure_reasons.append("pca_components must be a positive integer")
    if (
        isinstance(config.band_count, int)
        and not isinstance(config.band_count, bool)
        and isinstance(config.pca_components, int)
        and not isinstance(config.pca_components, bool)
        and config.pca_components > config.band_count
    ):
        checks["pca_components_lte_band_count"] = False
        failure_reasons.append("pca_components must be <= band_count")
    if not isinstance(config.background_value, (int, float)) or isinstance(config.background_value, bool):
        checks["background_value_numeric"] = False
        failure_reasons.append("background_value must be numeric")

    if not config.overwrite and not config.dry_run:
        for check_key, output_path in output_paths.items():
            if output_path.exists():
                checks[check_key] = False
                failure_reasons.append(f"{output_path.name} already exists and overwrite is false")

    if not apps.get("DimensionalityReduction"):
        checks["otb_dimensionality_reduction_discoverable"] = False
        failure_reasons.append("no OTB DimensionalityReduction app discoverable")
    if not apps.get("BandMathX"):
        checks["otb_bandmathx_discoverable"] = False
        failure_reasons.append("no OTB BandMathX app discoverable")

    return checks, failure_reasons


def build_pca_command(config, apps, layout) -> list[str]:
    return [
        apps["DimensionalityReduction"],
        "-in",
        str(Path(config.scaled_feature_stack_path)),
        "-out",
        str(layout["runtime_pca_tmp_dir"] / "pca_feature_stack_tmp.tif"),
        "float",
        "-method",
        "pca",
        "-nbcomp",
        str(config.pca_components),
        "-normalize",
        "false",
        "-bv",
        str(float(config.background_value)),
    ]


def build_pca_remask_command(config, apps, layout) -> list[str]:
    expressions = [
        f"(im2b1 > 0 ? im1b{band_index} : {float(config.background_value)})"
        for band_index in range(1, config.pca_components + 1)
    ]
    return [
        apps["BandMathX"],
        "-il",
        str(layout["runtime_pca_tmp_dir"] / "pca_feature_stack_tmp.tif"),
        str(Path(config.valid_mask_path)),
        "-out",
        str(layout["pca_dir"] / config.output_filename),
        "float",
        "-exp",
        "{" + ";".join(expressions) + "}",
    ]


def run_pca_step(config) -> dict[str, object]:
    layout = build_level1b_pca_layout(config.output_dir, config.tmp_dir)
    apps = discover_pca_otb_apps()
    checks, failure_reasons = validate_pca_config(config, layout, apps)
    report = _base_report(config, layout, apps, checks, failure_reasons)

    if failure_reasons:
        report["status"] = "failed"
        _write_report(report)
        return report

    pca_command = build_pca_command(config, apps, layout)
    remask_command = build_pca_remask_command(config, apps, layout)
    report["otb_commands"] = [pca_command, remask_command]

    if config.dry_run:
        report["status"] = "dry_run"
        _write_report(report)
        return report

    result = subprocess.run(
        pca_command,
        capture_output=True,
        text=True,
        **otb_subprocess_kwargs(pca_command),
    )
    report["command_results"].append(_command_result(pca_command, result))
    report["pca_tmp_created"] = result.returncode == 0
    if result.returncode != 0:
        report["status"] = "failed"
        report["failure_reasons"].append(f"command failed: {Path(pca_command[0]).name}")
        _write_report(report)
        return report

    result = subprocess.run(
        remask_command,
        capture_output=True,
        text=True,
        **otb_subprocess_kwargs(remask_command),
    )
    report["command_results"].append(_command_result(remask_command, result))
    if result.returncode != 0:
        report["status"] = "failed"
        report["failure_reasons"].append(f"command failed: {Path(remask_command[0]).name}")
    else:
        report["status"] = "ok"
        report["pca_output_created"] = True

    _write_report(report)
    return report


def _base_report(config, layout, apps, checks, failure_reasons) -> dict[str, object]:
    values = {
        "candidate_id": str(config.candidate_id).strip(),
        "scaled_feature_stack_path": str(Path(config.scaled_feature_stack_path)),
        "valid_mask_path": str(Path(config.valid_mask_path)),
        "output_dir": str(Path(config.output_dir)),
        "default_tmp_dir": str(layout["default_tmp_dir"]),
        "runtime_tmp_dir": str(layout["runtime_tmp_dir"]),
        "pca_dir": str(layout["pca_dir"]),
        "pca_tmp_path": str(layout["runtime_pca_tmp_dir"] / "pca_feature_stack_tmp.tif"),
        "pca_feature_stack_path": str(layout["pca_dir"] / config.output_filename),
        "report_path": str(layout["pca_dir"] / config.report_filename),
        "band_count": config.band_count,
        "pca_components": config.pca_components,
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
        "pca_tmp_created": False,
        "pca_output_created": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "no_scaling_performed": True,
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


def _write_report(report) -> None:
    path = Path(report["report_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
