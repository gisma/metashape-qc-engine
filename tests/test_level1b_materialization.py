from pathlib import Path

from metashape_qc_engine.level1b_materialization import (
    _selected_label_raster_path,
)


def test_selected_label_raster_uses_explicit_versioned_path() -> None:
    row = {
        "run_contract_version": 2,
        "merged_labels_path": "/canonical/run/merged_labels.tif",
        "masked_segmentation_stack_path": "/response/masked_segmentation_stack.tif",
    }

    assert _selected_label_raster_path(row) == Path(
        "/canonical/run/merged_labels.tif"
    )


def test_selected_label_raster_keeps_explicit_legacy_contract() -> None:
    row = {
        "masked_segmentation_stack_path": (
            "/legacy/run/masked_segmentation_stack.tif"
        )
    }

    assert _selected_label_raster_path(row) == Path(
        "/legacy/run/merged_labels.tif"
    )
