from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import shutil
import subprocess


_SAVED_OTB_ENVIRONMENT = {
    "LEVEL1B_OTB_LD_LIBRARY_PATH_ORIG": "LD_LIBRARY_PATH",
    "LEVEL1B_OTB_APPLICATION_PATH_ORIG": "OTB_APPLICATION_PATH",
    "LEVEL1B_OTB_PATH_ORIG": "PATH",
    "LEVEL1B_OTB_GDAL_DATA_ORIG": "GDAL_DATA",
    "LEVEL1B_OTB_PROJ_LIB_ORIG": "PROJ_LIB",
}


def is_otb_cli_command(command: Sequence[object]) -> bool:
    if not command:
        return False
    return Path(os.fspath(command[0])).name.lower().startswith("otbcli_")


def discover_otb_cli(command_name: str) -> str | None:
    """Find an OTB launcher in the saved OTB runtime or current PATH."""

    saved_path = os.environ.get("LEVEL1B_OTB_PATH_ORIG")
    if saved_path:
        discovered = shutil.which(command_name, path=saved_path)
        if discovered:
            return discovered
    return shutil.which(command_name)


def otb_cli_env() -> dict[str, str]:
    env = os.environ.copy()
    for saved_name, runtime_name in _SAVED_OTB_ENVIRONMENT.items():
        if saved_name in os.environ:
            env[runtime_name] = os.environ[saved_name]
    return env


def otb_subprocess_command(command: Sequence[object]) -> list[str]:
    """Return an executable command, explicitly wrapping Windows batch launchers."""

    normalized = [os.fspath(part) for part in command]
    if os.name != "nt" or not normalized:
        return normalized
    if Path(normalized[0]).suffix.lower() not in {".bat", ".cmd"}:
        return normalized
    comspec = os.environ.get("COMSPEC") or shutil.which("cmd.exe") or "cmd.exe"
    return [
        comspec,
        "/d",
        "/s",
        "/c",
        subprocess.list2cmdline(normalized),
    ]


def otb_subprocess_kwargs(command: Sequence[object]) -> dict[str, object]:
    if not is_otb_cli_command(command):
        return {}
    return {"env": otb_cli_env()}
