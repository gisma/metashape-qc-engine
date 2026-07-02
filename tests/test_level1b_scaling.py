import json
from pathlib import Path
import subprocess

import numpy as np

import metashape_qc_engine.level1b_scaling as scaling
from metashape_qc_engine.level1b_scaling import (
    REPORT_KEYS,
    Level1BScalingConfig,
    build_level1b_scaling_layout,
    build_masked_feature_stack_command,
    build_quantile_scaling_command,
    build_statistics_command,
    compute_quantile_scaling_parameters,
    run_scaling_step,
    validate_scaling_config,
)


def fake_otb_path(executable_name: str) -> str:
    return f"/fake/bin/{executable_name}"


def make_input(tmp_path: Path, name: str = "proxy_stack.tif") -> Path:
    path = tmp_path / name
    path.touch()
    return path


def make_mask(tmp_path: Path) -> Path:
    path = tmp_path / "valid_mask.tif"
    path.touch()
    return path


def make_config(tmp_path: Path, **overrides) -> Level1BScalingConfig:
    values = {
        "candidate_id": "candidate-1",
        "feature_stack_path": make_input(tmp_path),
        "valid_mask_path": make_mask(tmp_path),
        "output_dir": tmp_path / "out",
        "band_count": 6,
    }
    values.update(overrides)
    return Level1BScalingConfig(**values)


def run_dry(tmp_path: Path, monkeypatch, **overrides) -> dict[str, object]:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    return run_scaling_step(make_config(tmp_path, dry_run=True, **overrides))


def test_layout_creates_required_directories(tmp_path: Path) -> None:
    custom_tmp = tmp_path / "runtime"
    layout = build_level1b_scaling_layout(tmp_path / "out", custom_tmp)
    assert layout["runtime_scaling_tmp_dir"] == custom_tmp / "scaling"
    assert all(path.is_dir() for path in layout.values())


def test_masked_stack_command_is_band_count_generic_for_six_bands(tmp_path: Path) -> None:
    config = make_config(tmp_path, band_count=6, background_value=-123.5)
    layout = build_level1b_scaling_layout(config.output_dir)
    command = build_masked_feature_stack_command(
        config, {"BandMathX": "/fake/bmx"}, layout
    )
    expression = command[-1]
    assert str(config.valid_mask_path) in command
    assert expression.count(";") == 5
    assert all(f"im1b{index}" in expression for index in range(1, 7))
    assert expression.count("im2b1 > 0") == 6
    assert "-123.5" in expression


def test_dry_run_builds_mask_and_statistics_commands_without_execution(
    tmp_path: Path, monkeypatch
) -> None:
    called = False

    def fail_run(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("dry run must not execute subprocesses")

    monkeypatch.setattr("shutil.which", fake_otb_path)
    monkeypatch.setattr(scaling.subprocess, "run", fail_run)
    report = run_scaling_step(make_config(tmp_path, dry_run=True))
    assert report["status"] == "dry_run"
    assert called is False
    assert len(report["otb_commands"]) == 2
    assert "BandMathX" in report["otb_commands"][0][0]
    assert "ComputeImagesStatistics" in report["otb_commands"][1][0]


def test_statistics_command_uses_background_and_xml_output(tmp_path: Path) -> None:
    config = make_config(tmp_path, background_value=-7)
    layout = build_level1b_scaling_layout(config.output_dir)
    command = build_statistics_command(
        config, {"ComputeImagesStatistics": "/fake/stats"}, layout
    )
    assert command[command.index("-bv") + 1] == "-7.0"
    assert command[command.index("-out.xml") + 1].endswith(
        "scaling_parameters.xml"
    )


def test_validation_rejects_missing_inputs_and_invalid_band_count(tmp_path: Path) -> None:
    config = make_config(
        tmp_path,
        feature_stack_path=tmp_path / "missing-stack.tif",
        valid_mask_path=tmp_path / "missing-mask.tif",
        band_count=0,
    )
    layout = build_level1b_scaling_layout(config.output_dir)
    checks, reasons = validate_scaling_config(
        config,
        layout,
        {"BandMathX": "/fake/bmx", "ComputeImagesStatistics": "/fake/stats"},
    )
    assert checks["feature_stack_path_exists"] is False
    assert checks["valid_mask_path_exists"] is False
    assert checks["band_count_positive_integer"] is False
    assert "band_count must be a positive integer" in reasons


def test_validation_rejects_missing_required_otb_apps(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    layout = build_level1b_scaling_layout(config.output_dir)
    checks, reasons = validate_scaling_config(
        config,
        layout,
        {"BandMathX": None, "ComputeImagesStatistics": None},
    )
    assert checks["otb_bandmathx_discoverable"] is False
    assert checks["otb_compute_images_statistics_discoverable"] is False
    assert "no OTB BandMathX app discoverable" in reasons
    assert "no OTB ComputeImagesStatistics app discoverable" in reasons


class _FakeBand:
    def __init__(self, values):
        self.values = np.asarray(values)

    def ReadAsArray(self):
        return self.values


class _FakeDataset:
    def __init__(self, bands):
        self.bands = bands

    def GetRasterBand(self, index):
        return _FakeBand(self.bands[index - 1])


def test_quantile_parameters_use_valid_finite_two_and_ninety_eight_percentiles(
    tmp_path: Path, monkeypatch
) -> None:
    background = -999999.0
    bands = []
    for offset in range(6):
        values = np.array(
            [[background, np.nan, offset], [offset + 1, offset + 2, offset + 100]],
            dtype=float,
        )
        bands.append(values)
    monkeypatch.setattr(scaling.gdal, "Open", lambda path: _FakeDataset(bands))
    stats = compute_quantile_scaling_parameters(
        tmp_path / "masked.tif",
        make_config(tmp_path, background_value=background, band_count=6),
    )
    assert len(stats["lower_values"]) == 6
    assert len(stats["upper_values"]) == 6
    for index, values in enumerate(bands):
        valid = values[(values != background) & np.isfinite(values)]
        lower, upper = np.quantile(valid, [0.02, 0.98])
        assert stats["lower_values"][index] == float(lower)
        assert stats["upper_values"][index] == float(upper)
        assert stats["centers"][index] == (float(lower) + float(upper)) / 2
        assert stats["scales"][index] == (float(upper) - float(lower)) / 2


def test_quantile_parameters_reject_empty_or_constant_valid_band(
    tmp_path: Path, monkeypatch
) -> None:
    config = make_config(tmp_path, band_count=1)
    for array, expected in (
        (np.full((2, 2), config.background_value), "no valid pixels"),
        (np.ones((2, 2)), "upper <= lower"),
    ):
        monkeypatch.setattr(
            scaling.gdal, "Open", lambda path, array=array: _FakeDataset([array])
        )
        try:
            compute_quantile_scaling_parameters(tmp_path / "masked.tif", config)
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("expected robust-scaling validation failure")


def test_quantile_scaling_command_clips_six_bands_to_minus_one_plus_one(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, band_count=6, background_value=-9)
    layout = build_level1b_scaling_layout(config.output_dir)
    stats = {
        "centers": [float(index) for index in range(1, 7)],
        "scales": [2.0] * 6,
    }
    command = build_quantile_scaling_command(
        config, {"BandMathX": "/fake/bmx"}, layout, stats
    )
    expression = command[-1]
    assert expression.count(";") == 5
    assert expression.count("< -1.0") == 6
    assert expression.count("> 1.0") == 6
    assert expression.count("im2b1 > 0") == 6
    assert all(f"im1b{index}" in expression for index in range(1, 7))
    assert "-9.0" in expression


def test_successful_run_writes_robust_percentile_parameters(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    def fake_run(command, capture_output, text):
        output = Path(command[command.index("-out") + 1]) if "-out" in command else None
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.touch()
        if "-out.xml" in command:
            xml = Path(command[command.index("-out.xml") + 1])
            xml.parent.mkdir(parents=True, exist_ok=True)
            xml.write_text("<stats/>")
        return subprocess.CompletedProcess(command, 0, "ok", "")

    stats = {
        "lower_values": [float(index) for index in range(6)],
        "upper_values": [float(index + 10) for index in range(6)],
        "centers": [float(index + 5) for index in range(6)],
        "scales": [5.0] * 6,
    }
    monkeypatch.setattr(scaling.subprocess, "run", fake_run)
    monkeypatch.setattr(
        scaling, "compute_quantile_scaling_parameters", lambda path, config: stats
    )
    report = run_scaling_step(make_config(tmp_path, band_count=6))
    parameters = json.loads(
        Path(report["scaling_parameters_json_path"]).read_text()
    )
    assert report["status"] == "ok"
    assert len(report["otb_commands"]) == 3
    assert parameters["method"] == "robust_percentile_clipped"
    assert parameters["lower_quantile"] == 0.02
    assert parameters["upper_quantile"] == 0.98
    assert parameters["output_min"] == -1.0
    assert parameters["output_max"] == 1.0
    assert parameters["band_count"] == 6
    assert parameters["lower_values"] == stats["lower_values"]
    assert parameters["upper_values"] == stats["upper_values"]
    assert report["scaled_output_created"] is True


def test_failed_subprocess_stops_without_parameters_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    monkeypatch.setattr(
        scaling.subprocess,
        "run",
        lambda command, capture_output, text: subprocess.CompletedProcess(
            command, 2, "", "failed"
        ),
    )
    report = run_scaling_step(make_config(tmp_path))
    assert report["status"] == "failed"
    assert report["command_results"][0]["returncode"] == 2
    assert report["scaling_parameters_json_written"] is False


def test_existing_output_is_preserved_without_overwrite(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    config = make_config(tmp_path)
    existing = Path(config.output_dir) / "level1b" / "scaling" / config.output_filename
    existing.parent.mkdir(parents=True)
    existing.write_text("keep")
    report = run_scaling_step(config)
    assert report["status"] == "failed"
    assert existing.read_text() == "keep"


def test_report_contains_exactly_current_report_keys(tmp_path: Path, monkeypatch) -> None:
    report = run_dry(tmp_path, monkeypatch)
    on_disk = json.loads(Path(report["report_path"]).read_text())
    assert tuple(report) == REPORT_KEYS
    assert set(on_disk) == set(REPORT_KEYS)


def test_zscore_builder_is_not_exposed() -> None:
    assert not hasattr(scaling, "build_zscore_scaling_command")
