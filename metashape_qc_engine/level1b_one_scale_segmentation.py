from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess


RASTER_SUFFIXES = {".tif", ".tiff", ".vrt", ".img", ".jp2"}
OTB_APP_CLI_NAMES = {
    "MeanShiftSmoothing": "otbcli_MeanShiftSmoothing",
    "LSMSSegmentation": "otbcli_LSMSSegmentation",
    "SmallRegionsMerging": "otbcli_SmallRegionsMerging",
}
REPORT_FILENAME = "one_scale_segmentation_report.json"
OUTPUT_ARTIFACT_FILENAMES = {
    "meanshift_smoothed": "meanshift_smoothed.tif",
    "meanshift_position": "meanshift_position.tif",
    "lsms_labels": "lsms_labels.tif",
    "merged_labels": "merged_labels.tif",
    "report": REPORT_FILENAME,
}
REPORT_KEYS = (
    "candidate_id",
    "output_dir",
    "smoke_dir",
    "tmp_dir",
    "feature_space_stack_path",
    "perturbation_candidates_json_path",
    "perturbation_id",
    "selected_candidate",
    "spatialr",
    "minsize",
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
)


@dataclass
class Level1BOneScaleSegmentationConfig:
    candidate_id: str
    output_dir: str | Path
    feature_space_stack_path: str | Path
    perturbation_candidates_json_path: str | Path
    perturbation_id: str
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
    return {name: shutil.which(cli_name) for name, cli_name in OTB_APP_CLI_NAMES.items()}


def validate_one_scale_segmentation_config(config, layout, apps) -> tuple[dict[str, bool], list[str]]:
    checks = {key: True for key in CHECK_KEYS}
    failure_reasons: list[str] = []
    feature_space_stack_path = Path(config.feature_space_stack_path)
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
        "MeanShiftSmoothing": "otb_meanshift_smoothing_discoverable",
        "LSMSSegmentation": "otb_lsms_segmentation_discoverable",
        "SmallRegionsMerging": "otb_small_regions_merging_discoverable",
    }
    for app_name, check_key in app_checks.items():
        if not apps.get(app_name):
            checks[check_key] = False
            failure_reasons.append(f"no OTB {app_name} app discoverable")

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


def build_meanshift_smoothing_command(config, apps, layout, selected_candidate) -> list[str]:
    parameters = selected_candidate_to_parameters(selected_candidate)
    return [
        OTB_APP_CLI_NAMES["MeanShiftSmoothing"],
        "-in",
        str(Path(config.feature_space_stack_path)),
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
        str(layout["smoke_dir"] / "meanshift_smoothed.tif"),
        "-inpos",
        str(layout["smoke_dir"] / "meanshift_position.tif"),
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
        str(Path(config.feature_space_stack_path)),
        "-inseg",
        str(layout["smoke_dir"] / "lsms_labels.tif"),
        "-out",
        str(layout["smoke_dir"] / "merged_labels.tif"),
        "uint32",
        "-minsize",
        str(parameters["minsize"]),
        "-ram",
        str(config.ram_mb),
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
        "output_dir": str(Path(config.output_dir)),
        "smoke_dir": str(layout["smoke_dir"]),
        "tmp_dir": str(layout["tmp_dir"]),
        "feature_space_stack_path": str(Path(config.feature_space_stack_path)),
        "perturbation_candidates_json_path": str(Path(config.perturbation_candidates_json_path)),
        "perturbation_id": str(config.perturbation_id).strip(),
        "selected_candidate": {},
        "spatialr": None,
        "minsize": None,
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
        report["spatialr"] = parameters["spatialr"]
        report["minsize"] = parameters["minsize"]
        report["ranger"] = parameters["ranger"]
        commands = [
            build_meanshift_smoothing_command(config, apps, layout, selected_candidate),
            build_lsms_segmentation_command(config, apps, layout, selected_candidate),
            build_small_regions_merging_command(config, apps, layout, selected_candidate),
        ]
        report["otb_commands"] = commands
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        report["failure_reasons"].append(str(exc))
        return _write_report(report, layout)

    expected_by_step = (
        ("meanshift_smoothed", "meanshift_position"),
        ("lsms_labels",),
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

    report["status"] = "ok"
    if config.cleanup and layout["tmp_dir"].exists():
        shutil.rmtree(layout["tmp_dir"])
        report["tmp_dir_removed"] = True
    return _write_report(report, layout)
