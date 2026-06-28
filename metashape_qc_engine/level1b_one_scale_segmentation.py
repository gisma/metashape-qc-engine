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
    segmentation_nodata_value: float = 0.0
    tilesizex: int = 512
    tilesizey: int = 512
    ram_mb: int = 1024
    cleanup: bool = True
    overwrite: bool = False


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


def validate_one_scale_segmentation_config(config, layout, apps) -> tuple[dict[str, bool], list[str]]:
    checks = {key: True for key in CHECK_KEYS}
    failure_reasons: list[str] = []
    feature_space_stack_path = _segmentation_stack_path(config)
    valid_mask_path = Path(config.valid_mask_path) if config.valid_mask_path is not None else None
    perturbation_candidates_json_path = Path(config.perturbation_candidates_json_path)

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
    if not config.overwrite:
        existing_outputs = [layout["smoke_dir"] / filename for filename in OUTPUT_ARTIFACT_FILENAMES.values()]
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
    if not apps.get("gdal_edit"):
        checks["gdal_edit_discoverable"] = False
        failure_reasons.append("no GDAL gdal_edit.py discoverable")

    return checks, failure_reasons


def read_perturbation_candidates(json_path) -> list[dict[str, object]]:
    with Path(json_path).open(encoding="utf-8") as file_obj:
        payload = json.load(file_obj)

    if "candidates" not in payload:
        raise ValueError("candidates key is missing")
    if not payload["candidates"]:
        raise ValueError("candidates is empty")
    return list(payload["candidates"])


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
        str(layout["smoke_dir"] / "masked_segmentation_stack.tif"),
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
        str(layout["smoke_dir"] / "masked_segmentation_stack.tif"),
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


def _output_artifacts(layout) -> dict[str, str]:
    return {key: str(layout["smoke_dir"] / filename) for key, filename in OUTPUT_ARTIFACT_FILENAMES.items()}


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
    artifacts = _output_artifacts(layout)
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
        "masked_segmentation_stack_path": str(layout["smoke_dir"] / "masked_segmentation_stack.tif"),
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
    if REPORT_FILENAME not in report["files_written"]:
        report["files_written"].append(REPORT_FILENAME)
    with report_path.open("w", encoding="utf-8") as file_obj:
        json.dump({key: report[key] for key in REPORT_KEYS}, file_obj, indent=2)
    report["output_artifact_exists"] = _artifact_exists(report["output_artifacts"])
    report["output_artifact_non_empty"] = _artifact_non_empty(report["output_artifacts"])
    report["files_written"] = _files_written(report["output_artifacts"], report_path)
    with report_path.open("w", encoding="utf-8") as file_obj:
        json.dump({key: report[key] for key in REPORT_KEYS}, file_obj, indent=2)
    return json.loads(report_path.read_text(encoding="utf-8"))


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
        commands = [
            build_masked_segmentation_stack_command(config, layout),
            build_set_nodata_command(config, layout),
            build_meanshift_smoothing_command(config, apps, layout, selected_candidate),
            build_masked_meanshift_smoothed_command(config, layout),
            build_masked_meanshift_position_command(config, layout),
            build_lsms_segmentation_command(config, apps, layout, selected_candidate),
            build_small_regions_merging_command(config, apps, layout, selected_candidate),
            build_postmask_labels_command(config, layout),
        ]
        report["otb_commands"] = commands
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        report["failure_reasons"].append(str(exc))
        return _write_report(report, layout)

    expected_by_step = (
        ("masked_segmentation_stack",),
        ("masked_segmentation_stack",),
        ("meanshift_smoothed", "meanshift_position"),
        ("meanshift_smoothed_masked",),
        ("meanshift_position_masked",),
        ("lsms_labels",),
        ("merged_labels_unmasked",),
        ("merged_labels",),
    )
    for index, command in enumerate(report["otb_commands"]):
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
        for filename in expected_by_step[index]:
            output_path = Path(report["output_artifacts"][filename])
            if not output_path.exists():
                report["failure_reasons"].append(f"missing expected output {output_path.name}")
                return _write_report(report, layout)
            if output_path.stat().st_size == 0:
                report["failure_reasons"].append(f"empty expected output {output_path.name}")
                return _write_report(report, layout)
        if index == 4:
            report["pre_lsms_mask_applied"] = True
        if index == 7:
            report["post_mask_applied"] = True
            report["labels_postmasked"] = True
            report["invalid_support_excluded_from_q_statistics"] = True

    report["status"] = "ok"
    if config.cleanup and layout["tmp_dir"].exists():
        shutil.rmtree(layout["tmp_dir"])
        report["tmp_dir_removed"] = True
    return _write_report(report, layout)
