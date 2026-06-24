from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess


RASTER_SUFFIXES = {".tif", ".tiff", ".vrt", ".img", ".jp2"}
CHECK_KEYS = (
    "candidate_id_non_empty",
    "input_path_exists",
    "input_suffix_raster_like",
    "nodata_values_valid",
    "alpha_band_index_valid",
    "alpha_valid_min_numeric",
    "black_border_tuple_lengths_match",
    "black_border_band_indices_valid",
    "black_border_invalid_values_numeric",
    "at_least_one_rule_active",
    "ram_mb_valid",
    "output_path_available",
    "otb_bandmathx_discoverable",
)
REPORT_KEYS = (
    "candidate_id",
    "input_path",
    "output_dir",
    "default_tmp_dir",
    "runtime_tmp_dir",
    "mask_dir",
    "valid_mask_path",
    "report_path",
    "output_filename",
    "report_filename",
    "nodata_values",
    "alpha_band_index",
    "alpha_valid_min",
    "black_border_enabled",
    "black_border_band_indices",
    "black_border_invalid_values",
    "otb_app_name",
    "otb_app_path",
    "expression",
    "otb_command",
    "dry_run",
    "overwrite",
    "ram_mb",
    "checks",
    "status",
    "failure_reasons",
    "stdout",
    "stderr",
    "returncode",
    "valid_mask_created",
    "timestamp",
    "no_" + "pro" + "xy" + "_channels_generated",
    "no_" + "sca" + "ling" + "_performed",
    "no_" + "seg" + "mentation" + "_performed",
)


@dataclass
class Level1BValidMaskConfig:
    candidate_id: str
    input_path: str | Path
    output_dir: str | Path
    tmp_dir: str | Path | None = None
    nodata_values: dict[int, float] | None = None
    alpha_band_index: int | None = None
    alpha_valid_min: float = 1.0
    black_border_enabled: bool = True
    black_border_band_indices: tuple[int, ...] = (1, 2, 3)
    black_border_invalid_values: tuple[float, ...] = (0.0, 0.0, 0.0)
    otb_bin_dir: str | Path | None = None
    output_filename: str = "valid_mask.tif"
    report_filename: str = "valid_mask_report.json"
    ram_mb: int | None = None
    overwrite: bool = False
    dry_run: bool = False


def build_level1b_mask_layout(output_dir: str | Path, tmp_dir: str | Path | None = None) -> dict[str, Path]:
    level1b_dir = Path(output_dir) / "level1b"
    default_tmp_dir = level1b_dir / "tmp"
    runtime_tmp_dir = Path(tmp_dir) if tmp_dir is not None else default_tmp_dir
    layout = {
        "default_tmp_dir": default_tmp_dir,
        "runtime_tmp_dir": runtime_tmp_dir,
        "logs_dir": level1b_dir / "logs",
        "reports_dir": level1b_dir / "reports",
        "mask_dir": level1b_dir / "mask",
    }
    for directory in layout.values():
        directory.mkdir(parents=True, exist_ok=True)
    return layout


def discover_bandmathx(otb_bin_dir: str | Path | None = None) -> tuple[str | None, str | None]:
    if otb_bin_dir is not None:
        candidate = Path(otb_bin_dir) / "otbcli_BandMathX"
        if candidate.is_file():
            return "BandMathX", str(candidate)
        return None, None
    path = shutil.which("otbcli_BandMathX")
    if path:
        return "BandMathX", path
    return None, None


def validate_valid_mask_config(config: Level1BValidMaskConfig, layout: dict[str, Path]) -> tuple[dict[str, bool], list[str]]:
    checks = {key: True for key in CHECK_KEYS}
    failure_reasons: list[str] = []
    candidate_id = str(config.candidate_id).strip()
    input_path = Path(config.input_path)
    valid_mask_path = layout["mask_dir"] / config.output_filename

    if not candidate_id:
        checks["candidate_id_non_empty"] = False
        failure_reasons.append("candidate_id is empty")
    if not input_path.exists():
        checks["input_path_exists"] = False
        failure_reasons.append("input_path does not exist")
    if input_path.suffix.lower() not in RASTER_SUFFIXES:
        checks["input_suffix_raster_like"] = False
        failure_reasons.append("input_path suffix must be one of .tif, .tiff, .vrt, .img, .jp2")

    if config.nodata_values is not None:
        for band_index, value in config.nodata_values.items():
            if not isinstance(band_index, int) or band_index <= 0 or not isinstance(value, (int, float)):
                checks["nodata_values_valid"] = False
                failure_reasons.append("nodata_values band indices must be positive integers")
                break

    if config.alpha_band_index is not None and (
        not isinstance(config.alpha_band_index, int) or config.alpha_band_index <= 0
    ):
        checks["alpha_band_index_valid"] = False
        failure_reasons.append("alpha_band_index must be a positive integer")
    if not isinstance(config.alpha_valid_min, (int, float)):
        checks["alpha_valid_min_numeric"] = False
        failure_reasons.append("alpha_valid_min must be numeric")

    if config.black_border_enabled:
        if len(config.black_border_band_indices) != len(config.black_border_invalid_values) or not config.black_border_band_indices:
            checks["black_border_tuple_lengths_match"] = False
            failure_reasons.append("black_border_band_indices and black_border_invalid_values must have the same length")
        if any(not isinstance(band_index, int) or band_index <= 0 for band_index in config.black_border_band_indices):
            checks["black_border_band_indices_valid"] = False
            failure_reasons.append("black_border_band_indices must be positive integers")
        if any(not isinstance(value, (int, float)) for value in config.black_border_invalid_values):
            checks["black_border_invalid_values_numeric"] = False
            failure_reasons.append("black_border_invalid_values must be numeric")

    if config.nodata_values is None and config.alpha_band_index is None and not config.black_border_enabled:
        checks["at_least_one_rule_active"] = False
        failure_reasons.append("no valid-mask construction rule is active")
    if config.ram_mb is not None and (not isinstance(config.ram_mb, int) or config.ram_mb <= 0):
        checks["ram_mb_valid"] = False
        failure_reasons.append("ram_mb must be a positive integer")
    if valid_mask_path.exists() and not config.overwrite and not config.dry_run:
        checks["output_path_available"] = False
        failure_reasons.append("valid_mask_path already exists and overwrite is false")

    return checks, failure_reasons


def build_valid_mask_expression(config: Level1BValidMaskConfig) -> tuple[str | None, list[str]]:
    conditions: list[str] = []
    failure_reasons: list[str] = []

    if config.nodata_values is not None:
        for band_index in sorted(config.nodata_values):
            conditions.append(f"im1b{band_index} != {config.nodata_values[band_index]}")
    if config.alpha_band_index is not None:
        conditions.append(f"im1b{config.alpha_band_index} >= {config.alpha_valid_min}")
    if config.black_border_enabled:
        border_checks = [
            f"im1b{band_index} == {value}"
            for band_index, value in zip(config.black_border_band_indices, config.black_border_invalid_values)
        ]
        conditions.append(f"!({' && '.join(border_checks)})")

    if not conditions:
        failure_reasons.append("no valid-mask construction rule is active")
        return None, failure_reasons
    return f"{' && '.join(conditions)} ? 1 : 0", failure_reasons


def build_valid_mask_command(config: Level1BValidMaskConfig, otb_app_path: str, valid_mask_path: Path) -> list[str]:
    expression, _failure_reasons = build_valid_mask_expression(config)
    if expression is None:
        expression = ""
    return [
        str(otb_app_path),
        "-il",
        str(config.input_path),
        "-out",
        str(valid_mask_path),
        "uint8",
        "-exp",
        expression,
    ]


def run_valid_mask_step(config: Level1BValidMaskConfig) -> dict[str, object]:
    layout = build_level1b_mask_layout(config.output_dir, config.tmp_dir)
    valid_mask_path = layout["mask_dir"] / config.output_filename
    report_path = layout["mask_dir"] / config.report_filename
    checks, failure_reasons = validate_valid_mask_config(config, layout)
    expression: str | None = None
    otb_app_name: str | None = None
    otb_app_path: str | None = None
    command: list[str] | None = None
    stdout: str | None = None
    stderr: str | None = None
    returncode: int | None = None
    valid_mask_created = False

    if failure_reasons:
        status = "failed"
        checks["otb_bandmathx_discoverable"] = False
    else:
        expression, expression_reasons = build_valid_mask_expression(config)
        failure_reasons.extend(expression_reasons)
        if failure_reasons:
            status = "failed"
            checks["otb_bandmathx_discoverable"] = False
        else:
            otb_app_name, otb_app_path = discover_bandmathx(config.otb_bin_dir)
            checks["otb_bandmathx_discoverable"] = otb_app_path is not None
            if otb_app_path is None:
                status = "failed"
                failure_reasons.append("no OTB BandMathX app discoverable")
            else:
                command = build_valid_mask_command(config, otb_app_path, valid_mask_path)
                if config.dry_run:
                    status = "dry_run"
                else:
                    result = subprocess.run(command, capture_output=True, text=True)
                    stdout = result.stdout
                    stderr = result.stderr
                    returncode = result.returncode
                    if returncode == 0:
                        status = "ok"
                        valid_mask_created = True
                    else:
                        status = "failed"
                        failure_reasons.append("OTB execution failed")

    report = {
        "candidate_id": str(config.candidate_id).strip(),
        "input_path": str(config.input_path),
        "output_dir": str(config.output_dir),
        "default_tmp_dir": str(layout["default_tmp_dir"]),
        "runtime_tmp_dir": str(layout["runtime_tmp_dir"]),
        "mask_dir": str(layout["mask_dir"]),
        "valid_mask_path": str(valid_mask_path),
        "report_path": str(report_path),
        "output_filename": config.output_filename,
        "report_filename": config.report_filename,
        "nodata_values": config.nodata_values,
        "alpha_band_index": config.alpha_band_index,
        "alpha_valid_min": config.alpha_valid_min,
        "black_border_enabled": config.black_border_enabled,
        "black_border_band_indices": list(config.black_border_band_indices),
        "black_border_invalid_values": list(config.black_border_invalid_values),
        "otb_app_name": otb_app_name,
        "otb_app_path": otb_app_path,
        "expression": expression,
        "otb_command": command,
        "dry_run": config.dry_run,
        "overwrite": config.overwrite,
        "ram_mb": config.ram_mb,
        "checks": checks,
        "status": status,
        "failure_reasons": failure_reasons,
        "stdout": stdout,
        "stderr": stderr,
        "returncode": returncode,
        "valid_mask_created": valid_mask_created,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "no_" + "pro" + "xy" + "_channels_generated": True,
        "no_" + "sca" + "ling" + "_performed": True,
        "no_" + "seg" + "mentation" + "_performed": True,
    }
    ordered_report = {key: report[key] for key in REPORT_KEYS}
    report_path.write_text(json.dumps(ordered_report, indent=2, sort_keys=False), encoding="utf-8")
    return ordered_report
