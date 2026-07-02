from pathlib import Path

from metashape_qc_engine.level1b_otb_env import (
    is_otb_cli_command,
    otb_subprocess_kwargs,
)


def test_otb_command_receives_saved_cli_runtime_without_otb_pythonpath(
    monkeypatch,
) -> None:
    monkeypatch.setenv("PYTHONPATH", "/repo:/venv/site-packages")
    monkeypatch.setenv(
        "LEVEL1B_OTB_PYTHONPATH_ORIG",
        "/otb/lib/python3/dist-packages",
    )
    monkeypatch.setenv("LEVEL1B_OTB_LD_LIBRARY_PATH_ORIG", "/otb/lib")
    monkeypatch.setenv("LEVEL1B_OTB_APPLICATION_PATH_ORIG", "/otb/lib/otb/applications")
    monkeypatch.setenv("LEVEL1B_OTB_PATH_ORIG", "/otb/bin:/usr/bin")
    monkeypatch.setenv("LEVEL1B_OTB_GDAL_DATA_ORIG", "/otb/share/gdal")
    monkeypatch.setenv("LEVEL1B_OTB_PROJ_LIB_ORIG", "/otb/share/proj")

    command = ["/otb/bin/otbcli_BandMathX", "-help"]
    kwargs = otb_subprocess_kwargs(command)
    env = kwargs["env"]

    assert is_otb_cli_command(command) is True
    assert env["LD_LIBRARY_PATH"] == "/otb/lib"
    assert env["OTB_APPLICATION_PATH"] == "/otb/lib/otb/applications"
    assert env["PATH"] == "/otb/bin:/usr/bin"
    assert env["GDAL_DATA"] == "/otb/share/gdal"
    assert env["PROJ_LIB"] == "/otb/share/proj"
    assert env["PYTHONPATH"] == "/repo:/venv/site-packages"
    assert "/otb/lib/python3/dist-packages" not in env["PYTHONPATH"]


def test_non_otb_command_receives_no_environment_override() -> None:
    command = ["Rscript", "script.R"]
    assert is_otb_cli_command(command) is False
    assert otb_subprocess_kwargs(command) == {}


def test_otb_detection_uses_executable_basename() -> None:
    assert is_otb_cli_command([Path("/opt/otb/bin/otbcli_MeanShiftSmoothing")])
    assert not is_otb_cli_command([Path("/usr/bin/gdal_edit.py")])
