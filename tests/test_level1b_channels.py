import json
from pathlib import Path
import subprocess

import pytest

import metashape_qc_engine.level1b.proxy_stack_rgb_dglcm as proxy_recipe
from metashape_qc_engine.level1b.channels import (
    GLCM_DIRECTIONS,
    REPORT_KEYS,
    RGB_CHANNEL_NAMES,
    Level1BChannelConfig,
    build_level1b_channel_layout,
    run_channel_construction_step,
)
from metashape_qc_engine.level1b.pca import Level1BPCAConfig


def fake_otb_path(executable_name: str) -> str:
    return f"/fake/bin/{executable_name}"


def make_input(tmp_path: Path, name: str = "input.tif") -> Path:
    path = tmp_path / name
    path.touch()
    return path


def make_mask(tmp_path: Path) -> Path:
    path = tmp_path / "valid_mask.tif"
    path.touch()
    return path


def run_rgb_dry(tmp_path: Path, monkeypatch, **overrides) -> dict[str, object]:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    values = {
        "candidate_id": "candidate-1",
        "input_path": make_input(tmp_path),
        "output_dir": tmp_path / "out",
        "input_type": "rgb",
        "valid_mask_path": make_mask(tmp_path),
        "pixel_size_m": 0.1,
        "dglcm_pc1_small_radius_m": 0.25,
        "dglcm_pc1_large_radius_m": 0.5,
        "dry_run": True,
    }
    values.update(overrides)
    return run_channel_construction_step(Level1BChannelConfig(**values))


def run_multi_dry(tmp_path: Path, monkeypatch, **overrides) -> dict[str, object]:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    values = {
        "candidate_id": "candidate-1",
        "input_path": make_input(tmp_path),
        "output_dir": tmp_path / "out",
        "input_type": "multichannel",
        "valid_mask_path": make_mask(tmp_path),
        "pixel_size_m": 0.5,
        "declared_channels": ("red", "nir"),
        "declared_band_indices": (3, 5),
        "dry_run": True,
    }
    values.update(overrides)
    return run_channel_construction_step(Level1BChannelConfig(**values))


def test_layout_creation(tmp_path: Path) -> None:
    layout = build_level1b_channel_layout(tmp_path / "out", tmp_path / "runtime")
    assert all(path.is_dir() for path in layout.values())


def test_rgb_report_declares_exact_six_band_normal_stack(tmp_path, monkeypatch) -> None:
    report = run_rgb_dry(tmp_path, monkeypatch)
    assert report["status"] == "dry_run"
    assert report["normal_stack"] == "exgr_exr_bri_directional_glcm_pc1"
    assert report["band_count"] == 6
    assert report["channel_names"] == RGB_CHANNEL_NAMES
    assert report["band_names"] == [
        "ExGR",
        "ExR",
        "BRI",
        "DGLCM_PC1_SMALL",
        "DGLCM_PC1_LARGE",
        "RATIO_DGLCM_PC1",
    ]
    assert report["structure_operator"] == "HaralickTextureExtraction"
    assert report["structure_feature"] == "simple.inertia"
    assert report["structure_feature_band"] == 5
    assert report["structure_source"] == "RGB_PC1"
    assert report["direction_aggregation"] == "max_over_0_45_90_135"
    assert report["glcm_directions"] == [[1, 0], [1, 1], [0, 1], [-1, 1]]


def test_rgb_builds_masked_rgb_then_reuses_existing_pca_commands(tmp_path, monkeypatch) -> None:
    report = run_rgb_dry(tmp_path, monkeypatch, rgb_band_indices=(3, 2, 1))
    commands = report["otb_commands"]
    masked_rgb, pca, pca_remask = commands[:3]
    assert "BandMathX" in masked_rgb[0]
    assert masked_rgb[-1] == (
        "{(im2b1 > 0 ? im1b3 : -999999.0);"
        "(im2b1 > 0 ? im1b2 : -999999.0);"
        "(im2b1 > 0 ? im1b1 : -999999.0)}"
    )
    assert "DimensionalityReduction" in pca[0]
    assert pca[pca.index("-nbcomp") + 1] == "1"
    assert pca[pca.index("-in") + 1].endswith("masked_rgb.tif")
    assert pca[pca.index("-normalize") + 1] == "false"
    assert "BandMathX" in pca_remask[0]
    assert report["mask_application"]["valid_mask_applied_to_rgb_before_pca"] is True


def test_pc1_quantization_contract_is_reported_and_commanded(tmp_path, monkeypatch) -> None:
    report = run_rgb_dry(tmp_path, monkeypatch)
    quantization = report["pc1_quantization"]
    assert quantization["clip_quantiles"] == [0.02, 0.98]
    assert quantization["output_min"] == 0
    assert quantization["output_max"] == 255
    assert quantization["nbbin"] == 32
    command = report["otb_commands"][3]
    assert command.count("-il") == 1
    assert command[command.index("-il") + 1].endswith("rgb_pc1.tif")
    assert "PC1_Q02" in command[-1]
    assert "PC1_Q98" in command[-1]
    assert "255.0" in command[-1]


def test_exactly_eight_directional_haralick_simple_calls(tmp_path, monkeypatch) -> None:
    report = run_rgb_dry(tmp_path, monkeypatch, pixel_size_m=0.1)
    commands = [
        command
        for command in report["otb_commands"]
        if "HaralickTextureExtraction" in command[0]
    ]
    assert len(commands) == 8
    expected = list(GLCM_DIRECTIONS) * 2
    observed = [
        (
            int(command[command.index("-parameters.xoff") + 1]),
            int(command[command.index("-parameters.yoff") + 1]),
        )
        for command in commands
    ]
    assert observed == expected
    assert [int(command[command.index("-parameters.xrad") + 1]) for command in commands] == [2] * 4 + [5] * 4
    for command in commands:
        assert command[command.index("-texture") + 1] == "simple"
        assert command[command.index("-parameters.min") + 1] == "0"
        assert command[command.index("-parameters.max") + 1] == "255"
        assert command[command.index("-parameters.nbbin") + 1] == "32"


def test_direction_aggregation_uses_max_of_inertia_band_five(tmp_path, monkeypatch) -> None:
    report = run_rgb_dry(tmp_path, monkeypatch)
    max_commands = [
        command
        for command in report["otb_commands"]
        if command[-1] == "max(max(im1b5,im2b5),max(im3b5,im4b5))"
    ]
    assert len(max_commands) == 2
    assert all(len(command[command.index("-il") + 1 : command.index("-out")]) == 4 for command in max_commands)


def test_final_stack_has_rgb_proxies_structure_bands_and_ratio(tmp_path, monkeypatch) -> None:
    report = run_rgb_dry(tmp_path, monkeypatch, rgb_band_indices=(3, 2, 1))
    expression = report["otb_commands"][-1][-1]
    assert "2*im1b2 - im1b3 - im1b1" in expression
    assert "1.4*im1b3 - im1b1" in expression
    assert "(im1b3 + im1b2 + im1b1) / 3" in expression
    assert "im2b1 / (im3b1 + 1e-06)" in expression
    assert report["ratio_formula"] == "DGLCM_PC1_SMALL / (DGLCM_PC1_LARGE + eps)"
    assert report["ratio_eps"] == 1e-6


def test_metric_radii_use_max_one_round_rule(tmp_path, monkeypatch) -> None:
    report = run_rgb_dry(tmp_path, monkeypatch, pixel_size_m=0.4)
    assert report["small_radius_m"] == 0.25
    assert report["large_radius_m"] == 0.5
    assert report["small_radius_px"] == 1
    assert report["large_radius_px"] == 1
    assert report["derived_radius_px"] == {
        "DGLCM_PC1_SMALL": 1,
        "DGLCM_PC1_LARGE": 1,
    }


def test_old_local_statistic_stack_is_absent(tmp_path, monkeypatch) -> None:
    report = run_rgb_dry(tmp_path, monkeypatch)
    serialized = json.dumps(report)
    assert "LocalStatisticExtraction" not in serialized
    assert "TEX_100M" not in serialized
    assert "TEX_200M" not in serialized


@pytest.mark.parametrize(
    ("missing", "reason"),
    [
        ("otbcli_BandMathX", "no OTB BandMathX app discoverable"),
        (
            "otbcli_DimensionalityReduction",
            "no OTB DimensionalityReduction app discoverable",
        ),
        (
            "otbcli_HaralickTextureExtraction",
            "no OTB HaralickTextureExtraction app discoverable",
        ),
    ],
)
def test_rgb_fails_when_required_otb_app_is_missing(
    tmp_path, monkeypatch, missing, reason
) -> None:
    monkeypatch.setattr(
        "shutil.which",
        lambda name: None if name == missing else fake_otb_path(name),
    )
    report = run_channel_construction_step(
        Level1BChannelConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
            valid_mask_path=make_mask(tmp_path),
            pixel_size_m=0.1,
            dry_run=True,
        )
    )
    assert report["status"] == "failed"
    assert reason in report["failure_reasons"]


def test_actual_rgb_execution_calls_existing_pca_and_valid_quantiles(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    pca_configs = []

    def fake_subprocess(command, capture_output, text, **kwargs):
        assert kwargs["env"]["PATH"]
        return subprocess.CompletedProcess(command, 0, "ok", "")

    def fake_pca(config):
        pca_configs.append(config)
        return {"status": "ok", "command_results": []}

    monkeypatch.setattr(proxy_recipe.subprocess, "run", fake_subprocess)
    monkeypatch.setattr(proxy_recipe, "run_pca_step", fake_pca)
    monkeypatch.setattr(
        proxy_recipe,
        "compute_quantile_scaling_parameters",
        lambda path, config, **kwargs: {
            "lower_values": [-12.5],
            "upper_values": [42.5],
        },
    )
    report = run_channel_construction_step(
        Level1BChannelConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
            valid_mask_path=make_mask(tmp_path),
            pixel_size_m=0.1,
        )
    )
    assert report["status"] == "ok"
    assert report["output_created"] is True
    assert len(pca_configs) == 1
    assert isinstance(pca_configs[0], Level1BPCAConfig)
    assert pca_configs[0].band_count == 3
    assert pca_configs[0].pca_components == 1
    assert str(pca_configs[0].scaled_feature_stack_path).endswith("masked_rgb.tif")
    assert report["pc1_quantization"]["valid_pixel_clip_values"] == {
        "lower": -12.5,
        "upper": 42.5,
    }


def test_invalid_radii_are_rejected(tmp_path, monkeypatch) -> None:
    report = run_rgb_dry(
        tmp_path,
        monkeypatch,
        dglcm_pc1_small_radius_m=0.5,
        dglcm_pc1_large_radius_m=0.5,
    )
    assert report["status"] == "failed"
    assert report["checks"]["texture_radius_order_valid"] is False


def test_multichannel_path_remains_direct_and_has_no_rgb_structure_apps(tmp_path, monkeypatch) -> None:
    report = run_multi_dry(tmp_path, monkeypatch)
    assert report["status"] == "dry_run"
    assert report["channel_names"] == ["red", "nir"]
    assert len(report["otb_commands"]) == 1
    assert "HaralickTextureExtraction" not in report["otb_apps"]
    assert "DimensionalityReduction" not in report["otb_apps"]


def test_report_contains_exactly_required_keys(tmp_path, monkeypatch) -> None:
    report = run_rgb_dry(tmp_path, monkeypatch)
    on_disk = json.loads(Path(report["report_path"]).read_text())
    assert tuple(report) == REPORT_KEYS
    assert tuple(on_disk) == REPORT_KEYS


def test_recipe_band_list_is_the_single_source_of_band_names_and_count(
    tmp_path, monkeypatch
) -> None:
    original = proxy_recipe.rgb_dglcm_pc1_band_definitions

    def extended(rgb_band_indices, ratio_eps):
        bands, expressions = original(rgb_band_indices, ratio_eps)
        return [*bands, ("EXTRA_TEST_CHANNEL", "im1b1")], expressions

    monkeypatch.setattr(
        proxy_recipe, "rgb_dglcm_pc1_band_definitions", extended
    )
    report = run_rgb_dry(tmp_path, monkeypatch)

    assert report["band_count"] == 7
    assert report["band_names"][-1] == "EXTRA_TEST_CHANNEL"
    assert report["otb_commands"][-1][-1].count(";") == 6


def test_yaml_controlled_recipe_parameters_reach_commands_and_report(
    tmp_path, monkeypatch
) -> None:
    report = run_rgb_dry(
        tmp_path,
        monkeypatch,
        pc1_clip_quantiles=(0.1, 0.9),
        pc1_output_min=5,
        pc1_output_max=200,
        glcm_nbbin=16,
        glcm_directions=((2, 0), (0, 2)),
        ratio_eps=0.001,
    )

    haralick = [
        command
        for command in report["otb_commands"]
        if "HaralickTextureExtraction" in command[0]
    ]
    assert len(haralick) == 4
    assert report["pc1_quantization"]["clip_quantiles"] == [0.1, 0.9]
    assert report["pc1_quantization"]["output_min"] == 5
    assert report["pc1_quantization"]["output_max"] == 200
    assert report["pc1_quantization"]["nbbin"] == 16
    assert "PC1_Q10" in report["otb_commands"][3][-1]
    assert "PC1_Q90" in report["otb_commands"][3][-1]
    assert all(command[command.index("-parameters.nbbin") + 1] == "16" for command in haralick)
    assert all(command[command.index("-parameters.min") + 1] == "5" for command in haralick)
    assert all(command[command.index("-parameters.max") + 1] == "200" for command in haralick)
    assert "0.001" in report["otb_commands"][-1][-1]
