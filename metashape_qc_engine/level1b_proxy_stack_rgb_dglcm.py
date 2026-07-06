"""Scientific recipe for the normal Level-1B RGB proxy stack.

This module owns the channel formulas and the deterministic raster operations
that create the stack.  Workflow validation, artifact layout, and reporting
remain in :mod:`level1b_channels`.

To extend the stack, add the channel expression in
``rgb_dglcm_pc1_band_definitions``.  The band names and band count returned to
the downstream workflow are derived from that list.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace

from metashape_qc_engine.level1b_otb_env import (
    discover_otb_cli,
    otb_subprocess_command,
    otb_subprocess_kwargs,
)
from metashape_qc_engine.level1b_pca import (
    Level1BPCAConfig,
    build_level1b_pca_layout,
    build_pca_command,
    build_pca_remask_command,
    run_pca_step,
)
from metashape_qc_engine.level1b_scaling import compute_quantile_scaling_parameters


NORMAL_STACK_NAME = "exgr_exr_bri_directional_glcm_pc1"
DEFAULT_GLCM_DIRECTIONS = ((1, 0), (1, 1), (0, 1), (-1, 1))
DEFAULT_PC1_CLIP_QUANTILES = (0.02, 0.98)
DEFAULT_PC1_OUTPUT_MIN = 0.0
DEFAULT_PC1_OUTPUT_MAX = 255.0
DEFAULT_PC1_NBBIN = 32
DEFAULT_RATIO_EPS = 1e-6
STRUCTURE_FEATURE_BAND = 5
REQUIRED_OTB_APPS = (
    "BandMathX",
    "DimensionalityReduction",
    "HaralickTextureExtraction",
)


def rgb_dglcm_pc1_band_definitions(
    rgb_band_indices: tuple[int, int, int],
    ratio_eps: float,
) -> tuple[list[tuple[str, str]], dict[str, str]]:
    """Return the ordered scientific band definitions for the normal stack."""

    red_index, green_index, blue_index = rgb_band_indices
    red = f"im1b{red_index}"
    green = f"im1b{green_index}"
    blue = f"im1b{blue_index}"
    exg = f"(2*{green} - {red} - {blue})"
    exr = f"(1.4*{red} - {blue})"
    exgr = f"({exg} - {exr})"
    bri = f"(({red} + {green} + {blue}) / 3)"

    bands = [
        ("ExGR", exgr),
        ("ExR", exr),
        ("BRI", bri),
        ("DGLCM_PC1_SMALL", "im2b1"),
        ("DGLCM_PC1_LARGE", "im3b1"),
        (
            "RATIO_DGLCM_PC1",
            f"(im2b1 / (im3b1 + {float(ratio_eps)}))",
        ),
    ]
    return bands, {"ExG": exg, "ExR": exr, "ExGR": exgr, "BRI": bri}


def rgb_dglcm_pc1_band_names(
    rgb_band_indices: tuple[int, int, int] = (1, 2, 3),
    ratio_eps: float = DEFAULT_RATIO_EPS,
) -> list[str]:
    """Return the ordered output band names derived from the recipe."""

    bands, _ = rgb_dglcm_pc1_band_definitions(rgb_band_indices, ratio_eps)
    return [name for name, _ in bands]


def describe_rgb_dglcm_pc1_stack(
    *,
    rgb_band_indices: tuple[int, int, int],
    pc1_clip_quantiles: tuple[float, float],
    pc1_output_min: float,
    pc1_output_max: float,
    glcm_nbbin: int,
    glcm_directions: tuple[tuple[int, int], ...],
    ratio_eps: float,
    small_radius_m: float,
    large_radius_m: float,
    pc1_clip_values: dict[str, float | None] | None = None,
) -> dict[str, object]:
    """Describe the active scientific recipe without executing it."""

    band_names = rgb_dglcm_pc1_band_names(rgb_band_indices, ratio_eps)
    return {
        "normal_stack": NORMAL_STACK_NAME,
        "channel_names": band_names,
        "band_names": band_names,
        "band_count": len(band_names),
        "structure_operator": "HaralickTextureExtraction",
        "structure_feature": "simple.inertia",
        "structure_feature_band": STRUCTURE_FEATURE_BAND,
        "structure_source": "RGB_PC1",
        "direction_aggregation": (
            "max_over_0_45_90_135"
            if glcm_directions == DEFAULT_GLCM_DIRECTIONS
            else "max_over_configured_directions"
        ),
        "glcm_directions": [list(value) for value in glcm_directions],
        "pc1_quantization": {
            "clip_quantiles": list(pc1_clip_quantiles),
            "output_min": pc1_output_min,
            "output_max": pc1_output_max,
            "nbbin": glcm_nbbin,
            "valid_pixel_clip_values": pc1_clip_values
            or {"lower": None, "upper": None},
        },
        "small_radius_m": small_radius_m,
        "large_radius_m": large_radius_m,
        "ratio_formula": "DGLCM_PC1_SMALL / (DGLCM_PC1_LARGE + eps)",
        "ratio_eps": ratio_eps,
    }


def _intermediate_paths(
    *,
    candidate_id: str,
    valid_mask_path: str | Path,
    runtime_tmp_dir: str | Path,
    background_value: float,
    overwrite: bool,
    dry_run: bool,
    direction_count: int,
) -> dict[str, object]:
    runtime_channel_tmp = Path(runtime_tmp_dir) / "channels"
    runtime_channel_tmp.mkdir(parents=True, exist_ok=True)
    pca_work_root = runtime_channel_tmp / "rgb_pc1_work"
    pca_config = Level1BPCAConfig(
        candidate_id=f"{candidate_id.strip()}__rgb_pc1",
        scaled_feature_stack_path=runtime_channel_tmp / "masked_rgb.tif",
        valid_mask_path=valid_mask_path,
        output_dir=pca_work_root,
        band_count=3,
        pca_components=1,
        background_value=background_value,
        output_filename="rgb_pc1.tif",
        report_filename="rgb_pc1_pca_report.json",
        overwrite=overwrite,
        dry_run=dry_run,
    )
    pca_layout = build_level1b_pca_layout(pca_work_root)
    direction_paths = {
        scale: [
            runtime_channel_tmp / f"dglcm_pc1_{scale}_direction_{index}.tif"
            for index in range(direction_count)
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


def build_masked_rgb_command(
    *,
    bandmathx: str,
    input_path: str | Path,
    valid_mask_path: str | Path,
    output_path: str | Path,
    rgb_band_indices: tuple[int, int, int],
    background_value: float,
) -> list[str]:
    expression = "{" + ";".join(
        f"(im2b1 > 0 ? im1b{index} : {float(background_value)})"
        for index in rgb_band_indices
    ) + "}"
    return [
        str(bandmathx),
        "-il",
        str(input_path),
        str(valid_mask_path),
        "-out",
        str(output_path),
        "float",
        "-exp",
        expression,
    ]


def build_pc1_quantization_command(
    *,
    bandmathx: str,
    pc1_path: str | Path,
    valid_mask_path: str | Path,
    output_path: str | Path,
    lower: float | str,
    upper: float | str,
    output_min: float,
    output_max: float,
) -> list[str]:
    clipped = (
        f"(im1b1 < {lower} ? {lower} : "
        f"(im1b1 > {upper} ? {upper} : im1b1))"
    )
    scaled = f"(({clipped} - {lower}) * {output_max} / ({upper} - {lower}))"
    expression = f"(im2b1 > 0 ? {scaled} : {output_min})"
    return [
        str(bandmathx),
        "-il",
        str(pc1_path),
        str(valid_mask_path),
        "-out",
        str(output_path),
        "float",
        "-exp",
        expression,
    ]


def build_haralick_commands(
    *,
    haralick_app: str,
    input_path: str | Path,
    direction_paths: dict[str, list[Path]],
    radius_small: int,
    radius_large: int,
    glcm_directions: tuple[tuple[int, int], ...],
    output_min: float,
    output_max: float,
    nbbin: int,
) -> list[list[str]]:
    commands: list[list[str]] = []
    for scale, radius in (("small", radius_small), ("large", radius_large)):
        for output_path, (xoff, yoff) in zip(
            direction_paths[scale], glcm_directions, strict=True
        ):
            commands.append(
                [
                    str(haralick_app),
                    "-in",
                    str(input_path),
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
                    _number_token(output_min),
                    "-parameters.max",
                    _number_token(output_max),
                    "-parameters.nbbin",
                    str(nbbin),
                    "-texture",
                    "simple",
                    "-out",
                    str(output_path),
                    "float",
                ]
            )
    return commands


def _balanced_max_expression(terms: list[str]) -> str:
    if not terms:
        raise ValueError("direction aggregation requires at least one input")
    values = list(terms)
    while len(values) > 1:
        next_values = []
        for index in range(0, len(values), 2):
            pair = values[index : index + 2]
            next_values.append(
                pair[0] if len(pair) == 1 else f"max({pair[0]},{pair[1]})"
            )
        values = next_values
    return values[0]


def build_direction_max_command(
    *,
    bandmathx: str,
    input_paths: list[Path],
    output_path: str | Path,
) -> list[str]:
    inertia_terms = [
        f"im{input_index}b{STRUCTURE_FEATURE_BAND}"
        for input_index in range(1, len(input_paths) + 1)
    ]
    return [
        str(bandmathx),
        "-il",
        *(str(path) for path in input_paths),
        "-out",
        str(output_path),
        "float",
        "-exp",
        _balanced_max_expression(inertia_terms),
    ]


def build_final_stack_command(
    *,
    bandmathx: str,
    input_path: str | Path,
    small_structure_path: str | Path,
    large_structure_path: str | Path,
    valid_mask_path: str | Path,
    output_path: str | Path,
    rgb_band_indices: tuple[int, int, int],
    ratio_eps: float,
) -> tuple[list[str], dict[str, object]]:
    bands, expressions = rgb_dglcm_pc1_band_definitions(
        rgb_band_indices, ratio_eps
    )
    mask = "im4b1"
    final_expression = "{" + ";".join(
        f"({mask} > 0 ? {expression} : 0)" for _, expression in bands
    ) + "}"
    command = [
        str(bandmathx),
        "-il",
        str(input_path),
        str(small_structure_path),
        str(large_structure_path),
        str(valid_mask_path),
        "-out",
        str(output_path),
        "float",
        "-exp",
        final_expression,
    ]
    return command, {
        "band_names": [name for name, _ in bands],
        "band_definitions": [
            {"name": name, "expression": expression}
            for name, expression in bands
        ],
        "expressions": expressions,
    }


def _quantile_placeholder(value: float) -> str:
    percentage = float(value) * 100.0
    token = f"{percentage:g}".replace("-", "m").replace(".", "p")
    if percentage.is_integer() and 0 <= percentage < 10:
        token = "0" + token
    return "PC1_Q" + token


def _number_token(value: float) -> str:
    return f"{float(value):g}"


def build_rgb_dglcm_pc1_commands(
    *,
    candidate_id: str,
    input_path: str | Path,
    valid_mask_path: str | Path,
    output_path: str | Path,
    runtime_tmp_dir: str | Path,
    pixel_size_m: float,
    rgb_band_indices: tuple[int, int, int],
    small_radius_m: float,
    large_radius_m: float,
    background_value: float,
    pc1_clip_quantiles: tuple[float, float],
    pc1_output_min: float,
    pc1_output_max: float,
    glcm_nbbin: int,
    glcm_directions: tuple[tuple[int, int], ...],
    ratio_eps: float,
    overwrite: bool,
    dry_run: bool,
    apps: dict[str, str | None],
    pc1_lower: float | str | None = None,
    pc1_upper: float | str | None = None,
) -> tuple[list[list[str]], dict[str, object]]:
    paths = _intermediate_paths(
        candidate_id=candidate_id,
        valid_mask_path=valid_mask_path,
        runtime_tmp_dir=runtime_tmp_dir,
        background_value=background_value,
        overwrite=overwrite,
        dry_run=dry_run,
        direction_count=len(glcm_directions),
    )
    radius_small = max(1, round(small_radius_m / pixel_size_m))
    radius_large = max(1, round(large_radius_m / pixel_size_m))
    lower = (
        pc1_lower
        if pc1_lower is not None
        else _quantile_placeholder(pc1_clip_quantiles[0])
    )
    upper = (
        pc1_upper
        if pc1_upper is not None
        else _quantile_placeholder(pc1_clip_quantiles[1])
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
        build_masked_rgb_command(
            bandmathx=str(apps["BandMathX"]),
            input_path=input_path,
            valid_mask_path=valid_mask_path,
            output_path=paths["masked_rgb"],
            rgb_band_indices=rgb_band_indices,
            background_value=background_value,
        ),
        *pca_commands,
        build_pc1_quantization_command(
            bandmathx=str(apps["BandMathX"]),
            pc1_path=paths["pc1"],
            valid_mask_path=valid_mask_path,
            output_path=paths["pc1_haralick_input"],
            lower=lower,
            upper=upper,
            output_min=pc1_output_min,
            output_max=pc1_output_max,
        ),
        *build_haralick_commands(
            haralick_app=str(apps["HaralickTextureExtraction"]),
            input_path=paths["pc1_haralick_input"],
            direction_paths=paths["direction_paths"],
            radius_small=radius_small,
            radius_large=radius_large,
            glcm_directions=glcm_directions,
            output_min=pc1_output_min,
            output_max=pc1_output_max,
            nbbin=glcm_nbbin,
        ),
        build_direction_max_command(
            bandmathx=str(apps["BandMathX"]),
            input_paths=paths["direction_paths"]["small"],
            output_path=paths["small_max"],
        ),
        build_direction_max_command(
            bandmathx=str(apps["BandMathX"]),
            input_paths=paths["direction_paths"]["large"],
            output_path=paths["large_max"],
        ),
    ]
    final_command, final_metadata = build_final_stack_command(
        bandmathx=str(apps["BandMathX"]),
        input_path=input_path,
        small_structure_path=paths["small_max"],
        large_structure_path=paths["large_max"],
        valid_mask_path=valid_mask_path,
        output_path=output_path,
        rgb_band_indices=rgb_band_indices,
        ratio_eps=ratio_eps,
    )
    commands.append(final_command)
    metadata = {
        **describe_rgb_dglcm_pc1_stack(
            rgb_band_indices=rgb_band_indices,
            pc1_clip_quantiles=pc1_clip_quantiles,
            pc1_output_min=pc1_output_min,
            pc1_output_max=pc1_output_max,
            glcm_nbbin=glcm_nbbin,
            glcm_directions=glcm_directions,
            ratio_eps=ratio_eps,
            small_radius_m=small_radius_m,
            large_radius_m=large_radius_m,
        ),
        "channel_names": final_metadata["band_names"],
        "band_names": final_metadata["band_names"],
        "band_count": len(final_metadata["band_names"]),
        "band_definitions": final_metadata["band_definitions"],
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
        "expressions": final_metadata["expressions"],
        "pca_config": paths["pca_config"],
        "paths": paths,
        "mask_application": {
            "valid_mask_applied_to_rgb_before_pca": True,
            "invalid_rgb_value": float(background_value),
            "valid_mask_applied_to_pc1_after_pca": True,
            "valid_mask_applied_to_final_stack": True,
        },
    }
    return commands, metadata


def _run_command(command: list[str]) -> tuple[dict[str, object], bool]:
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


def run_rgb_dglcm_pc1_proxy_stack(
    *,
    candidate_id: str,
    input_path: str | Path,
    valid_mask_path: str | Path,
    output_path: str | Path,
    runtime_tmp_dir: str | Path,
    pixel_size_m: float,
    rgb_band_indices: tuple[int, int, int],
    small_radius_m: float,
    large_radius_m: float,
    background_value: float,
    pc1_clip_quantiles: tuple[float, float],
    pc1_output_min: float,
    pc1_output_max: float,
    glcm_nbbin: int,
    glcm_directions: tuple[tuple[int, int], ...],
    ratio_eps: float,
    overwrite: bool,
    dry_run: bool,
    apps: dict[str, str | None],
) -> dict[str, object]:
    """Create the normal RGB proxy stack and return execution metadata."""

    commands, metadata = build_rgb_dglcm_pc1_commands(
        candidate_id=candidate_id,
        input_path=input_path,
        valid_mask_path=valid_mask_path,
        output_path=output_path,
        runtime_tmp_dir=runtime_tmp_dir,
        pixel_size_m=pixel_size_m,
        rgb_band_indices=rgb_band_indices,
        small_radius_m=small_radius_m,
        large_radius_m=large_radius_m,
        background_value=background_value,
        pc1_clip_quantiles=pc1_clip_quantiles,
        pc1_output_min=pc1_output_min,
        pc1_output_max=pc1_output_max,
        glcm_nbbin=glcm_nbbin,
        glcm_directions=glcm_directions,
        ratio_eps=ratio_eps,
        overwrite=overwrite,
        dry_run=dry_run,
        apps=apps,
    )
    command_results: list[dict[str, object]] = []
    failure_reasons: list[str] = []
    pc1_clip_values: dict[str, float | None] = {"lower": None, "upper": None}

    if dry_run:
        status = "dry_run"
        output_created = False
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
                    background_value=float(background_value),
                )
                try:
                    stats = compute_quantile_scaling_parameters(
                        metadata["paths"]["pc1"],
                        stats_config,
                        quantile_probs=pc1_clip_quantiles,
                    )
                    lower = float(stats["lower_values"][0])
                    upper = float(stats["upper_values"][0])
                    pc1_clip_values = {"lower": lower, "upper": upper}
                    commands, metadata = build_rgb_dglcm_pc1_commands(
                        candidate_id=candidate_id,
                        input_path=input_path,
                        valid_mask_path=valid_mask_path,
                        output_path=output_path,
                        runtime_tmp_dir=runtime_tmp_dir,
                        pixel_size_m=pixel_size_m,
                        rgb_band_indices=rgb_band_indices,
                        small_radius_m=small_radius_m,
                        large_radius_m=large_radius_m,
                        background_value=background_value,
                        pc1_clip_quantiles=pc1_clip_quantiles,
                        pc1_output_min=pc1_output_min,
                        pc1_output_max=pc1_output_max,
                        glcm_nbbin=glcm_nbbin,
                        glcm_directions=glcm_directions,
                        ratio_eps=ratio_eps,
                        overwrite=overwrite,
                        dry_run=dry_run,
                        apps=apps,
                        pc1_lower=lower,
                        pc1_upper=upper,
                    )
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

    metadata["pc1_quantization"]["valid_pixel_clip_values"] = pc1_clip_values
    return {
        **metadata,
        "status": status,
        "failure_reasons": failure_reasons,
        "command_results": command_results,
        "commands": commands,
        "output_created": output_created,
    }
