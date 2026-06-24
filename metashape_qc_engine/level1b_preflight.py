"""Level-1b Step 0 preflight/controller foundation only.

This module validates controller inputs, discovers required OTB CLI app paths,
creates the Level-1b artifact layout, and writes a preflight report. It does
not process rasters, does not run segmentation, and does not execute OTB during
preflight. Later Level-1b workflow steps are intentionally not implemented here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any, Iterable


DEFAULT_REQUIRED_OTB_APPS = (
    "BandMathX",
    "LocalStatisticExtraction",
    "ComputeImagesStatistics",
    "MeanShiftSmoothing",
    "LSMSSegmentation",
    "SmallRegionsMerging",
    "LSMSVectorization",
    "ZonalStatistics",
    "HooverCompareSegmentation",
)

VALID_INPUT_TYPES = {"rgb", "multichannel"}


@dataclass(frozen=True)
class Level1BPreflightConfig:
    """Configuration for Level-1b Step 0 preflight."""

    candidate_id: str
    input_path: str | Path
    output_dir: str | Path
    tmp_dir: str | Path | None = None
    input_type: str = "rgb"
    valid_mask_path: str | Path | None = None
    candidate_state: Any = None
    ram_mb: int = 4096
    required_otb_apps: Iterable[str] | None = None


def otb_executable_name(app_name: str) -> str:
    """Return the expected otbcli executable name for an OTB application."""

    return f"otbcli_{app_name}"


def discover_otb_app(app_name: str) -> str | None:
    """Discover an OTB CLI app by executable path without executing it."""

    return shutil.which(otb_executable_name(app_name))


def discover_required_otb_apps(
    required_apps: Iterable[str] | None = None,
) -> tuple[dict[str, dict[str, str | bool | None]], str | None]:
    """Discover required OTB CLI applications using path lookup only."""

    apps = tuple(required_apps or DEFAULT_REQUIRED_OTB_APPS)
    app_availability: dict[str, dict[str, str | bool | None]] = {}
    small_regions_merging_app: str | None = None

    for app_name in apps:
        if app_name == "SmallRegionsMerging":
            primary_path = discover_otb_app("SmallRegionsMerging")
            legacy_path = discover_otb_app("LSMSSmallRegionsMerging")
            if primary_path:
                small_regions_merging_app = "SmallRegionsMerging"
            elif legacy_path:
                small_regions_merging_app = "LSMSSmallRegionsMerging"

            app_availability["SmallRegionsMerging"] = {
                "available": bool(primary_path),
                "path": primary_path,
            }
            app_availability["LSMSSmallRegionsMerging"] = {
                "available": bool(legacy_path),
                "path": legacy_path,
            }
            continue

        app_path = discover_otb_app(app_name)
        app_availability[app_name] = {
            "available": bool(app_path),
            "path": app_path,
        }

    return app_availability, small_regions_merging_app


def build_level1b_layout(output_dir: str | Path, tmp_dir: str | Path | None = None) -> dict[str, Path]:
    """Create and return Level-1b output, tmp, log, and report directories."""

    level1b_dir = Path(output_dir) / "level1b"
    layout = {
        "level1b_dir": level1b_dir,
        "tmp_dir": Path(tmp_dir) if tmp_dir is not None else level1b_dir / "tmp",
        "logs_dir": level1b_dir / "logs",
        "reports_dir": level1b_dir / "reports",
    }

    for directory in layout.values():
        directory.mkdir(parents=True, exist_ok=True)

    return layout


def candidate_state_failed(candidate_state: Any) -> bool:
    """Return whether a provided candidate state represents failure."""

    if candidate_state is None:
        return False
    if isinstance(candidate_state, str):
        return candidate_state.strip().lower() == "failed"
    if isinstance(candidate_state, dict):
        state = candidate_state.get("status", candidate_state.get("state"))
        return isinstance(state, str) and state.strip().lower() == "failed"
    return bool(getattr(candidate_state, "failed", False))


def run_preflight(config: Level1BPreflightConfig) -> dict[str, Any]:
    """Run Level-1b Step 0 preflight and write the JSON report."""

    checks: dict[str, bool] = {}
    failure_reasons: list[str] = []

    candidate_id = config.candidate_id.strip()
    checks["candidate_id_non_empty"] = bool(candidate_id)
    if not checks["candidate_id_non_empty"]:
        failure_reasons.append("candidate_id is empty")

    input_path = Path(config.input_path)
    checks["input_path_exists"] = input_path.exists()
    if not checks["input_path_exists"]:
        failure_reasons.append(f"input_path does not exist: {input_path}")

    checks["input_type_valid"] = config.input_type in VALID_INPUT_TYPES
    if not checks["input_type_valid"]:
        failure_reasons.append("input_type must be exactly 'rgb' or 'multichannel'")

    valid_mask_path = Path(config.valid_mask_path) if config.valid_mask_path is not None else None
    checks["valid_mask_path_exists"] = valid_mask_path is None or valid_mask_path.exists()
    if not checks["valid_mask_path_exists"]:
        failure_reasons.append(f"valid_mask_path does not exist: {valid_mask_path}")

    checks["candidate_state_not_failed"] = not candidate_state_failed(config.candidate_state)
    if not checks["candidate_state_not_failed"]:
        failure_reasons.append("candidate_state is failed")

    layout: dict[str, Path] = {}
    try:
        layout = build_level1b_layout(config.output_dir, config.tmp_dir)
        checks["output_layout_created"] = True
    except OSError as exc:
        checks["output_layout_created"] = False
        failure_reasons.append(f"could not create output layout: {exc}")

    required_apps = tuple(config.required_otb_apps or DEFAULT_REQUIRED_OTB_APPS)
    app_availability, small_regions_merging_app = discover_required_otb_apps(required_apps)
    missing_apps = []
    for app_name in required_apps:
        if app_name == "SmallRegionsMerging":
            if small_regions_merging_app is None:
                missing_apps.append("SmallRegionsMerging or LSMSSmallRegionsMerging")
            continue
        if not app_availability.get(app_name, {}).get("available"):
            missing_apps.append(app_name)

    checks["required_otb_apps_discoverable"] = not missing_apps
    if missing_apps:
        failure_reasons.append("missing required OTB app(s): " + ", ".join(missing_apps))

    status = "failed" if failure_reasons else "ok"
    tmp_dir = layout.get("tmp_dir", Path(config.tmp_dir) if config.tmp_dir is not None else None)
    report = {
        "candidate_id": candidate_id,
        "input_path": str(input_path),
        "input_type": config.input_type,
        "output_dir": str(Path(config.output_dir)),
        "tmp_dir": str(tmp_dir) if tmp_dir is not None else None,
        "required_otb_apps": list(required_apps),
        "app_availability": app_availability,
        "small_regions_merging_app": small_regions_merging_app,
        "checks": checks,
        "status": status,
        "failure_reasons": failure_reasons,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "no_processing_performed": True,
    }

    reports_dir = layout.get("reports_dir")
    if reports_dir is not None:
        report_path = reports_dir / "preflight.json"
        with report_path.open("w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")

    return report
