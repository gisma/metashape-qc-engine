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

from metashape_qc_engine.level1b.otb_env import discover_otb_cli
from metashape_qc_engine.level1b.saga_segmentation import discover_saga_cmd
from metashape_qc_engine.level1b.step_manifest import write_step_manifest


DEFAULT_REQUIRED_OTB_APPS = (
    "BandMathX",
    "DimensionalityReduction",
    "HaralickTextureExtraction",
    "ComputeImagesStatistics",
)

VALID_INPUT_TYPES = {"rgb", "multichannel"}
VALID_RASTER_LIKE_SUFFIXES = {".tif", ".tiff", ".vrt", ".img", ".jp2"}
LEGACY_SMALL_REGIONS_MERGING_APP = "LSMSSmallRegionsMerging"


@dataclass(frozen=True)
class Level1BPreflightConfig:
    """Configuration for Level-1b Step 0 preflight."""

    candidate_id: str
    input_path: str | Path
    output_dir: str | Path
    tmp_dir: str | Path | None = None
    input_type: str = "rgb"
    valid_mask_path: str | Path | None = None
    band_roles: Iterable[str] | None = None
    declared_channels: Iterable[str] | None = None
    mask_contract: str = "optional"
    candidate_state: Any = None
    required_otb_apps: Iterable[str] | None = None


def otb_executable_name(app_name: str) -> str:
    """Return the expected otbcli executable name for an OTB application."""

    return f"otbcli_{app_name}"


def discover_otb_app(app_name: str) -> str | None:
    """Discover an OTB CLI app by executable path without executing it."""

    return discover_otb_cli(otb_executable_name(app_name))


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
            legacy_path = discover_otb_app(LEGACY_SMALL_REGIONS_MERGING_APP)
            if primary_path:
                small_regions_merging_app = "SmallRegionsMerging"
            elif legacy_path:
                small_regions_merging_app = LEGACY_SMALL_REGIONS_MERGING_APP

            app_availability["SmallRegionsMerging"] = {
                "available": bool(primary_path),
                "path": primary_path,
            }
            app_availability[LEGACY_SMALL_REGIONS_MERGING_APP] = {
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
    default_tmp_dir = level1b_dir / "tmp"
    runtime_tmp_dir = Path(tmp_dir) if tmp_dir is not None else default_tmp_dir
    layout = {
        "level1b_dir": level1b_dir,
        "default_tmp_dir": default_tmp_dir,
        "runtime_tmp_dir": runtime_tmp_dir,
        "tmp_dir": runtime_tmp_dir,
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


def input_suffix_raster_like(input_path: str | Path) -> bool:
    """Return whether the path suffix is accepted for Step 0 preflight."""

    return Path(input_path).suffix.lower() in VALID_RASTER_LIKE_SUFFIXES


CONTRACT_CHECK_KEYS = (
    "input_contract_valid",
    "rgb_band_roles_valid",
    "rgb_declared_channels_absent",
    "multichannel_declared_channels_present",
    "multichannel_declared_channels_non_empty",
    "multichannel_declared_channels_unique",
    "multichannel_band_roles_valid",
    "mask_contract_valid",
    "mask_path_requirement_valid",
)

VALID_MASK_CONTRACTS = {"required", "optional", "absent"}
RGB_BAND_ROLES = ["red", "green", "blue"]


def normalize_declaration(values: Iterable[str] | None) -> list[str] | None:
    """Normalize a declaration iterable without inferring values from data."""

    if values is None:
        return None
    return [str(value).strip() for value in values]


def validate_input_contract(
    input_type: str,
    band_roles: Iterable[str] | None,
    declared_channels: Iterable[str] | None,
) -> tuple[str, list[str] | None, list[str] | None, dict[str, bool], list[str]]:
    """Validate declaration-only input contracts."""

    normalized_band_roles = normalize_declaration(band_roles)
    normalized_declared_channels = normalize_declaration(declared_channels)
    contract_checks = {key: True for key in CONTRACT_CHECK_KEYS}
    failure_reasons: list[str] = []
    input_contract = "invalid"

    if input_type not in VALID_INPUT_TYPES:
        contract_checks["input_contract_valid"] = False
        return (
            input_contract,
            normalized_band_roles,
            normalized_declared_channels,
            contract_checks,
            failure_reasons,
        )

    if input_type == "rgb":
        if normalized_band_roles is None:
            normalized_band_roles = list(RGB_BAND_ROLES)
        if normalized_band_roles != RGB_BAND_ROLES:
            contract_checks["rgb_band_roles_valid"] = False
            failure_reasons.append("rgb band_roles must be exactly red, green, blue")
        if normalized_declared_channels is not None:
            contract_checks["rgb_declared_channels_absent"] = False
            failure_reasons.append("rgb input must not declare generic channels")
        if contract_checks["rgb_band_roles_valid"] and contract_checks["rgb_declared_channels_absent"]:
            input_contract = "rgb"
        else:
            contract_checks["input_contract_valid"] = False
        return (
            input_contract,
            normalized_band_roles,
            normalized_declared_channels,
            contract_checks,
            failure_reasons,
        )

    if normalized_declared_channels is None:
        contract_checks["multichannel_declared_channels_present"] = False
        failure_reasons.append("multichannel input requires declared_channels")
    elif not normalized_declared_channels:
        contract_checks["multichannel_declared_channels_non_empty"] = False
        failure_reasons.append("multichannel input requires declared_channels")
    elif any(channel == "" for channel in normalized_declared_channels):
        contract_checks["multichannel_declared_channels_non_empty"] = False
        failure_reasons.append("declared_channels must not contain empty values")

    if normalized_declared_channels is not None and len(set(normalized_declared_channels)) != len(
        normalized_declared_channels
    ):
        contract_checks["multichannel_declared_channels_unique"] = False
        failure_reasons.append("declared_channels must be unique")

    if normalized_band_roles is not None:
        if not normalized_band_roles:
            contract_checks["multichannel_band_roles_valid"] = False
            failure_reasons.append("multichannel band_roles must not contain empty values")
        elif any(role == "" for role in normalized_band_roles):
            contract_checks["multichannel_band_roles_valid"] = False
            failure_reasons.append("multichannel band_roles must not contain empty values")
        elif normalized_declared_channels is not None and len(normalized_band_roles) != len(
            normalized_declared_channels
        ):
            contract_checks["multichannel_band_roles_valid"] = False
            failure_reasons.append("multichannel band_roles length must match declared_channels")

    input_check_keys = (
        "multichannel_declared_channels_present",
        "multichannel_declared_channels_non_empty",
        "multichannel_declared_channels_unique",
        "multichannel_band_roles_valid",
    )
    if all(contract_checks[key] for key in input_check_keys):
        input_contract = "multichannel"
    else:
        contract_checks["input_contract_valid"] = False

    return (
        input_contract,
        normalized_band_roles,
        normalized_declared_channels,
        contract_checks,
        failure_reasons,
    )


def validate_mask_contract(
    mask_contract: str,
    valid_mask_path: Path | None,
) -> tuple[str, str, dict[str, bool], list[str]]:
    """Validate declaration-only mask contract requirements."""

    normalized_mask_contract = str(mask_contract).strip().lower()
    contract_checks = {key: True for key in CONTRACT_CHECK_KEYS}
    failure_reasons: list[str] = []

    if normalized_mask_contract not in VALID_MASK_CONTRACTS:
        contract_checks["mask_contract_valid"] = False
        failure_reasons.append("mask_contract must be one of required, optional, absent")
        return normalized_mask_contract, "invalid_contract", contract_checks, failure_reasons

    if normalized_mask_contract == "required":
        if valid_mask_path is None:
            contract_checks["mask_path_requirement_valid"] = False
            failure_reasons.append("valid_mask_path is required by mask_contract")
            return normalized_mask_contract, "missing_required", contract_checks, failure_reasons
        if not valid_mask_path.exists():
            contract_checks["mask_path_requirement_valid"] = False
            failure_reasons.append("valid_mask_path does not exist")
            return normalized_mask_contract, "missing_path", contract_checks, failure_reasons
        return normalized_mask_contract, "provided", contract_checks, failure_reasons

    if normalized_mask_contract == "optional":
        if valid_mask_path is None:
            return (
                normalized_mask_contract,
                "not_provided_optional",
                contract_checks,
                failure_reasons,
            )
        if not valid_mask_path.exists():
            contract_checks["mask_path_requirement_valid"] = False
            failure_reasons.append("valid_mask_path does not exist")
            return normalized_mask_contract, "missing_path", contract_checks, failure_reasons
        return normalized_mask_contract, "provided", contract_checks, failure_reasons

    if valid_mask_path is not None:
        contract_checks["mask_path_requirement_valid"] = False
        failure_reasons.append("valid_mask_path must be omitted when mask_contract is absent")
        return normalized_mask_contract, "forbidden_when_absent", contract_checks, failure_reasons
    return normalized_mask_contract, "declared_absent", contract_checks, failure_reasons


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

    checks["input_suffix_raster_like"] = input_suffix_raster_like(input_path)
    if not checks["input_suffix_raster_like"]:
        failure_reasons.append(
            "input_path suffix must be one of: "
            + ", ".join(sorted(VALID_RASTER_LIKE_SUFFIXES))
        )

    checks["input_type_valid"] = config.input_type in VALID_INPUT_TYPES
    if not checks["input_type_valid"]:
        failure_reasons.append("input_type must be exactly 'rgb' or 'multichannel'")

    valid_mask_path = Path(config.valid_mask_path) if config.valid_mask_path is not None else None
    checks["valid_mask_path_exists"] = valid_mask_path is None or valid_mask_path.exists()

    checks["candidate_state_not_failed"] = not candidate_state_failed(config.candidate_state)
    if not checks["candidate_state_not_failed"]:
        failure_reasons.append("candidate_state is failed")

    layout: dict[str, Path] = {}
    try:
        layout = build_level1b_layout(config.output_dir, config.tmp_dir)
        checks["output_layout_created"] = True
        checks["default_tmp_dir_created"] = layout["default_tmp_dir"].is_dir()
        checks["runtime_tmp_dir_created"] = layout["runtime_tmp_dir"].is_dir()
    except OSError as exc:
        checks["output_layout_created"] = False
        checks["default_tmp_dir_created"] = False
        checks["runtime_tmp_dir_created"] = False
        failure_reasons.append(f"could not create output layout: {exc}")

    required_apps = tuple(config.required_otb_apps or DEFAULT_REQUIRED_OTB_APPS)
    app_availability, small_regions_merging_app = discover_required_otb_apps(required_apps)
    missing_apps = []
    for app_name in required_apps:
        if app_name == "SmallRegionsMerging":
            if small_regions_merging_app is None:
                missing_apps.append(
                    "SmallRegionsMerging or " + LEGACY_SMALL_REGIONS_MERGING_APP
                )
            continue
        if not app_availability.get(app_name, {}).get("available"):
            missing_apps.append(app_name)

    checks["required_otb_apps_discoverable"] = not missing_apps
    if missing_apps:
        failure_reasons.append("missing required OTB app(s): " + ", ".join(missing_apps))

    saga_cmd_path = discover_saga_cmd()
    checks["saga_cmd_discoverable"] = saga_cmd_path is not None
    if saga_cmd_path is None:
        failure_reasons.append("missing required executable: saga_cmd")

    gdal_edit_path = shutil.which("gdal_edit.py")
    checks["gdal_edit_discoverable"] = gdal_edit_path is not None
    if gdal_edit_path is None:
        failure_reasons.append("missing required executable: gdal_edit.py")

    (
        input_contract,
        normalized_band_roles,
        normalized_declared_channels,
        input_contract_checks,
        input_contract_failures,
    ) = validate_input_contract(
        config.input_type,
        config.band_roles,
        config.declared_channels,
    )
    normalized_mask_contract, mask_status, mask_contract_checks, mask_contract_failures = (
        validate_mask_contract(config.mask_contract, valid_mask_path)
    )
    contract_checks = {key: True for key in CONTRACT_CHECK_KEYS}
    for key in CONTRACT_CHECK_KEYS:
        contract_checks[key] = input_contract_checks[key] and mask_contract_checks[key]
    failure_reasons.extend(input_contract_failures)
    failure_reasons.extend(mask_contract_failures)

    status = "failed" if failure_reasons else "ok"
    default_tmp_dir = layout.get("default_tmp_dir", Path(config.output_dir) / "level1b" / "tmp")
    runtime_tmp_dir = layout.get(
        "runtime_tmp_dir",
        Path(config.tmp_dir) if config.tmp_dir is not None else default_tmp_dir,
    )
    report = {
        "candidate_id": candidate_id,
        "input_path": str(input_path),
        "input_type": config.input_type,
        "output_dir": str(Path(config.output_dir)),
        "default_tmp_dir": str(default_tmp_dir),
        "runtime_tmp_dir": str(runtime_tmp_dir),
        "tmp_dir": str(runtime_tmp_dir),
        "required_otb_apps": list(required_apps),
        "app_availability": app_availability,
        "small_regions_merging_app": small_regions_merging_app,
        "gdal_edit_path": gdal_edit_path,
        "saga_cmd_path": saga_cmd_path,
        "checks": checks,
        "input_contract": input_contract,
        "mask_contract": normalized_mask_contract,
        "band_roles": normalized_band_roles,
        "declared_channels": normalized_declared_channels,
        "mask_status": mask_status,
        "contract_checks": contract_checks,
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

    write_step_manifest(
        config.output_dir,
        step="preflight",
        status=status,
        inputs={"input_ortho": input_path},
        artifacts={
            "preflight_report": Path(config.output_dir)
            / "level1b"
            / "reports"
            / "preflight.json"
        },
        candidate_id=candidate_id,
    )

    return report
