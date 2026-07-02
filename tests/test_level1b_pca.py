import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import metashape_qc_engine.level1b_pca as pca
from metashape_qc_engine.level1b_pca import (
    REPORT_KEYS,
    Level1BPCAConfig,
    build_level1b_pca_layout,
    build_pca_command,
    build_pca_remask_command,
    run_pca_step,
    validate_pca_config,
)


def fake_otb_path(executable_name: str) -> str:
    return f"/fake/bin/{executable_name}"


def make_stack(tmp_path: Path, name: str = "scaled_feature_stack.tif") -> Path:
    stack_path = tmp_path / name
    stack_path.touch()
    return stack_path


def make_mask(tmp_path: Path) -> Path:
    mask_path = tmp_path / "valid_mask.tif"
    mask_path.touch()
    return mask_path


def make_config(tmp_path: Path, **overrides: object) -> Level1BPCAConfig:
    values = {
        "candidate_id": "candidate-1",
        "scaled_feature_stack_path": make_stack(tmp_path),
        "valid_mask_path": make_mask(tmp_path),
        "output_dir": tmp_path / "out",
        "band_count": 5,
        "pca_components": 3,
    }
    values.update(overrides)
    return Level1BPCAConfig(**values)


def run_dry(tmp_path: Path, monkeypatch, **overrides: object) -> dict[str, object]:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    return run_pca_step(make_config(tmp_path, dry_run=True, **overrides))


def test_layout_creates_required_dirs_and_paths(tmp_path: Path) -> None:
    custom_tmp = tmp_path / "runtime-tmp"
    layout = build_level1b_pca_layout(tmp_path / "out", custom_tmp)

    assert layout["default_tmp_dir"] == tmp_path / "out" / "level1b" / "tmp"
    assert layout["runtime_tmp_dir"] == custom_tmp
    assert layout["logs_dir"].is_dir()
    assert layout["reports_dir"].is_dir()
    assert layout["pca_dir"].is_dir()
    assert layout["runtime_pca_tmp_dir"] == custom_tmp / "pca"
    assert layout["runtime_pca_tmp_dir"].is_dir()


def test_dry_run_builds_dimensionality_reduction_command(tmp_path: Path, monkeypatch) -> None:
    report = run_dry(tmp_path, monkeypatch)
    command = report["otb_commands"][0]

    assert report["status"] == "dry_run"
    assert command[0] == "/fake/bin/otbcli_DimensionalityReduction"
    assert command[command.index("-in") + 1] == str(Path(report["scaled_feature_stack_path"]))
    assert command[command.index("-out") + 1].endswith("pca_feature_stack_tmp.tif")


def test_pca_command_uses_method_pca(tmp_path: Path) -> None:
    command = build_pca_command(
        make_config(tmp_path),
        {"DimensionalityReduction": "/fake/dr"},
        build_level1b_pca_layout(tmp_path / "out"),
    )

    assert command[command.index("-method") + 1] == "pca"


def test_pca_command_uses_nbcomp_pca_components(tmp_path: Path) -> None:
    command = build_pca_command(
        make_config(tmp_path, pca_components=2),
        {"DimensionalityReduction": "/fake/dr"},
        build_level1b_pca_layout(tmp_path / "out"),
    )

    assert command[command.index("-nbcomp") + 1] == "2"


def test_pca_command_uses_normalize_false(tmp_path: Path) -> None:
    command = build_pca_command(
        make_config(tmp_path),
        {"DimensionalityReduction": "/fake/dr"},
        build_level1b_pca_layout(tmp_path / "out"),
    )

    assert command[command.index("-normalize") + 1] == "false"


def test_pca_command_uses_bv_background_value(tmp_path: Path) -> None:
    command = build_pca_command(
        make_config(tmp_path, background_value=-123.5),
        {"DimensionalityReduction": "/fake/dr"},
        build_level1b_pca_layout(tmp_path / "out"),
    )

    assert command[command.index("-bv") + 1] == "-123.5"


def test_dry_run_builds_bandmathx_remask_command(tmp_path: Path, monkeypatch) -> None:
    report = run_dry(tmp_path, monkeypatch)
    command = report["otb_commands"][1]

    assert command[0] == "/fake/bin/otbcli_BandMathX"
    assert command[command.index("-out") + 1].endswith("pca_feature_stack.tif")
    assert command[-1].startswith("{")
    assert command[-1].count(";") == 2


def test_remask_command_uses_valid_mask_and_background_value(tmp_path: Path) -> None:
    config = make_config(tmp_path, background_value=-7)
    command = build_pca_remask_command(config, {"BandMathX": "/fake/bmx"}, build_level1b_pca_layout(tmp_path / "out"))

    assert str(config.valid_mask_path) in command
    assert "im2b1 > 0" in command[-1]
    assert "-7.0" in command[-1]
    assert "im1b1" in command[-1]
    assert "im1b3" in command[-1]


def test_dry_run_does_not_call_subprocess(tmp_path: Path, monkeypatch) -> None:
    called = {"value": False}

    def fake_run(*_args: object, **_kwargs: object) -> object:
        called["value"] = True
        raise AssertionError("process must not run")

    monkeypatch.setattr("shutil.which", fake_otb_path)
    monkeypatch.setattr("metashape_qc_engine.level1b_pca.subprocess.run", fake_run)
    report = run_pca_step(make_config(tmp_path, dry_run=True))

    assert called["value"] is False
    assert report["pca_tmp_created"] is False
    assert report["pca_output_created"] is False


def test_validation_fails_for_missing_scaled_feature_stack(tmp_path: Path, monkeypatch) -> None:
    report = run_dry(tmp_path, monkeypatch, scaled_feature_stack_path=tmp_path / "missing.tif")

    assert report["status"] == "failed"
    assert report["checks"]["scaled_feature_stack_path_exists"] is False


def test_validation_fails_for_missing_mask(tmp_path: Path, monkeypatch) -> None:
    report = run_dry(tmp_path, monkeypatch, valid_mask_path=tmp_path / "missing.tif")

    assert report["status"] == "failed"
    assert report["checks"]["valid_mask_path_exists"] is False


def test_validation_fails_for_invalid_band_count(tmp_path: Path) -> None:
    config = make_config(tmp_path, band_count=0)
    checks, reasons = validate_pca_config(
        config,
        build_level1b_pca_layout(tmp_path / "out"),
        {"DimensionalityReduction": "/fake/dr", "BandMathX": "/fake/bmx"},
    )

    assert checks["band_count_positive_integer"] is False
    assert "band_count must be a positive integer" in reasons


def test_validation_fails_for_invalid_pca_components(tmp_path: Path) -> None:
    config = make_config(tmp_path, pca_components=0)
    checks, reasons = validate_pca_config(
        config,
        build_level1b_pca_layout(tmp_path / "out"),
        {"DimensionalityReduction": "/fake/dr", "BandMathX": "/fake/bmx"},
    )

    assert checks["pca_components_positive_integer"] is False
    assert "pca_components must be a positive integer" in reasons


def test_validation_fails_when_pca_components_gt_band_count(tmp_path: Path) -> None:
    config = make_config(tmp_path, band_count=2, pca_components=3)
    checks, reasons = validate_pca_config(
        config,
        build_level1b_pca_layout(tmp_path / "out"),
        {"DimensionalityReduction": "/fake/dr", "BandMathX": "/fake/bmx"},
    )

    assert checks["pca_components_lte_band_count"] is False
    assert "pca_components must be <= band_count" in reasons


def test_validation_fails_if_dimensionality_reduction_is_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "shutil.which",
        lambda name: None if name == "otbcli_DimensionalityReduction" else fake_otb_path(name),
    )
    report = run_pca_step(make_config(tmp_path, dry_run=True))

    assert report["checks"]["otb_dimensionality_reduction_discoverable"] is False
    assert "no OTB DimensionalityReduction app discoverable" in report["failure_reasons"]


def test_validation_fails_if_bandmathx_is_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None if name == "otbcli_BandMathX" else fake_otb_path(name))
    report = run_pca_step(make_config(tmp_path, dry_run=True))

    assert report["checks"]["otb_bandmathx_discoverable"] is False
    assert "no OTB BandMathX app discoverable" in report["failure_reasons"]


def test_mocked_successful_execution_returns_ok(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    def fake_run(command: list[str], capture_output: bool, text: bool, **kwargs) -> subprocess.CompletedProcess:
        assert capture_output is True
        assert text is True
        return subprocess.CompletedProcess(command, 0, "ok", "")

    monkeypatch.setattr("metashape_qc_engine.level1b_pca.subprocess.run", fake_run)
    report = run_pca_step(make_config(tmp_path))

    assert report["status"] == "ok"
    assert report["pca_tmp_created"] is True
    assert report["pca_output_created"] is True
    assert len(report["command_results"]) == 2


def test_mocked_failed_dimensionality_reduction_returns_failed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    monkeypatch.setattr(
        "metashape_qc_engine.level1b_pca.subprocess.run",
        lambda command, capture_output, text, **kwargs: subprocess.CompletedProcess(command, 2, "", "failed"),
    )
    report = run_pca_step(make_config(tmp_path))

    assert report["status"] == "failed"
    assert report["pca_tmp_created"] is False
    assert report["pca_output_created"] is False
    assert report["command_results"][0]["returncode"] == 2


def test_mocked_failed_remask_returns_failed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    calls = {"count": 0}

    def fake_run(command: list[str], capture_output: bool, text: bool, **kwargs) -> subprocess.CompletedProcess:
        calls["count"] += 1
        returncode = 0 if calls["count"] == 1 else 2
        return subprocess.CompletedProcess(command, returncode, "", "failed" if returncode else "")

    monkeypatch.setattr("metashape_qc_engine.level1b_pca.subprocess.run", fake_run)
    report = run_pca_step(make_config(tmp_path))

    assert report["status"] == "failed"
    assert report["pca_tmp_created"] is True
    assert report["pca_output_created"] is False
    assert report["command_results"][1]["returncode"] == 2


def test_report_contains_exactly_required_keys(tmp_path: Path, monkeypatch) -> None:
    report = run_dry(tmp_path, monkeypatch)

    assert tuple(report) == REPORT_KEYS
    assert set(json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))) == set(REPORT_KEYS)


def test_source_has_no_forbidden_raster_imports_and_no_blocked_workflow_symbols() -> None:
    source = Path(pca.__file__).read_text(encoding="utf-8")
    import_tokens = [
        "rast" + "erio",
        "os" + "geo",
        "gd" + "al",
        "num" + "py",
        "sci" + "py",
        "ski" + "mage",
        "c" + "v2",
        "P" + "IL",
        "pan" + "das",
        "geo" + "pan" + "das",
        "xar" + "ray",
        "rio" + "xar" + "ray",
        "ter" + "ra",
        "sta" + "rs",
        "link" + "2GI",
    ]
    blocked_symbols = [
        "scaling_" + "parameters",
        "ComputeImages" + "Statistics",
        "LocalStatistic" + "Extraction",
        "TrainDimensionality" + "Reduction",
        "ImageDimensionality" + "Reduction",
        "Mean" + "Shift",
        "LS" + "MS",
        "Hoo" + "ver",
        "scale_" + "candidates",
        "rang" + "er",
        "seg" + "mentation",
    ]

    for token in import_tokens + blocked_symbols:
        assert token not in source


def test_protected_existing_files_are_unchanged(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    output_dir = tmp_path / "out"
    existing = output_dir / "level1b" / "pca" / "pca_feature_stack.tif"
    existing.parent.mkdir(parents=True)
    existing.write_text("keep", encoding="utf-8")

    report = run_pca_step(make_config(tmp_path, output_dir=output_dir))

    assert report["status"] == "failed"
    assert existing.read_text(encoding="utf-8") == "keep"
