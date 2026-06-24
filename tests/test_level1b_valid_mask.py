import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import metashape_qc_engine.level1b_valid_mask as lvm
from metashape_qc_engine.level1b_valid_mask import (
    CHECK_KEYS,
    REPORT_KEYS,
    Level1BValidMaskConfig,
    build_level1b_mask_layout,
    build_valid_mask_command,
    build_valid_mask_expression,
    run_valid_mask_step,
)


def fake_otb_path(executable_name: str) -> str:
    return f"/fake/bin/{executable_name}"


def make_input(tmp_path: Path, name: str = "input.tif") -> Path:
    input_path = tmp_path / name
    input_path.touch()
    return input_path


def run_dry(tmp_path: Path, monkeypatch, **overrides: object) -> dict[str, object]:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    config_values = {
        "candidate_id": "candidate-1",
        "input_path": make_input(tmp_path),
        "output_dir": tmp_path / "out",
        "dry_run": True,
    }
    config_values.update(overrides)
    return run_valid_mask_step(Level1BValidMaskConfig(**config_values))


def test_layout_creates_tmp_logs_reports_mask_dirs(tmp_path: Path) -> None:
    layout = build_level1b_mask_layout(tmp_path / "out")

    assert layout["default_tmp_dir"].is_dir()
    assert layout["runtime_tmp_dir"].is_dir()
    assert layout["logs_dir"].is_dir()
    assert layout["reports_dir"].is_dir()
    assert layout["mask_dir"].is_dir()


def test_custom_tmp_dir_preserves_default_tmp_dir_and_creates_runtime_tmp_dir(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    custom_tmp = tmp_path / "custom-tmp"

    layout = build_level1b_mask_layout(output_dir, custom_tmp)

    assert layout["default_tmp_dir"] == output_dir / "level1b" / "tmp"
    assert layout["runtime_tmp_dir"] == custom_tmp
    assert layout["default_tmp_dir"].is_dir()
    assert layout["runtime_tmp_dir"].is_dir()


def test_candidate_id_empty_fails_before_command(tmp_path: Path, monkeypatch) -> None:
    report = run_dry(tmp_path, monkeypatch, candidate_id=" ")

    assert report["status"] == "failed"
    assert report["otb_command"] is None
    assert "candidate_id is empty" in report["failure_reasons"]


def test_input_path_missing_fails_before_command(tmp_path: Path, monkeypatch) -> None:
    report = run_dry(tmp_path, monkeypatch, input_path=tmp_path / "missing.tif")

    assert report["status"] == "failed"
    assert report["otb_command"] is None
    assert any("input_path does not exist" in reason for reason in report["failure_reasons"])


def test_invalid_suffix_fails_before_command(tmp_path: Path, monkeypatch) -> None:
    report = run_dry(tmp_path, monkeypatch, input_path=make_input(tmp_path, "input.txt"))

    assert report["status"] == "failed"
    assert report["otb_command"] is None
    assert any("input_path suffix must be one of" in reason for reason in report["failure_reasons"])


def test_no_active_construction_rule_fails_before_command(tmp_path: Path, monkeypatch) -> None:
    report = run_dry(tmp_path, monkeypatch, black_border_enabled=False)

    assert report["status"] == "failed"
    assert report["otb_command"] is None
    assert "no valid-mask construction rule is active" in report["failure_reasons"]


def test_nodata_non_positive_band_index_fails(tmp_path: Path, monkeypatch) -> None:
    report = run_dry(tmp_path, monkeypatch, nodata_values={0: 255.0})

    assert report["status"] == "failed"
    assert report["checks"]["nodata_values_valid"] is False
    assert "nodata_values band indices must be positive integers" in report["failure_reasons"]


def test_alpha_band_index_non_positive_fails(tmp_path: Path, monkeypatch) -> None:
    report = run_dry(tmp_path, monkeypatch, alpha_band_index=0)

    assert report["status"] == "failed"
    assert report["checks"]["alpha_band_index_valid"] is False
    assert "alpha_band_index must be a positive integer" in report["failure_reasons"]


def test_alpha_valid_min_non_numeric_fails(tmp_path: Path, monkeypatch) -> None:
    report = run_dry(tmp_path, monkeypatch, alpha_valid_min="one")

    assert report["status"] == "failed"
    assert report["checks"]["alpha_valid_min_numeric"] is False
    assert "alpha_valid_min must be numeric" in report["failure_reasons"]


def test_black_border_tuple_length_mismatch_fails(tmp_path: Path, monkeypatch) -> None:
    report = run_dry(tmp_path, monkeypatch, black_border_band_indices=(1, 2), black_border_invalid_values=(0.0,))

    assert report["status"] == "failed"
    assert report["checks"]["black_border_tuple_lengths_match"] is False
    assert any(
        "black_border_band_indices and black_border_invalid_values must have the same length" in reason
        for reason in report["failure_reasons"]
    )


def test_black_border_non_positive_band_index_fails(tmp_path: Path, monkeypatch) -> None:
    report = run_dry(tmp_path, monkeypatch, black_border_band_indices=(1, 0, 3))

    assert report["status"] == "failed"
    assert report["checks"]["black_border_band_indices_valid"] is False
    assert "black_border_band_indices must be positive integers" in report["failure_reasons"]


def test_black_border_invalid_value_non_numeric_fails(tmp_path: Path, monkeypatch) -> None:
    report = run_dry(tmp_path, monkeypatch, black_border_invalid_values=(0.0, "zero", 0.0))

    assert report["status"] == "failed"
    assert report["checks"]["black_border_invalid_values_numeric"] is False
    assert "black_border_invalid_values must be numeric" in report["failure_reasons"]


def test_ram_mb_invalid_fails(tmp_path: Path, monkeypatch) -> None:
    report = run_dry(tmp_path, monkeypatch, ram_mb=0)

    assert report["status"] == "failed"
    assert report["checks"]["ram_mb_valid"] is False
    assert "ram_mb must be a positive integer" in report["failure_reasons"]


def test_existing_valid_mask_path_with_overwrite_false_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    input_path = make_input(tmp_path)
    output_dir = tmp_path / "out"
    existing = output_dir / "level1b" / "mask" / "valid_mask.tif"
    existing.parent.mkdir(parents=True)
    existing.touch()

    report = run_valid_mask_step(
        Level1BValidMaskConfig(candidate_id="candidate-1", input_path=input_path, output_dir=output_dir)
    )

    assert report["status"] == "failed"
    assert report["otb_command"] is None
    assert "valid_mask_path already exists and overwrite is false" in report["failure_reasons"]


def test_bandmathx_missing_fails_before_command(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)

    report = run_valid_mask_step(
        Level1BValidMaskConfig(candidate_id="candidate-1", input_path=make_input(tmp_path), output_dir=tmp_path / "out")
    )

    assert report["status"] == "failed"
    assert report["otb_command"] is None
    assert "no OTB BandMathX app discoverable" in report["failure_reasons"]


def test_dry_run_does_not_call_process_and_writes_report(tmp_path: Path, monkeypatch) -> None:
    called = {"value": False}

    def fake_run(*_args: object, **_kwargs: object) -> object:
        called["value"] = True
        raise AssertionError("process must not run")

    monkeypatch.setattr("shutil.which", fake_otb_path)
    monkeypatch.setattr("metashape_qc_engine.level1b_valid_mask.subprocess.run", fake_run)

    report = run_valid_mask_step(
        Level1BValidMaskConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            dry_run=True,
        )
    )

    assert called["value"] is False
    assert Path(report["report_path"]).is_file()


def test_dry_run_status_is_dry_run_and_valid_mask_created_is_false(tmp_path: Path, monkeypatch) -> None:
    report = run_dry(tmp_path, monkeypatch)

    assert report["status"] == "dry_run"
    assert report["valid_mask_created"] is False


def test_default_black_border_expression_contains_expected_bands_and_values() -> None:
    expression, reasons = build_valid_mask_expression(
        Level1BValidMaskConfig(candidate_id="candidate-1", input_path="input.tif", output_dir="out")
    )

    assert reasons == []
    assert "im1b1" in expression
    assert "im1b2" in expression
    assert "im1b3" in expression
    assert "0.0" in expression


def test_default_black_border_expression_uses_bandmathx_boolean_syntax() -> None:
    expression, reasons = build_valid_mask_expression(
        Level1BValidMaskConfig(candidate_id="candidate-1", input_path="input.tif", output_dir="out")
    )

    assert reasons == []
    assert "!(" not in expression
    assert "&&" not in expression
    assert "||" not in expression
    assert expression == "((im1b1 != 0.0) or (im1b2 != 0.0) or (im1b3 != 0.0)) ? 1 : 0"


def test_nodata_expression_contains_band_and_value() -> None:
    expression, reasons = build_valid_mask_expression(
        Level1BValidMaskConfig(
            candidate_id="candidate-1",
            input_path="input.tif",
            output_dir="out",
            nodata_values={4: -9999.0},
            black_border_enabled=False,
        )
    )

    assert reasons == []
    assert "im1b4 != -9999.0" in expression


def test_alpha_expression_contains_band_and_value() -> None:
    expression, reasons = build_valid_mask_expression(
        Level1BValidMaskConfig(
            candidate_id="candidate-1",
            input_path="input.tif",
            output_dir="out",
            alpha_band_index=5,
            alpha_valid_min=2.5,
            black_border_enabled=False,
        )
    )

    assert reasons == []
    assert "im1b5 >= 2.5" in expression


def test_combined_expression_uses_boolean_join_and_output_branch() -> None:
    expression, reasons = build_valid_mask_expression(
        Level1BValidMaskConfig(
            candidate_id="candidate-1",
            input_path="input.tif",
            output_dir="out",
            nodata_values={1: 255.0},
            alpha_band_index=4,
        )
    )

    assert reasons == []
    assert " and " in expression
    assert expression.endswith("? 1 : 0")


def test_combined_expression_uses_bandmathx_and_between_valid_conditions() -> None:
    expression, reasons = build_valid_mask_expression(
        Level1BValidMaskConfig(
            candidate_id="candidate-1",
            input_path="input.tif",
            output_dir="out",
            nodata_values={1: 255.0},
            alpha_band_index=4,
        )
    )

    assert reasons == []
    assert expression == (
        "(im1b1 != 255.0) and (im1b4 >= 1.0) and "
        "((im1b1 != 0.0) or (im1b2 != 0.0) or (im1b3 != 0.0)) ? 1 : 0"
    )
    assert " and " in expression
    assert expression.endswith("? 1 : 0")


def test_command_first_element_is_discovered_bandmathx_path(tmp_path: Path) -> None:
    command = build_valid_mask_command(
        Level1BValidMaskConfig(candidate_id="candidate-1", input_path="input.tif", output_dir="out"),
        "/fake/bin/otbcli_BandMathX",
        tmp_path / "valid_mask.tif",
    )

    assert command[0] == "/fake/bin/otbcli_BandMathX"


def test_command_contains_required_otb_flags(tmp_path: Path) -> None:
    command = build_valid_mask_command(
        Level1BValidMaskConfig(candidate_id="candidate-1", input_path="input.tif", output_dir="out"),
        "/fake/bin/otbcli_BandMathX",
        tmp_path / "valid_mask.tif",
    )

    assert "-il" in command
    assert "-out" in command
    assert "-exp" in command


def test_successful_mocked_process_returns_status_ok(tmp_path: Path, monkeypatch) -> None:
    class Result:
        stdout = "done"
        stderr = ""
        returncode = 0

    monkeypatch.setattr("shutil.which", fake_otb_path)
    monkeypatch.setattr("metashape_qc_engine.level1b_valid_mask.subprocess.run", lambda *_args, **_kwargs: Result())

    report = run_valid_mask_step(
        Level1BValidMaskConfig(candidate_id="candidate-1", input_path=make_input(tmp_path), output_dir=tmp_path / "out")
    )

    assert report["status"] == "ok"
    assert report["valid_mask_created"] is True
    assert report["stdout"] == "done"
    assert report["returncode"] == 0


def test_failed_mocked_process_returns_failed_and_reason(tmp_path: Path, monkeypatch) -> None:
    class Result:
        stdout = ""
        stderr = "bad"
        returncode = 2

    monkeypatch.setattr("shutil.which", fake_otb_path)
    monkeypatch.setattr("metashape_qc_engine.level1b_valid_mask.subprocess.run", lambda *_args, **_kwargs: Result())

    report = run_valid_mask_step(
        Level1BValidMaskConfig(candidate_id="candidate-1", input_path=make_input(tmp_path), output_dir=tmp_path / "out")
    )

    assert report["status"] == "failed"
    assert report["valid_mask_created"] is False
    assert "OTB execution failed" in report["failure_reasons"]


def test_report_contains_exactly_required_report_keys(tmp_path: Path, monkeypatch) -> None:
    report = run_dry(tmp_path, monkeypatch)
    report_json = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))

    assert set(report) == set(REPORT_KEYS)
    assert set(report_json) == set(REPORT_KEYS)


def test_checks_contains_exactly_required_check_keys(tmp_path: Path, monkeypatch) -> None:
    report = run_dry(tmp_path, monkeypatch)

    assert set(report["checks"]) == set(CHECK_KEYS)


def test_boundary_source_scan_no_forbidden_raster_imports() -> None:
    source = (REPO_ROOT / "metashape_qc_engine" / "level1b_valid_mask.py").read_text(encoding="utf-8")
    terms = [
        "ras" + "terio",
        "os" + "geo",
        "g" + "dal",
        "num" + "py",
        "sci" + "py",
        "ski" + "mage",
        "c" + "v2",
        "P" + "IL",
        "xar" + "ray",
        "rio" + "xar" + "ray",
        "pan" + "das",
        "geo" + "pan" + "das",
        "ter" + "ra",
        "st" + "ars",
        "link" + "2GI",
    ]

    assert not any(term in source for term in terms)


def test_boundary_source_scan_no_forbidden_workflow_terms_in_production_module() -> None:
    source = (REPO_ROOT / "metashape_qc_engine" / "level1b_valid_mask.py").read_text(encoding="utf-8")
    terms = [
        "run_" + "otb_app",
        "OTBCommand" + "Result",
        "OTBCommand" + "Error",
        "MeanShift" + "Smoothing",
        "LSMS" + "Segment" + "ation",
        "SmallRegions" + "Merging",
        "LSMSSmallRegions" + "Merging",
        "LSMS" + "Vectorization",
        "Hoo" + "verCompare" + "Segment" + "ation",
        "Zonal" + "Statistics",
        "TrainDimensionality" + "Reduction",
        "ImageDimensionality" + "Reduction",
        "proxy" + "_stack",
        "channel" + "_stack",
        "scaled" + "_feature_stack",
        "P" + "CA",
        "Hoo" + "ver",
        "A" + "RI",
        "ran" + "ger",
        "Spatial " + "Scale",
        "seg" + "mentation",
    ]

    assert not any(term in source for term in terms)


def test_level1b_preflight_py_diff_is_empty() -> None:
    result = lvm.subprocess.run(
        ["git", "diff", "--", "metashape_qc_engine/level1b_preflight.py"],
        capture_output=True,
        text=True,
    )

    assert result.stdout == ""


def test_cli_py_diff_is_empty() -> None:
    result = lvm.subprocess.run(
        ["git", "diff", "--", "metashape_qc_engine/cli.py"],
        capture_output=True,
        text=True,
    )

    assert result.stdout == ""
