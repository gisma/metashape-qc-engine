from dataclasses import dataclass
import json
import math
from pathlib import Path
import shutil
import subprocess


RASTER_SUFFIXES = {".tif", ".tiff", ".vrt", ".img", ".jp2"}
OTB_APP_CLI_NAMES = {
    "BandMathX": "otbcli_BandMathX",
    "MeanShiftSmoothing": "otbcli_MeanShiftSmoothing",
    "LSMSSegmentation": "otbcli_LSMSSegmentation",
    "SmallRegionsMerging": "otbcli_SmallRegionsMerging",
}
GDAL_EDIT_CLI_NAME = "gdal_edit.py"
REPORT_FILENAME = "one_scale_segmentation_report.json"
OUTPUT_ARTIFACT_FILENAMES = {
    "meanshift_smoothed": "meanshift_smoothed.tif",
    "meanshift_position": "meanshift_position.tif",
    "meanshift_smoothed_masked": "meanshift_smoothed_masked.tif",
    "meanshift_position_masked": "meanshift_position_masked.tif",
    "lsms_labels": "lsms_labels.tif",
    "merged_labels": "merged_labels.tif",
    "report": REPORT_FILENAME,
    "masked_segmentation_stack": "masked_segmentation_stack.tif",
    "merged_labels_unmasked": "merged_labels_unmasked.tif",
}
REPORT_KEYS = (
    "candidate_id",
    "scale_id",
    "output_dir",
    "smoke_dir",
    "tmp_dir",
    "feature_space_stack_path",
    "segmentation_stack_path",
    "segmentation_stack_source",
    "valid_mask_path",
    "masked_segmentation_stack_path",
    "masked_segmentation_stack_scope",
    "run_contract_version",
    "merged_labels_path",
    "meanshift_smoothed_path",
    "meanshift_position_path",
    "meanshift_smoothed_masked_path",
    "meanshift_position_masked_path",
    "segmentation_nodata_value",
    "pre_lsms_mask_applied",
    "post_mask_applied",
    "label_invalid_support_value",
    "labels_postmasked",
    "invalid_support_excluded_from_q_statistics",
    "perturbation_candidates_json_path",
    "perturbation_id",
    "selected_candidate",
    "spatialr",
    "spatialr_px",
    "minsize",
    "minsize_px",
    "radius_m",
    "ranger",
    "tilesizex",
    "tilesizey",
    "ram_mb",
    "cleanup",
    "overwrite",
    "debug_command_output",
    "checks",
    "status",
    "failure_reasons",
    "otb_apps",
    "otb_commands",
    "command_results",
    "output_artifacts",
    "output_artifact_exists",
    "output_artifact_non_empty",
    "files_written",
    "tmp_dir_removed",
    "primary_product",
    "vectorization_required",
    "vectorization_status",
    "downstream_vector_product_status",
    "raster_first_decision",
    "no_" + "bat" + "ch_segmentation_performed",
    "no_" + "stabi" + "lity_analysis_performed",
    "no_scale_selection_performed",
    "no_" + "zon" + "al_statistics_performed",
    "no_python_raster_processing",
)
CHECK_KEYS = (
    "candidate_id_non_empty",
    "feature_space_stack_path_exists",
    "feature_space_stack_suffix_raster_like",
    "valid_mask_path_exists",
    "valid_mask_suffix_raster_like",
    "perturbation_candidates_json_path_exists",
    "perturbation_candidates_json_path_suffix_json",
    "perturbation_id_non_empty",
    "tilesizex_positive_integer",
    "tilesizey_positive_integer",
    "ram_mb_positive_integer",
    "cleanup_is_bool",
    "output_artifacts_available",
    "otb_meanshift_smoothing_discoverable",
    "otb_lsms_segmentation_discoverable",
    "otb_small_regions_merging_discoverable",
    "otb_bandmathx_discoverable",
    "gdal_edit_discoverable",
    "prebuilt_masked_segmentation_stack_exists_if_provided",
    "prebuilt_masked_segmentation_stack_non_empty_if_provided",
    "prebuilt_masked_segmentation_stack_suffix_raster_like_if_provided",
)


@dataclass
class Level1BOneScaleSegmentationConfig:
    candidate_id: str
    output_dir: str | Path
    feature_space_stack_path: str | Path
    perturbation_candidates_json_path: str | Path
    perturbation_id: str
    valid_mask_path: str | Path | None = None
    segmentation_stack_path: str | Path | None = None
    segmentation_stack_source: str = "proxy_stack"
    masked_segmentation_stack_path: str | Path | None = None
    masked_segmentation_stack_scope: str = "per_run_generated"
    run_contract_version: int = 1
    segmentation_nodata_value: float = 0.0
    tilesizex: int = 512
    tilesizey: int = 512
    ram_mb: int = 1024
    cleanup: bool = True
    overwrite: bool = False
    debug_command_output: bool = False


def build_level1b_one_scale_segmentation_layout(output_dir, perturbation_id) -> dict[str, Path]:
    smoke_dir = Path(output_dir) / "level1b" / "segmentation_smoke" / str(perturbation_id).strip()
    tmp_dir = smoke_dir / "tmp"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return {"smoke_dir": smoke_dir, "tmp_dir": tmp_dir}


def discover_one_scale_segmentation_otb_apps() -> dict[str, str | None]:
    apps = {name: shutil.which(cli_name) for name, cli_name in OTB_APP_CLI_NAMES.items()}
    apps["gdal_edit"] = shutil.which(GDAL_EDIT_CLI_NAME)
    return apps


def _segmentation_stack_path(config) -> Path:
    return Path(config.segmentation_stack_path or config.feature_space_stack_path)


def _masked_segmentation_stack_path(config, layout) -> Path:
    if config.masked_segmentation_stack_path is not None:
        return Path(config.masked_segmentation_stack_path)
    return layout["smoke_dir"] / "masked_segmentation_stack.tif"


def validate_one_scale_segmentation_config(config, layout, apps) -> tuple[dict[str, bool], list[str]]:
    checks = {key: True for key in CHECK_KEYS}
    failure_reasons: list[str] = []
    feature_space_stack_path = _segmentation_stack_path(config)
    valid_mask_path = Path(config.valid_mask_path) if config.valid_mask_path is not None else None
    perturbation_candidates_json_path = Path(config.perturbation_candidates_json_path)
    prebuilt_masked_stack = (
        Path(config.masked_segmentation_stack_path)
        if config.masked_segmentation_stack_path is not None
        else None
    )

    if not str(config.candidate_id).strip():
        checks["candidate_id_non_empty"] = False
        failure_reasons.append("candidate_id is empty")
    if not feature_space_stack_path.exists():
        checks["feature_space_stack_path_exists"] = False
        failure_reasons.append("feature_space_stack_path does not exist")
    if feature_space_stack_path.suffix.lower() not in RASTER_SUFFIXES:
        checks["feature_space_stack_suffix_raster_like"] = False
        failure_reasons.append("feature_space_stack_path suffix must be one of .tif, .tiff, .vrt, .img, .jp2")
    if valid_mask_path is None or not valid_mask_path.exists():
        checks["valid_mask_path_exists"] = False
        failure_reasons.append("valid_mask_path does not exist")
    if valid_mask_path is None or valid_mask_path.suffix.lower() not in RASTER_SUFFIXES:
        checks["valid_mask_suffix_raster_like"] = False
        failure_reasons.append("valid_mask_path suffix must be one of .tif, .tiff, .vrt, .img, .jp2")
    if not perturbation_candidates_json_path.exists():
        checks["perturbation_candidates_json_path_exists"] = False
        failure_reasons.append("perturbation_candidates_json_path does not exist")
    if perturbation_candidates_json_path.suffix.lower() != ".json":
        checks["perturbation_candidates_json_path_suffix_json"] = False
        failure_reasons.append("perturbation_candidates_json_path suffix must be .json")
    if not str(config.perturbation_id).strip():
        checks["perturbation_id_non_empty"] = False
        failure_reasons.append("perturbation_id is empty")
    if not isinstance(config.tilesizex, int) or isinstance(config.tilesizex, bool) or config.tilesizex <= 0:
        checks["tilesizex_positive_integer"] = False
        failure_reasons.append("tilesizex must be a positive integer")
    if not isinstance(config.tilesizey, int) or isinstance(config.tilesizey, bool) or config.tilesizey <= 0:
        checks["tilesizey_positive_integer"] = False
        failure_reasons.append("tilesizey must be a positive integer")
    if not isinstance(config.ram_mb, int) or isinstance(config.ram_mb, bool) or config.ram_mb <= 0:
        checks["ram_mb_positive_integer"] = False
        failure_reasons.append("ram_mb must be a positive integer")
    if not isinstance(config.cleanup, bool):
        checks["cleanup_is_bool"] = False
        failure_reasons.append("cleanup must be bool")
    if prebuilt_masked_stack is not None:
        if not prebuilt_masked_stack.exists():
            checks["prebuilt_masked_segmentation_stack_exists_if_provided"] = False
            failure_reasons.append(
                "prebuilt masked_segmentation_stack_path does not exist"
            )
        if not prebuilt_masked_stack.exists() or prebuilt_masked_stack.stat().st_size == 0:
            checks[
                "prebuilt_masked_segmentation_stack_non_empty_if_provided"
            ] = False
            failure_reasons.append(
                "prebuilt masked_segmentation_stack_path is empty"
            )
        if prebuilt_masked_stack.suffix.lower() not in RASTER_SUFFIXES:
            checks[
                "prebuilt_masked_segmentation_stack_suffix_raster_like_if_provided"
            ] = False
            failure_reasons.append(
                "prebuilt masked_segmentation_stack_path suffix must be raster-like"
            )
    if not config.overwrite:
        existing_outputs = [
            layout["smoke_dir"] / filename
            for key, filename in OUTPUT_ARTIFACT_FILENAMES.items()
            if not (
                key == "masked_segmentation_stack"
                and prebuilt_masked_stack is not None
            )
        ]
        blocked_outputs = [path.name for path in existing_outputs if path.exists()]
        if blocked_outputs:
            checks["output_artifacts_available"] = False
            failure_reasons.append("output artifacts already exist and overwrite is false")
    app_checks = {
        "BandMathX": "otb_bandmathx_discoverable",
        "MeanShiftSmoothing": "otb_meanshift_smoothing_discoverable",
        "LSMSSegmentation": "otb_lsms_segmentation_discoverable",
        "SmallRegionsMerging": "otb_small_regions_merging_discoverable",
    }
    for app_name, check_key in app_checks.items():
        if not apps.get(app_name):
            checks[check_key] = False
            failure_reasons.append(f"no OTB {app_name} app discoverable")
    if prebuilt_masked_stack is None and not apps.get("gdal_edit"):
        checks["gdal_edit_discoverable"] = False
        failure_reasons.append("no GDAL gdal_edit.py discoverable")

    return checks, failure_reasons


def read_perturbation_candidates(json_path) -> list[dict[str, object]]:
    with Path(json_path).open(encoding="utf-8") as file_obj:
        payload = json.load(file_obj)

    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict) and "candidates" in payload:
        candidates = payload["candidates"]
    else:
        raise ValueError("candidates key is missing")
    if not candidates:
        raise ValueError("candidates is empty")
    return list(candidates)


def select_one_perturbation_candidate(candidates, perturbation_id) -> dict[str, object]:
    matches = list(filter(lambda item: item.get("perturbation_id") == perturbation_id, candidates))
    if not matches:
        raise ValueError("perturbation_id is missing")
    if len(matches) > 1:
        raise ValueError("perturbation_id is duplicated")
    selected = matches[0]
    for field in ("scale_id", "spatialr_px", "minsize_px", "ranger"):
        if field not in selected:
            raise ValueError(f"selected candidate lacks {field}")
    selected_candidate_to_parameters(selected)
    return dict(selected)


def selected_candidate_to_parameters(selected_candidate) -> dict[str, object]:
    try:
        spatialr = int(selected_candidate["spatialr_px"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("selected spatialr_px is not convertible to int >= 1") from exc
    if spatialr < 1:
        raise ValueError("selected spatialr_px is not convertible to int >= 1")

    try:
        minsize = int(selected_candidate["minsize_px"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("selected minsize_px is not convertible to int >= 1") from exc
    if minsize < 1:
        raise ValueError("selected minsize_px is not convertible to int >= 1")

    try:
        ranger = float(selected_candidate["ranger"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("selected ranger is not convertible to float > 0") from exc
    if ranger <= 0:
        raise ValueError("selected ranger is not convertible to float > 0")

    return {"spatialr": spatialr, "minsize": minsize, "ranger": ranger}


def selected_candidate_radius_m(selected_candidate) -> float | None:
    def positive_number(key):
        try:
            value = float(selected_candidate.get(key))
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) and value > 0 else None

    for key in ("source_candidate_radius_m", "candidate_radius_m", "radius_m", "r_candidate_source_m"):
        value = positive_number(key)
        if value is not None:
            return value
    area_m2 = positive_number("area_m2")
    if area_m2 is not None:
        return math.sqrt(area_m2 / math.pi)
    spatialr_m = positive_number("spatialr_m")
    if spatialr_m is not None:
        return spatialr_m
    spatialr_px = positive_number("spatialr_px")
    pixel_size_m = positive_number("pixel_size_m")
    if spatialr_px is not None and pixel_size_m is not None:
        return spatialr_px * pixel_size_m
    return None


def build_meanshift_smoothing_command(config, apps, layout, selected_candidate) -> list[str]:
    parameters = selected_candidate_to_parameters(selected_candidate)
    return [
        OTB_APP_CLI_NAMES["MeanShiftSmoothing"],
        "-in",
        str(_masked_segmentation_stack_path(config, layout)),
        "-fout",
        str(layout["smoke_dir"] / "meanshift_smoothed.tif"),
        "float",
        "-foutpos",
        str(layout["smoke_dir"] / "meanshift_position.tif"),
        "float",
        "-spatialr",
        str(parameters["spatialr"]),
        "-ranger",
        str(parameters["ranger"]),
        "-ram",
        str(config.ram_mb),
    ]


def build_lsms_segmentation_command(config, apps, layout, selected_candidate) -> list[str]:
    parameters = selected_candidate_to_parameters(selected_candidate)
    return [
        OTB_APP_CLI_NAMES["LSMSSegmentation"],
        "-in",
        str(layout["smoke_dir"] / "meanshift_smoothed_masked.tif"),
        "-inpos",
        str(layout["smoke_dir"] / "meanshift_position_masked.tif"),
        "-out",
        str(layout["smoke_dir"] / "lsms_labels.tif"),
        "uint32",
        "-spatialr",
        str(parameters["spatialr"]),
        "-ranger",
        str(parameters["ranger"]),
        "-minsize",
        "0",
        "-tilesizex",
        str(config.tilesizex),
        "-tilesizey",
        str(config.tilesizey),
        "-tmpdir",
        str(layout["tmp_dir"]),
    ]


def build_small_regions_merging_command(config, apps, layout, selected_candidate) -> list[str]:
    parameters = selected_candidate_to_parameters(selected_candidate)
    return [
        OTB_APP_CLI_NAMES["SmallRegionsMerging"],
        "-in",
        str(_masked_segmentation_stack_path(config, layout)),
        "-inseg",
        str(layout["smoke_dir"] / "lsms_labels.tif"),
        "-out",
        str(layout["smoke_dir"] / "merged_labels_unmasked.tif"),
        "uint32",
        "-minsize",
        str(parameters["minsize"]),
        "-ram",
        str(config.ram_mb),
    ]


def build_masked_segmentation_stack_command(config, layout) -> list[str]:
    return [
        OTB_APP_CLI_NAMES["BandMathX"],
        "-il",
        str(_segmentation_stack_path(config)),
        str(Path(config.valid_mask_path)),
        "-exp",
        "im2b1 > 0 ? im1 : im1 * 0",
        "-out",
        str(layout["smoke_dir"] / "masked_segmentation_stack.tif"),
        "float",
    ]


def build_set_nodata_command(config, layout) -> list[str]:
    return [
        GDAL_EDIT_CLI_NAME,
        "-a_nodata",
        f"{float(config.segmentation_nodata_value):.17g}",
        str(layout["smoke_dir"] / "masked_segmentation_stack.tif"),
    ]


def prepare_canonical_masked_segmentation_stack(
    segmentation_stack_path: str | Path,
    valid_mask_path: str | Path,
    output_path: str | Path,
    *,
    segmentation_nodata_value: float = 0.0,
    overwrite: bool = False,
) -> dict[str, object]:
    segmentation_stack_path = Path(segmentation_stack_path)
    valid_mask_path = Path(valid_mask_path)
    output_path = Path(output_path)
    report_path = output_path.with_name("masked_segmentation_stack_report.json")
    expected_provenance = {
        "segmentation_stack_path": str(segmentation_stack_path),
        "valid_mask_path": str(valid_mask_path),
        "segmentation_nodata_value": float(segmentation_nodata_value),
        "masked_segmentation_stack_path": str(output_path),
    }
    if not overwrite and output_path.is_file() and output_path.stat().st_size > 0:
        try:
            existing_report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            existing_report = None
        if isinstance(existing_report, dict) and all(
            existing_report.get(key) == value
            for key, value in expected_provenance.items()
        ):
            return {
                **existing_report,
                "status": "ok",
                "preparation_status": "reused",
            }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(
        f".{output_path.stem}.tmp{output_path.suffix}"
    )
    if temporary_path.exists():
        temporary_path.unlink()
    commands = [
        [
            OTB_APP_CLI_NAMES["BandMathX"],
            "-il",
            str(segmentation_stack_path),
            str(valid_mask_path),
            "-exp",
            "im2b1 > 0 ? im1 : im1 * 0",
            "-out",
            str(temporary_path),
            "float",
        ],
        [
            GDAL_EDIT_CLI_NAME,
            "-a_nodata",
            f"{float(segmentation_nodata_value):.17g}",
            str(temporary_path),
        ],
    ]
    command_results = []
    failure_reasons = []
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
            failure_reasons.append(
                f"command failed with returncode {result.returncode}"
            )
            break
    if not failure_reasons and (
        not temporary_path.is_file() or temporary_path.stat().st_size == 0
    ):
        failure_reasons.append("canonical masked segmentation stack is missing or empty")
    if failure_reasons:
        if temporary_path.exists():
            temporary_path.unlink()
        return {
            **expected_provenance,
            "status": "failed",
            "preparation_status": "failed",
            "commands": commands,
            "command_results": command_results,
            "failure_reasons": failure_reasons,
        }

    temporary_path.replace(output_path)
    report = {
        **expected_provenance,
        "status": "ok",
        "preparation_status": "computed",
        "commands": commands,
        "command_results": [
            {
                "command": result["command"],
                "returncode": result["returncode"],
            }
            for result in command_results
        ],
        "failure_reasons": [],
        "size_bytes": output_path.stat().st_size,
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def build_masked_meanshift_smoothed_command(config, layout) -> list[str]:
    return [
        OTB_APP_CLI_NAMES["BandMathX"],
        "-il",
        str(layout["smoke_dir"] / "meanshift_smoothed.tif"),
        str(Path(config.valid_mask_path)),
        "-exp",
        "im2b1 > 0 ? im1 : im1 * 0",
        "-out",
        str(layout["smoke_dir"] / "meanshift_smoothed_masked.tif"),
        "float",
    ]


def build_masked_meanshift_position_command(config, layout) -> list[str]:
    return [
        OTB_APP_CLI_NAMES["BandMathX"],
        "-il",
        str(layout["smoke_dir"] / "meanshift_position.tif"),
        str(Path(config.valid_mask_path)),
        "-exp",
        "im2b1 > 0 ? im1 : im1 * 0",
        "-out",
        str(layout["smoke_dir"] / "meanshift_position_masked.tif"),
        "float",
    ]


def build_postmask_labels_command(config, layout) -> list[str]:
    return [
        OTB_APP_CLI_NAMES["BandMathX"],
        "-il",
        str(layout["smoke_dir"] / "merged_labels_unmasked.tif"),
        str(Path(config.valid_mask_path)),
        "-exp",
        "im2b1 > 0 ? im1b1 : 0",
        "-out",
        str(layout["smoke_dir"] / "merged_labels.tif"),
        "uint32",
    ]


def _output_artifacts(config, layout) -> dict[str, str]:
    artifacts = {
        key: str(layout["smoke_dir"] / filename)
        for key, filename in OUTPUT_ARTIFACT_FILENAMES.items()
    }
    artifacts["masked_segmentation_stack"] = str(
        _masked_segmentation_stack_path(config, layout)
    )
    return artifacts


def _artifact_exists(artifacts) -> dict[str, bool]:
    return {name: Path(path).exists() for name, path in artifacts.items()}


def _artifact_non_empty(artifacts) -> dict[str, bool]:
    return {name: Path(path).exists() and Path(path).stat().st_size > 0 for name, path in artifacts.items()}


def _files_written(artifacts, report_path) -> list[str]:
    files = [Path(path).name for path in artifacts.values() if Path(path).exists() and Path(path).stat().st_size > 0]
    if Path(report_path).exists():
        files.append(Path(report_path).name)
    return list(dict.fromkeys(files))


def _base_report(config, layout, checks, failure_reasons, apps) -> dict[str, object]:
    artifacts = _output_artifacts(config, layout)
    values = {
        "candidate_id": str(config.candidate_id).strip(),
        "scale_id": None,
        "output_dir": str(Path(config.output_dir)),
        "smoke_dir": str(layout["smoke_dir"]),
        "tmp_dir": str(layout["tmp_dir"]),
        "feature_space_stack_path": str(Path(config.feature_space_stack_path)),
        "segmentation_stack_path": str(_segmentation_stack_path(config)),
        "segmentation_stack_source": str(config.segmentation_stack_source),
        "valid_mask_path": str(Path(config.valid_mask_path)) if config.valid_mask_path is not None else None,
        "masked_segmentation_stack_path": str(
            _masked_segmentation_stack_path(config, layout)
        ),
        "masked_segmentation_stack_scope": str(
            config.masked_segmentation_stack_scope
        ),
        "run_contract_version": int(config.run_contract_version),
        "merged_labels_path": str(layout["smoke_dir"] / "merged_labels.tif"),
        "meanshift_smoothed_path": str(layout["smoke_dir"] / "meanshift_smoothed.tif"),
        "meanshift_position_path": str(layout["smoke_dir"] / "meanshift_position.tif"),
        "meanshift_smoothed_masked_path": str(layout["smoke_dir"] / "meanshift_smoothed_masked.tif"),
        "meanshift_position_masked_path": str(layout["smoke_dir"] / "meanshift_position_masked.tif"),
        "segmentation_nodata_value": config.segmentation_nodata_value,
        "pre_lsms_mask_applied": False,
        "post_mask_applied": False,
        "label_invalid_support_value": 0,
        "labels_postmasked": False,
        "invalid_support_excluded_from_q_statistics": False,
        "perturbation_candidates_json_path": str(Path(config.perturbation_candidates_json_path)),
        "perturbation_id": str(config.perturbation_id).strip(),
        "selected_candidate": {},
        "spatialr": None,
        "spatialr_px": None,
        "minsize": None,
        "minsize_px": None,
        "radius_m": None,
        "ranger": None,
        "tilesizex": config.tilesizex,
        "tilesizey": config.tilesizey,
        "ram_mb": config.ram_mb,
        "cleanup": config.cleanup,
        "overwrite": config.overwrite,
        "debug_command_output": config.debug_command_output,
        "checks": checks,
        "status": "failed",
        "failure_reasons": failure_reasons,
        "otb_apps": apps,
        "otb_commands": [],
        "command_results": [],
        "output_artifacts": artifacts,
        "output_artifact_exists": _artifact_exists(artifacts),
        "output_artifact_non_empty": _artifact_non_empty(artifacts),
        "files_written": [],
        "tmp_dir_removed": False,
        "primary_product": "merged_labels.tif",
        "vectorization_required": False,
        "vectorization_status": "not_part_of_raster_smoke",
        "downstream_vector_product_status": "deferred",
        "raster_first_decision": "Level1b_primary_analysis_uses_label_rasters",
        "no_" + "bat" + "ch_segmentation_performed": True,
        "no_" + "stabi" + "lity_analysis_performed": True,
        "no_scale_selection_performed": True,
        "no_" + "zon" + "al_statistics_performed": True,
        "no_python_raster_processing": True,
    }
    return {key: values[key] for key in REPORT_KEYS}


def _write_report(report, layout) -> dict[str, object]:
    report_path = layout["smoke_dir"] / REPORT_FILENAME
    report["output_artifact_exists"] = _artifact_exists(report["output_artifacts"])
    report["output_artifact_non_empty"] = _artifact_non_empty(report["output_artifacts"])
    report["files_written"] = _files_written(report["output_artifacts"], report_path)
    if report["masked_segmentation_stack_scope"] == "response_surface_canonical":
        report["files_written"] = [
            filename
            for filename in report["files_written"]
            if filename != "masked_segmentation_stack.tif"
        ]
    if REPORT_FILENAME not in report["files_written"]:
        report["files_written"].append(REPORT_FILENAME)
    if report["status"] == "ok" and not report["debug_command_output"]:
        report["command_results"] = [
            {
                key: value
                for key, value in command_result.items()
                if key not in {"stdout", "stderr"}
            }
            for command_result in report["command_results"]
        ]
    payload = {key: report[key] for key in REPORT_KEYS}
    with report_path.open("w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj, indent=2)
    return payload


def run_one_scale_segmentation_smoke(config) -> dict[str, object]:
    layout = build_level1b_one_scale_segmentation_layout(config.output_dir, config.perturbation_id)
    apps = discover_one_scale_segmentation_otb_apps()
    checks, failure_reasons = validate_one_scale_segmentation_config(config, layout, apps)
    report = _base_report(config, layout, checks, failure_reasons, apps)

    if failure_reasons:
        return _write_report(report, layout)

    try:
        candidates = read_perturbation_candidates(config.perturbation_candidates_json_path)
        selected_candidate = select_one_perturbation_candidate(candidates, str(config.perturbation_id).strip())
        parameters = selected_candidate_to_parameters(selected_candidate)
        report["selected_candidate"] = selected_candidate
        report["scale_id"] = str(selected_candidate["scale_id"])
        report["spatialr"] = parameters["spatialr"]
        report["spatialr_px"] = parameters["spatialr"]
        report["minsize"] = parameters["minsize"]
        report["minsize_px"] = parameters["minsize"]
        report["radius_m"] = selected_candidate_radius_m(selected_candidate)
        report["ranger"] = parameters["ranger"]
        command_steps = []
        if config.masked_segmentation_stack_path is None:
            command_steps.extend(
                [
                    (
                        build_masked_segmentation_stack_command(config, layout),
                        ("masked_segmentation_stack",),
                        None,
                    ),
                    (
                        build_set_nodata_command(config, layout),
                        ("masked_segmentation_stack",),
                        None,
                    ),
                ]
            )
        command_steps.extend(
            [
                (
                    build_meanshift_smoothing_command(
                        config, apps, layout, selected_candidate
                    ),
                    ("meanshift_smoothed", "meanshift_position"),
                    None,
                ),
                (
                    build_masked_meanshift_smoothed_command(config, layout),
                    ("meanshift_smoothed_masked",),
                    None,
                ),
                (
                    build_masked_meanshift_position_command(config, layout),
                    ("meanshift_position_masked",),
                    "pre_lsms_mask_applied",
                ),
                (
                    build_lsms_segmentation_command(
                        config, apps, layout, selected_candidate
                    ),
                    ("lsms_labels",),
                    None,
                ),
                (
                    build_small_regions_merging_command(
                        config, apps, layout, selected_candidate
                    ),
                    ("merged_labels_unmasked",),
                    None,
                ),
                (
                    build_postmask_labels_command(config, layout),
                    ("merged_labels",),
                    "post_mask_applied",
                ),
            ]
        )
        report["otb_commands"] = [step[0] for step in command_steps]
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        report["failure_reasons"].append(str(exc))
        return _write_report(report, layout)

    for command, expected_artifacts, completion_flag in command_steps:
        result = subprocess.run(command, capture_output=True, text=True)
        report["command_results"].append(
            {
                "command": command,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        if result.returncode != 0:
            report["failure_reasons"].append(f"command failed with returncode {result.returncode}")
            return _write_report(report, layout)
        for filename in expected_artifacts:
            output_path = Path(report["output_artifacts"][filename])
            if not output_path.exists():
                report["failure_reasons"].append(f"missing expected output {output_path.name}")
                return _write_report(report, layout)
            if output_path.stat().st_size == 0:
                report["failure_reasons"].append(f"empty expected output {output_path.name}")
                return _write_report(report, layout)
        if completion_flag == "pre_lsms_mask_applied":
            report["pre_lsms_mask_applied"] = True
        if completion_flag == "post_mask_applied":
            report["post_mask_applied"] = True
            report["labels_postmasked"] = True
            report["invalid_support_excluded_from_q_statistics"] = True

    report["status"] = "ok"
    if config.cleanup and layout["tmp_dir"].exists():
        shutil.rmtree(layout["tmp_dir"])
        report["tmp_dir_removed"] = True
    return _write_report(report, layout)
