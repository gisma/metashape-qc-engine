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


def test_one_scale_uses_masked_input_postmasks_labels_and_reports_contract(tmp_path: Path, monkeypatch) -> None:
    stack = tmp_path / "proxy_stack.tif"
    mask = tmp_path / "valid_mask.tif"
    candidates = tmp_path / "candidates.json"
    write_stack(stack)
    write_mask(mask)
    candidates.write_text(json.dumps({"candidates": [{"perturbation_id": "run-a", "scale_id": "s", "radius_m": 1.5, "spatialr_px": 2, "minsize_px": 3, "ranger": 0.4}]}), encoding="utf-8")
    monkeypatch.setattr(one, "discover_one_scale_segmentation_otb_apps", lambda: {name: name for name in (*one.OTB_APP_CLI_NAMES, "gdal_edit")})

    def fake_run(command, **_kwargs):
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        if "-fout" in command:
            Path(command[command.index("-fout") + 1]).write_bytes(b"smoothed")
            Path(command[command.index("-foutpos") + 1]).write_bytes(b"position")
        elif "-out" in command:
            Path(command[command.index("-out") + 1]).write_bytes(b"output")
        return Result()

    monkeypatch.setattr(one.subprocess, "run", fake_run)
    report = one.run_one_scale_segmentation_smoke(one.Level1BOneScaleSegmentationConfig(
        candidate_id="candidate", output_dir=tmp_path / "out", feature_space_stack_path=stack,
        segmentation_stack_path=stack, segmentation_stack_source="proxy_stack", valid_mask_path=mask,
        perturbation_candidates_json_path=candidates, perturbation_id="run-a",
    ))

    meanshift = next(command for command in report["otb_commands"] if command[0] == "otbcli_MeanShiftSmoothing")
    lsms = next(command for command in report["otb_commands"] if command[0] == "otbcli_LSMSSegmentation")
    stack_mask = next(command for command in report["otb_commands"] if "masked_segmentation_stack.tif" in " ".join(command) and command[0] == "otbcli_BandMathX")
    smoothed_mask = next(command for command in report["otb_commands"] if "meanshift_smoothed_masked.tif" in " ".join(command) and command[0] == "otbcli_BandMathX")
    position_mask = next(command for command in report["otb_commands"] if "meanshift_position_masked.tif" in " ".join(command) and command[0] == "otbcli_BandMathX")
    postmask = report["otb_commands"][-1]
    assert meanshift[meanshift.index("-in") + 1] == report["masked_segmentation_stack_path"]
    assert lsms[lsms.index("-in") + 1] == report["meanshift_smoothed_masked_path"]
    assert lsms[lsms.index("-inpos") + 1] == report["meanshift_position_masked_path"]
    assert report["otb_commands"].index(meanshift) < report["otb_commands"].index(smoothed_mask) < report["otb_commands"].index(lsms)
    assert report["otb_commands"].index(meanshift) < report["otb_commands"].index(position_mask) < report["otb_commands"].index(lsms)
    assert smoothed_mask[smoothed_mask.index("-il") + 2] == str(mask)
    assert position_mask[position_mask.index("-il") + 2] == str(mask)
    assert stack_mask[stack_mask.index("-exp") + 1] == "im2b1 > 0 ? im1 : im1 * 0"
    assert smoothed_mask[smoothed_mask.index("-exp") + 1] == "im2b1 > 0 ? im1 : im1 * 0"
    assert position_mask[position_mask.index("-exp") + 1] == "im2b1 > 0 ? im1 : im1 * 0"
    assert postmask[postmask.index("-exp") + 1] == "im2b1 > 0 ? im1b1 : 0"
    assert postmask[postmask.index("-il") + 2] == str(mask)
    assert report["segmentation_stack_path"] == str(stack)
    assert report["segmentation_stack_source"] == "proxy_stack"
    assert report["valid_mask_path"] == str(mask)
    assert report["scale_id"] == "s"
    assert report["radius_m"] == 1.5
    assert report["spatialr_px"] == 2
    assert report["minsize_px"] == 3
    assert report["segmentation_nodata_value"] == 0.0
    assert report["pre_lsms_mask_applied"] is True
    assert report["post_mask_applied"] is True
    assert report["label_invalid_support_value"] == 0
    assert report["meanshift_smoothed_path"].endswith("meanshift_smoothed.tif")
    assert report["meanshift_position_path"].endswith("meanshift_position.tif")
    assert report["meanshift_smoothed_masked_path"].endswith("meanshift_smoothed_masked.tif")
    assert report["meanshift_position_masked_path"].endswith("meanshift_position_masked.tif")
    assert report["labels_postmasked"] is True
    assert report["invalid_support_excluded_from_q_statistics"] is True
