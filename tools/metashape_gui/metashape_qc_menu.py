# Copyright (c) 2026 Chris Reudenbach, Lars Opgenoorth, Christian Mestre Runge
"""Metashape GUI menu launcher for the metashape-qc command line tool."""

from __future__ import annotations

import datetime as _datetime
import csv
import json
import os
from pathlib import Path
import platform
import re
import shlex
import subprocess
import sys
from typing import Callable, Iterable, List, Optional, Sequence, Union

try:
    import Metashape  # type: ignore
except Exception:  # pragma: no cover - exercised outside Metashape.
    class _FallbackApp:
        def addMenuItem(self, path: str, callback: Callable[[], None]) -> None:
            print("Metashape menu registration unavailable: %s" % path)

    class _FallbackMetashape:
        app = _FallbackApp()

    Metashape = _FallbackMetashape()  # type: ignore

try:
    from PySide2 import QtCore, QtWidgets  # type: ignore
except Exception:  # pragma: no cover - depends on Metashape runtime.
    try:
        from PySide6 import QtCore, QtWidgets  # type: ignore
    except Exception:  # pragma: no cover - Qt is optional for py_compile.
        QtCore = None  # type: ignore
        QtWidgets = None  # type: ignore


CONFIG_PATH = Path.home() / ".config" / "metashape-qc-engine" / "gui_config.json"
LOG_DIR = Path.home() / "tmp" / "metashape_qc_gui_logs"
MENU_GROUP = "Metashape QC Engine"
CLI_NAME = "metashape-qc"
DEFAULT_PROJECT_CRS_SENTINEL = "USER_MUST_SET_PROJECT_CRS"
DEFAULT_CAMERA_CRS = "EPSG::4326"
FAST_SCREENING_PRESET_NAME = "rgb_mesh_ortho_fast_screening_v1.json"
RUNTIME_CRS_PATHS = (
    "project_crs",
    "camera_crs",
    "addGCPs.gcp_crs",
)
CRS_VARIANT_COLUMNS = {
    "project_crs",
    "camera_crs",
    "gcp_crs",
    "addGCPs.gcp_crs",
}

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

SUPPORTED_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".png",
    ".dng",
    ".arw",
    ".cr2",
    ".cr3",
    ".nef",
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
        return _default_config(infer_runtime=True)
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        message("Could not read launcher config:\n%s\n\nUsing empty values." % exc)
        return _default_config(infer_runtime=True)
    config = _default_config(infer_runtime=False)
    if isinstance(data, dict):
        for key in CONFIG_KEYS:
            value = data.get(key, "")
            config[key] = "" if value is None else str(value)
    if not config.get("default_project_crs"):
        config["default_project_crs"] = DEFAULT_PROJECT_CRS_SENTINEL
    if not config.get("default_camera_crs"):
        config["default_camera_crs"] = DEFAULT_CAMERA_CRS
    return config


def save_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    clean = {key: str(config.get(key, "")) for key in CONFIG_KEYS}
    CONFIG_PATH.write_text(json.dumps(clean, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _default_config(infer_runtime: bool = False) -> dict:
    config = {key: "" for key in CONFIG_KEYS}
    config["default_project_crs"] = DEFAULT_PROJECT_CRS_SENTINEL
    config["default_camera_crs"] = DEFAULT_CAMERA_CRS
    if infer_runtime:
        repo = Path(__file__).resolve().parents[2]
        config["repository_root"] = str(repo)
        local_cli = repo / ".venv" / "bin" / CLI_NAME
        config["metashape_qc_executable"] = str(local_cli) if local_cli.exists() else CLI_NAME
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


def normalize_crs(value: str, allow_empty: bool = False) -> str:
    stripped = str(value).strip()
    if not stripped:
        return "" if allow_empty else ""
    if stripped == DEFAULT_PROJECT_CRS_SENTINEL:
        return stripped
    if stripped.isdigit():
        return "EPSG::%s" % stripped
    upper = stripped.upper()
    if upper.startswith("EPSG::"):
        return "EPSG::%s" % stripped[6:].strip()
    if upper.startswith("EPSG:"):
        return "EPSG::%s" % stripped[5:].strip()
    return stripped


def _metashape_coordinate_system(value: str) -> object:
    constructor = getattr(Metashape, "CoordinateSystem", None)
    if not callable(constructor):
        return None
    return constructor(value)


def get_current_metashape_project_crs() -> str:
    app = _app()
    document = getattr(app, "document", None) if app is not None else None
    chunk = getattr(document, "chunk", None) if document is not None else None
    crs = getattr(chunk, "crs", None) if chunk is not None else None
    if crs is None:
        return ""
    for attr in ("auth_id", "authority"):
        value = getattr(crs, attr, None)
        if callable(value):
            try:
                value = value()
            except Exception:
                value = None
        if value:
            return normalize_crs(str(value), allow_empty=True)
    text = str(crs).strip()
    return normalize_crs(text, allow_empty=True) if text else ""


def validate_crs_for_metashape(value: str, label: str, allow_empty: bool = False) -> str:
    normalized = normalize_crs(value, allow_empty=allow_empty)
    if not normalized:
        if allow_empty:
            return ""
        raise ValueError("%s is required." % label)
    if normalized == DEFAULT_PROJECT_CRS_SENTINEL:
        raise ValueError("%s must be set to a real CRS." % label)
    try:
        _metashape_coordinate_system(normalized)
    except Exception as exc:
        raise ValueError("%s is not accepted by Metashape: %s\n%s" % (label, normalized, exc))
    return normalized


def validate_project_crs_for_metashape(value: str) -> str:
    return validate_crs_for_metashape(value, "Project CRS", allow_empty=False)


def _prefill_project_crs(config: dict) -> str:
    configured = normalize_crs(config.get("default_project_crs", ""), allow_empty=True)
    if configured and configured != DEFAULT_PROJECT_CRS_SENTINEL:
        return configured
    return get_current_metashape_project_crs()


def _strip_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] in ("'", '"') and value[-1] == value[0]:
        try:
            parsed = json.loads(value) if value[0] == '"' else value[1:-1]
            return str(parsed)
        except Exception:
            return value[1:-1]
    return value


def read_config_crs_values(config_yml_path: Union[str, Path]) -> dict:
    path = Path(config_yml_path).expanduser()
    values = {}
    stack = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw_line = line.rstrip("\n")
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#") or ":" not in stripped:
                continue
            indent = len(raw_line) - len(raw_line.lstrip(" "))
            while stack and indent <= stack[-1][0]:
                stack.pop()
            key, raw = stripped.split(":", 1)
            key = key.strip()
            full_key = ".".join([item[1] for item in stack] + [key])
            raw_value = raw.split("#", 1)[0]
            if raw_value.strip():
                if full_key in set(RUNTIME_CRS_PATHS) | {"photo_path", "output_path", "project_path"}:
                    values[full_key] = _strip_scalar(raw_value)
                if key in {"photo_path", "output_path", "project_path"}:
                    values[key] = _strip_scalar(raw_value)
            else:
                stack.append((indent, key))
    return values


def find_runtime_crs_values(config_yml_path: Union[str, Path]) -> dict:
    values = read_config_crs_values(config_yml_path)
    return {path: values.get(path, "") for path in RUNTIME_CRS_PATHS if path in values}


def _integrity_error(title: str, lines: Sequence[str]) -> None:
    message("%s\n\n%s" % (title, "\n".join(str(line) for line in lines)))


def _config_crs_error(
    config_yml: Path,
    key_path: str,
    expected: str,
    actual: str,
    prepare_log_path: Union[str, Path],
    reason: str,
) -> RuntimeError:
    return RuntimeError(
        "CRS integrity check failed\n"
        "Reason: %s\n"
        "config path: %s\n"
        "config key path: %s\n"
        "expected value: %s\n"
        "actual value: %s\n"
        "prepare log path: %s"
        % (reason, config_yml, key_path, expected or "(valid CRS)", actual or "(empty)", prepare_log_path)
    )


def assert_generated_config_crs(
    config_yml: Union[str, Path],
    expected_project_crs: str,
    expected_camera_crs_or_empty: str,
    prepare_log_path: Union[str, Path],
    expected_gcp_crs_or_empty: str = "",
) -> dict:
    path = Path(config_yml).expanduser()
    if not path.is_file():
        raise RuntimeError("generated config.yml does not exist or is not a file: %s" % path)
    values = read_config_crs_values(path)
    runtime_values = find_runtime_crs_values(path)
    actual_project = normalize_crs(runtime_values.get("project_crs", ""), allow_empty=True)
    actual_camera = normalize_crs(runtime_values.get("camera_crs", ""), allow_empty=True)
    actual_gcp = normalize_crs(runtime_values.get("addGCPs.gcp_crs", ""), allow_empty=True)
    expected_project = validate_project_crs_for_metashape(expected_project_crs)
    expected_camera = normalize_crs(expected_camera_crs_or_empty, allow_empty=True)
    expected_gcp = normalize_crs(expected_gcp_crs_or_empty, allow_empty=True) or expected_project
    if not actual_project or actual_project == DEFAULT_PROJECT_CRS_SENTINEL:
        raise _config_crs_error(path, "project_crs", expected_project, actual_project, prepare_log_path, "missing or unset project CRS")
    if actual_project != expected_project:
        raise _config_crs_error(path, "project_crs", expected_project, actual_project, prepare_log_path, "project CRS mismatch")
    validate_project_crs_for_metashape(actual_project)
    if expected_camera and actual_camera != expected_camera:
        raise _config_crs_error(path, "camera_crs", expected_camera, actual_camera, prepare_log_path, "camera CRS mismatch")
    if expected_camera:
        validate_crs_for_metashape(actual_camera, "Camera CRS", allow_empty=False)
    if "addGCPs.gcp_crs" in runtime_values:
        if not actual_gcp or actual_gcp == DEFAULT_PROJECT_CRS_SENTINEL:
            raise _config_crs_error(path, "addGCPs.gcp_crs", expected_gcp, actual_gcp, prepare_log_path, "missing or unset GCP CRS")
        if actual_gcp != expected_gcp:
            raise _config_crs_error(path, "addGCPs.gcp_crs", expected_gcp, actual_gcp, prepare_log_path, "GCP CRS mismatch")
        try:
            validate_crs_for_metashape(actual_gcp, "GCP CRS", allow_empty=False)
        except ValueError as exc:
            raise _config_crs_error(path, "addGCPs.gcp_crs", expected_gcp, actual_gcp, prepare_log_path, str(exc))
    return values


def _same_resolved_path(left: Union[str, Path], right: Union[str, Path]) -> bool:
    return Path(left).expanduser().resolve(strict=False) == Path(right).expanduser().resolve(strict=False)


def assert_generated_variants_integrity(
    variants_csv: Union[str, Path],
    expected_project_crs: str,
    expected_camera_crs_or_empty: str,
    image_dir: Union[str, Path],
    output_root: Union[str, Path],
    preset_dir: Union[str, Path],
    prepare_log_path: Union[str, Path],
    expected_gcp_crs_or_empty: str = "",
) -> None:
    path = Path(variants_csv).expanduser()
    if not path.is_file():
        raise RuntimeError("variants.csv does not exist or is not a file: %s" % path)
    expected_project = normalize_crs(expected_project_crs, allow_empty=True)
    expected_camera = normalize_crs(expected_camera_crs_or_empty, allow_empty=True)
    expected_gcp = normalize_crs(expected_gcp_crs_or_empty, allow_empty=True) or expected_project
    expected_by_column = {
        "project_crs": expected_project,
        "camera_crs": expected_camera,
        "gcp_crs": expected_gcp,
        "addGCPs.gcp_crs": expected_gcp,
    }
    try:
        handle = path.open("r", encoding="utf-8", newline="")
    except OSError as exc:
        raise RuntimeError("variants.csv is not readable: %s\n%s" % (path, exc))
    with handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        for row_number, row in enumerate(reader, start=2):
            for column in fieldnames:
                column_lower = column.lower()
                is_crs_column = column in CRS_VARIANT_COLUMNS or "crs" in column_lower or "coordinate_system" in column_lower
                if not is_crs_column:
                    continue
                actual = normalize_crs(row.get(column, ""), allow_empty=True)
                if not actual:
                    raise RuntimeError(
                        "variants.csv integrity check failed\nColumn: %s\nRow: %d\nExpected: valid CRS\nActual: (empty)\nvariants.csv: %s\nprepare log: %s"
                        % (column, row_number, path, prepare_log_path)
                    )
                validate_crs_for_metashape(actual, "variants.csv %s row %d" % (column, row_number), allow_empty=False)
                expected = expected_by_column.get(column)
                if expected and actual != expected:
                    raise RuntimeError(
                        "variants.csv integrity check failed\nColumn: %s\nRow: %d\nExpected: %s\nActual: %s\nvariants.csv: %s\nprepare log: %s"
                        % (column, row_number, expected, actual, path, prepare_log_path)
                    )
            for column, raw in row.items():
                if raw is None or not raw.strip():
                    continue
                column_lower = column.lower()
                if not any(token in column_lower for token in ("image_dir", "photo_path", "input_path")):
                    continue
                candidate = Path(raw).expanduser()
                if _same_resolved_path(candidate, output_root) or _same_resolved_path(candidate, preset_dir):
                    raise RuntimeError(
                        "variants.csv integrity check failed\nColumn: %s\nRow: %d\nOffending path: %s\nvariants.csv: %s\nprepare log: %s"
                        % (column, row_number, candidate, path, prepare_log_path)
                    )
                if column_lower in {"image_dir", "photo_path"} and not candidate.is_dir():
                    raise RuntimeError(
                        "variants.csv integrity check failed\nColumn: %s\nRow: %d\nMissing image directory: %s\nvariants.csv: %s\nprepare log: %s"
                        % (column, row_number, candidate, path, prepare_log_path)
                    )


def assert_prepare_outputs(
    run_dir: Path,
    expected_project_crs: str,
    expected_camera_crs_or_empty: str,
    image_dir: str,
    output_root: str,
    preset: Path,
    prepare_log_path: Path,
    expected_gcp_crs_or_empty: str = "",
) -> None:
    config_yml = run_dir / "config.yml"
    variants_csv = run_dir / "variants.csv"
    if config_yml.parent.resolve(strict=False) != run_dir.resolve(strict=False):
        raise RuntimeError("run_dir does not match config.yml directory: %s" % config_yml)
    if variants_csv.parent.resolve(strict=False) != run_dir.resolve(strict=False):
        raise RuntimeError("run_dir does not match variants.csv directory: %s" % variants_csv)
    if preset.name not in NEUTRAL_PRESET_NAMES:
        raise RuntimeError("Preset path is not one of the allowed neutral presets: %s" % preset)
    if _same_resolved_path(output_root, image_dir) or _same_resolved_path(output_root, preset.parent):
        raise RuntimeError("Output root must not be the image folder or preset directory: %s" % output_root)
    values = assert_generated_config_crs(
        config_yml,
        expected_project_crs,
        expected_camera_crs_or_empty,
        prepare_log_path,
        expected_gcp_crs_or_empty,
    )
    photo_path = values.get("photo_path", "")
    if photo_path and _same_resolved_path(Path(photo_path), output_root):
        raise RuntimeError("config.yml photo_path points at output_root: %s" % output_root)
    assert_generated_variants_integrity(
        variants_csv,
        expected_project_crs,
        expected_camera_crs_or_empty,
        image_dir,
        output_root,
        preset.parent,
        prepare_log_path,
        expected_gcp_crs_or_empty,
    )


def _has_supported_image(path: Path) -> bool:
    if not path.is_dir():
        return False
    for child in path.rglob("*"):
        if child.is_file() and child.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS:
            return True
    return False


def _quote_command(args: Sequence[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in args)


def _prepare_args(
    config: dict,
    image_dir: str,
    product_id: str,
    preset: Path,
    reps: int,
    output_root: str,
    project_crs: str,
    camera_crs: str,
    gcp_crs: str = "",
    overwrite: bool = False,
) -> List[str]:
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
    args.extend(["--factor", "addGCPs.gcp_crs=%s" % (gcp_crs or project_crs)])
    if overwrite:
        args.append("--overwrite")
    return args


def _log_path(prefix: str) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return LOG_DIR / ("%s_%s.log" % (prefix, stamp))


def _qt_exec(dialog: object) -> int:
    exec_method = getattr(dialog, "exec", None)
    if callable(exec_method):
        result = exec_method()
    else:
        result = dialog.exec_()
    try:
        return int(result)
    except TypeError:
        return int(getattr(result, "value", 0))


def _confirm_launch(display: str, log_path: Path) -> bool:
    if QtWidgets is not None:
        app = QtWidgets.QApplication.instance()
        if app is None:
            app = QtWidgets.QApplication([])
        dialog = QtWidgets.QDialog()
        dialog.setWindowTitle("Launch Command")
        dialog.resize(760, 360)
        layout = QtWidgets.QVBoxLayout(dialog)
        label = QtWidgets.QLabel("Launch this command?")
        label.setWordWrap(True)
        layout.addWidget(label)
        command_text = QtWidgets.QPlainTextEdit()
        command_text.setReadOnly(True)
        command_text.setPlainText("%s\n\nLog:\n%s" % (display, log_path))
        layout.addWidget(command_text)
        buttons = QtWidgets.QDialogButtonBox()
        accept_role = getattr(QtWidgets.QDialogButtonBox, "AcceptRole", None)
        reject_role = getattr(QtWidgets.QDialogButtonBox, "RejectRole", None)
        if accept_role is None:
            accept_role = QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole
        if reject_role is None:
            reject_role = QtWidgets.QDialogButtonBox.ButtonRole.RejectRole
        launch_button = buttons.addButton("Launch", accept_role)
        buttons.addButton("Cancel", reject_role)
        layout.addWidget(buttons)
        launch_button.clicked.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        accepted = getattr(QtWidgets.QDialog, "Accepted", 1)
        try:
            accepted_value = int(accepted)
        except TypeError:
            accepted_value = int(getattr(accepted, "value", 1))
        return _qt_exec(dialog) == accepted_value
    try:
        confirmation = get_string(
            "Type start to launch this command:\n%s\nLog:\n%s" % (display, log_path),
            "",
        )
    except RuntimeError as exc:
        message(str(exc))
        return False
    return confirmation.strip().lower() == "start"


def run_short_command(args: Sequence[str], log_prefix: str) -> dict:
    log_path = _log_path(log_prefix)
    display = _quote_command(args)
    result = {"returncode": 1, "log_path": str(log_path), "command": display}
    try:
        completed = subprocess.run(
            [str(part) for part in args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        output = completed.stdout or b""
        with log_path.open("wb") as log_handle:
            log_handle.write(("Command: %s\n\n" % display).encode("utf-8"))
            log_handle.write(output)
        result["returncode"] = int(completed.returncode)
    except Exception as exc:
        with log_path.open("wb") as log_handle:
            log_handle.write(("Command: %s\n\n" % display).encode("utf-8"))
            log_handle.write(("Failed to run command: %s\n" % exc).encode("utf-8"))
        result["error"] = str(exc)
    return result


def launch_command(args: Sequence[str], log_prefix: str, confirm: bool = True) -> Union[dict, bool]:
    log_path = _log_path(log_prefix)
    display = _quote_command(args)
    if confirm and not _confirm_launch(display, log_path):
        message("Launch cancelled.")
        return False
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
        return {"success": False, "log_path": str(log_path), "command": display, "error": str(exc)}
    message("Started process %s.\nLog:\n%s" % (process.pid, log_path))
    return {
        "success": True,
        "pid": process.pid,
        "log_path": str(log_path),
        "command": display,
        "process": process,
    }


def detect_prepared_run_dir(output_root: str, product_id: str, after_timestamp: float) -> Optional[Path]:
    root = Path(output_root).expanduser()
    if not root.is_dir():
        return None
    candidates = []
    for path in root.rglob("*"):
        if not path.is_dir():
            continue
        if product_id and not path.name.startswith(product_id):
            continue
        config_yml = path / "config.yml"
        variants_csv = path / "variants.csv"
        if not config_yml.exists() or not variants_csv.exists():
            continue
        newest_mtime = max(path.stat().st_mtime, config_yml.stat().st_mtime, variants_csv.stat().st_mtime)
        if newest_mtime + 1 < after_timestamp:
            continue
        candidates.append((newest_mtime, path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _fast_screening_preset(config: dict) -> Optional[Path]:
    for preset in neutral_presets(config):
        if preset.name == FAST_SCREENING_PRESET_NAME:
            return preset
    return None


def start_generic_sampling_probe(
    config: dict,
    config_yml: Union[str, Path],
    run_dir: Union[str, Path],
    confirm: bool = False,
    overwrite: bool = False,
) -> Union[dict, bool]:
    args = [
        _cli_executable(config),
        "run-analysis",
        str(config_yml),
        "--reps",
        "1",
        "--run-dir",
        str(run_dir),
        "--generic-ortho-resolution",
    ]
    if overwrite:
        args.append("--overwrite")
    metashape_dir = config.get("metashape_dir", "").strip()
    if metashape_dir:
        args.extend(["--metashape-dir", metashape_dir])
    return launch_command(args, "generic_sampling_probe", confirm=confirm)


def _tail_text(path: Path, max_chars: int = 6000) -> str:
    if not path.exists():
        return "Waiting for log output..."
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return "Could not read log file: %s" % exc
    return text[-max_chars:]


def _tail_lines(path: Path, max_lines: int = 80) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        return "Could not read inner launcher.log: %s" % exc
    return "\n".join(lines[-max_lines:])


def _detect_inner_launcher_log(text: str) -> Optional[Path]:
    matches = re.findall(r"failed\.\s+See:\s+([^\r\n]+launcher\.log)", text)
    for match in reversed(matches):
        path = Path(match.strip()).expanduser()
        if path.is_file():
            return path
    return None


def _parse_field_screening_block(text: str) -> Optional[dict]:
    match = re.search(
        r"FIELD SCREENING RESULT\s*(.*?)\s*END FIELD SCREENING RESULT",
        text,
        flags=re.DOTALL,
    )
    if not match:
        return None
    values = {}
    for raw_line in match.group(1).splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        values[key.strip()] = value.strip()
    if not values.get("status"):
        return None
    return values


def _load_field_screening_summary(run_dir: Path, log_text: str) -> Optional[dict]:
    summary_json = run_dir / "field_screening_summary.json"
    if summary_json.exists():
        try:
            data = json.loads(summary_json.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("status"):
                return {str(key): str(value) for key, value in data.items()}
        except Exception:
            pass

    summary_txt = run_dir / "field_screening_summary.txt"
    if summary_txt.exists():
        try:
            parsed = _parse_field_screening_block(
                summary_txt.read_text(encoding="utf-8", errors="replace")
            )
            if parsed:
                return parsed
        except Exception:
            pass

    return _parse_field_screening_block(log_text)


def _field_screening_panel_text(summary: dict) -> str:
    lines = [
        "FIELD SCREENING RESULT",
        "Status: %s" % summary.get("status", "UNKNOWN"),
        "Orthomosaic: %s" % summary.get("orthomosaic", "UNKNOWN"),
        "Alignment: %s" % summary.get("alignment", "UNKNOWN"),
        "Technical sampling: %s m/px"
        % summary.get("technical_sampling_m_per_px", "unavailable"),
        "Recommended sampling: %s m/px"
        % summary.get("recommended_sampling_m_per_px", "unavailable"),
        "Interpretation: %s" % summary.get("interpretation", ""),
    ]
    return "\n".join(lines)


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
    else:
        try:
            config["default_project_crs"] = validate_project_crs_for_metashape(config["default_project_crs"])
        except ValueError as exc:
            message(str(exc))
            return
    if not config.get("default_camera_crs"):
        config["default_camera_crs"] = DEFAULT_CAMERA_CRS
    else:
        try:
            config["default_camera_crs"] = validate_crs_for_metashape(
                config["default_camera_crs"],
                "Camera CRS",
                allow_empty=True,
            ) or DEFAULT_CAMERA_CRS
        except ValueError as exc:
            message(str(exc))
            return
    save_config(config)
    message("Launcher config saved:\n%s" % CONFIG_PATH)


def launcher_settings() -> None:
    if QtWidgets is None:
        message(
            "Launcher Settings dialog is unavailable because Qt bindings are not available in this Metashape Python environment."
        )
        return
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    dialog = LauncherSettingsDialog(load_config())
    _qt_exec(dialog)


def show_current_config() -> None:
    config = load_config()
    lines = ["Config path: %s" % CONFIG_PATH, ""]
    for key in CONFIG_KEYS:
        lines.append("%s: %s" % (key, config.get(key, "")))
    message("\n".join(lines))


def _show_loaded_presets_serial() -> None:
    config = load_config()
    repo = _repo_root(config)
    presets = neutral_presets(config)
    lines = ["Repository root: %s" % (repo if repo is not None else "")]
    if presets:
        lines.append("")
        lines.append("Eligible neutral presets:")
        lines.extend(path.name for path in presets)
    else:
        lines.append("")
        lines.append("No eligible neutral presets found. repository_root likely needs configuration.")
    message("\n".join(lines))


def show_loaded_presets() -> None:
    if QtWidgets is None:
        message(
            "Loaded Presets dialog is unavailable because Qt bindings are not available in this Metashape Python environment."
        )
        return
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    config = load_config()
    dialog = LoadedPresetsDialog(config, neutral_presets(config))
    _qt_exec(dialog)


_PRESET_LABELS = {
    "rgb_mesh_ortho_fast_screening_v1.json": "Fast screening",
    "rgb_mesh_ortho_reference_v1.json": "Reference analysis",
    "rgb_mesh_ortho_alignment_sensitivity_v1.json": "Alignment sensitivity",
}


def _preset_default_reps(preset_name: str) -> int:
    if preset_name == "rgb_mesh_ortho_fast_screening_v1.json":
        return 3
    return 5


if QtWidgets is not None:

    class LauncherSettingsDialog(QtWidgets.QDialog):  # type: ignore[misc]
        def __init__(self, config: dict) -> None:
            super().__init__()
            self.config = dict(config)
            self.setWindowTitle("Launcher Settings")
            self.resize(760, 360)

            self.edits = {}
            root_layout = QtWidgets.QVBoxLayout(self)
            form = QtWidgets.QFormLayout()
            root_layout.addLayout(form)

            self._add_file_row(form, "metashape_qc_executable")
            self._add_directory_row(form, "repository_root")
            self._add_directory_row(form, "default_output_root")
            self._add_directory_row(form, "metashape_dir")
            self._add_file_row(form, "qgis_executable")
            self._add_text_row(form, "default_project_crs")
            self._add_text_row(form, "default_camera_crs")

            actions = QtWidgets.QDialogButtonBox()
            save_role = getattr(QtWidgets.QDialogButtonBox, "AcceptRole", None)
            reject_role = getattr(QtWidgets.QDialogButtonBox, "RejectRole", None)
            if save_role is None:
                save_role = QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole
            if reject_role is None:
                reject_role = QtWidgets.QDialogButtonBox.ButtonRole.RejectRole
            save_button = actions.addButton("Save", save_role)
            actions.addButton("Cancel", reject_role)
            root_layout.addWidget(actions)

            save_button.clicked.connect(lambda *_args: self._save())
            actions.rejected.connect(self.reject)

        def _add_text_row(self, form: object, key: str) -> None:
            edit = QtWidgets.QLineEdit()
            edit.setText(self.config.get(key, ""))
            self.edits[key] = edit
            form.addRow(key, edit)

        def _add_file_row(self, form: object, key: str) -> None:
            edit = QtWidgets.QLineEdit()
            edit.setText(self.config.get(key, ""))
            self.edits[key] = edit
            row = QtWidgets.QWidget()
            layout = QtWidgets.QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(edit)
            button = QtWidgets.QPushButton("Browse")
            button.clicked.connect(lambda *_args, field=edit: self._browse_file(field))
            layout.addWidget(button)
            form.addRow(key, row)

        def _add_directory_row(self, form: object, key: str) -> None:
            edit = QtWidgets.QLineEdit()
            edit.setText(self.config.get(key, ""))
            self.edits[key] = edit
            row = QtWidgets.QWidget()
            layout = QtWidgets.QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(edit)
            button = QtWidgets.QPushButton("Browse")
            button.clicked.connect(lambda *_args, field=edit: self._browse_directory(field))
            layout.addWidget(button)
            form.addRow(key, row)

        def _browse_file(self, edit: object) -> None:
            current = edit.text().strip()
            chosen = QtWidgets.QFileDialog.getOpenFileName(self, "Select file", current)
            if isinstance(chosen, tuple):
                chosen = chosen[0]
            if chosen:
                edit.setText(str(chosen))

        def _browse_directory(self, edit: object) -> None:
            current = edit.text().strip()
            chosen = QtWidgets.QFileDialog.getExistingDirectory(self, "Select directory", current)
            if chosen:
                edit.setText(chosen)

        def _save(self) -> None:
            for key, edit in self.edits.items():
                self.config[key] = edit.text().strip()
            try:
                raw_project = self.config.get("default_project_crs", "")
                project_crs = (
                    validate_project_crs_for_metashape(raw_project)
                    if raw_project.strip()
                    else ""
                )
                camera_crs = validate_crs_for_metashape(
                    self.config.get("default_camera_crs", ""),
                    "Camera CRS",
                    allow_empty=True,
                )
            except ValueError as exc:
                QtWidgets.QMessageBox.critical(self, "Launcher Settings", str(exc))
                return
            self.config["default_project_crs"] = project_crs or DEFAULT_PROJECT_CRS_SENTINEL
            self.config["default_camera_crs"] = camera_crs or DEFAULT_CAMERA_CRS
            save_config(self.config)
            QtWidgets.QMessageBox.information(self, "Launcher Settings", "Launcher settings saved.")
            self.accept()

    class LoadedPresetsDialog(QtWidgets.QDialog):  # type: ignore[misc]
        def __init__(self, config: dict, presets: Sequence[Path]) -> None:
            super().__init__()
            self.setWindowTitle("Loaded Neutral Presets")
            self.resize(680, 420)

            root_layout = QtWidgets.QVBoxLayout(self)
            form = QtWidgets.QFormLayout()
            repo_edit = QtWidgets.QLineEdit()
            repo = _repo_root(config)
            repo_edit.setText(str(repo) if repo is not None else "")
            repo_edit.setReadOnly(True)
            form.addRow("Repository root", repo_edit)
            root_layout.addLayout(form)

            if presets:
                preset_list = QtWidgets.QListWidget()
                for preset in presets:
                    preset_list.addItem(preset.name)
                root_layout.addWidget(preset_list)
            else:
                text = QtWidgets.QPlainTextEdit()
                text.setReadOnly(True)
                text.setPlainText("No eligible neutral presets found. Check repository_root in Launcher Settings.")
                root_layout.addWidget(text)

            actions = QtWidgets.QDialogButtonBox()
            reject_role = getattr(QtWidgets.QDialogButtonBox, "RejectRole", None)
            if reject_role is None:
                reject_role = QtWidgets.QDialogButtonBox.ButtonRole.RejectRole
            close_button = actions.addButton("Close", reject_role)
            close_button.clicked.connect(self.reject)
            root_layout.addWidget(actions)

    class ProcessMonitorDialog(QtWidgets.QDialog):  # type: ignore[misc]
        def __init__(
            self,
            process_label: str,
            process: object,
            command: str,
            current_log: Path,
            run_dir: Path,
            config_yml: Optional[Path] = None,
            variants_csv: Optional[Path] = None,
            prepare_log: Optional[Path] = None,
        ) -> None:
            super().__init__()
            self.process = process
            self.current_log = current_log
            self.inner_log = None
            self.run_dir = run_dir
            self.field_screening_summary = None
            self.setWindowTitle("Metashape QC process monitor")
            self.resize(880, 620)

            layout = QtWidgets.QVBoxLayout(self)
            self.status_label = QtWidgets.QLabel()
            self.status_label.setWordWrap(True)
            layout.addWidget(self.status_label)
            self.field_result_panel = QtWidgets.QLabel()
            self.field_result_panel.setWordWrap(True)
            self.field_result_panel.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            self.field_result_panel.setStyleSheet(
                "QLabel { border: 1px solid #999; padding: 8px; background: #f6f6f6; }"
            )
            self.field_result_panel.hide()
            layout.addWidget(self.field_result_panel)
            self.tail = QtWidgets.QPlainTextEdit()
            self.tail.setReadOnly(True)
            self.tail.setPlainText("Waiting for log output...")
            layout.addWidget(self.tail)
            pid = getattr(process, "pid", "")
            self.details = [
                "Process label: %s" % process_label,
                "PID: %s" % pid,
                "Run directory: %s" % run_dir,
                "config.yml: %s" % (config_yml or ""),
                "variants.csv: %s" % (variants_csv or ""),
                "prepare log path: %s" % (prepare_log or ""),
                "current process log path: %s" % current_log,
                "Command: %s" % command,
            ]

            buttons = QtWidgets.QDialogButtonBox()
            accept_role = getattr(QtWidgets.QDialogButtonBox, "AcceptRole", None)
            action_role = getattr(QtWidgets.QDialogButtonBox, "ActionRole", None)
            if accept_role is None:
                accept_role = QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole
            if action_role is None:
                action_role = QtWidgets.QDialogButtonBox.ButtonRole.ActionRole
            self.ok_button = buttons.addButton("Close", accept_role)
            self.ortho_button = buttons.addButton("Open Ortho Folder", action_role)
            self.summary_button = buttons.addButton("Open Field Screening Summary", action_role)
            self.protocol_button = buttons.addButton("Save Protocol", action_role)
            self.run_button = buttons.addButton("Open Run Folder", action_role)
            self.log_button = buttons.addButton("Open Log Folder", action_role)
            self.inner_log_button = buttons.addButton("Open Inner Log", action_role)
            self.stop_button = buttons.addButton("Stop Process", action_role)
            layout.addWidget(buttons)

            self.ok_button.clicked.connect(self.accept)
            self.ortho_button.clicked.connect(lambda *_args: self._open_ortho_folder())
            self.summary_button.clicked.connect(lambda *_args: self._open_field_summary())
            self.protocol_button.clicked.connect(lambda *_args: self._save_protocol())
            self.run_button.clicked.connect(lambda *_args: open_path(self.run_dir))
            self.log_button.clicked.connect(lambda *_args: open_path(self.current_log.parent))
            self.inner_log_button.clicked.connect(lambda *_args: open_path(self.inner_log) if self.inner_log else None)
            self.stop_button.clicked.connect(lambda *_args: self._stop_process())
            self.ortho_button.hide()
            self.summary_button.hide()
            self.protocol_button.hide()

            self.timer = QtCore.QTimer(self)
            self.timer.timeout.connect(self._refresh)
            self.timer.start(1000)
            self._refresh()

        def _stop_process(self) -> None:
            poll = getattr(self.process, "poll", None)
            return_code = poll() if callable(poll) else None
            if return_code is not None:
                self.stop_button.setEnabled(False)
                self.status_label.setText(
                    "Status: Process has already finished.\n%s" % "\n".join(self.details)
                )
                return
            terminate = getattr(self.process, "terminate", None)
            if callable(terminate):
                terminate()
            self._refresh()

        def _field_summary_path(self) -> Path:
            return self.run_dir / "field_screening_summary.txt"

        def _field_ortho_path(self) -> Optional[Path]:
            if not self.field_screening_summary:
                return None
            raw_path = str(self.field_screening_summary.get("ortho_path", "")).strip()
            if not raw_path or raw_path == "unavailable":
                return None
            path = Path(raw_path).expanduser()
            if path.exists():
                return path
            return None

        def _open_ortho_folder(self) -> None:
            ortho_path = self._field_ortho_path()
            if ortho_path is not None:
                open_path(ortho_path.parent)

        def _open_field_summary(self) -> None:
            summary_path = self._field_summary_path()
            if summary_path.exists():
                open_path(summary_path)

        def _save_protocol(self) -> None:
            if not self.field_screening_summary:
                return
            default_path = self.run_dir / "field_screening_protocol.txt"
            chosen, _selected_filter = QtWidgets.QFileDialog.getSaveFileName(
                self,
                "Save Field Screening Protocol",
                str(default_path),
                "Text files (*.txt);;All files (*)",
            )
            if not chosen:
                return
            try:
                Path(chosen).write_text(
                    _field_screening_panel_text(self.field_screening_summary)
                    + "\n\nRun directory: %s\nLog folder: %s\n"
                    % (self.run_dir, self.current_log.parent),
                    encoding="utf-8",
                )
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "Save Protocol", str(exc))

        def _update_field_result_panel(self, log_text: str) -> None:
            summary = _load_field_screening_summary(self.run_dir, log_text)
            if not summary:
                self.field_screening_summary = None
                self.field_result_panel.hide()
                self.ortho_button.hide()
                self.summary_button.hide()
                self.protocol_button.hide()
                return

            self.field_screening_summary = summary
            self.field_result_panel.setText(_field_screening_panel_text(summary))
            self.field_result_panel.show()

            ortho_path = self._field_ortho_path()
            self.ortho_button.setVisible(ortho_path is not None)
            self.ortho_button.setEnabled(ortho_path is not None)

            summary_path = self._field_summary_path()
            self.summary_button.setVisible(summary_path.exists())
            self.summary_button.setEnabled(summary_path.exists())

            self.protocol_button.setVisible(True)
            self.protocol_button.setEnabled(True)

        def _refresh(self) -> None:
            poll = getattr(self.process, "poll", None)
            return_code = poll() if callable(poll) else None
            if return_code is None:
                status = "Running..."
                self.stop_button.setEnabled(True)
            elif int(return_code) == 0:
                status = "Finished successfully"
                self.stop_button.setEnabled(False)
                self.timer.stop()
            else:
                status = "FAILED with exit code %s" % return_code
                self.stop_button.setEnabled(False)
                self.timer.stop()
            self.ok_button.setEnabled(True)
            self.run_button.setEnabled(self.run_dir.exists())
            self.log_button.setEnabled(True)
            self.inner_log_button.setEnabled(bool(self.inner_log and self.inner_log.exists()))
            self.status_label.setText("Status: %s\n%s" % (status, "\n".join(self.details)))
            scrollbar = self.tail.verticalScrollBar()
            at_bottom = scrollbar.value() >= scrollbar.maximum() - 4
            outer_tail = _tail_text(self.current_log)
            self._update_field_result_panel(outer_tail)
            detected_inner_log = _detect_inner_launcher_log(outer_tail)
            if detected_inner_log is not None:
                self.inner_log = detected_inner_log
            display_tail = outer_tail
            if self.inner_log and self.inner_log.exists():
                display_tail = "%s\n\nInner launcher.log path:\n%s\n\nLast 80 lines from inner launcher.log:\n%s" % (
                    outer_tail,
                    self.inner_log,
                    _tail_lines(self.inner_log, 80),
                )
                self.inner_log_button.setEnabled(True)
            self.tail.setPlainText(display_tail)
            if return_code is None or at_bottom:
                scrollbar.setValue(scrollbar.maximum())

    class ConfigurationCreatedDialog(QtWidgets.QDialog):  # type: ignore[misc]
        def __init__(self, run_dir: Path, config_yml: Path, variants_csv: Path, prepare_log: Path) -> None:
            super().__init__()
            self.run_dir = run_dir
            self.setWindowTitle("Configuration created")
            self.resize(760, 360)
            layout = QtWidgets.QVBoxLayout(self)
            text = QtWidgets.QPlainTextEdit()
            text.setReadOnly(True)
            text.setPlainText(
                "run_dir: %s\nconfig.yml: %s\nvariants.csv: %s\nprepare log: %s"
                % (run_dir, config_yml, variants_csv, prepare_log)
            )
            layout.addWidget(text)
            buttons = QtWidgets.QDialogButtonBox()
            accept_role = getattr(QtWidgets.QDialogButtonBox, "AcceptRole", None)
            action_role = getattr(QtWidgets.QDialogButtonBox, "ActionRole", None)
            if accept_role is None:
                accept_role = QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole
            if action_role is None:
                action_role = QtWidgets.QDialogButtonBox.ButtonRole.ActionRole
            close_button = buttons.addButton("Close", accept_role)
            run_button = buttons.addButton("Open Run Folder", action_role)
            layout.addWidget(buttons)
            close_button.clicked.connect(self.accept)
            run_button.clicked.connect(lambda *_args: open_path(self.run_dir))

    class NewFieldScreeningDialog(QtWidgets.QDialog):  # type: ignore[misc]
        def __init__(self, config: dict) -> None:
            super().__init__()
            self.config = config
            self.setWindowTitle("New Field Screening")
            self.resize(780, 520)

            self.image_dir_edit = QtWidgets.QLineEdit()
            self.image_dir_edit.setText(config.get("recent_image_dir", ""))
            self.product_id_edit = QtWidgets.QLineEdit()
            self.output_root_edit = QtWidgets.QLineEdit()
            self.output_root_edit.setText(config.get("default_output_root", ""))
            self.project_crs_edit = QtWidgets.QLineEdit()
            self.project_crs_edit.setText(_prefill_project_crs(config))
            self.camera_crs_edit = QtWidgets.QLineEdit()
            self.camera_crs_edit.setText(config.get("default_camera_crs", DEFAULT_CAMERA_CRS))
            self.overwrite_checkbox = QtWidgets.QCheckBox("Overwrite existing prepared output")

            root_layout = QtWidgets.QVBoxLayout(self)
            explanation = QtWidgets.QLabel(
                "This runs one dirty first-pass Metashape check and reports alignment/processability "
                "and technical sampling. It does not run stability evaluation."
            )
            explanation.setWordWrap(True)
            root_layout.addWidget(explanation)

            form = QtWidgets.QFormLayout()
            form.addRow("Image folder", self._directory_row(self.image_dir_edit))
            form.addRow("Screening id / product id", self.product_id_edit)
            form.addRow("Output root", self._directory_row(self.output_root_edit))
            form.addRow("Project CRS", self._crs_row(self.project_crs_edit))
            form.addRow("Camera CRS", self.camera_crs_edit)
            form.addRow("", self.overwrite_checkbox)
            root_layout.addLayout(form)

            actions = QtWidgets.QDialogButtonBox()
            accept_role = getattr(QtWidgets.QDialogButtonBox, "AcceptRole", None)
            reject_role = getattr(QtWidgets.QDialogButtonBox, "RejectRole", None)
            if accept_role is None:
                accept_role = QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole
            if reject_role is None:
                reject_role = QtWidgets.QDialogButtonBox.ButtonRole.RejectRole
            start_button = actions.addButton("Start Field Screening", accept_role)
            actions.addButton("Cancel", reject_role)
            root_layout.addWidget(actions)

            start_button.clicked.connect(lambda *_args: self._start())
            actions.rejected.connect(self.reject)

        def _directory_row(self, edit: object) -> object:
            row = QtWidgets.QWidget()
            layout = QtWidgets.QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(edit)
            button = QtWidgets.QPushButton("Browse")
            button.clicked.connect(lambda: self._browse_directory(edit))
            layout.addWidget(button)
            return row

        def _crs_row(self, edit: object) -> object:
            row = QtWidgets.QWidget()
            layout = QtWidgets.QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(edit)
            button = QtWidgets.QPushButton("Use current Metashape CRS")
            button.clicked.connect(lambda *_args: self._use_current_crs(edit))
            layout.addWidget(button)
            return row

        def _use_current_crs(self, edit: object) -> None:
            value = get_current_metashape_project_crs()
            if not value:
                self._show_error("Project CRS", "No usable CRS is available from the current Metashape chunk.")
                return
            edit.setText(value)

        def _browse_directory(self, edit: object) -> None:
            current = edit.text().strip()
            chosen = QtWidgets.QFileDialog.getExistingDirectory(self, "Select directory", current)
            if chosen:
                edit.setText(chosen)

        def _show_error(self, title: str, text: str) -> None:
            QtWidgets.QMessageBox.critical(self, title, text)

        def _start(self) -> None:
            image_dir = self.image_dir_edit.text().strip()
            product_id = self.product_id_edit.text().strip()
            output_root = self.output_root_edit.text().strip()
            try:
                project_crs = validate_project_crs_for_metashape(self.project_crs_edit.text())
                camera_crs = validate_crs_for_metashape(
                    self.camera_crs_edit.text(),
                    "Camera CRS",
                    allow_empty=True,
                )
            except ValueError as exc:
                self._show_error("New Field Screening", str(exc))
                return

            image_path = Path(image_dir).expanduser()
            if not image_path.is_dir():
                self._show_error("New Field Screening", "Image folder does not exist or is not a directory:\n%s" % image_path)
                return
            if not _has_supported_image(image_path):
                self._show_error("New Field Screening", "Image folder contains no supported image files:\n%s" % image_path)
                return
            if not product_id:
                self._show_error("New Field Screening", "Screening id / product id is required.")
                return
            if not output_root:
                self._show_error("New Field Screening", "Output root is required.")
                return
            preset = _fast_screening_preset(self.config)
            if preset is None:
                self._show_error(
                    "New Field Screening",
                    "Fast screening preset not found. Check repository_root in Launcher Settings.",
                )
                return

            overwrite = self.overwrite_checkbox.isChecked()
            start_time = _datetime.datetime.now().timestamp()
            args = _prepare_args(
                self.config,
                image_dir,
                product_id,
                preset,
                1,
                output_root,
                project_crs,
                camera_crs,
                overwrite=overwrite,
            )
            prepare_result = run_short_command(args, "field_screening_prepare")
            prepare_log = Path(str(prepare_result["log_path"]))
            if int(prepare_result.get("returncode", 1)) != 0:
                self._show_error(
                    "Configuration creation failed",
                    "Prepare exited with code %s.\nPrepare log path:\n%s"
                    "\n\nLast log lines:\n%s"
                    % (prepare_result.get("returncode"), prepare_log, _tail_text(prepare_log, 8000)),
                )
                return

            run_dir = detect_prepared_run_dir(output_root, product_id, start_time)
            if run_dir is None:
                self._show_error(
                    "Configuration creation failed",
                    "Prepare completed, but the created run directory containing config.yml and variants.csv was not found.\n"
                    "Prepare log path:\n%s" % prepare_log,
                )
                return

            config_yml = run_dir / "config.yml"
            variants_csv = run_dir / "variants.csv"
            try:
                assert_prepare_outputs(
                    run_dir,
                    project_crs,
                    camera_crs,
                    image_dir,
                    output_root,
                    preset,
                    prepare_log,
                )
            except Exception as exc:
                self._show_error("CRS integrity check failed", str(exc))
                return
            self.config["recent_run_dir"] = str(run_dir)
            self.config["recent_image_dir"] = image_dir
            self.config["default_output_root"] = output_root
            self.config["default_project_crs"] = project_crs
            self.config["default_camera_crs"] = camera_crs
            save_config(self.config)

            probe_result = start_generic_sampling_probe(
                self.config,
                config_yml,
                run_dir,
                confirm=False,
                overwrite=overwrite,
            )
            if not probe_result or not isinstance(probe_result, dict) or not probe_result.get("success", True):
                probe_command = [
                    _cli_executable(self.config),
                    "run-analysis",
                    str(config_yml),
                    "--reps",
                    "1",
                    "--run-dir",
                    str(run_dir),
                    "--generic-ortho-resolution",
                ]
                if overwrite:
                    probe_command.append("--overwrite")
                self._show_error(
                    "Generic sampling probe could not be started",
                    "Command:\n%s\n\nLog path if available:\n%s"
                    % (
                        _quote_command(probe_command),
                        LOG_DIR,
                    ),
                )
                return

            status = ProcessMonitorDialog(
                "Field Screening Generic Sampling Probe",
                probe_result["process"],
                str(probe_result["command"]),
                Path(str(probe_result["log_path"])),
                run_dir,
                config_yml,
                variants_csv,
                prepare_log,
            )
            _qt_exec(status)
            self.accept()

    class NewProductAnalysisDialog(QtWidgets.QDialog):  # type: ignore[misc]
        def __init__(self, config: dict, presets: Sequence[Path]) -> None:
            super().__init__()
            self.config = config
            self.presets = list(presets)
            self.setWindowTitle("New Product Analysis")
            self.resize(780, 680)

            self.image_dir_edit = QtWidgets.QLineEdit()
            recent_image_dir = config.get("recent_image_dir", "")
            self.image_dir_edit.setText(recent_image_dir)
            self.product_id_edit = QtWidgets.QLineEdit()
            self.output_root_edit = QtWidgets.QLineEdit()
            self.output_root_edit.setText(config.get("default_output_root", ""))

            self.project_crs_edit = QtWidgets.QLineEdit()
            self.project_crs_edit.setText(_prefill_project_crs(config))
            self.camera_crs_edit = QtWidgets.QLineEdit()
            self.camera_crs_edit.setText(config.get("default_camera_crs", DEFAULT_CAMERA_CRS))
            self.overwrite_checkbox = QtWidgets.QCheckBox("Overwrite existing prepared output")

            self.preset_combo = QtWidgets.QComboBox()
            for preset in self.presets:
                label = _PRESET_LABELS.get(preset.name, preset.name)
                self.preset_combo.addItem(label, str(preset))

            self.reps_spin = QtWidgets.QSpinBox()
            self.reps_spin.setMinimum(2)
            self.reps_spin.setMaximum(999)
            self.reps_spin.setValue(_preset_default_reps(self._selected_preset().name))

            self.preview = QtWidgets.QPlainTextEdit()
            self.preview.setReadOnly(True)
            self.preview.setMinimumHeight(130)

            root_layout = QtWidgets.QVBoxLayout(self)
            root_layout.addWidget(self._section_label("Input"))
            input_form = QtWidgets.QFormLayout()
            input_form.addRow("Image folder", self._directory_row(self.image_dir_edit))
            input_form.addRow("Product id", self.product_id_edit)
            input_form.addRow("Output root", self._directory_row(self.output_root_edit))
            root_layout.addLayout(input_form)

            root_layout.addWidget(self._section_label("Spatial reference"))
            spatial_form = QtWidgets.QFormLayout()
            spatial_form.addRow("Project CRS", self._crs_row(self.project_crs_edit))
            spatial_form.addRow("Camera CRS", self.camera_crs_edit)
            root_layout.addLayout(spatial_form)
            help_label = QtWidgets.QLabel("Project CRS is mandatory. Camera CRS describes image geotags.")
            help_label.setWordWrap(True)
            root_layout.addWidget(help_label)

            root_layout.addWidget(self._section_label("Analysis profile"))
            profile_form = QtWidgets.QFormLayout()
            profile_form.addRow("Preset", self.preset_combo)
            profile_form.addRow("Repetitions", self.reps_spin)
            profile_form.addRow("", self.overwrite_checkbox)
            root_layout.addLayout(profile_form)

            note = QtWidgets.QLabel(
                "Create configuration for a product analysis. This creates config.yml and variants.csv. "
                "Run, Resume, and Evaluate are started from the Run menu after configuration exists."
            )
            note.setWordWrap(True)
            root_layout.addWidget(note)

            root_layout.addWidget(self._section_label("Command preview"))
            root_layout.addWidget(self.preview)

            actions = QtWidgets.QDialogButtonBox()
            accept_role = getattr(QtWidgets.QDialogButtonBox, "AcceptRole", None)
            reject_role = getattr(QtWidgets.QDialogButtonBox, "RejectRole", None)
            if accept_role is None:
                accept_role = QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole
            if reject_role is None:
                reject_role = QtWidgets.QDialogButtonBox.ButtonRole.RejectRole
            self.prepare_button = actions.addButton("Create configuration", accept_role)
            actions.addButton("Cancel", reject_role)
            root_layout.addWidget(actions)

            self.image_dir_edit.textChanged.connect(lambda *_args: self._update_preview())
            self.product_id_edit.textChanged.connect(lambda *_args: self._update_preview())
            self.output_root_edit.textChanged.connect(lambda *_args: self._update_preview())
            self.project_crs_edit.textChanged.connect(lambda *_args: self._update_preview())
            self.camera_crs_edit.textChanged.connect(lambda *_args: self._update_preview())
            self.overwrite_checkbox.stateChanged.connect(lambda *_args: self._update_preview())
            self.reps_spin.valueChanged.connect(lambda *_args: self._update_preview())
            self.preset_combo.currentIndexChanged.connect(lambda *_args: self._preset_changed())
            self.prepare_button.clicked.connect(lambda *_args: self._prepare())
            actions.rejected.connect(self.reject)
            self._update_preview()

        def _section_label(self, text: str) -> object:
            label = QtWidgets.QLabel(text)
            font = label.font()
            font.setBold(True)
            label.setFont(font)
            return label

        def _directory_row(self, edit: object) -> object:
            row = QtWidgets.QWidget()
            layout = QtWidgets.QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(edit)
            button = QtWidgets.QPushButton("Browse")
            button.clicked.connect(lambda: self._browse_directory(edit))
            layout.addWidget(button)
            return row

        def _crs_row(self, edit: object) -> object:
            row = QtWidgets.QWidget()
            layout = QtWidgets.QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(edit)
            button = QtWidgets.QPushButton("Use current Metashape CRS")
            button.clicked.connect(lambda *_args: self._use_current_crs(edit))
            layout.addWidget(button)
            return row

        def _use_current_crs(self, edit: object) -> None:
            value = get_current_metashape_project_crs()
            if not value:
                message("No usable CRS is available from the current Metashape chunk.")
                return
            edit.setText(value)

        def _browse_directory(self, edit: object) -> None:
            current = edit.text().strip()
            chosen = QtWidgets.QFileDialog.getExistingDirectory(self, "Select directory", current)
            if chosen:
                edit.setText(chosen)

        def _selected_preset(self) -> Path:
            data = self.preset_combo.currentData()
            return Path(str(data))

        def _preset_changed(self) -> None:
            self.reps_spin.setValue(_preset_default_reps(self._selected_preset().name))
            self._update_preview()

        def _current_args(self) -> List[str]:
            project_crs = normalize_crs(self.project_crs_edit.text())
            camera_crs = normalize_crs(self.camera_crs_edit.text(), allow_empty=True)
            return _prepare_args(
                self.config,
                self.image_dir_edit.text().strip(),
                self.product_id_edit.text().strip(),
                self._selected_preset(),
                int(self.reps_spin.value()),
                self.output_root_edit.text().strip(),
                project_crs,
                camera_crs,
                overwrite=self.overwrite_checkbox.isChecked(),
            )

        def _update_preview(self) -> None:
            self.preview.setPlainText(_quote_command(self._current_args()))

        def _prepare(self) -> None:
            image_dir = self.image_dir_edit.text().strip()
            product_id = self.product_id_edit.text().strip()
            output_root = self.output_root_edit.text().strip()
            preset = self._selected_preset()
            try:
                project_crs = validate_project_crs_for_metashape(self.project_crs_edit.text())
                camera_crs = validate_crs_for_metashape(
                    self.camera_crs_edit.text(),
                    "Camera CRS",
                    allow_empty=True,
                )
            except ValueError as exc:
                message(str(exc))
                return

            image_path = Path(image_dir).expanduser()
            if not image_path.is_dir():
                message("Image directory does not exist or is not a directory:\n%s" % image_path)
                return
            if not _has_supported_image(image_path):
                message("Image directory contains no supported image files:\n%s" % image_path)
                return
            if not product_id:
                message("Product id is required.")
                return
            if not output_root:
                message("Output root is required.")
                return
            if preset.name not in NEUTRAL_PRESET_NAMES or preset not in self.presets:
                message("Selected preset is not eligible for the generic launcher.")
                return

            start_time = _datetime.datetime.now().timestamp()
            args = _prepare_args(
                self.config,
                image_dir,
                product_id,
                preset,
                int(self.reps_spin.value()),
                output_root,
                project_crs,
                camera_crs,
                overwrite=self.overwrite_checkbox.isChecked(),
            )
            prepare_result = run_short_command(args, "prepare")
            prepare_log = Path(str(prepare_result["log_path"]))
            if int(prepare_result.get("returncode", 1)) != 0:
                message(
                    "Configuration creation failed\nExit code: %s\nPrepare log path: %s\n\nLast log lines:\n%s"
                    % (prepare_result.get("returncode"), prepare_log, _tail_text(prepare_log, 8000))
                )
                return
            run_dir = detect_prepared_run_dir(output_root, product_id, start_time)
            if run_dir is None:
                message("Configuration creation failed\nCould not detect run directory.\nPrepare log path: %s" % prepare_log)
                return
            try:
                assert_prepare_outputs(
                    run_dir,
                    project_crs,
                    camera_crs,
                    image_dir,
                    output_root,
                    preset,
                    prepare_log,
                )
            except Exception as exc:
                message(str(exc))
                return
            config_yml = run_dir / "config.yml"
            variants_csv = run_dir / "variants.csv"
            self.config["recent_run_dir"] = str(run_dir)
            self.config["recent_image_dir"] = image_dir
            self.config["default_output_root"] = output_root
            self.config["default_project_crs"] = project_crs
            self.config["default_camera_crs"] = camera_crs
            save_config(self.config)
            dialog = ConfigurationCreatedDialog(run_dir, config_yml, variants_csv, prepare_log)
            _qt_exec(dialog)
            self.accept()


def new_product_analysis() -> None:
    if QtWidgets is None:
        message(
            "Guided dialog is unavailable because Qt bindings are not available in this Metashape Python environment."
        )
        return
    config = load_config()
    repo = _repo_root(config)
    if repo is None:
        message("Repository root is not configured. Use Settings/Launcher Settings first.")
        return
    presets = neutral_presets(config)
    if not presets:
        message("No eligible neutral presets found. Check repository_root in Settings/Launcher Settings.")
        return
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    dialog = NewProductAnalysisDialog(config, presets)
    _qt_exec(dialog)


def new_field_screening() -> None:
    if QtWidgets is None:
        message(
            "Field screening dialog is unavailable because Qt bindings are not available in this Metashape Python environment."
        )
        return
    config = load_config()
    repo = _repo_root(config)
    if repo is None:
        message("Repository root is not configured. Use Settings/Launcher Settings first.")
        return
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    dialog = NewFieldScreeningDialog(config)
    _qt_exec(dialog)


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
    image_path = Path(image_dir).expanduser()
    if not image_path.is_dir():
        message("Image directory does not exist or is not a directory:\n%s" % image_path)
        return
    if not _has_supported_image(image_path):
        message("Image directory contains no supported image files:\n%s" % image_path)
        return
    project_crs = normalize_crs(project_crs)
    camera_crs = normalize_crs(camera_crs, allow_empty=True)
    if not _valid_project_crs(project_crs):
        message("Project CRS is required. Configure or enter a real project CRS before preparing.")
        return
    if _contains_forbidden_token(preset):
        message("Selected preset is not eligible for the generic launcher.")
        return
    args = _prepare_args(
        config,
        image_dir,
        product_id,
        preset,
        reps,
        output_root,
        project_crs,
        camera_crs,
    )
    config["recent_image_dir"] = image_dir
    config["default_output_root"] = output_root
    config["default_project_crs"] = project_crs
    config["default_camera_crs"] = camera_crs
    save_config(config)
    launch_command(args, "prepare")


def probe_orthomosaic_sampling() -> None:
    config = load_config()
    try:
        config_yml = get_open_file_name("Existing config.yml required for generic sampling probe", "").strip()
        run_dir = get_existing_directory("Run directory", config.get("recent_run_dir", "")).strip()
    except RuntimeError as exc:
        message(str(exc))
        return
    if not config_yml or not run_dir:
        message("Probe cancelled or missing required input.")
        return
    config_path = Path(config_yml).expanduser()
    run_path = Path(run_dir).expanduser()
    variants_csv = run_path / "variants.csv"
    try:
        config_values = read_config_crs_values(config_path)
        values = assert_generated_config_crs(
            config_path,
            config_values.get("project_crs", ""),
            config_values.get("camera_crs", ""),
            "not used at this boundary",
        )
        if variants_csv.exists():
            project_crs = validate_project_crs_for_metashape(values.get("project_crs", ""))
            camera_crs = validate_crs_for_metashape(values.get("camera_crs", ""), "Camera CRS", allow_empty=True)
            assert_generated_variants_integrity(
                variants_csv,
                project_crs,
                camera_crs,
                values.get("photo_path", ""),
                run_path,
                run_path,
                "not used at this boundary",
                values.get("addGCPs.gcp_crs", project_crs),
            )
    except Exception as exc:
        message("Prepared probe integrity check failed:\n%s" % exc)
        return
    config["recent_run_dir"] = run_dir
    save_config(config)
    result = start_generic_sampling_probe(config, config_yml, run_dir, confirm=True)
    if QtWidgets is not None and isinstance(result, dict) and result.get("success", True):
        dialog = ProcessMonitorDialog(
            "Generic Sampling Probe",
            result["process"],
            str(result["command"]),
            Path(str(result["log_path"])),
            run_path,
            config_path,
            variants_csv if variants_csv.exists() else None,
            None,
        )
        _qt_exec(dialog)


def _analysis_command(command_name: str, log_prefix: str) -> None:
    config = load_config()
    try:
        run_dir = get_existing_directory("Run directory", config.get("recent_run_dir", "")).strip()
        reps = _parse_min_int(get_string("Reps", "2"), 2, "Reps")
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
    try:
        config_values = read_config_crs_values(config_yml)
        values = assert_generated_config_crs(
            config_yml,
            config_values.get("project_crs", ""),
            config_values.get("camera_crs", ""),
            "not used at this boundary",
        )
        project_crs = validate_project_crs_for_metashape(values.get("project_crs", ""))
        camera_crs = validate_crs_for_metashape(values.get("camera_crs", ""), "Camera CRS", allow_empty=True)
        gcp_crs = values.get("addGCPs.gcp_crs", project_crs)
        assert_generated_variants_integrity(
            variants_csv,
            project_crs,
            camera_crs,
            values.get("photo_path", ""),
            run_path,
            run_path,
            "not used at this boundary",
            gcp_crs,
        )
    except Exception as exc:
        message("Prepared analysis integrity check failed:\n%s" % exc)
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
    metashape_dir = config.get("metashape_dir", "").strip()
    if metashape_dir:
        args.extend(["--metashape-dir", metashape_dir])
    config["recent_run_dir"] = str(run_path)
    save_config(config)
    result = launch_command(args, log_prefix)
    if QtWidgets is not None and isinstance(result, dict) and result.get("success", True):
        dialog = ProcessMonitorDialog(
            "%s Prepared Analysis" % command_name,
            result["process"],
            str(result["command"]),
            Path(str(result["log_path"])),
            run_path,
            config_yml,
            variants_csv,
            None,
        )
        _qt_exec(dialog)


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
    args = [_cli_executable(config), "evaluate", run_dir]
    result = launch_command(args, "evaluate")
    if QtWidgets is not None and isinstance(result, dict) and result.get("success", True):
        run_path = Path(run_dir).expanduser()
        dialog = ProcessMonitorDialog(
            "Evaluate Analysis",
            result["process"],
            str(result["command"]),
            Path(str(result["log_path"])),
            run_path,
            run_path / "config.yml",
            run_path / "variants.csv",
            None,
        )
        _qt_exec(dialog)


def run_resolution_sensitivity() -> None:
    config = load_config()
    text = (
        "Resolution sensitivity is notes-only in this launcher.\n\n"
        "1. First run generic sampling probe.\n"
        "2. Then prepare separate reference runs with one fixed buildOrthomosaic.orthoRes each.\n"
        "3. No mixed-resolution evaluation.\n\n"
        "No orchestration yet."
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
        ("New Field Screening", new_field_screening),
        ("New Product Analysis", new_product_analysis),
        ("Sampling/Probe Generic Sampling", probe_orthomosaic_sampling),
        ("Sampling/Resolution Sensitivity Notes", run_resolution_sensitivity),
        ("Run/Run Prepared Analysis", run_product_analysis),
        ("Run/Resume Prepared Analysis", resume_product_analysis),
        ("Run/Evaluate Analysis", evaluate_product_analysis),
        ("Open/Run Folder", open_run_folder),
        ("Open/Evaluation Report", open_evaluation_report),
        ("Open/Selected Product Trace", open_selected_product_trace),
        ("Settings/Launcher Settings", launcher_settings),
        ("Settings/Show Loaded Presets", show_loaded_presets),
    )
    for label, callback in entries:
        _register_menu_item(label, callback)


register_menu()
