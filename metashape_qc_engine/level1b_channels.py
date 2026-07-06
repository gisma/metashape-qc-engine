from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
from metashape_qc_engine.level1b_otb_env import (
    discover_otb_cli,
    otb_subprocess_command,
    otb_subprocess_kwargs,
)
from metashape_qc_engine.level1b_proxy_stack_rgb_dglcm import (
    DEFAULT_GLCM_DIRECTIONS,
    DEFAULT_PC1_CLIP_QUANTILES,
    DEFAULT_PC1_NBBIN,
    DEFAULT_PC1_OUTPUT_MAX,
    DEFAULT_PC1_OUTPUT_MIN,
    DEFAULT_RATIO_EPS,
    REQUIRED_OTB_APPS as RGB_REQUIRED_OTB_APPS,
    describe_rgb_dglcm_pc1_stack,
    rgb_dglcm_pc1_band_names,
    run_rgb_dglcm_pc1_proxy_stack,
)
from metashape_qc_engine.level1b_step_manifest import write_step_manifest


RASTER_SUFFIXES = {".tif", ".tiff", ".vrt", ".img", ".jp2"}
RGB_CHANNEL_NAMES = rgb_dglcm_pc1_band_names()
GLCM_DIRECTIONS = DEFAULT_GLCM_DIRECTIONS
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
    "normal_stack",
    "band_count",
    "band_names",
    "structure_operator",
    "structure_feature",
    "structure_feature_band",
    "structure_source",
    "direction_aggregation",
    "glcm_directions",
    "pc1_quantization",
    "dglcm_pc1_small_radius_m",
    "dglcm_pc1_large_radius_m",
    "small_radius_m",
    "large_radius_m",
    "small_radius_px",
    "large_radius_px",
    "ratio_formula",
    "ratio_eps",
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
    "pc1_clip_quantiles_valid",
    "pc1_output_range_valid",
    "glcm_nbbin_valid",
    "glcm_directions_valid",
    "ratio_eps_valid",
    "otb_bandmathx_discoverable",
    "otb_dimensionality_reduction_discoverable",
    "otb_haralick_texture_extraction_discoverable",
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
    dglcm_pc1_small_radius_m: float = 0.25
    dglcm_pc1_large_radius_m: float = 0.5
    pc1_clip_quantiles: tuple[float, float] = DEFAULT_PC1_CLIP_QUANTILES
    pc1_output_min: float = DEFAULT_PC1_OUTPUT_MIN
    pc1_output_max: float = DEFAULT_PC1_OUTPUT_MAX
    glcm_nbbin: int = DEFAULT_PC1_NBBIN
    glcm_directions: tuple[tuple[int, int], ...] = DEFAULT_GLCM_DIRECTIONS
    ratio_eps: float = DEFAULT_RATIO_EPS
    background_value: float = -999999.0
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
    required_apps = RGB_REQUIRED_OTB_APPS if input_type == "rgb" else ("BandMathX",)
    return {
        name: discover_otb_cli(f"otbcli_{name}")
        for name in required_apps
    }


def validate_channel_config(config, layout) -> tuple[dict[str, bool], list[str], dict[str, object]]:
    def is_positive_number(value: object) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value > 0
        )

    output_filename = config.output_filename
    if output_filename is None:
        output_filename = (
            "channel_stack.tif"
            if config.input_type == "multichannel"
            else "proxy_stack.tif"
        )

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
        failure_reasons.append(
            "input_path suffix must be one of .tif, .tiff, .vrt, .img, .jp2"
        )
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
            or any(
                not isinstance(index, int) or index <= 0
                for index in config.rgb_band_indices
            )
        ):
            checks["rgb_band_indices_valid"] = False
            failure_reasons.append(
                "rgb_band_indices must contain exactly three positive integers"
            )
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
        elif not normalized_channels or any(
            channel == "" for channel in normalized_channels
        ):
            checks["multichannel_declared_channels_non_empty"] = False
            failure_reasons.append(
                "declared_channels must be non-empty after stripping"
            )
        elif len(set(normalized_channels)) != len(normalized_channels):
            checks["multichannel_declared_channels_unique"] = False
            failure_reasons.append("declared_channels must be unique after stripping")

        if normalized_indices is None:
            checks["multichannel_declared_band_indices_present"] = False
            failure_reasons.append("multichannel input requires declared_band_indices")
        elif normalized_channels is not None and len(normalized_indices) != len(
            normalized_channels
        ):
            checks["multichannel_declared_band_indices_length"] = False
            failure_reasons.append(
                "declared_band_indices length must equal declared_channels length"
            )
        if normalized_indices is not None and any(
            not isinstance(index, int) or index <= 0
            for index in normalized_indices
        ):
            checks["multichannel_declared_band_indices_valid"] = False
            failure_reasons.append(
                "declared_band_indices must be positive integers"
            )

    if not is_positive_number(
        config.dglcm_pc1_small_radius_m
    ) or not is_positive_number(config.dglcm_pc1_large_radius_m):
        checks["texture_radii_valid"] = False
        failure_reasons.append(
            "dglcm_pc1_small_radius_m and dglcm_pc1_large_radius_m must be positive numbers"
        )
    elif config.dglcm_pc1_small_radius_m >= config.dglcm_pc1_large_radius_m:
        checks["texture_radius_order_valid"] = False
        failure_reasons.append(
            "dglcm_pc1_small_radius_m must be smaller than dglcm_pc1_large_radius_m"
        )

    quantiles = config.pc1_clip_quantiles
    if (
        not isinstance(quantiles, tuple)
        or len(quantiles) != 2
        or any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in quantiles)
        or not 0 <= quantiles[0] < quantiles[1] <= 1
    ):
        checks["pc1_clip_quantiles_valid"] = False
        failure_reasons.append(
            "pc1_clip_quantiles must contain two numeric values with 0 <= lower < upper <= 1"
        )
    if (
        not isinstance(config.pc1_output_min, (int, float))
        or isinstance(config.pc1_output_min, bool)
        or not isinstance(config.pc1_output_max, (int, float))
        or isinstance(config.pc1_output_max, bool)
        or config.pc1_output_min >= config.pc1_output_max
    ):
        checks["pc1_output_range_valid"] = False
        failure_reasons.append("pc1_output_min must be smaller than pc1_output_max")
    if (
        not isinstance(config.glcm_nbbin, int)
        or isinstance(config.glcm_nbbin, bool)
        or config.glcm_nbbin <= 1
    ):
        checks["glcm_nbbin_valid"] = False
        failure_reasons.append("glcm_nbbin must be an integer > 1")
    if (
        not isinstance(config.glcm_directions, tuple)
        or not config.glcm_directions
        or any(
            not isinstance(direction, tuple)
            or len(direction) != 2
            or any(not isinstance(value, int) or isinstance(value, bool) for value in direction)
            for direction in config.glcm_directions
        )
    ):
        checks["glcm_directions_valid"] = False
        failure_reasons.append(
            "glcm_directions must be a non-empty tuple of integer (xoff, yoff) pairs"
        )
    if (
        not isinstance(config.ratio_eps, (int, float))
        or isinstance(config.ratio_eps, bool)
        or config.ratio_eps <= 0
    ):
        checks["ratio_eps_valid"] = False
        failure_reasons.append("ratio_eps must be numeric and > 0")

    if checks["pixel_size_m_valid"] and checks["texture_radii_valid"]:
        radius_small = max(
            1, round(config.dglcm_pc1_small_radius_m / config.pixel_size_m)
        )
        radius_large = max(
            1, round(config.dglcm_pc1_large_radius_m / config.pixel_size_m)
        )
        derived["derived_radius_px"] = {
            "DGLCM_PC1_SMALL": radius_small,
            "DGLCM_PC1_LARGE": radius_large,
        }

    return checks, failure_reasons, derived


def build_multichannel_stack_command(
    config,
    apps,
    output_path,
    normalized_declared_channels,
    normalized_declared_band_indices,
) -> tuple[list[str], dict[str, object]]:
    expression = "{" + ";".join(
        f"(im2b1 > 0 ? im1b{index} : 0)"
        for index in normalized_declared_band_indices
    ) + "}"
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
        "mask_application": {"valid_mask_applied_to_final_stack": True},
    }
    return command, metadata


def _run_command(command) -> tuple[dict[str, object], bool]:
    result = subprocess.run(
        otb_subprocess_command(command),
        capture_output=True,
        text=True,
        **otb_subprocess_kwargs(command),
    )
    return (
        {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        },
        result.returncode == 0,
    )


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
    intermediate_paths: dict[str, object] = {}
    mask_application: dict[str, object] = {}
    pc1_clip_values = {"lower": None, "upper": None}
    output_created = False
    recipe_result: dict[str, object] | None = None

    if apps.get("BandMathX") is None:
        checks["otb_bandmathx_discoverable"] = False
        failure_reasons.append("no OTB BandMathX app discoverable")
    if config.input_type == "rgb" and apps.get("DimensionalityReduction") is None:
        checks["otb_dimensionality_reduction_discoverable"] = False
        failure_reasons.append("no OTB DimensionalityReduction app discoverable")
    if config.input_type == "rgb" and apps.get("HaralickTextureExtraction") is None:
        checks["otb_haralick_texture_extraction_discoverable"] = False
        failure_reasons.append("no OTB HaralickTextureExtraction app discoverable")

    if not failure_reasons:
        if config.input_type == "rgb":
            recipe_result = run_rgb_dglcm_pc1_proxy_stack(
                candidate_id=str(config.candidate_id),
                input_path=config.input_path,
                valid_mask_path=config.valid_mask_path,
                output_path=output_path,
                runtime_tmp_dir=layout["runtime_tmp_dir"],
                pixel_size_m=float(config.pixel_size_m),
                rgb_band_indices=config.rgb_band_indices,
                small_radius_m=float(config.dglcm_pc1_small_radius_m),
                large_radius_m=float(config.dglcm_pc1_large_radius_m),
                background_value=float(config.background_value),
                pc1_clip_quantiles=config.pc1_clip_quantiles,
                pc1_output_min=config.pc1_output_min,
                pc1_output_max=config.pc1_output_max,
                glcm_nbbin=config.glcm_nbbin,
                glcm_directions=config.glcm_directions,
                ratio_eps=float(config.ratio_eps),
                overwrite=config.overwrite,
                dry_run=config.dry_run,
                apps=apps,
            )
            status = str(recipe_result["status"])
            failure_reasons.extend(recipe_result["failure_reasons"])
            command_results = list(recipe_result["command_results"])
            commands = list(recipe_result["commands"])
            channel_names = list(recipe_result["channel_names"])
            intermediate_paths = dict(recipe_result["intermediate_paths"])
            mask_application = dict(recipe_result["mask_application"])
            pc1_clip_values = dict(
                recipe_result["pc1_quantization"]["valid_pixel_clip_values"]
            )
            derived["derived_radius_px"] = dict(
                recipe_result["derived_radius_px"]
            )
            output_created = bool(recipe_result["output_created"])
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
                result_record, succeeded = _run_command(command)
                command_results.append(result_record)
                status = "ok" if succeeded else "failed"
                if not succeeded:
                    failure_reasons.append("OTB execution failed")
                output_created = succeeded
    else:
        status = "failed"
        if config.input_type == "rgb":
            channel_names = list(RGB_CHANNEL_NAMES)
        elif derived["normalized_declared_channels"] is not None:
            channel_names = list(derived["normalized_declared_channels"])

    is_rgb = config.input_type == "rgb"
    description_rgb_indices = (
        config.rgb_band_indices
        if checks["rgb_band_indices_valid"]
        else (1, 2, 3)
    )
    description_quantiles = (
        config.pc1_clip_quantiles
        if checks["pc1_clip_quantiles_valid"]
        else DEFAULT_PC1_CLIP_QUANTILES
    )
    description_output_min = (
        config.pc1_output_min
        if checks["pc1_output_range_valid"]
        else DEFAULT_PC1_OUTPUT_MIN
    )
    description_output_max = (
        config.pc1_output_max
        if checks["pc1_output_range_valid"]
        else DEFAULT_PC1_OUTPUT_MAX
    )
    description_nbbin = (
        config.glcm_nbbin
        if checks["glcm_nbbin_valid"]
        else DEFAULT_PC1_NBBIN
    )
    description_directions = (
        config.glcm_directions
        if checks["glcm_directions_valid"]
        else DEFAULT_GLCM_DIRECTIONS
    )
    description_ratio_eps = (
        config.ratio_eps if checks["ratio_eps_valid"] else DEFAULT_RATIO_EPS
    )
    rgb_method = recipe_result or describe_rgb_dglcm_pc1_stack(
        rgb_band_indices=description_rgb_indices,
        pc1_clip_quantiles=description_quantiles,
        pc1_output_min=description_output_min,
        pc1_output_max=description_output_max,
        glcm_nbbin=description_nbbin,
        glcm_directions=description_directions,
        ratio_eps=description_ratio_eps,
        small_radius_m=config.dglcm_pc1_small_radius_m,
        large_radius_m=config.dglcm_pc1_large_radius_m,
        pc1_clip_values=pc1_clip_values,
    )
    radius_px = derived["derived_radius_px"]
    small_radius_px = radius_px.get("DGLCM_PC1_SMALL")
    large_radius_px = radius_px.get("DGLCM_PC1_LARGE")
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
        "channel_mode": config.input_type
        if config.input_type in {"rgb", "multichannel"}
        else "invalid",
        "channel_names": channel_names,
        "rgb_band_indices": list(config.rgb_band_indices),
        "declared_channels": derived["normalized_declared_channels"],
        "declared_band_indices": derived["normalized_declared_band_indices"],
        "pixel_size_m": config.pixel_size_m,
        "normal_stack": rgb_method["normal_stack"] if is_rgb else None,
        "band_count": int(rgb_method["band_count"]) if is_rgb else len(channel_names),
        "band_names": list(rgb_method["band_names"]) if is_rgb else channel_names,
        "structure_operator": rgb_method["structure_operator"] if is_rgb else None,
        "structure_feature": rgb_method["structure_feature"] if is_rgb else None,
        "structure_feature_band": rgb_method["structure_feature_band"] if is_rgb else None,
        "structure_source": rgb_method["structure_source"] if is_rgb else None,
        "direction_aggregation": rgb_method["direction_aggregation"] if is_rgb else None,
        "glcm_directions": rgb_method["glcm_directions"] if is_rgb else None,
        "pc1_quantization": rgb_method["pc1_quantization"] if is_rgb else None,
        "dglcm_pc1_small_radius_m": config.dglcm_pc1_small_radius_m,
        "dglcm_pc1_large_radius_m": config.dglcm_pc1_large_radius_m,
        "small_radius_m": config.dglcm_pc1_small_radius_m,
        "large_radius_m": config.dglcm_pc1_large_radius_m,
        "small_radius_px": small_radius_px,
        "large_radius_px": large_radius_px,
        "ratio_formula": rgb_method["ratio_formula"] if is_rgb else None,
        "ratio_eps": rgb_method["ratio_eps"] if is_rgb else None,
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
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    write_step_manifest(
        config.output_dir,
        step="channels",
        status=status,
        inputs={
            "input_ortho": config.input_path,
            "valid_mask": config.valid_mask_path,
        },
        artifacts={"proxy_stack": output_path, "report": report_path},
        candidate_id=str(config.candidate_id).strip(),
    )
    return report
