from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from metashape_qc_engine import level1b_saga_segmentation as saga


def write_inputs(tmp_path: Path) -> tuple[Path, Path, np.ndarray, np.ndarray]:
    stack = tmp_path / "stack.tif"
    mask_path = tmp_path / "mask.tif"
    values = np.arange(2 * 3 * 4, dtype=np.float32).reshape(2, 3, 4)
    mask = np.array([[1, 1, 0, 1], [1, 0, 0, 1], [1, 1, 1, 1]], dtype=np.uint8)
    transform = from_origin(100, 200, 0.05, 0.05)
    with rasterio.open(stack, "w", driver="GTiff", width=4, height=3, count=2, dtype="float32", transform=transform) as dataset:
        dataset.write(values)
    with rasterio.open(mask_path, "w", driver="GTiff", width=4, height=3, count=1, dtype="uint8", transform=transform) as dataset:
        dataset.write(mask, 1)
    return stack, mask_path, values, mask


def test_prepare_saga_feature_grids_streams_bands_masks_invalid_and_reuses(tmp_path: Path) -> None:
    stack, mask_path, values, mask = write_inputs(tmp_path)
    output = tmp_path / "grids"

    first = saga.prepare_saga_feature_grids(stack, mask_path, output)
    second = saga.prepare_saga_feature_grids(stack, mask_path, output)

    assert first["preparation_status"] == "computed"
    assert second["preparation_status"] == "reused"
    assert len(first["grid_paths"]) == 2
    for band, header_name in enumerate(first["grid_paths"]):
        header = Path(header_name)
        raw = np.fromfile(header.with_suffix(".sdat"), dtype="<f4").reshape(3, 4)
        expected = values[band].copy()
        expected[mask == 0] = saga.SAGA_NODATA
        np.testing.assert_array_equal(raw, expected)
        assert "TOPTOBOTTOM\t= TRUE" in header.read_text(encoding="utf-8")


def test_saga_commands_map_spatial_radius_and_ranger_without_minsize(tmp_path: Path) -> None:
    grids = [tmp_path / "feature_001.sgrd", tmp_path / "feature_002.sgrd"]
    seed = saga.build_saga_variance_surface_command("/usr/bin/saga_cmd", grids, tmp_path, 16)
    grow = saga.build_saga_region_growing_command(
        "/usr/bin/saga_cmd", grids, tmp_path, feature_variance=0.2786, position_variance_px=16
    )

    assert seed[seed.index("-BAND_WIDTH") + 1] == "16"
    assert seed[seed.index("-SEED_TYPE") + 1] == "0"
    assert grow[grow.index("-SIG_1") + 1] == "0.27860000000000001"
    assert grow[grow.index("-SIG_2") + 1] == "16"
    assert grow[grow.index("-THRESHOLD") + 1] == "0"
    assert grow[grow.index("-METHOD") + 1] == "0"
    assert "minsize" not in " ".join(grow).lower()


def test_export_saga_segments_preserves_reference_grid_reserves_zero_and_masks(tmp_path: Path) -> None:
    stack, mask_path, _values, mask = write_inputs(tmp_path)
    header = tmp_path / "segments.sgrd"
    # SAGA normally serializes output bottom-to-top; the exporter restores raster row order.
    logical = np.array([[0, 0, 1, 1], [0, 2, 2, 1], [3, 3, 2, 1]], dtype=np.float32)
    np.flipud(logical).astype("<f4").tofile(header.with_suffix(".sdat"))
    saga._write_saga_grid_header(header, name="segments", width=4, height=3, nodata_value=-1, top_to_bottom=False)
    output = tmp_path / "labels.tif"

    result = saga.export_saga_segments_to_geotiff(header, stack, mask_path, output)

    with rasterio.open(output) as dataset:
        labels = dataset.read(1)
        assert dataset.transform == from_origin(100, 200, 0.05, 0.05)
        assert dataset.nodata == 0
    expected = logical.astype(np.uint32) + 1
    expected[mask == 0] = 0
    np.testing.assert_array_equal(labels, expected)
    assert result["max_label"] == 4
    assert result["valid_labelled_pixel_count"] == int(mask.sum())


def test_controlled_seed_grid_is_deterministic_valid_and_respects_minimum_distance(
    tmp_path: Path,
) -> None:
    width = height = 25
    variance_header = tmp_path / "variance.sgrd"
    variance = np.arange(width * height, dtype="<f4").reshape(height, width)
    variance.tofile(variance_header.with_suffix(".sdat"))
    saga._write_saga_grid_header(
        variance_header,
        name="variance",
        width=width,
        height=height,
        top_to_bottom=True,
    )
    mask_path = tmp_path / "valid.tif"
    mask = np.ones((height, width), dtype=np.uint8)
    mask[:2, :2] = 0
    with rasterio.open(
        mask_path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype="uint8",
        transform=from_origin(0, height, 1, 1),
    ) as dataset:
        dataset.write(mask, 1)

    first_path = tmp_path / "first" / "seeds.sgrd"
    second_path = tmp_path / "second" / "seeds.sgrd"
    first = saga.materialize_controlled_seed_grid(
        variance_header, mask_path, first_path, spatial_radius_px=4
    )
    second = saga.materialize_controlled_seed_grid(
        variance_header, mask_path, second_path, spatial_radius_px=4
    )

    assert first["policy"] == "hex_lattice_local_variance_minimum"
    assert first["target_footprint"] == "circular_candidate_radius"
    assert first["seed_count"] == second["seed_count"]
    assert first_path.with_suffix(".sdat").read_bytes() == second_path.with_suffix(
        ".sdat"
    ).read_bytes()
    seeds = np.fromfile(first_path.with_suffix(".sdat"), dtype="<f4").reshape(
        height, width
    )
    rows, cols = np.nonzero(seeds > 0)
    assert len(rows) == first["seed_count"]
    assert np.all(mask[rows, cols] == 1)
    for index in range(len(rows)):
        distance_sq = (rows[index + 1 :] - rows[index]) ** 2 + (
            cols[index + 1 :] - cols[index]
        ) ** 2
        assert np.all(distance_sq >= 4**2)


def test_coverage_completion_adds_deterministic_farthest_seeds(tmp_path: Path) -> None:
    width = height = 12
    seed_header = tmp_path / "seeds.sgrd"
    seeds = np.full((height, width), saga.SAGA_NODATA, dtype="<f4")
    seeds[0, 0] = 1
    seeds.tofile(seed_header.with_suffix(".sdat"))
    saga._write_saga_grid_header(
        seed_header,
        name="seeds",
        width=width,
        height=height,
        top_to_bottom=True,
    )
    rows, cols = np.ogrid[:height, :width]
    distance = np.sqrt(rows * rows + cols * cols).astype("<f4")
    distance_header = tmp_path / "distance.sgrd"
    distance.tofile(distance_header.with_suffix(".sdat"))
    saga._write_saga_grid_header(
        distance_header,
        name="distance",
        width=width,
        height=height,
        nodata_value=-1,
        top_to_bottom=True,
    )
    mask_path = tmp_path / "mask.tif"
    with rasterio.open(
        mask_path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype="uint8",
        transform=from_origin(0, height, 1, 1),
    ) as dataset:
        dataset.write(np.ones((height, width), dtype=np.uint8), 1)

    result = saga.complete_seed_coverage(
        seed_header,
        distance_header,
        mask_path,
        maximum_coverage_distance_px=3,
    )

    assert result["coverage_completion_seed_count"] > 0
    updated = np.fromfile(seed_header.with_suffix(".sdat"), dtype="<f4").reshape(
        height, width
    )
    seed_rows, seed_cols = np.nonzero(updated > 0)
    all_distances = [
        np.sqrt((rows - row) ** 2 + (cols - col) ** 2)
        for row, col in zip(seed_rows, seed_cols)
    ]
    assert float(np.min(all_distances, axis=0).max()) <= 3


def test_run_saga_uses_controlled_seeds_explicit_environment_and_exports_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stack, mask_path, _values, _mask = write_inputs(tmp_path)
    grid = tmp_path / "feature_001.sgrd"
    grid.write_text("grid", encoding="utf-8")
    grid.with_suffix(".sdat").write_bytes(b"feature-data")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[2:4] == ["imagery_segmentation", "2"]:
            variance = np.arange(12, dtype="<f4").reshape(3, 4)
            np.flipud(variance).tofile(tmp_path / "seed_variance.sdat")
            saga._write_saga_grid_header(
                tmp_path / "seed_variance.sgrd",
                name="variance",
                width=4,
                height=3,
                top_to_bottom=False,
            )
        elif command[2:4] == ["grid_tools", "26"]:
            distance = np.zeros((3, 4), dtype="<f4")
            np.flipud(distance).tofile(tmp_path / "seed_distance.sdat")
            saga._write_saga_grid_header(
                tmp_path / "seed_distance.sgrd",
                name="distance",
                width=4,
                height=3,
                nodata_value=-1,
                top_to_bottom=False,
            )
        elif command[2:4] == ["imagery_segmentation", "3"]:
            logical = np.zeros((3, 4), dtype="<f4")
            np.flipud(logical).tofile(tmp_path / "segments.sdat")
            saga._write_saga_grid_header(
                tmp_path / "segments.sgrd",
                name="segments",
                width=4,
                height=3,
                nodata_value=-1,
                top_to_bottom=False,
            )

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(saga.subprocess, "run", fake_run)
    result = saga.run_saga_seeded_region_growing(
        saga_cmd_path="/usr/bin/saga_cmd",
        feature_grid_paths=[grid],
        work_dir=tmp_path,
        reference_raster_path=stack,
        valid_mask_path=mask_path,
        output_labels_path=tmp_path / "labels.tif",
        spatial_radius_px=2,
        feature_variance=0.4,
    )

    assert result["status"] == "ok"
    assert result["backend"] == "saga_seeded_region_growing"
    assert result["seed_policy"] == "hex_lattice_local_variance_minimum"
    assert result["seed_report"]["coverage"]["coverage_within_limit"] is True
    assert len(calls) == 3
    assert all("env" in kwargs for _command, kwargs in calls)
    assert calls[0][0][calls[0][0].index("-BAND_WIDTH") + 1] == "2"
    assert calls[1][0][2:4] == ["grid_tools", "26"]
    assert calls[2][0][calls[2][0].index("-SIG_1") + 1] == "0.40000000000000002"
    assert (tmp_path / "labels.tif").is_file()

    calls.clear()
    reused = saga.run_saga_seeded_region_growing(
        saga_cmd_path="/usr/bin/saga_cmd",
        feature_grid_paths=[grid],
        work_dir=tmp_path,
        reference_raster_path=stack,
        valid_mask_path=mask_path,
        output_labels_path=tmp_path / "labels.tif",
        spatial_radius_px=2,
        feature_variance=0.6,
    )

    assert reused["seed_report"]["preparation_status"] == "reused"
    assert len(calls) == 1
    assert calls[0][0][2:4] == ["imagery_segmentation", "3"]
    assert calls[0][0][calls[0][0].index("-SIG_1") + 1] == "0.59999999999999998"


def test_saga_discovery_and_environment_use_saved_windows_path(monkeypatch) -> None:
    calls = []
    monkeypatch.setenv("LEVEL1B_SAGA_PATH_ORIG", r"C:\SAGA;C:\Windows\System32")
    monkeypatch.setattr(saga.shutil, "which", lambda name, path=None: calls.append((name, path)) or r"C:\SAGA\saga_cmd.exe")

    assert saga.discover_saga_cmd().endswith("saga_cmd.exe")
    assert calls == [("saga_cmd", r"C:\SAGA;C:\Windows\System32")]
    assert saga.saga_cli_env()["PATH"] == r"C:\SAGA;C:\Windows\System32"
