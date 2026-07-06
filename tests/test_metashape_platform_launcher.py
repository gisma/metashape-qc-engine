from __future__ import annotations

import importlib.util
from pathlib import Path

import metashape_qc_engine.cli as cli


def _load_reproducibility_runner():
    path = Path(__file__).resolve().parents[1] / "metashape_qc_engine" / "level1a" / "reproducibility_runner.py"
    spec = importlib.util.spec_from_file_location("reproducibility_runner_tested", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_uses_powershell_wrapper_on_windows(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cli.os, "name", "nt")
    monkeypatch.setattr(cli.shutil, "which", lambda name: "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe" if name == "powershell.exe" else None)

    command = cli._metashape_wrapper_command(tmp_path, "config.yml")

    assert command[-2:] == [
        str(tmp_path / "scripts" / "run_metashape_workflow.ps1"),
        "config.yml",
    ]
    assert "-File" in command


def test_replicate_runner_uses_powershell_wrapper_on_windows(monkeypatch, tmp_path: Path):
    module = _load_reproducibility_runner()
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(module.shutil, "which", lambda name: "powershell.exe" if name == "powershell.exe" else None)

    command = module.metashape_wrapper_command(tmp_path, tmp_path / "config.yml")

    assert command[-2:] == [
        str(tmp_path / "scripts" / "run_metashape_workflow.ps1"),
        str(tmp_path / "config.yml"),
    ]
    assert command[0] == "powershell.exe"
