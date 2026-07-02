from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

from metashape_qc_engine.level1b_otb_env import otb_subprocess_kwargs

from metashape_qc_engine.level1b_pca import (
    Level1BPCAConfig,
    build_level1b_pca_layout,
    build_pca_command,
    build_pca_remask_command,
    run_pca_step,
)
from metashape_qc_engine.level1b_scaling import compute_quantile_scaling_parameters
from metashape_qc_engine.level1b_step_manifest import write_step_manifest


RASTER_SUFFIXES = {".tif", ".tiff", ".vrt", ".img", ".jp2"}
RGB_CHANNEL_NAMES = [
    "ExGR",
    "ExR",
    "BRI",
    "DGLCM_PC1_SMALL",
    "DGLCM_PC1_LARGE",
    "RATIO_DGLCM_PC1",
]
GLCM_DIRECTIONS = ((1, 0), (1, 1), (0, 1), (-1, 1))
PC1_CLIP_QUANTILES = (0.02, 0.98)
PC1_OUTPUT_MIN = 0.0
PC1_OUTPUT_MAX = 255.0
PC1_NBBIN = 32
RATIO_EPS = 1e-6
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
    apps = {"BandMathX": shutil.which("otbcli_BandMathX")}
    if input_type == "rgb":
        apps["DimensionalityReduction"] = shutil.which(
            "otbcli_DimensionalityReduction"
        )
        apps["HaralickTextureExtraction"] = shutil.which(
            "otbcli_HaralickTextureExtraction"
        )
    return apps


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


def _rgb_intermediate_paths(config, layout) -> dict[str, object]:
    runtime_channel_tmp = layout["runtime_tmp_dir"] / "channels"
    runtime_channel_tmp.mkdir(parents=True, exist_ok=True)
    pca_work_root = runtime_channel_tmp / "rgb_pc1_work"
    pca_config = Level1BPCAConfig(
        candidate_id=f"{str(config.candidate_id).strip()}__rgb_pc1",
        scaled_feature_stack_path=runtime_channel_tmp / "masked_rgb.tif",
        valid_mask_path=config.valid_mask_path,
        output_dir=pca_work_root,
        band_count=3,
        pca_components=1,
        background_value=config.background_value,
        output_filename="rgb_pc1.tif",
        report_filename="rgb_pc1_pca_report.json",
        overwrite=config.overwrite,
        dry_run=config.dry_run,
    )
    pca_layout = build_level1b_pca_layout(pca_work_root)
    direction_paths = {
        scale: [
            runtime_channel_tmp / f"dglcm_pc1_{scale}_direction_{index}.tif"
            for index in range(len(GLCM_DIRECTIONS))
        ]
        for scale in ("small", "large")
    }
    return {
        "masked_rgb": runtime_channel_tmp / "masked_rgb.tif",
        "pca_config": pca_config,
        "pca_layout": pca_layout,
        "pc1": pca_layout["pca_dir"] / pca_config.output_filename,
        "pc1_haralick_input": runtime_channel_tmp / "pc1_haralick_input.tif",
        "direction_paths": direction_paths,
        "small_max": runtime_channel_tmp / "dglcm_pc1_small_max.tif",
        "large_max": runtime_channel_tmp / "dglcm_pc1_large_max.tif",
    }


def _masked_rgb_command(config, apps, paths) -> list[str]:
    expression = "{" + ";".join(
        f"(im2b1 > 0 ? im1b{index} : {float(config.background_value)})"
        for index in config.rgb_band_indices
    ) + "}"
    return [
        str(apps["BandMathX"]),
        "-il",
        str(config.input_path),
        str(config.valid_mask_path),
        "-out",
        str(paths["masked_rgb"]),
        "float",
        "-exp",
        expression,
    ]


def _pc1_quantization_command(config, apps, paths, lower, upper) -> list[str]:
    clipped = (
        f"(im1b1 < {lower} ? {lower} : "
        f"(im1b1 > {upper} ? {upper} : im1b1))"
    )
    scaled = (
        f"(({clipped} - {lower}) * {PC1_OUTPUT_MAX} / ({upper} - {lower}))"
    )
    expression = f"(im2b1 > 0 ? {scaled} : {PC1_OUTPUT_MIN})"
    return [
        str(apps["BandMathX"]),
        "-il",
        str(paths["pc1"]),
        str(config.valid_mask_path),
        "-out",
        str(paths["pc1_haralick_input"]),
        "float",
        "-exp",
        expression,
    ]


def _haralick_commands(apps, paths, radius_small, radius_large) -> list[list[str]]:
    commands: list[list[str]] = []
    for scale, radius in (("small", radius_small), ("large", radius_large)):
        for output_path, (xoff, yoff) in zip(
            paths["direction_paths"][scale], GLCM_DIRECTIONS, strict=True
        ):
            commands.append(
                [
                    str(apps["HaralickTextureExtraction"]),
                    "-in",
                    str(paths["pc1_haralick_input"]),
                    "-channel",
                    "1",
                    "-step",
                    "1",
                    "-parameters.xrad",
                    str(radius),
                    "-parameters.yrad",
                    str(radius),
                    "-parameters.xoff",
                    str(xoff),
                    "-parameters.yoff",
                    str(yoff),
                    "-parameters.min",
                    str(int(PC1_OUTPUT_MIN)),
                    "-parameters.max",
                    str(int(PC1_OUTPUT_MAX)),
                    "-parameters.nbbin",
                    str(PC1_NBBIN),
                    "-texture",
                    "simple",
                    "-out",
                    str(output_path),
                    "float",
                ]
            )
    return commands


def _direction_max_command(apps, input_paths, output_path) -> list[str]:
    return [
        str(apps["BandMathX"]),
        "-il",
        *(str(path) for path in input_paths),
        "-out",
        str(output_path),
        "float",
        "-exp",
        "max(max(im1b5,im2b5),max(im3b5,im4b5))",
    ]


def _final_rgb_stack_command(config, apps, paths, output_path) -> tuple[list[str], dict[str, str]]:
    red_index, green_index, blue_index = config.rgb_band_indices
    red = f"im1b{red_index}"
    green = f"im1b{green_index}"
    blue = f"im1b{blue_index}"
    mask = "im4b1"
    exg = f"(2*{green} - {red} - {blue})"
    exr = f"(1.4*{red} - {blue})"
    exgr = f"({exg} - {exr})"
    bri = f"(({red} + {green} + {blue}) / 3)"
    expressions = {"ExG": exg, "ExR": exr, "ExGR": exgr, "BRI": bri}
    final_expression = (
        "{"
        f"({mask} > 0 ? {exgr} : 0);"
        f"({mask} > 0 ? {exr} : 0);"
        f"({mask} > 0 ? {bri} : 0);"
        f"({mask} > 0 ? im2b1 : 0);"
        f"({mask} > 0 ? im3b1 : 0);"
        f"({mask} > 0 ? (im2b1 / (im3b1 + {RATIO_EPS})) : 0)"
        "}"
    )
    command = [
        str(apps["BandMathX"]),
        "-il",
        str(config.input_path),
        str(paths["small_max"]),
        str(paths["large_max"]),
        str(config.valid_mask_path),
        "-out",
        str(output_path),
        "float",
        "-exp",
        final_expression,
    ]
    return command, expressions


def build_rgb_proxy_commands(
    config,
    apps,
    layout,
    output_path,
    pc1_lower="PC1_Q02",
    pc1_upper="PC1_Q98",
) -> tuple[list[list[str]], dict[str, object]]:
    paths = _rgb_intermediate_paths(config, layout)
    radius_small = max(
        1, round(config.dglcm_pc1_small_radius_m / config.pixel_size_m)
    )
    radius_large = max(
        1, round(config.dglcm_pc1_large_radius_m / config.pixel_size_m)
    )
    pca_apps = {
        "DimensionalityReduction": apps["DimensionalityReduction"],
        "BandMathX": apps["BandMathX"],
    }
    pca_commands = [
        build_pca_command(paths["pca_config"], pca_apps, paths["pca_layout"]),
        build_pca_remask_command(
            paths["pca_config"], pca_apps, paths["pca_layout"]
        ),
    ]
    commands = [
        _masked_rgb_command(config, apps, paths),
        *pca_commands,
        _pc1_quantization_command(
            config, apps, paths, pc1_lower, pc1_upper
        ),
        *_haralick_commands(apps, paths, radius_small, radius_large),
        _direction_max_command(
            apps, paths["direction_paths"]["small"], paths["small_max"]
        ),
        _direction_max_command(
            apps, paths["direction_paths"]["large"], paths["large_max"]
        ),
    ]
    final_command, expressions = _final_rgb_stack_command(
        config, apps, paths, output_path
    )
    commands.append(final_command)
    metadata = {
        "channel_names": list(RGB_CHANNEL_NAMES),
        "derived_radius_px": {
            "DGLCM_PC1_SMALL": radius_small,
            "DGLCM_PC1_LARGE": radius_large,
        },
        "intermediate_paths": {
            "masked_rgb": str(paths["masked_rgb"]),
            "rgb_pc1": str(paths["pc1"]),
            "pc1_haralick_input": str(paths["pc1_haralick_input"]),
            "dglcm_pc1_small_directions": [
                str(path) for path in paths["direction_paths"]["small"]
            ],
            "dglcm_pc1_large_directions": [
                str(path) for path in paths["direction_paths"]["large"]
            ],
            "dglcm_pc1_small_max": str(paths["small_max"]),
            "dglcm_pc1_large_max": str(paths["large_max"]),
            "rgb_pc1_pca_report": str(
                paths["pca_layout"]["pca_dir"]
                / paths["pca_config"].report_filename
            ),
        },
        "expressions": expressions,
        "pca_config": paths["pca_config"],
        "paths": paths,
        "mask_application": {
            "valid_mask_applied_to_rgb_before_pca": True,
            "invalid_rgb_value": float(config.background_value),
            "valid_mask_applied_to_pc1_after_pca": True,
            "valid_mask_applied_to_final_stack": True,
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
        command,
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
            commands, metadata = build_rgb_proxy_commands(
                config, apps, layout, output_path
            )
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
        elif config.input_type == "multichannel":
            result_record, succeeded = _run_command(commands[0])
            command_results.append(result_record)
            status = "ok" if succeeded else "failed"
            if not succeeded:
                failure_reasons.append("OTB execution failed")
            output_created = succeeded
        else:
            result_record, succeeded = _run_command(commands[0])
            command_results.append(result_record)
            if not succeeded:
                status = "failed"
                failure_reasons.append("OTB execution failed")
            else:
                pca_result = run_pca_step(metadata["pca_config"])
                command_results.extend(pca_result.get("command_results", []))
                if pca_result.get("status") != "ok":
                    status = "failed"
                    failure_reasons.append("RGB-PC1 construction failed")
                else:
                    stats_config = SimpleNamespace(
                        band_count=1,
                        background_value=float(config.background_value),
                    )
                    try:
                        stats = compute_quantile_scaling_parameters(
                            metadata["paths"]["pc1"], stats_config
                        )
                        lower = float(stats["lower_values"][0])
                        upper = float(stats["upper_values"][0])
                        pc1_clip_values = {"lower": lower, "upper": upper}
                        commands, metadata = build_rgb_proxy_commands(
                            config,
                            apps,
                            layout,
                            output_path,
                            pc1_lower=lower,
                            pc1_upper=upper,
                        )
                        intermediate_paths = dict(metadata["intermediate_paths"])
                        mask_application = dict(metadata["mask_application"])
                    except ValueError as exc:
                        status = "failed"
                        failure_reasons.append(str(exc))
                    else:
                        status = "ok"
                        for command in commands[3:]:
                            result_record, succeeded = _run_command(command)
                            command_results.append(result_record)
                            if not succeeded:
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

    radius_px = derived["derived_radius_px"]
    small_radius_px = radius_px.get("DGLCM_PC1_SMALL")
    large_radius_px = radius_px.get("DGLCM_PC1_LARGE")
    is_rgb = config.input_type == "rgb"
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
        "normal_stack": "exgr_exr_bri_directional_glcm_pc1" if is_rgb else None,
        "band_count": 6 if is_rgb else len(channel_names),
        "band_names": list(RGB_CHANNEL_NAMES) if is_rgb else channel_names,
        "structure_operator": "HaralickTextureExtraction" if is_rgb else None,
        "structure_feature": "simple.inertia" if is_rgb else None,
        "structure_feature_band": 5 if is_rgb else None,
        "structure_source": "RGB_PC1" if is_rgb else None,
        "direction_aggregation": "max_over_0_45_90_135" if is_rgb else None,
        "glcm_directions": [list(value) for value in GLCM_DIRECTIONS]
        if is_rgb
        else None,
        "pc1_quantization": {
            "clip_quantiles": list(PC1_CLIP_QUANTILES),
            "output_min": int(PC1_OUTPUT_MIN),
            "output_max": int(PC1_OUTPUT_MAX),
            "nbbin": PC1_NBBIN,
            "valid_pixel_clip_values": pc1_clip_values,
        }
        if is_rgb
        else None,
        "dglcm_pc1_small_radius_m": config.dglcm_pc1_small_radius_m,
        "dglcm_pc1_large_radius_m": config.dglcm_pc1_large_radius_m,
        "small_radius_m": config.dglcm_pc1_small_radius_m,
        "large_radius_m": config.dglcm_pc1_large_radius_m,
        "small_radius_px": small_radius_px,
        "large_radius_px": large_radius_px,
        "ratio_formula": "DGLCM_PC1_SMALL / (DGLCM_PC1_LARGE + eps)"
        if is_rgb
        else None,
        "ratio_eps": RATIO_EPS if is_rgb else None,
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
