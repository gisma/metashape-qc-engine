"""Metashape GUI menu launcher for the metashape-qc command line tool."""

from __future__ import annotations

import datetime as _datetime
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys
from typing import Callable, Iterable, List, Optional, Sequence

try:
    import Metashape  # type: ignore
except Exception:  # pragma: no cover - exercised outside Metashape.
    class _FallbackApp:
        def addMenuItem(self, path: str, callback: Callable[[], None]) -> None:
            print("Metashape menu registration unavailable: %s" % path)

    class _FallbackMetashape:
        app = _FallbackApp()

    Metashape = _FallbackMetashape()  # type: ignore


CONFIG_PATH = Path.home() / ".config" / "metashape-qc-engine" / "gui_config.json"
LOG_DIR = Path.home() / "tmp" / "metashape_qc_gui_logs"
MENU_GROUP = "Metashape QC Engine"
CLI_NAME = "metashape-qc"
DEFAULT_PROJECT_CRS_SENTINEL = "USER_MUST_SET_PROJECT_CRS"
DEFAULT_CAMERA_CRS = "EPSG::4326"

CONFIG_KEYS = (
    "metashape_qc_executable",
    "repository_root",
    "default_output_root",
    "metashape_dir",
    "qgis_executable",
    "recent_run_dir",
    "recent_image_dir",
    "default_project_crs",
    "default_camera_crs",
)

NEUTRAL_PRESET_NAMES = {
    "rgb_mesh_ortho_fast_screening_v1.json",
    "rgb_mesh_ortho_reference_v1.json",
    "rgb_mesh_ortho_alignment_sensitivity_v1.json",
}

WORKFLOW_ACTION_NAMES = {
    "generic_ortho_resolution_probe_v1.json",
    "rgb_mesh_ortho_resolution_sensitivity_v1.json",
}

_FORBIDDEN_PARTS = (
    ("m", "of"),
    ("M", "OF"),
    ("Franzosen", "wiese"),
    ("franzosen", "wiese"),
    ("forest", "_knoll"),
    ("test", "_mesh"),
    ("/datadisk/data/uav/", "M", "OF"),
)


def _app() -> object:
    return getattr(Metashape, "app", None)


def message(text: str) -> None:
    app = _app()
    if app is not None and hasattr(app, "messageBox"):
        try:
            app.messageBox(str(text))
            return
        except Exception as exc:
            print("Metashape messageBox failed: %s" % exc)
    print(str(text))


def _dialog_method(name: str) -> Callable[..., str]:
    app = _app()
    method = getattr(app, name, None) if app is not None else None
    if not callable(method):
        raise RuntimeError("Metashape dialog method unavailable: %s" % name)
    return method


def get_string(label: str, default: str = "") -> str:
    method = _dialog_method("getString")
    try:
        value = method(label, default)
    except TypeError:
        value = method(label)
    return "" if value is None else str(value)


def get_existing_directory(label: str, default: str = "") -> str:
    method = _dialog_method("getExistingDirectory")
    try:
        value = method(label, default)
    except TypeError:
        value = method(label)
    return "" if value is None else str(value)


def get_open_file_name(label: str, default: str = "") -> str:
    method = _dialog_method("getOpenFileName")
    try:
        value = method(label, default)
    except TypeError:
        value = method(label)
    return "" if value is None else str(value)


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return _empty_config()
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        message("Could not read launcher config:\n%s\n\nUsing empty values." % exc)
        return _empty_config()
    config = _empty_config()
    if isinstance(data, dict):
        for key in CONFIG_KEYS:
            value = data.get(key, "")
            config[key] = "" if value is None else str(value)
    return config


def save_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    clean = {key: str(config.get(key, "")) for key in CONFIG_KEYS}
    CONFIG_PATH.write_text(json.dumps(clean, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _empty_config() -> dict:
    config = {key: "" for key in CONFIG_KEYS}
    config["default_project_crs"] = DEFAULT_PROJECT_CRS_SENTINEL
    config["default_camera_crs"] = DEFAULT_CAMERA_CRS
    return config


def _cli_executable(config: dict) -> str:
    return config.get("metashape_qc_executable") or CLI_NAME


def _repo_root(config: dict) -> Optional[Path]:
    value = config.get("repository_root", "").strip()
    if not value:
        return None
    return Path(value).expanduser()


def _contains_forbidden_token(path: Path) -> bool:
    text = str(path)
    try:
        text += "\n" + path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        pass
    for pieces in _FORBIDDEN_PARTS:
        if "".join(pieces) in text:
            return True
    return False


def _discover_json_files(config: dict, relative_dir: str, allowed_names: Iterable[str]) -> List[Path]:
    repo = _repo_root(config)
    if repo is None:
        return []
    root = repo / relative_dir
    if not root.is_dir():
        return []
    allowed = set(allowed_names)
    files = []
    for path in sorted(root.glob("*.json")):
        if path.name not in allowed:
            continue
        if _contains_forbidden_token(path):
            continue
        files.append(path)
    return files


def neutral_presets(config: dict) -> List[Path]:
    return _discover_json_files(config, "config/experiments/presets", NEUTRAL_PRESET_NAMES)


def workflow_actions(config: dict) -> List[Path]:
    return _discover_json_files(config, "config/experiments/workflows", WORKFLOW_ACTION_NAMES)


def _choose_from_list(title: str, items: Sequence[Path]) -> Optional[Path]:
    if not items:
        message("%s: no eligible files found. Configure repository_root first." % title)
        return None
    numbered = ["%d: %s" % (index + 1, item.name) for index, item in enumerate(items)]
    raw = get_string("%s\n%s\nEnter number:" % (title, "\n".join(numbered)), "1").strip()
    try:
        index = int(raw) - 1
    except ValueError:
        message("Invalid selection: %s" % raw)
        return None
    if index < 0 or index >= len(items):
        message("Selection out of range: %s" % raw)
        return None
    return items[index]


def _parse_min_int(raw: str, minimum: int, label: str) -> Optional[int]:
    try:
        value = int(str(raw).strip())
    except ValueError:
        message("%s must be an integer." % label)
        return None
    if value < minimum:
        message("%s must be at least %d." % (label, minimum))
        return None
    return value


def _valid_project_crs(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    return stripped != DEFAULT_PROJECT_CRS_SENTINEL


def _quote_command(args: Sequence[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in args)


def _log_path(prefix: str) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return LOG_DIR / ("%s_%s.log" % (prefix, stamp))


def launch_command(args: Sequence[str], log_prefix: str) -> None:
    log_path = _log_path(log_prefix)
    display = _quote_command(args)
    message("Launching command:\n%s\n\nLog:\n%s" % (display, log_path))
    try:
        log_handle = log_path.open("ab")
        log_handle.write(("Command: %s\n\n" % display).encode("utf-8"))
        process = subprocess.Popen(
            [str(part) for part in args],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
    except Exception as exc:
        message("Failed to launch command:\n%s\n\n%s" % (display, exc))
        return
    message("Started process %s.\nLog:\n%s" % (process.pid, log_path))


def configure_launcher() -> None:
    config = load_config()
    fields = (
        ("metashape_qc_executable", "metashape-qc executable"),
        ("repository_root", "Repository root"),
        ("default_output_root", "Default output root"),
        ("metashape_dir", "Metashape directory"),
        ("qgis_executable", "QGIS executable"),
        ("default_project_crs", "Default project CRS"),
        ("default_camera_crs", "Default camera CRS"),
    )
    for key, label in fields:
        current = config.get(key, "")
        config[key] = get_string(label, current).strip()
    if not config.get("default_project_crs"):
        config["default_project_crs"] = DEFAULT_PROJECT_CRS_SENTINEL
    if not config.get("default_camera_crs"):
        config["default_camera_crs"] = DEFAULT_CAMERA_CRS
    save_config(config)
    message("Launcher config saved:\n%s" % CONFIG_PATH)


def prepare_product_analysis() -> None:
    config = load_config()
    try:
        image_dir = get_existing_directory("Image directory", config.get("recent_image_dir", "")).strip()
        product_id = get_string("Product id", "").strip()
        output_root = get_existing_directory("Output root", config.get("default_output_root", "")).strip()
        preset = _choose_from_list("Preset", neutral_presets(config))
        reps = _parse_min_int(get_string("Reps", "2"), 2, "Reps")
        project_crs = get_string("Project CRS", config.get("default_project_crs", DEFAULT_PROJECT_CRS_SENTINEL)).strip()
        camera_crs = get_string("Camera CRS (optional)", config.get("default_camera_crs", DEFAULT_CAMERA_CRS)).strip()
    except RuntimeError as exc:
        message(str(exc))
        return
    if not image_dir or not product_id or not output_root or preset is None or reps is None:
        message("Prepare cancelled or missing required input.")
        return
    if not _valid_project_crs(project_crs):
        message("Project CRS is required. Configure or enter a real project CRS before preparing.")
        return
    if _contains_forbidden_token(preset):
        message("Selected preset is not eligible for the generic launcher.")
        return
    args = [
        _cli_executable(config),
        "prepare",
        "--image-dir",
        image_dir,
        "--product-id",
        product_id,
        "--preset",
        str(preset),
        "--reps",
        str(reps),
        "--output-root",
        output_root,
        "--factor",
        "project_crs=%s" % project_crs,
    ]
    if camera_crs:
        args.extend(["--factor", "camera_crs=%s" % camera_crs])
    config["recent_image_dir"] = image_dir
    config["default_output_root"] = output_root
    config["default_project_crs"] = project_crs
    config["default_camera_crs"] = camera_crs
    save_config(config)
    launch_command(args, "prepare")


def probe_orthomosaic_sampling() -> None:
    config = load_config()
    try:
        config_yml = get_open_file_name("config.yml", "").strip()
        run_dir = get_existing_directory("Run directory", config.get("recent_run_dir", "")).strip()
        metashape_dir = get_existing_directory("Metashape directory (optional)", config.get("metashape_dir", "")).strip()
    except RuntimeError as exc:
        message(str(exc))
        return
    if not config_yml or not run_dir:
        message("Probe cancelled or missing required input.")
        return
    args = [
        _cli_executable(config),
        "run-analysis",
        config_yml,
        "--reps",
        "1",
        "--run-dir",
        run_dir,
        "--generic-ortho-resolution",
    ]
    if metashape_dir:
        args.extend(["--metashape-dir", metashape_dir])
        config["metashape_dir"] = metashape_dir
    config["recent_run_dir"] = run_dir
    save_config(config)
    launch_command(args, "probe")


def _analysis_command(command_name: str, log_prefix: str) -> None:
    config = load_config()
    try:
        run_dir = get_existing_directory("Run directory", config.get("recent_run_dir", "")).strip()
        reps = _parse_min_int(get_string("Reps", "2"), 2, "Reps")
        metashape_dir = get_existing_directory("Metashape directory (optional)", config.get("metashape_dir", "")).strip()
    except RuntimeError as exc:
        message(str(exc))
        return
    if not run_dir or reps is None:
        message("Analysis cancelled or missing required input.")
        return
    run_path = Path(run_dir).expanduser()
    config_yml = run_path / "config.yml"
    variants_csv = run_path / "variants.csv"
    if not config_yml.exists():
        message("Missing required file:\n%s" % config_yml)
        return
    if not variants_csv.exists():
        message("Missing required file:\n%s" % variants_csv)
        return
    args = [
        _cli_executable(config),
        command_name,
        str(config_yml),
        "--variants",
        str(variants_csv),
        "--reps",
        str(reps),
        "--run-dir",
        str(run_path),
    ]
    if metashape_dir:
        args.extend(["--metashape-dir", metashape_dir])
        config["metashape_dir"] = metashape_dir
    config["recent_run_dir"] = str(run_path)
    save_config(config)
    launch_command(args, log_prefix)


def run_product_analysis() -> None:
    _analysis_command("run-analysis", "run")


def resume_product_analysis() -> None:
    _analysis_command("resume-analysis", "resume")


def evaluate_product_analysis() -> None:
    config = load_config()
    try:
        run_dir = get_existing_directory("Run directory", config.get("recent_run_dir", "")).strip()
    except RuntimeError as exc:
        message(str(exc))
        return
    if not run_dir:
        message("Evaluate cancelled or missing run directory.")
        return
    config["recent_run_dir"] = run_dir
    save_config(config)
    launch_command([_cli_executable(config), "evaluate", run_dir], "evaluate")


def run_resolution_sensitivity() -> None:
    config = load_config()
    text = (
        "Resolution sensitivity is not orchestrated by this first launcher.\n\n"
        "1. Run Probe Orthomosaic Sampling first.\n"
        "2. Use the reported generic value as the first stratum.\n"
        "3. Prepare separate reference runs with one fixed buildOrthomosaic.orthoRes per run."
    )
    repo = _repo_root(config)
    if repo is not None:
        docs_path = repo / "docs" / "presets.md"
        if docs_path.exists():
            text += "\n\nOpening preset notes:\n%s" % docs_path
            message(text)
            open_path(docs_path)
            return
    message(text)


def open_path(path: Path) -> None:
    try:
        system = platform.system().lower()
        if system == "windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif system == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:
        message("Could not open:\n%s\n\n%s" % (path, exc))


def open_run_folder() -> None:
    config = load_config()
    try:
        run_dir = get_existing_directory("Run directory", config.get("recent_run_dir", "")).strip()
    except RuntimeError as exc:
        message(str(exc))
        return
    if not run_dir:
        return
    config["recent_run_dir"] = run_dir
    save_config(config)
    open_path(Path(run_dir).expanduser())


def open_evaluation_report() -> None:
    config = load_config()
    try:
        run_dir = get_existing_directory("Run directory", config.get("recent_run_dir", "")).strip()
    except RuntimeError as exc:
        message(str(exc))
        return
    if not run_dir:
        return
    run_path = Path(run_dir).expanduser()
    candidates = (
        run_path / "stability_union" / "evaluation_report.md",
        run_path / "evaluation_report.md",
    )
    for candidate in candidates:
        if candidate.exists():
            config["recent_run_dir"] = str(run_path)
            save_config(config)
            open_path(candidate)
            return
    message("No evaluation report found in:\n%s" % run_path)


def open_selected_product_trace() -> None:
    config = load_config()
    try:
        run_dir = get_existing_directory("Run directory", config.get("recent_run_dir", "")).strip()
    except RuntimeError as exc:
        message(str(exc))
        return
    if not run_dir:
        return
    run_path = Path(run_dir).expanduser()
    trace = run_path / "selected_product.json"
    if trace.exists():
        config["recent_run_dir"] = str(run_path)
        save_config(config)
        open_path(trace)
        return
    message("No selected product trace found in:\n%s" % run_path)


def _register_menu_item(label: str, callback: Callable[[], None]) -> None:
    app = _app()
    add_menu_item = getattr(app, "addMenuItem", None) if app is not None else None
    if not callable(add_menu_item):
        message("Metashape.app.addMenuItem is unavailable for: %s" % label)
        return
    try:
        add_menu_item("%s/%s" % (MENU_GROUP, label), callback)
    except Exception as exc:
        message("Failed to register menu item %s:\n%s" % (label, exc))


def register_menu() -> None:
    entries = (
        ("Configure Launcher", configure_launcher),
        ("Probe Orthomosaic Sampling", probe_orthomosaic_sampling),
        ("Prepare Product Analysis", prepare_product_analysis),
        ("Run Product Analysis", run_product_analysis),
        ("Resume Product Analysis", resume_product_analysis),
        ("Evaluate Product Analysis", evaluate_product_analysis),
        ("Run Resolution Sensitivity", run_resolution_sensitivity),
        ("Open Run Folder", open_run_folder),
        ("Open Evaluation Report", open_evaluation_report),
        ("Open Selected Product Trace", open_selected_product_trace),
    )
    for label, callback in entries:
        _register_menu_item(label, callback)


register_menu()
