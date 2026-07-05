import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from metashape_qc_engine import level1b_one_scale_segmentation as one


def write_stack(path: Path, band_count: int = 5) -> Path:
    data = np.arange(band_count * 6, dtype=np.float32).reshape(band_count, 2, 3)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=3,
        height=2,
        count=band_count,
        dtype="float32",
        transform=from_origin(0, 2, 1, 1),
    ) as dataset:
        dataset.write(data)
    return path


def write_mask(path: Path) -> Path:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=3,
        height=2,
        count=1,
        dtype="uint8",
        transform=from_origin(0, 2, 1, 1),
    ) as dataset:
        dataset.write(np.array([[1, 0, 1], [0, 1, 0]], dtype=np.uint8), 1)
    return path


def test_read_perturbation_candidates_accepts_midpoint_list_payload(tmp_path: Path) -> None:
    path = tmp_path / "step9b_midpoint_perturbation_candidates.json"
    rows = [
        {
            "perturbation_id": "local_midpoint__baseline",
            "scale_id": "local_midpoint",
            "spatialr_px": 61,
            "minsize_px": 12327,
            "ranger": 0.7,
        }
    ]
    path.write_text(json.dumps(rows), encoding="utf-8")

    assert one.read_perturbation_candidates(path) == rows


def test_report_is_serialized_once_and_success_output_is_compact(
    tmp_path: Path, monkeypatch
) -> None:
    config = one.Level1BOneScaleSegmentationConfig(
        candidate_id="candidate",
        output_dir=tmp_path / "out",
        feature_space_stack_path=tmp_path / "stack.tif",
        perturbation_candidates_json_path=tmp_path / "candidates.json",
        perturbation_id="run-a",
    )
    layout = one.build_level1b_one_scale_segmentation_layout(
        config.output_dir, config.perturbation_id
    )
    report = one._base_report(config, layout, {}, [], {})
    report["status"] = "ok"
    report["command_results"] = [
        {
            "command": ["otbcli_Test"],
            "returncode": 0,
            "stdout": "verbose successful output",
            "stderr": "successful warning",
        }
    ]
    original_dump = one.json.dump
    dump_calls = []

    def counting_dump(*args, **kwargs):
        dump_calls.append(None)
        return original_dump(*args, **kwargs)

    monkeypatch.setattr(one.json, "dump", counting_dump)
    written = one._write_report(report, layout)

    assert len(dump_calls) == 1
    assert written["command_results"] == [
        {"command": ["otbcli_Test"], "returncode": 0}
    ]
    assert json.loads(
        (layout["smoke_dir"] / one.REPORT_FILENAME).read_text(encoding="utf-8")
    ) == written


def test_failed_or_debug_report_retains_full_command_output(tmp_path: Path) -> None:
    for status, debug in (("failed", False), ("ok", True)):
        config = one.Level1BOneScaleSegmentationConfig(
            candidate_id="candidate",
            output_dir=tmp_path / status,
            feature_space_stack_path=tmp_path / "stack.tif",
            perturbation_candidates_json_path=tmp_path / "candidates.json",
            perturbation_id="run-a",
            debug_command_output=debug,
        )
        layout = one.build_level1b_one_scale_segmentation_layout(
            config.output_dir, config.perturbation_id
        )
        report = one._base_report(config, layout, {}, [], {})
        report["status"] = status
        report["command_results"] = [
            {
                "command": ["otbcli_Test"],
                "returncode": 1 if status == "failed" else 0,
                "stdout": "diagnostic stdout",
                "stderr": "diagnostic stderr",
            }
        ]

        written = one._write_report(report, layout)

        assert written["command_results"][0]["stdout"] == "diagnostic stdout"
        assert written["command_results"][0]["stderr"] == "diagnostic stderr"


def test_matrix_zero_mask_expression_is_accepted_by_otb_when_available(tmp_path: Path) -> None:
    otb = shutil.which("otbcli_BandMathX")
    if otb is None:
        pytest.skip("OTB BandMathX is not available on PATH")
    source = write_stack(tmp_path / "source.tif")
    mask = write_mask(tmp_path / "mask.tif")
    output = tmp_path / "masked.tif"

    result = subprocess.run(
        [
            otb,
            "-il",
            str(source),
            str(mask),
            "-exp",
            "im2b1 > 0 ? im1 : im1 * 0",
            "-out",
            str(output),
            "float",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    with rasterio.open(output) as dataset:
        assert dataset.count == 5
        masked = dataset.read()
    assert np.all(masked[:, 0, 1] == 0)
    assert np.all(masked[:, 1, 0] == 0)
    assert np.all(masked[:, 1, 2] == 0)


def test_one_scale_uses_saga_with_candidate_spatial_and_feature_parameters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack = write_stack(tmp_path / "proxy_stack.tif", band_count=6)
    mask = write_mask(tmp_path / "valid_mask.tif")
    candidates = tmp_path / "candidates.json"
    candidates.write_text(json.dumps({"candidates": [{"perturbation_id": "run-a", "scale_id": "s", "radius_m": 1.5, "spatialr_px": 2, "minsize_px": 3, "ranger": 0.4}]}), encoding="utf-8")
    monkeypatch.setattr(one, "discover_one_scale_segmentation_otb_apps", lambda: {"BandMathX": "otbcli_BandMathX", "gdal_edit": "gdal_edit.py", "saga_cmd": "/usr/bin/saga_cmd"})
    mask_commands = []

    def fake_run(command, **_kwargs):
        mask_commands.append(command)
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""
        if "-out" in command:
            Path(command[command.index("-out") + 1]).write_bytes(b"masked")
        return Result()

    monkeypatch.setattr(one.subprocess, "run", fake_run)
    monkeypatch.setattr(one, "prepare_saga_feature_grids", lambda *_args, **_kwargs: {"grid_paths": [str(tmp_path / "feature.sgrd")]})
    saga_calls = []

    def fake_saga(**kwargs):
        saga_calls.append(kwargs)
        Path(kwargs["output_labels_path"]).write_bytes(b"labels")
        return {"commands": [["saga_cmd", "imagery_segmentation", "2"]], "command_results": [{"command": ["saga_cmd"], "returncode": 0, "stdout": "", "stderr": ""}], "seed_policy": "hex_lattice_local_variance_minimum", "seed_report_path": str(tmp_path / "controlled_seed_report.json"), "seed_report": {"seed_count": 2}}

    monkeypatch.setattr(one, "run_saga_seeded_region_growing", fake_saga)
    report = one.run_one_scale_segmentation_smoke(one.Level1BOneScaleSegmentationConfig(
        candidate_id="candidate", output_dir=tmp_path / "out", feature_space_stack_path=stack,
        segmentation_stack_path=stack, segmentation_stack_source="scaled_proxy_stack", valid_mask_path=mask,
        perturbation_candidates_json_path=candidates, perturbation_id="run-a",
    ))

    assert report["status"] == "ok"
    assert report["segmentation_backend"] == "saga_seeded_region_growing"
    assert report["saga_seed_policy"] == "hex_lattice_local_variance_minimum"
    assert report["saga_seed_report"]["seed_count"] == 2
    assert report["saga_variance_band_width_px"] == 2
    assert report["saga_feature_variance"] == pytest.approx(0.4)
    assert report["saga_position_variance_px"] == pytest.approx(2.0)
    assert report["saga_similarity_threshold"] == 0.0
    assert len(saga_calls) == 1
    assert saga_calls[0]["spatial_radius_px"] == 2
    assert saga_calls[0]["feature_variance"] == pytest.approx(0.4)
    assert len(mask_commands) == 2
    assert report["segmentation_stack_path"] == str(stack)
    assert report["segmentation_stack_source"] == "scaled_proxy_stack"
    assert report["valid_mask_path"] == str(mask)
    assert report["scale_id"] == "s"
    assert report["radius_m"] == 1.5
    assert report["spatialr_px"] == 2
    assert report["minsize_px"] == 3
    assert report["pre_lsms_mask_applied"] is False
    assert report["pre_segmentation_mask_applied"] is True
    assert report["post_mask_applied"] is True
    assert report["label_invalid_support_value"] == 0
    assert report["merged_labels_path"].endswith("merged_labels.tif")
    assert report["labels_postmasked"] is True
    assert report["invalid_support_excluded_from_q_statistics"] is True


def test_one_scale_reuses_prebuilt_masked_stack_and_canonical_saga_grids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack = write_stack(tmp_path / "proxy_stack.tif", band_count=6)
    mask = write_mask(tmp_path / "valid_mask.tif")
    canonical = write_stack(tmp_path / "canonical_masked_stack.tif", band_count=6)
    candidates = tmp_path / "candidates.json"
    candidates.write_text(json.dumps({"candidates": [{"perturbation_id": "run-a", "scale_id": "s", "radius_m": 1.5, "spatialr_px": 2, "minsize_px": 3, "ranger": 0.4}]}), encoding="utf-8")
    monkeypatch.setattr(one, "discover_one_scale_segmentation_otb_apps", lambda: {"saga_cmd": "/usr/bin/saga_cmd", "BandMathX": None, "gdal_edit": None})
    monkeypatch.setattr(one, "prepare_saga_feature_grids", lambda _source, _mask, output, **_kwargs: {"grid_paths": [str(Path(output) / "feature_001.sgrd")]})
    saga_calls = []

    def fake_saga(**kwargs):
        saga_calls.append(kwargs)
        Path(kwargs["output_labels_path"]).write_bytes(b"labels")
        return {"commands": [["saga_cmd"]], "command_results": [], "seed_policy": "hex_lattice_local_variance_minimum", "seed_report_path": str(tmp_path / "controlled_seed_report.json"), "seed_report": {"seed_count": 2}}

    monkeypatch.setattr(one, "run_saga_seeded_region_growing", fake_saga)
    report = one.run_one_scale_segmentation_smoke(one.Level1BOneScaleSegmentationConfig(
        candidate_id="candidate", output_dir=tmp_path / "out", feature_space_stack_path=stack,
        segmentation_stack_path=stack, segmentation_stack_source="scaled_proxy_stack",
        masked_segmentation_stack_path=canonical, masked_segmentation_stack_scope="response_surface_canonical",
        run_contract_version=5, valid_mask_path=mask, perturbation_candidates_json_path=candidates,
        perturbation_id="run-a",
    ))

    assert report["status"] == "ok"
    assert report["otb_commands"] == []
    assert len(saga_calls) == 1
    assert saga_calls[0]["reference_raster_path"] == canonical
    assert report["masked_segmentation_stack_path"] == str(canonical)
    assert report["masked_segmentation_stack_scope"] == "response_surface_canonical"
    assert report["run_contract_version"] == 5
    assert report["segmentation_backend"] == "saga_seeded_region_growing"
    assert "masked_segmentation_stack.tif" not in report["files_written"]


def test_canonical_masked_stack_preparation_is_reused_by_exact_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = write_stack(tmp_path / "source.tif")
    mask = write_mask(tmp_path / "mask.tif")
    output = tmp_path / "response_surface" / "masked_segmentation_stack.tif"
    commands = []

    def fake_run(command, **_kwargs):
        commands.append(command)

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        if "-out" in command:
            target = Path(command[command.index("-out") + 1])
            target.write_bytes(b"canonical")
        return Result()

    monkeypatch.setattr(one.subprocess, "run", fake_run)

    first = one.prepare_canonical_masked_segmentation_stack(
        source, mask, output
    )
    second = one.prepare_canonical_masked_segmentation_stack(
        source, mask, output
    )

    assert first["status"] == "ok"
    assert first["preparation_status"] == "computed"
    assert second["status"] == "ok"
    assert second["preparation_status"] == "reused"
    assert len(commands) == 2
    assert output.read_bytes() == b"canonical"
    assert output.with_name("masked_segmentation_stack_report.json").exists()
