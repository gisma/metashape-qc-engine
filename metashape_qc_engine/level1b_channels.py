from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess


RASTER_SUFFIXES = {".tif", ".tiff", ".vrt", ".img", ".jp2"}
RGB_CHANNEL_NAMES = ["VIG", "DRY", "BRI", "TEX_100M", "TEX_200M"]
REPORT_KEYS = (
    "candidate_id",
    "input_path",
    "input_type",
    "output_dir",
    "default_tmp_dir",
    "runtime_tmp_dir",
    "channels_dir",
    "output_path",
    "output_filename",
    "report_path",
    "valid_mask_path",
    "channel_mode",
    "channel_names",
    "rgb_band_indices",
    "declared_channels",
    "declared_band_indices",
    "pixel_size_m",
    "tex_100m_radius_m",
    "tex_200m_radius_m",
    "derived_radius_px",
    "intermediate_paths",
    "mask_application",
    "otb_apps",
    "otb_commands",
    "dry_run",
    "overwrite",
    "checks",
    "status",
    "failure_reasons",
    "command_results",
    "output_created",
    "timestamp",
)
CHECK_KEYS = (
    "candidate_id_non_empty",
    "input_path_exists",
    "input_suffix_raster_like",
    "valid_mask_path_exists",
    "input_type_valid",
    "pixel_size_m_valid",
    "output_path_available",
    "rgb_band_indices_valid",
    "rgb_declared_channels_absent",
    "rgb_declared_band_indices_absent",
    "multichannel_declared_channels_present",
    "multichannel_declared_channels_non_empty",
    "multichannel_declared_channels_unique",
    "multichannel_declared_band_indices_present",
    "multichannel_declared_band_indices_length",
    "multichannel_declared_band_indices_valid",
    "texture_radii_valid",
    "texture_radius_order_valid",
    "derived_radius_px_valid",
    "otb_bandmathx_discoverable",
    "otb_local_statistic_extraction_discoverable",
)


@dataclass
class Level1BChannelConfig:
    candidate_id: str
    input_path: str | Path
    output_dir: str | Path
    input_type: str
    valid_mask_path: str | Path
    pixel_size_m: float
    tmp_dir: str | Path | None = None
    rgb_band_indices: tuple[int, int, int] = (1, 2, 3)
    declared_channels: tuple[str, ...] | None = None
    declared_band_indices: tuple[int, ...] | None = None
    tex_100m_radius_m: float = 1.0
    tex_200m_radius_m: float = 2.0
    output_filename: str | None = None
    report_filename: str = "channel_report.json"
    overwrite: bool = False
    dry_run: bool = False


def build_level1b_channel_layout(output_dir, tmp_dir=None) -> dict[str, Path]:
    level1b_dir = Path(output_dir) / "level1b"
    default_tmp_dir = level1b_dir / "tmp"
    runtime_tmp_dir = Path(tmp_dir) if tmp_dir is not None else default_tmp_dir
    layout = {
        "default_tmp_dir": default_tmp_dir,
        "runtime_tmp_dir": runtime_tmp_dir,
        "logs_dir": level1b_dir / "logs",
        "reports_dir": level1b_dir / "reports",
        "channels_dir": level1b_dir / "channels",
    }
    for directory in layout.values():
        directory.mkdir(parents=True, exist_ok=True)
    return layout


def discover_channel_otb_apps(input_type) -> dict[str, str | None]:
    apps = {"BandMathX": shutil.which("otbcli_BandMathX")}
    if input_type == "rgb":
        apps["LocalStatisticExtraction"] = shutil.which("otbcli_LocalStatisticExtraction")
    return apps


def validate_channel_config(config, layout) -> tuple[dict[str, bool], list[str], dict[str, object]]:
    def is_positive_number(value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0

    output_filename = config.output_filename
    if output_filename is None:
        output_filename = "channel_stack.tif" if config.input_type == "multichannel" else "proxy_stack.tif"

    normalized_channels = None
    if config.declared_channels is not None:
        normalized_channels = [str(value).strip() for value in config.declared_channels]

    checks = {key: True for key in CHECK_KEYS}
    failure_reasons: list[str] = []
    derived: dict[str, object] = {
        "candidate_id": str(config.candidate_id).strip(),
        "output_filename": output_filename,
        "output_path": layout["channels_dir"] / output_filename,
        "normalized_declared_channels": normalized_channels,
        "normalized_declared_band_indices": list(config.declared_band_indices)
        if config.declared_band_indices is not None
        else None,
        "derived_radius_px": {},
    }

    input_path = Path(config.input_path)
    valid_mask_path = Path(config.valid_mask_path)
    output_path = derived["output_path"]

    if not derived["candidate_id"]:
        checks["candidate_id_non_empty"] = False
        failure_reasons.append("candidate_id is empty")
    if not input_path.exists():
        checks["input_path_exists"] = False
        failure_reasons.append("input_path does not exist")
    if input_path.suffix.lower() not in RASTER_SUFFIXES:
        checks["input_suffix_raster_like"] = False
        failure_reasons.append("input_path suffix must be one of .tif, .tiff, .vrt, .img, .jp2")
    if not valid_mask_path.exists():
        checks["valid_mask_path_exists"] = False
        failure_reasons.append("valid_mask_path does not exist")
    if config.input_type not in {"rgb", "multichannel"}:
        checks["input_type_valid"] = False
        failure_reasons.append("input_type must be exactly 'rgb' or 'multichannel'")
    if not is_positive_number(config.pixel_size_m):
        checks["pixel_size_m_valid"] = False
        failure_reasons.append("pixel_size_m must be numeric and > 0")
    if Path(output_path).exists() and not config.overwrite and not config.dry_run:
        checks["output_path_available"] = False
        failure_reasons.append("output_path already exists and overwrite is false")

    if config.input_type == "rgb":
        if (
            not isinstance(config.rgb_band_indices, tuple)
            or len(config.rgb_band_indices) != 3
            or any(not isinstance(index, int) or index <= 0 for index in config.rgb_band_indices)
        ):
            checks["rgb_band_indices_valid"] = False
            failure_reasons.append("rgb_band_indices must contain exactly three positive integers")
        if config.declared_channels is not None:
            checks["rgb_declared_channels_absent"] = False
            failure_reasons.append("rgb input must not receive declared_channels")
        if config.declared_band_indices is not None:
            checks["rgb_declared_band_indices_absent"] = False
            failure_reasons.append("rgb input must not receive declared_band_indices")

    if config.input_type == "multichannel":
        normalized_channels = derived["normalized_declared_channels"]
        normalized_indices = derived["normalized_declared_band_indices"]
        if normalized_channels is None:
            checks["multichannel_declared_channels_present"] = False
            failure_reasons.append("multichannel input requires declared_channels")
        elif not normalized_channels or any(channel == "" for channel in normalized_channels):
            checks["multichannel_declared_channels_non_empty"] = False
            failure_reasons.append("declared_channels must be non-empty after stripping")
        elif len(set(normalized_channels)) != len(normalized_channels):
            checks["multichannel_declared_channels_unique"] = False
            failure_reasons.append("declared_channels must be unique after stripping")

        if normalized_indices is None:
            checks["multichannel_declared_band_indices_present"] = False
            failure_reasons.append("multichannel input requires declared_band_indices")
        elif normalized_channels is not None and len(normalized_indices) != len(normalized_channels):
            checks["multichannel_declared_band_indices_length"] = False
            failure_reasons.append("declared_band_indices length must equal declared_channels length")
        if normalized_indices is not None and any(not isinstance(index, int) or index <= 0 for index in normalized_indices):
            checks["multichannel_declared_band_indices_valid"] = False
            failure_reasons.append("declared_band_indices must be positive integers")

    if not is_positive_number(config.tex_100m_radius_m) or not is_positive_number(config.tex_200m_radius_m):
        checks["texture_radii_valid"] = False
        failure_reasons.append("tex_100m_radius_m and tex_200m_radius_m must be positive numbers")
    elif config.tex_100m_radius_m >= config.tex_200m_radius_m:
        checks["texture_radius_order_valid"] = False
        failure_reasons.append("tex_100m_radius_m must be smaller than tex_200m_radius_m")

    if checks["pixel_size_m_valid"] and checks["texture_radii_valid"]:
        radius_100 = round(config.tex_100m_radius_m / config.pixel_size_m)
        radius_200 = round(config.tex_200m_radius_m / config.pixel_size_m)
        derived["derived_radius_px"] = {"TEX_100M": radius_100, "TEX_200M": radius_200}
        if radius_100 < 1 or radius_200 < 1:
            checks["derived_radius_px_valid"] = False
            failure_reasons.append("derived texture radii must be >= 1 px")

    return checks, failure_reasons, derived


def build_rgb_proxy_commands(config, apps, layout, output_path) -> tuple[list[list[str]], dict[str, object]]:
    runtime_channel_tmp = layout["runtime_tmp_dir"] / "channels"
    runtime_channel_tmp.mkdir(parents=True, exist_ok=True)
    exgr_tmp = runtime_channel_tmp / "exgr_tmp.tif"
    tex_100m_stats_tmp = runtime_channel_tmp / "tex_100m_stats_tmp.tif"
    tex_200m_stats_tmp = runtime_channel_tmp / "tex_200m_stats_tmp.tif"
    radius_100 = round(config.tex_100m_radius_m / config.pixel_size_m)
    radius_200 = round(config.tex_200m_radius_m / config.pixel_size_m)
    red_index, green_index, blue_index = config.rgb_band_indices
    red = f"im1b{red_index}"
    green = f"im1b{green_index}"
    blue = f"im1b{blue_index}"
    mask_from_second_input = "im2b1"
    mask_from_fourth_input = "im4b1"
    exg = f"(2*{green} - {red} - {blue})"
    exr = f"(1.4*{red} - {blue})"
    exgr = f"({exg} - {exr})"
    bri = f"(({red} + {green} + {blue}) / 3)"
    expressions = {"ExG": exg, "ExR": exr, "ExGR": exgr, "VIG": exgr, "DRY": exr, "BRI": bri}
    masked_exgr = f"({mask_from_second_input} > 0 ? {expressions['ExGR']} : 0)"
    final_expression = (
        "{"
        f"({mask_from_fourth_input} > 0 ? {expressions['VIG']} : 0);"
        f"({mask_from_fourth_input} > 0 ? {expressions['DRY']} : 0);"
        f"({mask_from_fourth_input} > 0 ? {expressions['BRI']} : 0);"
        f"({mask_from_fourth_input} > 0 ? im2b2 : 0);"
        f"({mask_from_fourth_input} > 0 ? im3b2 : 0)"
        "}"
    )
    commands = [
        [
            str(apps["BandMathX"]),
            "-il",
            str(config.input_path),
            str(config.valid_mask_path),
            "-out",
            str(exgr_tmp),
            "float",
            "-exp",
            masked_exgr,
        ],
        [
            str(apps["LocalStatisticExtraction"]),
            "-in",
            str(exgr_tmp),
            "-out",
            str(tex_100m_stats_tmp),
            "-radius",
            str(radius_100),
        ],
        [
            str(apps["LocalStatisticExtraction"]),
            "-in",
            str(exgr_tmp),
            "-out",
            str(tex_200m_stats_tmp),
            "-radius",
            str(radius_200),
        ],
        [
            str(apps["BandMathX"]),
            "-il",
            str(config.input_path),
            str(tex_100m_stats_tmp),
            str(tex_200m_stats_tmp),
            str(config.valid_mask_path),
            "-out",
            str(output_path),
            "float",
            "-exp",
            final_expression,
        ],
    ]
    metadata = {
        "channel_names": list(RGB_CHANNEL_NAMES),
        "derived_radius_px": {"TEX_100M": radius_100, "TEX_200M": radius_200},
        "intermediate_paths": {
            "exgr_tmp": str(exgr_tmp),
            "tex_100m_stats_tmp": str(tex_100m_stats_tmp),
            "tex_200m_stats_tmp": str(tex_200m_stats_tmp),
        },
        "expressions": expressions,
        "mask_application": {
            "valid_mask_applied_to_exgr_intermediate": True,
            "valid_mask_applied_to_final_stack": True,
            "texture_neighborhood_note": (
                "LocalStatisticExtraction runs on the masked ExGR intermediate; outside-support pixels are zeroed "
                "before texture computation and final texture bands are masked again."
            ),
        },
    }
    return commands, metadata


def build_multichannel_stack_command(
    config,
    apps,
    output_path,
    normalized_declared_channels,
    normalized_declared_band_indices,
) -> tuple[list[str], dict[str, object]]:
    expression = "{" + ";".join(f"(im2b1 > 0 ? im1b{index} : 0)" for index in normalized_declared_band_indices) + "}"
    command = [
        str(apps["BandMathX"]),
        "-il",
        str(config.input_path),
        str(config.valid_mask_path),
        "-out",
        str(output_path),
        "float",
        "-exp",
        expression,
    ]
    metadata = {
        "channel_names": list(normalized_declared_channels),
        "declared_band_indices": list(normalized_declared_band_indices),
        "expression": expression,
        "mask_application": {
            "valid_mask_applied_to_final_stack": True,
        },
    }
    return command, metadata


def run_channel_construction_step(config) -> dict[str, object]:
    layout = build_level1b_channel_layout(config.output_dir, config.tmp_dir)
    checks, failure_reasons, derived = validate_channel_config(config, layout)
    output_filename = str(derived["output_filename"])
    output_path = Path(derived["output_path"])
    report_path = layout["channels_dir"] / config.report_filename
    apps = discover_channel_otb_apps(config.input_type)
    command_results: list[dict[str, object]] = []
    commands: list[list[str]] = []
    channel_names: list[str] = []
    intermediate_paths: dict[str, str] = {}
    mask_application: dict[str, object] = {}
    output_created = False

    if apps.get("BandMathX") is None:
        checks["otb_bandmathx_discoverable"] = False
        failure_reasons.append("no OTB BandMathX app discoverable")
    if config.input_type == "rgb" and apps.get("LocalStatisticExtraction") is None:
        checks["otb_local_statistic_extraction_discoverable"] = False
        failure_reasons.append("no OTB LocalStatisticExtraction app discoverable")

    if not failure_reasons:
        if config.input_type == "rgb":
            commands, metadata = build_rgb_proxy_commands(config, apps, layout, output_path)
            channel_names = list(metadata["channel_names"])
            intermediate_paths = dict(metadata["intermediate_paths"])
            derived["derived_radius_px"] = metadata["derived_radius_px"]
            mask_application = dict(metadata["mask_application"])
        else:
            command, metadata = build_multichannel_stack_command(
                config,
                apps,
                output_path,
                derived["normalized_declared_channels"],
                derived["normalized_declared_band_indices"],
            )
            commands = [command]
            channel_names = list(metadata["channel_names"])
            mask_application = dict(metadata["mask_application"])

        if config.dry_run:
            status = "dry_run"
        else:
            status = "ok"
            for command in commands:
                result = subprocess.run(command, capture_output=True, text=True)
                command_results.append(
                    {
                        "command": command,
                        "returncode": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }
                )
                if result.returncode != 0:
                    status = "failed"
                    failure_reasons.append("OTB execution failed")
                    break
            output_created = status == "ok"
    else:
        status = "failed"
        if config.input_type == "rgb":
            channel_names = list(RGB_CHANNEL_NAMES)
        elif derived["normalized_declared_channels"] is not None:
            channel_names = list(derived["normalized_declared_channels"])

    report = {
        "candidate_id": str(config.candidate_id).strip(),
        "input_path": str(config.input_path),
        "input_type": config.input_type,
        "output_dir": str(config.output_dir),
        "default_tmp_dir": str(layout["default_tmp_dir"]),
        "runtime_tmp_dir": str(layout["runtime_tmp_dir"]),
        "channels_dir": str(layout["channels_dir"]),
        "output_path": str(output_path),
        "output_filename": output_filename,
        "report_path": str(report_path),
        "valid_mask_path": str(config.valid_mask_path),
        "channel_mode": config.input_type if config.input_type in {"rgb", "multichannel"} else "invalid",
        "channel_names": channel_names,
        "rgb_band_indices": list(config.rgb_band_indices),
        "declared_channels": derived["normalized_declared_channels"],
        "declared_band_indices": derived["normalized_declared_band_indices"],
        "pixel_size_m": config.pixel_size_m,
        "tex_100m_radius_m": config.tex_100m_radius_m,
        "tex_200m_radius_m": config.tex_200m_radius_m,
        "derived_radius_px": derived["derived_radius_px"],
        "intermediate_paths": intermediate_paths,
        "mask_application": mask_application,
        "otb_apps": apps,
        "otb_commands": commands,
        "dry_run": config.dry_run,
        "overwrite": config.overwrite,
        "checks": checks,
        "status": status,
        "failure_reasons": failure_reasons,
        "command_results": command_results,
        "output_created": output_created,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    report = {key: report[key] for key in REPORT_KEYS}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return report
