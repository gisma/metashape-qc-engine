from __future__ import annotations

import os
from pathlib import Path
from collections.abc import Sequence


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
    return Path(os.fspath(command[0])).name.startswith("otbcli_")


def otb_cli_env() -> dict[str, str]:
    env = os.environ.copy()
    for saved_name, runtime_name in _SAVED_OTB_ENVIRONMENT.items():
        if saved_name in os.environ:
            env[runtime_name] = os.environ[saved_name]
    return env


def otb_subprocess_kwargs(command: Sequence[object]) -> dict[str, object]:
    if not is_otb_cli_command(command):
        return {}
    return {"env": otb_cli_env()}
