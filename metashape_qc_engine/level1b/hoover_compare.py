from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import subprocess

from metashape_qc_engine.level1b.otb_env import (
    discover_otb_cli,
    otb_subprocess_command,
    otb_subprocess_kwargs,
)


HOOVER_APP_NAME = "otbcli_HooverCompareSegmentation"
RASTER_SUFFIXES = {".tif", ".tiff"}
REPORT_KEYS = (
    "candidate_id",
    "comparison_id",
    "baseline_labels_path",
    "perturbation_labels_path",
    "command",
    "returncode",
    "stdout_path",
    "stderr_text",
    "raw_output_path",
    "hoover_app_path",
    "parsed_metrics",
    "parser_status",
    "raster_only",
    "no_vector_output",
    "no_lsms_vectorization",
    "no_final_output",
    "no_scale_selection",
    "no_cli_integration",
    "checks",
    "failure_reasons",
    "status",
    "self_comparison",
)
CHECK_KEYS = (
    "comparison_id_non_empty",
    "output_dir_present",
    "baseline_labels_path_exists",
    "perturbation_labels_path_exists",
    "baseline_labels_suffix_raster_like",
    "perturbation_labels_suffix_raster_like",
    "output_artifacts_available",
    "hoover_compare_app_discoverable",
)


@dataclass
class Level1BHooverCompareConfig:
    candidate_id: str
    comparison_id: str
    baseline_labels_path: str | Path
    perturbation_labels_path: str | Path
    output_dir: str | Path
    otb_bin_dir: str | Path | None = None
    report_filename: str = "hoover_report.json"
    raw_output_filename: str = "hoover_raw.txt"
    ram_mb: int = 4096
    overwrite: bool = False
    dry_run: bool = False


def build_level1b_hoover_compare_layout(config: Level1BHooverCompareConfig) -> dict[str, Path]:
    compare_dir = Path(config.output_dir) / "level1b" / "hoover" / str(config.comparison_id).strip()
    return {
        "compare_dir": compare_dir,
        "report_path": compare_dir / config.report_filename,
        "raw_output_path": compare_dir / config.raw_output_filename,
    }


def discover_hoover_compare_app(otb_bin_dir=None) -> str | None:
    if otb_bin_dir is not None:
        app_path = Path(otb_bin_dir) / HOOVER_APP_NAME
        return str(app_path) if app_path.exists() else None
    return discover_otb_cli(HOOVER_APP_NAME)


def _expected_app_path(otb_bin_dir=None) -> str:
    if otb_bin_dir is not None:
        return str(Path(otb_bin_dir) / HOOVER_APP_NAME)
    return HOOVER_APP_NAME


def validate_hoover_compare_config(
    config: Level1BHooverCompareConfig, layout: dict[str, Path], app_path: str | None
) -> tuple[dict[str, bool], list[str]]:
    checks = {key: True for key in CHECK_KEYS}
    failure_reasons: list[str] = []
    baseline_path = Path(config.baseline_labels_path)
    perturbation_path = Path(config.perturbation_labels_path)

    if not str(config.comparison_id).strip():
        checks["comparison_id_non_empty"] = False
        failure_reasons.append("comparison_id is empty")
    if not str(config.output_dir).strip():
        checks["output_dir_present"] = False
        failure_reasons.append("output_dir is missing")
    if not baseline_path.exists():
        checks["baseline_labels_path_exists"] = False
        failure_reasons.append("baseline_labels_path does not exist")
    if not perturbation_path.exists():
        checks["perturbation_labels_path_exists"] = False
        failure_reasons.append("perturbation_labels_path does not exist")
    if baseline_path.suffix.lower() not in RASTER_SUFFIXES:
        checks["baseline_labels_suffix_raster_like"] = False
        failure_reasons.append("baseline_labels_path suffix must be one of .tif, .tiff")
    if perturbation_path.suffix.lower() not in RASTER_SUFFIXES:
        checks["perturbation_labels_suffix_raster_like"] = False
        failure_reasons.append("perturbation_labels_path suffix must be one of .tif, .tiff")
    if not config.overwrite:
        blocked_outputs = [path.name for path in (layout["report_path"], layout["raw_output_path"]) if path.exists()]
        if blocked_outputs:
            checks["output_artifacts_available"] = False
            failure_reasons.append("output artifacts already exist and overwrite is false")
    if not app_path and not config.dry_run:
        checks["hoover_compare_app_discoverable"] = False
        failure_reasons.append("no OTB HooverCompareSegmentation app discoverable")

    return checks, failure_reasons


def build_hoover_compare_command(
    config: Level1BHooverCompareConfig, app_path: str, layout: dict[str, Path]
) -> list[str]:
    return [
        str(app_path),
        "-ingt",
        str(Path(config.baseline_labels_path)),
        "-inms",
        str(Path(config.perturbation_labels_path)),
    ]


def parse_hoover_numeric_metrics(output_text: str) -> tuple[dict[str, float], str]:
    parsed_metrics: dict[str, float] = {}
    pattern = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 _/().-]*?)\s*(?::|=)\s*(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*$")

    for line in output_text.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        key = re.sub(r"[^A-Za-z0-9]+", "_", match.group(1).strip().lower()).strip("_")
        if key:
            parsed_metrics[key] = float(match.group(2))

    if not parsed_metrics:
        return {}, "raw_only_no_safe_numeric_schema"
    return parsed_metrics, "parsed_numeric_key_values"


def _base_report(
    config: Level1BHooverCompareConfig,
    layout: dict[str, Path],
    app_path: str,
    command: list[str],
    checks: dict[str, bool],
    failure_reasons: list[str],
) -> dict[str, object]:
    return {
        "candidate_id": str(config.candidate_id),
        "comparison_id": str(config.comparison_id).strip(),
        "baseline_labels_path": str(Path(config.baseline_labels_path)),
        "perturbation_labels_path": str(Path(config.perturbation_labels_path)),
        "command": command,
        "returncode": None,
        "stdout_path": str(layout["raw_output_path"]),
        "stderr_text": "",
        "raw_output_path": str(layout["raw_output_path"]),
        "hoover_app_path": app_path,
        "parsed_metrics": {},
        "parser_status": "not_run",
        "raster_only": True,
        "no_vector_output": True,
        "no_lsms_vectorization": True,
        "no_final_output": True,
        "no_scale_selection": True,
        "no_cli_integration": True,
        "checks": checks,
        "failure_reasons": failure_reasons,
        "status": "failed" if failure_reasons else "pending",
        "self_comparison": Path(config.baseline_labels_path) == Path(config.perturbation_labels_path),
    }


def _write_report(report: dict[str, object], report_path: Path) -> dict[str, object]:
    with report_path.open("w", encoding="utf-8") as file_obj:
        json.dump({key: report[key] for key in REPORT_KEYS}, file_obj, indent=2)
    return json.loads(report_path.read_text(encoding="utf-8"))


def run_hoover_compare(config: Level1BHooverCompareConfig) -> dict[str, object]:
    layout = build_level1b_hoover_compare_layout(config)
    discovered_app_path = discover_hoover_compare_app(config.otb_bin_dir)
    command_app_path = discovered_app_path or _expected_app_path(config.otb_bin_dir)
    checks, failure_reasons = validate_hoover_compare_config(config, layout, discovered_app_path)
    command = build_hoover_compare_command(config, command_app_path, layout)
    report = _base_report(config, layout, command_app_path, command, checks, failure_reasons)

    if failure_reasons:
        return report
    if config.dry_run:
        report["status"] = "dry_run"
        return report

    layout["compare_dir"].mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        otb_subprocess_command(command),
        capture_output=True,
        text=True,
        **otb_subprocess_kwargs(command),
    )
    raw_text = result.stdout
    if result.stderr:
        raw_text = f"{raw_text}\n[stderr]\n{result.stderr}" if raw_text else f"[stderr]\n{result.stderr}"
    layout["raw_output_path"].write_text(raw_text, encoding="utf-8")

    parsed_metrics, parser_status = parse_hoover_numeric_metrics(result.stdout)
    report["returncode"] = result.returncode
    report["stderr_text"] = result.stderr
    report["parsed_metrics"] = parsed_metrics
    report["parser_status"] = parser_status
    report["status"] = "ok" if result.returncode == 0 else "failed"
    if result.returncode != 0:
        report["failure_reasons"].append(f"command failed with returncode {result.returncode}")
        _write_report(report, layout["report_path"])
        raise RuntimeError(f"HooverCompareSegmentation failed with returncode {result.returncode}")

    return _write_report(report, layout["report_path"])
