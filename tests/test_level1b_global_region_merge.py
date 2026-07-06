from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from metashape_qc_engine.level1b.global_region_merge import (
    GlobalRegionMergeConfig,
    build_initial_regions,
    merge_regions_global_rms,
    run_global_region_merge_poc,
)


def test_global_rms_stops_transitive_feature_chain() -> None:
    labels = np.array([[1, 2, 3]], dtype=np.uint32)
    features = np.array([[[0.0, 0.2, 0.4]]], dtype=np.float32)

    merged, diagnostics = merge_regions_global_rms(labels, features, 0.11)

    assert diagnostics["global_rms_contract_satisfied"] is True
    assert diagnostics["final_region_count"] == 2
    assert merged[0, 0] == merged[0, 1]
    assert merged[0, 2] != merged[0, 1]



def test_global_spatial_rms_stops_long_identical_chain() -> None:
    labels = np.arange(1, 7, dtype=np.uint32).reshape(1, 6)
    features = np.zeros((1, 1, 6), dtype=np.float32)

    merged, diagnostics = merge_regions_global_rms(
        labels, features, 1.0, max_spatial_rms_px=0.6
    )

    assert diagnostics["global_rms_contract_satisfied"] is True
    assert diagnostics["final_spatial_rms_px_max"] <= 0.6
    assert diagnostics["final_region_count"] == 3

def test_overdispersed_initial_block_is_split_before_merging() -> None:
    features = np.array([[[0.0, 0.0], [1.0, 1.0]]], dtype=np.float32)
    valid = np.ones((2, 2), dtype=bool)

    labels = build_initial_regions(features, valid, 2, 0.1)

    assert len(np.unique(labels[labels > 0])) == 4


def test_global_merge_is_deterministic() -> None:
    labels = np.array([[1, 2], [3, 4]], dtype=np.uint32)
    features = np.array([[[0.0, 0.05], [0.8, 0.85]]], dtype=np.float32)

    first, first_report = merge_regions_global_rms(labels, features, 0.08)
    second, second_report = merge_regions_global_rms(labels, features, 0.08)

    assert np.array_equal(first, second)
    assert first_report == second_report
    assert first_report["final_region_count"] == 2


def test_raster_poc_writes_labels_and_report(tmp_path: Path) -> None:
    stack_path = tmp_path / "stack.tif"
    mask_path = tmp_path / "mask.tif"
    profile = {
        "driver": "GTiff",
        "width": 4,
        "height": 4,
        "count": 1,
        "dtype": "float32",
        "transform": from_origin(0, 4, 1, 1),
    }
    with rasterio.open(stack_path, "w", **profile) as destination:
        destination.write(
            np.array(
                [[0.0, 0.0, 0.8, 0.8]] * 4,
                dtype=np.float32,
            ),
            1,
        )
    with rasterio.open(
        mask_path,
        "w",
        **{**profile, "dtype": "uint8"},
    ) as destination:
        destination.write(np.ones((4, 4), dtype=np.uint8), 1)

    result = run_global_region_merge_poc(
        GlobalRegionMergeConfig(
            feature_stack_path=stack_path,
            valid_mask_path=mask_path,
            output_dir=tmp_path / "out",
            max_region_rms=0.1,
            max_spatial_rms_px=2.0,
            initial_block_size_px=2,
        )
    )

    assert result["status"] == "global_region_merge_poc_ready"
    assert result["final_region_count"] == 2
    assert result["global_rms_contract_satisfied"] is True
    assert Path(result["labels_path"]).is_file()
    payload = json.loads(Path(result["report_path"]).read_text())
    assert payload["workflow_integrated"] is False
