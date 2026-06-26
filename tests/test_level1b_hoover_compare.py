import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from metashape_qc_engine.level1b_hoover_compare import (
    HOOVER_APP_NAME,
    Level1BHooverCompareConfig,
    build_hoover_compare_command,
    build_level1b_hoover_compare_layout,
    discover_hoover_compare_app,
    parse_hoover_numeric_metrics,
    run_hoover_compare,
    validate_hoover_compare_config,
)


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("labels", encoding="utf-8")
    return path


def make_config(tmp_path: Path, **overrides: object) -> Level1BHooverCompareConfig:
    values = {
        "candidate_id": "candidate-1",
        "comparison_id": "cmp-001",
        "baseline_labels_path": touch(tmp_path / "baseline" / "merged_labels.tif"),
        "perturbation_labels_path": touch(tmp_path / "perturbation" / "merged_labels.tif"),
        "output_dir": tmp_path / "out",
        "dry_run": True,
    }
    values.update(overrides)
    return Level1BHooverCompareConfig(**values)


def test_01_layout_creates_deterministic_path(tmp_path: Path) -> None:
    config = make_config(tmp_path, comparison_id="abc")
    layout = build_level1b_hoover_compare_layout(config)

    assert layout["compare_dir"] == tmp_path / "out" / "level1b" / "hoover" / "abc"
    assert layout["report_path"].name == "hoover_report.json"
    assert layout["raw_output_path"].name == "hoover_raw.txt"


def test_02_discovery_checks_otb_bin_dir_when_provided(tmp_path: Path) -> None:
    app = touch(tmp_path / "otb" / HOOVER_APP_NAME)

    assert discover_hoover_compare_app(tmp_path / "otb") == str(app)


def test_03_discovery_falls_back_to_shutil_which(monkeypatch) -> None:
    monkeypatch.setattr("metashape_qc_engine.level1b_hoover_compare.shutil.which", lambda name: f"/usr/bin/{name}")

    assert discover_hoover_compare_app() == f"/usr/bin/{HOOVER_APP_NAME}"


def test_04_validation_rejects_missing_baseline_raster(tmp_path: Path) -> None:
    config = make_config(tmp_path, baseline_labels_path=tmp_path / "missing.tif")
    checks, reasons = validate_hoover_compare_config(config, build_level1b_hoover_compare_layout(config), "/app")

    assert checks["baseline_labels_path_exists"] is False
    assert "baseline_labels_path does not exist" in reasons


def test_05_validation_rejects_missing_perturbation_raster(tmp_path: Path) -> None:
    config = make_config(tmp_path, perturbation_labels_path=tmp_path / "missing.tif")
    checks, reasons = validate_hoover_compare_config(config, build_level1b_hoover_compare_layout(config), "/app")

    assert checks["perturbation_labels_path_exists"] is False
    assert "perturbation_labels_path does not exist" in reasons


def test_06_validation_rejects_non_tif_suffixes(tmp_path: Path) -> None:
    config = make_config(
        tmp_path,
        baseline_labels_path=touch(tmp_path / "baseline" / "merged_labels.img"),
        perturbation_labels_path=touch(tmp_path / "perturbation" / "merged_labels.png"),
    )
    checks, reasons = validate_hoover_compare_config(config, build_level1b_hoover_compare_layout(config), "/app")

    assert checks["baseline_labels_suffix_raster_like"] is False
    assert checks["perturbation_labels_suffix_raster_like"] is False
    assert "baseline_labels_path suffix must be one of .tif, .tiff" in reasons
    assert "perturbation_labels_path suffix must be one of .tif, .tiff" in reasons


def test_07_validation_rejects_existing_outputs_when_overwrite_is_false(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    layout = build_level1b_hoover_compare_layout(config)
    touch(layout["report_path"])

    checks, reasons = validate_hoover_compare_config(config, layout, "/app")

    assert checks["output_artifacts_available"] is False
    assert "output artifacts already exist and overwrite is false" in reasons


def test_08_command_construction_uses_discovered_app_path(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    command = build_hoover_compare_command(config, "/opt/otb/otbcli_HooverCompareSegmentation", build_level1b_hoover_compare_layout(config))

    assert command[0] == "/opt/otb/otbcli_HooverCompareSegmentation"


def test_09_command_construction_includes_baseline_raster_path(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    command = build_hoover_compare_command(config, "/app", build_level1b_hoover_compare_layout(config))

    assert str(config.baseline_labels_path) in command


def test_10_command_construction_includes_perturbation_raster_path(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    command = build_hoover_compare_command(config, "/app", build_level1b_hoover_compare_layout(config))

    assert str(config.perturbation_labels_path) in command


def test_11_dry_run_does_not_call_subprocess(tmp_path: Path, monkeypatch) -> None:
    def fail_run(*_args, **_kwargs):
        raise AssertionError("subprocess should not be called")

    monkeypatch.setattr("metashape_qc_engine.level1b_hoover_compare.discover_hoover_compare_app", lambda _bin=None: "/app")
    monkeypatch.setattr("metashape_qc_engine.level1b_hoover_compare.subprocess.run", fail_run)

    report = run_hoover_compare(make_config(tmp_path, dry_run=True))

    assert report["status"] == "dry_run"


def test_12_non_dry_run_calls_subprocess_run(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def fake_run(command: list[str], capture_output: bool, text: bool) -> subprocess.CompletedProcess[str]:
        calls.append((command, capture_output, text))
        return subprocess.CompletedProcess(command, 0, "Correct detection score: 0.5\n", "")

    monkeypatch.setattr("metashape_qc_engine.level1b_hoover_compare.discover_hoover_compare_app", lambda _bin=None: "/app")
    monkeypatch.setattr("metashape_qc_engine.level1b_hoover_compare.subprocess.run", fake_run)

    report = run_hoover_compare(make_config(tmp_path, dry_run=False))

    assert calls
    assert calls[0][1:] == (True, True)
    assert report["status"] == "ok"


def test_13_stdout_is_written_to_raw_output_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("metashape_qc_engine.level1b_hoover_compare.discover_hoover_compare_app", lambda _bin=None: "/app")
    monkeypatch.setattr(
        "metashape_qc_engine.level1b_hoover_compare.subprocess.run",
        lambda command, capture_output, text: subprocess.CompletedProcess(command, 0, "RC: 0.7\n", ""),
    )

    report = run_hoover_compare(make_config(tmp_path, dry_run=False))

    assert Path(report["raw_output_path"]).read_text(encoding="utf-8") == "RC: 0.7\n"


def test_14_report_json_is_written(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("metashape_qc_engine.level1b_hoover_compare.discover_hoover_compare_app", lambda _bin=None: "/app")
    monkeypatch.setattr(
        "metashape_qc_engine.level1b_hoover_compare.subprocess.run",
        lambda command, capture_output, text: subprocess.CompletedProcess(command, 0, "RF = 0.2\n", ""),
    )

    report = run_hoover_compare(make_config(tmp_path, dry_run=False))
    report_json = json.loads(Path(report["stdout_path"]).with_name("hoover_report.json").read_text(encoding="utf-8"))

    assert report_json["comparison_id"] == "cmp-001"


def test_15_parser_extracts_only_clear_numeric_key_value_pairs() -> None:
    metrics, status = parse_hoover_numeric_metrics(
        "Correct detection score: 0.75\nnoise line\nOver segmentation score = 1.25e-1\nNot numeric: abc\n"
    )

    assert status == "parsed_numeric_key_values"
    assert metrics == {"correct_detection_score": 0.75, "over_segmentation_score": 0.125}


def test_16_parser_returns_raw_only_status_when_no_safe_numeric_schema_exists() -> None:
    metrics, status = parse_hoover_numeric_metrics("Hoover finished without scalar output\n")

    assert status == "raw_only_no_safe_numeric_schema"
    assert metrics == {}


def test_17_report_contains_raster_only_no_vector_no_final_output_flags(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("metashape_qc_engine.level1b_hoover_compare.discover_hoover_compare_app", lambda _bin=None: "/app")
    monkeypatch.setattr(
        "metashape_qc_engine.level1b_hoover_compare.subprocess.run",
        lambda command, capture_output, text: subprocess.CompletedProcess(command, 0, "", ""),
    )

    report = run_hoover_compare(make_config(tmp_path, dry_run=False))

    assert report["raster_only"] is True
    assert report["no_vector_output"] is True
    assert report["no_final_output"] is True
    assert report["no_lsms_vectorization"] is True
    assert report["no_scale_selection"] is True
    assert report["no_cli_integration"] is True


def test_18_no_forbidden_concepts_are_introduced() -> None:
    source = (REPO_ROOT / "metashape_qc_engine" / "level1b_hoover_compare.py").read_text(encoding="utf-8")
    tests = (REPO_ROOT / "tests" / "test_level1b_hoover_compare.py").read_text(encoding="utf-8")
    combined = source + "\n" + tests
    blocked = [
        "LSMS" + "Vectorization",
        "shape" + "file",
        "g" + "pkg",
        "final_" + "segments",
        "final_" + "labels",
        "selected_" + "scale_id",
        "side" + "car",
        "C" + "LI",
        "run" + "ner",
    ]

    assert [term for term in blocked if term in combined] == []


def test_19_no_step_1_8_files_are_modified() -> None:
    protected = [
        "metashape_qc_engine/level1b_preflight.py",
        "metashape_qc_engine/level1b_channels.py",
        "metashape_qc_engine/level1b_valid_mask.py",
        "metashape_qc_engine/level1b_pca.py",
        "metashape_qc_engine/level1b_scaling.py",
        "metashape_qc_engine/level1b_scale_distribution.py",
        "metashape_qc_engine/level1b_feature_range.py",
        "metashape_qc_engine/level1b_perturbations.py",
    ]

    assert subprocess.run(["git", "diff", "--quiet", "--", *protected]).returncode == 0


def test_20_no_multi_run_orchestration_is_implemented() -> None:
    source = (REPO_ROOT / "metashape_qc_engine" / "level1b_hoover_compare.py").read_text(encoding="utf-8")

    assert "candidate_stability" not in source
    assert "multi_run" not in source
