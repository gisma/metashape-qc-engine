import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import metashape_qc_engine.level1b_channels as channels
from metashape_qc_engine.level1b_channels import (
    REPORT_KEYS,
    Level1BChannelConfig,
    build_level1b_channel_layout,
    run_channel_construction_step,
)


def fake_otb_path(executable_name: str) -> str:
    return f"/fake/bin/{executable_name}"


def fake_missing_local_stat(executable_name: str) -> str | None:
    if executable_name == "otbcli_LocalStatisticExtraction":
        return None
    return fake_otb_path(executable_name)


def make_input(tmp_path: Path, name: str = "input.tif") -> Path:
    input_path = tmp_path / name
    input_path.touch()
    return input_path


def make_mask(tmp_path: Path) -> Path:
    mask_path = tmp_path / "valid_mask.tif"
    mask_path.touch()
    return mask_path


def run_rgb_dry(tmp_path: Path, monkeypatch, **overrides: object) -> dict[str, object]:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    values = {
        "candidate_id": "candidate-1",
        "input_path": make_input(tmp_path),
        "output_dir": tmp_path / "out",
        "input_type": "rgb",
        "valid_mask_path": make_mask(tmp_path),
        "pixel_size_m": 0.5,
        "dry_run": True,
    }
    values.update(overrides)
    return run_channel_construction_step(Level1BChannelConfig(**values))


def run_multi_dry(tmp_path: Path, monkeypatch, **overrides: object) -> dict[str, object]:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    values = {
        "candidate_id": "candidate-1",
        "input_path": make_input(tmp_path),
        "output_dir": tmp_path / "out",
        "input_type": "multichannel",
        "valid_mask_path": make_mask(tmp_path),
        "pixel_size_m": 0.5,
        "declared_channels": (" red ", "nir"),
        "declared_band_indices": (3, 5),
        "dry_run": True,
    }
    values.update(overrides)
    return run_channel_construction_step(Level1BChannelConfig(**values))


def test_layout_creation(tmp_path: Path) -> None:
    custom_tmp = tmp_path / "runtime-tmp"
    layout = build_level1b_channel_layout(tmp_path / "out", custom_tmp)

    assert layout["default_tmp_dir"] == tmp_path / "out" / "level1b" / "tmp"
    assert layout["runtime_tmp_dir"] == custom_tmp
    assert layout["default_tmp_dir"].is_dir()
    assert layout["runtime_tmp_dir"].is_dir()
    assert layout["logs_dir"].is_dir()
    assert layout["reports_dir"].is_dir()
    assert layout["channels_dir"].is_dir()


def test_rgb_dry_run_builds_five_channel_names(tmp_path: Path, monkeypatch) -> None:
    report = run_rgb_dry(tmp_path, monkeypatch)

    assert report["status"] == "dry_run"
    assert report["channel_names"] == ["VIG", "DRY", "BRI", "TEX_100M", "TEX_200M"]
    assert report["output_path"].endswith("proxy_stack.tif")
    assert report["output_filename"] == "proxy_stack.tif"


def test_rgb_dry_run_builds_expressions_from_original_rgb_bands(tmp_path: Path, monkeypatch) -> None:
    report = run_rgb_dry(tmp_path, monkeypatch, rgb_band_indices=(3, 2, 1))
    joined = "\n".join(" ".join(command) for command in report["otb_commands"])

    assert "2*im1b2 - im1b3 - im1b1" in joined
    assert "1.4*im1b3 - im1b1" in joined
    assert "(im1b3 + im1b2 + im1b1) / 3" in joined
    assert "im2b2" in joined
    assert "im3b2" in joined


def test_rgb_proxy_commands_apply_valid_mask(tmp_path: Path, monkeypatch) -> None:
    mask_path = make_mask(tmp_path)
    report = run_rgb_dry(tmp_path, monkeypatch, valid_mask_path=mask_path)
    joined = "\n".join(" ".join(command) for command in report["otb_commands"])

    assert str(mask_path) in report["otb_commands"][0]
    assert str(mask_path) in report["otb_commands"][-1]
    assert "im2b1 > 0" in report["otb_commands"][0][-1]
    assert "im4b1 > 0" in report["otb_commands"][-1][-1]
    assert str(mask_path) in joined


def test_rgb_dry_run_builds_local_statistic_commands_for_texture(tmp_path: Path, monkeypatch) -> None:
    report = run_rgb_dry(tmp_path, monkeypatch, pixel_size_m=1.0)
    commands = report["otb_commands"]

    local_commands = [command for command in commands if "LocalStatisticExtraction" in command[0]]
    assert len(local_commands) == 2
    assert local_commands[0][-2:] == ["-radius", "1"]
    assert local_commands[1][-2:] == ["-radius", "2"]
    assert "exgr_tmp.tif" in local_commands[0][local_commands[0].index("-in") + 1]


def test_rgb_derived_radii_are_reported_from_pixel_size(tmp_path: Path, monkeypatch) -> None:
    report = run_rgb_dry(tmp_path, monkeypatch, pixel_size_m=0.4)

    assert report["derived_radius_px"] == {"TEX_100M": 2, "TEX_200M": 5}


def test_rgb_fails_if_bandmathx_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)

    report = run_channel_construction_step(
        Level1BChannelConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
            valid_mask_path=make_mask(tmp_path),
            pixel_size_m=1.0,
            dry_run=True,
        )
    )

    assert report["status"] == "failed"
    assert "no OTB BandMathX app discoverable" in report["failure_reasons"]


def test_rgb_fails_if_local_statistic_extraction_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_missing_local_stat)

    report = run_channel_construction_step(
        Level1BChannelConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
            valid_mask_path=make_mask(tmp_path),
            pixel_size_m=1.0,
            dry_run=True,
        )
    )

    assert report["status"] == "failed"
    assert "no OTB LocalStatisticExtraction app discoverable" in report["failure_reasons"]


def test_multichannel_dry_run_builds_channel_stack(tmp_path: Path, monkeypatch) -> None:
    report = run_multi_dry(tmp_path, monkeypatch)

    assert report["status"] == "dry_run"
    assert report["output_filename"] == "channel_stack.tif"
    assert report["output_path"].endswith("channel_stack.tif")


def test_multichannel_uses_declared_names_and_band_indices_in_order(tmp_path: Path, monkeypatch) -> None:
    report = run_multi_dry(
        tmp_path,
        monkeypatch,
        declared_channels=("blue", "green", "red"),
        declared_band_indices=(1, 2, 3),
    )

    assert report["channel_names"] == ["blue", "green", "red"]
    assert report["declared_band_indices"] == [1, 2, 3]
    assert report["otb_commands"][0][-1] == "{(im2b1 > 0 ? im1b1 : 0);(im2b1 > 0 ? im1b2 : 0);(im2b1 > 0 ? im1b3 : 0)}"


def test_multichannel_stack_command_applies_valid_mask(tmp_path: Path, monkeypatch) -> None:
    mask_path = make_mask(tmp_path)
    report = run_multi_dry(tmp_path, monkeypatch, valid_mask_path=mask_path)
    command = report["otb_commands"][0]

    assert str(mask_path) in command
    assert command[command.index("-il") + 1 : command.index("-out")] == [str(report["input_path"]), str(mask_path)]
    assert "im2b1 > 0" in command[-1]


def test_multichannel_does_not_call_local_statistic_extraction(tmp_path: Path, monkeypatch) -> None:
    report = run_multi_dry(tmp_path, monkeypatch)
    joined = "\n".join(" ".join(command) for command in report["otb_commands"])

    assert "LocalStatisticExtraction" not in joined
    assert "LocalStatisticExtraction" not in report["otb_apps"]


def test_validation_catches_missing_input_missing_mask_invalid_type_bad_pixel_size(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_channel_construction_step(
        Level1BChannelConfig(
            candidate_id="candidate-1",
            input_path=tmp_path / "missing.tif",
            output_dir=tmp_path / "out",
            input_type="pan",
            valid_mask_path=tmp_path / "missing-mask.tif",
            pixel_size_m=0,
            dry_run=True,
        )
    )

    assert report["status"] == "failed"
    assert report["checks"]["input_path_exists"] is False
    assert report["checks"]["valid_mask_path_exists"] is False
    assert report["checks"]["input_type_valid"] is False
    assert report["checks"]["pixel_size_m_valid"] is False


def test_validation_catches_invalid_rgb_generic_declarations(tmp_path: Path, monkeypatch) -> None:
    report = run_rgb_dry(
        tmp_path,
        monkeypatch,
        rgb_band_indices=(1, 0, 3),
        declared_channels=("nir",),
        declared_band_indices=(4,),
    )

    assert report["status"] == "failed"
    assert report["checks"]["rgb_band_indices_valid"] is False
    assert report["checks"]["rgb_declared_channels_absent"] is False
    assert report["checks"]["rgb_declared_band_indices_absent"] is False


def test_validation_catches_invalid_multichannel_declarations(tmp_path: Path, monkeypatch) -> None:
    report = run_multi_dry(
        tmp_path,
        monkeypatch,
        declared_channels=("red", " red "),
        declared_band_indices=(1, 0, 3),
    )

    assert report["status"] == "failed"
    assert report["checks"]["multichannel_declared_channels_unique"] is False
    assert report["checks"]["multichannel_declared_band_indices_length"] is False
    assert report["checks"]["multichannel_declared_band_indices_valid"] is False

    missing = run_multi_dry(tmp_path, monkeypatch, declared_channels=None, declared_band_indices=None)
    assert missing["checks"]["multichannel_declared_channels_present"] is False
    assert missing["checks"]["multichannel_declared_band_indices_present"] is False


def test_validation_catches_invalid_texture_radii_and_derived_radii_below_one(tmp_path: Path, monkeypatch) -> None:
    bad_order = run_rgb_dry(tmp_path, monkeypatch, tex_100m_radius_m=2.0, tex_200m_radius_m=2.0)
    below_one = run_rgb_dry(
        tmp_path,
        monkeypatch,
        output_dir=tmp_path / "out2",
        tex_100m_radius_m=0.1,
        tex_200m_radius_m=0.2,
        pixel_size_m=1.0,
    )

    assert bad_order["status"] == "failed"
    assert bad_order["checks"]["texture_radius_order_valid"] is False
    assert below_one["status"] == "failed"
    assert below_one["checks"]["derived_radius_px_valid"] is False


def test_dry_run_does_not_call_subprocess(tmp_path: Path, monkeypatch) -> None:
    called = {"value": False}

    def fake_run(*_args: object, **_kwargs: object) -> object:
        called["value"] = True
        raise AssertionError("process must not run")

    monkeypatch.setattr("metashape_qc_engine.level1b_channels.subprocess.run", fake_run)

    report = run_rgb_dry(tmp_path, monkeypatch)

    assert called["value"] is False
    assert report["output_created"] is False


def test_mocked_subprocess_success_returns_ok(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    def fake_run(command: list[str], capture_output: bool, text: bool) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "ok", "")

    monkeypatch.setattr("metashape_qc_engine.level1b_channels.subprocess.run", fake_run)

    report = run_channel_construction_step(
        Level1BChannelConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
            valid_mask_path=make_mask(tmp_path),
            pixel_size_m=1.0,
        )
    )

    assert report["status"] == "ok"
    assert report["output_created"] is True
    assert len(report["command_results"]) == 4


def test_mocked_subprocess_failure_returns_failed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    def fake_run(command: list[str], capture_output: bool, text: bool) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 8, "", "failed")

    monkeypatch.setattr("metashape_qc_engine.level1b_channels.subprocess.run", fake_run)

    report = run_channel_construction_step(
        Level1BChannelConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="multichannel",
            valid_mask_path=make_mask(tmp_path),
            pixel_size_m=1.0,
            declared_channels=("red",),
            declared_band_indices=(1,),
        )
    )

    assert report["status"] == "failed"
    assert report["output_created"] is False
    assert report["command_results"][0]["returncode"] == 8


def test_report_contains_exactly_required_report_keys(tmp_path: Path, monkeypatch) -> None:
    report = run_rgb_dry(tmp_path, monkeypatch)
    report_json = json.loads(Path(report["report_path"]).read_text(encoding="utf-8"))

    assert tuple(report.keys()) == REPORT_KEYS
    assert tuple(report_json.keys()) == REPORT_KEYS


def test_source_has_no_forbidden_raster_imports_or_workflow_symbols() -> None:
    channel_source = Path(channels.__file__).read_text(encoding="utf-8")
    test_source = Path(__file__).read_text(encoding="utf-8")
    forbidden_import_parts = [
        "rast" + "erio",
        "os" + "geo",
        "g" + "dal",
        "num" + "py",
        "sci" + "py",
        "ski" + "mage",
        "c" + "v2",
        "P" + "IL",
        "xa" + "rray",
        "rio" + "xa" + "rray",
        "pan" + "das",
        "geo" + "pan" + "das",
        "ter" + "ra",
        "sta" + "rs",
        "link" + "2GI",
    ]
    forbidden_workflow_parts = [
        "run_" + "otb_app",
        "OTBCommand" + "Result",
        "OTBCommand" + "Error",
        "Band" + "Math ",
        "Har" + "alick",
        "So" + "bel",
        "ED" + "GE",
        "VEG_" + "NBH",
        "N" + "BR",
        "Mean" + "Shift",
        "LS" + "MS",
        "Ho" + "over",
        "Zonal" + "Statistics",
        "Compute" + "ImagesStatistics",
        "Train" + "DimensionalityReduction",
        "Image" + "DimensionalityReduction",
        "scale_" + "candidates",
        "scaled_" + "feature_stack",
    ]

    for token in forbidden_import_parts:
        assert token not in channel_source
        assert token not in test_source
    for token in forbidden_workflow_parts:
        assert token not in channel_source
