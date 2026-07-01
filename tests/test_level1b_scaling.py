import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import metashape_qc_engine.level1b_scaling as scaling
from metashape_qc_engine.level1b_scaling import (
    REPORT_KEYS,
    Level1BScalingConfig,
    build_level1b_scaling_layout,
    build_masked_feature_stack_command,
    build_statistics_command,
    build_zscore_scaling_command,
    parse_scaling_statistics_xml,
    run_scaling_step,
    validate_scaling_config,
)


def fake_otb_path(executable_name: str) -> str:
    return f"/fake/bin/{executable_name}"


def make_input(tmp_path: Path, name: str = "proxy_stack.tif") -> Path:
    input_path = tmp_path / name
    input_path.touch()
    return input_path


def make_mask(tmp_path: Path) -> Path:
    mask_path = tmp_path / "valid_mask.tif"
    mask_path.touch()
    return mask_path


def make_config(tmp_path: Path, **overrides: object) -> Level1BScalingConfig:
    values = {
        "candidate_id": "candidate-1",
        "feature_stack_path": make_input(tmp_path),
        "valid_mask_path": make_mask(tmp_path),
        "output_dir": tmp_path / "out",
        "band_count": 3,
    }
    values.update(overrides)
    return Level1BScalingConfig(**values)


def run_dry(tmp_path: Path, monkeypatch, **overrides: object) -> dict[str, object]:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    return run_scaling_step(make_config(tmp_path, dry_run=True, **overrides))


def test_layout_creates_required_dirs_and_paths(tmp_path: Path) -> None:
    custom_tmp = tmp_path / "runtime-tmp"
    layout = build_level1b_scaling_layout(tmp_path / "out", custom_tmp)

    assert layout["default_tmp_dir"] == tmp_path / "out" / "level1b" / "tmp"
    assert layout["runtime_tmp_dir"] == custom_tmp
    assert layout["logs_dir"].is_dir()
    assert layout["reports_dir"].is_dir()
    assert layout["scaling_dir"].is_dir()
    assert layout["runtime_scaling_tmp_dir"] == custom_tmp / "scaling"
    assert layout["runtime_scaling_tmp_dir"].is_dir()


def test_dry_run_builds_bandmathx_masked_stack_command(tmp_path: Path, monkeypatch) -> None:
    report = run_dry(tmp_path, monkeypatch)
    command = report["otb_commands"][0]

    assert report["status"] == "dry_run"
    assert command[0] == "/fake/bin/otbcli_BandMathX"
    assert command[command.index("-out") + 1].endswith("masked_feature_stack_tmp.tif")
    assert command[-1].startswith("{")
    assert command[-1].count(";") == 2


def test_masked_stack_command_uses_valid_mask_and_background_value(tmp_path: Path) -> None:
    config = make_config(tmp_path, background_value=-123.5)
    layout = build_level1b_scaling_layout(tmp_path / "out")
    command = build_masked_feature_stack_command(config, {"BandMathX": "/fake/bmx"}, layout)

    assert str(config.valid_mask_path) in command
    assert "im2b1 > 0" in command[-1]
    assert "-123.5" in command[-1]
    assert "im1b1" in command[-1]
    assert "im1b3" in command[-1]


def test_dry_run_builds_compute_images_statistics_command_with_bv_and_out_xml(tmp_path: Path, monkeypatch) -> None:
    report = run_dry(tmp_path, monkeypatch, background_value=-7)
    command = report["otb_commands"][1]

    assert command[0] == "/fake/bin/otbcli_ComputeImagesStatistics"
    assert command[command.index("-bv") + 1] == "-7.0"
    assert command[command.index("-out.xml") + 1].endswith("scaling_parameters.xml")


def test_dry_run_does_not_call_subprocess(tmp_path: Path, monkeypatch) -> None:
    called = {"value": False}

    def fake_run(*_args: object, **_kwargs: object) -> object:
        called["value"] = True
        raise AssertionError("process must not run")

    monkeypatch.setattr("shutil.which", fake_otb_path)
    monkeypatch.setattr("metashape_qc_engine.level1b_scaling.subprocess.run", fake_run)
    report = run_scaling_step(make_config(tmp_path, dry_run=True))

    assert called["value"] is False
    assert report["scaled_output_created"] is False
    assert report["scaling_parameters_json_written"] is False


def test_validation_fails_for_missing_feature_stack(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    report = run_scaling_step(make_config(tmp_path, feature_stack_path=tmp_path / "missing.tif", dry_run=True))

    assert report["status"] == "failed"
    assert report["checks"]["feature_stack_path_exists"] is False


def test_validation_fails_for_missing_mask(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    report = run_scaling_step(make_config(tmp_path, valid_mask_path=tmp_path / "missing.tif", dry_run=True))

    assert report["status"] == "failed"
    assert report["checks"]["valid_mask_path_exists"] is False


def test_validation_fails_for_invalid_band_count(tmp_path: Path) -> None:
    config = make_config(tmp_path, band_count=0)
    layout = build_level1b_scaling_layout(tmp_path / "out")
    checks, reasons = validate_scaling_config(
        config,
        layout,
        {"BandMathX": "/fake/bmx", "ComputeImagesStatistics": "/fake/stats"},
    )

    assert checks["band_count_positive_integer"] is False
    assert "band_count must be a positive integer" in reasons


def test_validation_fails_if_bandmathx_is_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "shutil.which",
        lambda name: None if name == "otbcli_BandMathX" else fake_otb_path(name),
    )
    report = run_scaling_step(make_config(tmp_path, dry_run=True))

    assert report["checks"]["otb_bandmathx_discoverable"] is False
    assert "no OTB BandMathX app discoverable" in report["failure_reasons"]


def test_validation_fails_if_compute_images_statistics_is_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "shutil.which",
        lambda name: None if name == "otbcli_ComputeImagesStatistics" else fake_otb_path(name),
    )
    report = run_scaling_step(make_config(tmp_path, dry_run=True))

    assert report["checks"]["otb_compute_images_statistics_discoverable"] is False
    assert "no OTB ComputeImagesStatistics app discoverable" in report["failure_reasons"]


def test_xml_parser_extracts_means_and_standard_deviations_for_band_count(tmp_path: Path) -> None:
    xml_path = tmp_path / "stats.xml"
    xml_path.write_text(
        """
<FeatureStatistics>
  <Statistic name="mean"><Values>1.0 2.0 3.0</Values></Statistic>
  <Statistic name="stddev"><Values>4.0 5.0 6.0</Values></Statistic>
</FeatureStatistics>
""",
        encoding="utf-8",
    )

    assert parse_scaling_statistics_xml(xml_path, 3) == {
        "means": [1.0, 2.0, 3.0],
        "standard_deviations": [4.0, 5.0, 6.0],
    }


def test_xml_parser_fails_on_missing_or_nonpositive_standard_deviation(tmp_path: Path) -> None:
    missing_xml = tmp_path / "missing-std.xml"
    missing_xml.write_text("<Stats><Mean>1 2</Mean></Stats>", encoding="utf-8")
    bad_xml = tmp_path / "bad-std.xml"
    bad_xml.write_text("<Stats><Mean>1 2</Mean><StdDev>1 0</StdDev></Stats>", encoding="utf-8")

    for xml_path in (missing_xml, bad_xml):
        try:
            parse_scaling_statistics_xml(xml_path, 2)
        except ValueError as exc:
            assert "invalid scaling statistics" in str(exc)
        else:
            raise AssertionError("expected parser failure")


def test_zscore_command_uses_valid_mask_and_one_expression_per_band(tmp_path: Path) -> None:
    config = make_config(tmp_path, band_count=2, background_value=-9)
    layout = build_level1b_scaling_layout(tmp_path / "out")
    command = build_zscore_scaling_command(
        config,
        {"BandMathX": "/fake/bmx"},
        layout,
        {"means": [10.0, 20.0], "standard_deviations": [2.0, 4.0]},
    )

    assert str(config.valid_mask_path) in command
    assert "im2b1 > 0" in command[-1]
    assert "((im1b1 - 10.0) / 2.0)" in command[-1]
    assert "((im1b2 - 20.0) / 4.0)" in command[-1]
    assert command[-1].count(";") == 1


def test_mocked_successful_execution_returns_ok_and_writes_parameters_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    def fake_run(command: list[str], capture_output: bool, text: bool) -> subprocess.CompletedProcess:
        assert capture_output is True
        assert text is True
        if "otbcli_ComputeImagesStatistics" in command[0]:
            Path(command[command.index("-out.xml") + 1]).write_text(
                "<Stats><Mean>1 2 3</Mean><StdDev>4 5 6</StdDev></Stats>",
                encoding="utf-8",
            )
        if "otbcli_BandMathX" in command[0] and command[command.index("-out") + 1].endswith(
            "scaled_feature_stack.tif"
        ):
            Path(command[command.index("-out") + 1]).touch()
        return subprocess.CompletedProcess(command, 0, "ok", "")

    monkeypatch.setattr("metashape_qc_engine.level1b_scaling.subprocess.run", fake_run)
    report = run_scaling_step(make_config(tmp_path))
    params = json.loads(Path(report["scaling_parameters_json_path"]).read_text(encoding="utf-8"))

    assert report["status"] == "ok"
    assert report["scaling_parameters_json_written"] is True
    assert params["means"] == [1.0, 2.0, 3.0]
    assert params["standard_deviations"] == [4.0, 5.0, 6.0]


def test_mocked_failed_subprocess_execution_returns_failed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    monkeypatch.setattr(
        "metashape_qc_engine.level1b_scaling.subprocess.run",
        lambda command, capture_output, text: subprocess.CompletedProcess(command, 2, "", "failed"),
    )

    report = run_scaling_step(make_config(tmp_path))

    assert report["status"] == "failed"
    assert report["command_results"][0]["returncode"] == 2


def test_report_contains_exactly_required_keys(tmp_path: Path, monkeypatch) -> None:
    report = run_dry(tmp_path, monkeypatch)

    assert tuple(report) == REPORT_KEYS
    assert set(json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))) == set(REPORT_KEYS)


def test_protected_existing_files_are_unchanged(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    output_dir = tmp_path / "out"
    existing = output_dir / "level1b" / "scaling" / "scaled_feature_stack.tif"
    existing.parent.mkdir(parents=True)
    existing.write_text("keep", encoding="utf-8")

    report = run_scaling_step(make_config(tmp_path, output_dir=output_dir))

    assert report["status"] == "failed"
    assert existing.read_text(encoding="utf-8") == "keep"


def test_source_has_no_forbidden_raster_imports_and_no_blocked_workflow_symbols() -> None:
    source = Path(scaling.__file__).read_text(encoding="utf-8")
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
        "pca_feature" + "_stack",
        "pca_" + "report",
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
