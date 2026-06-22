import csv
import importlib.util
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
from osgeo import gdal, osr


REPO_ROOT = Path(__file__).resolve().parents[1]
ANALYZER = REPO_ROOT / "python" / "ortho_stability_analyzer.py"
EVALUATOR = REPO_ROOT / "python" / "evaluate_ortho_stability.py"
MANIFEST_COLUMNS = [
    "experiment_id",
    "variant_id",
    "replicate",
    "status",
    "return_code",
    "config_file",
    "project_dir",
    "output_dir",
    "project_file",
    "ortho_file",
    "launcher_log",
    "elapsed_sec",
]


def projection_wkt() -> str:
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3857)
    return srs.ExportToWkt()


def write_rgb_tif(path: Path, array: np.ndarray) -> None:
    driver = gdal.GetDriverByName("GTiff")
    bands, ysize, xsize = array.shape
    ds = driver.Create(str(path), xsize, ysize, bands, gdal.GDT_Float32)
    assert ds is not None
    ds.SetGeoTransform((0.0, 1.0, 0.0, float(ysize), 0.0, -1.0))
    ds.SetProjection(projection_wkt())
    for band_index in range(bands):
        rb = ds.GetRasterBand(band_index + 1)
        rb.SetNoDataValue(0)
        rb.WriteArray(array[band_index])
    ds = None


def read_raster(path: Path) -> np.ndarray:
    ds = gdal.Open(str(path), gdal.GA_ReadOnly)
    assert ds is not None
    arr = ds.ReadAsArray().astype("float32")
    ds = None
    return arr


def expected_outputs(arrays: list[np.ndarray], threshold: float) -> dict[str, np.ndarray]:
    stack = []
    valids = []
    for array in arrays:
        image = array.astype("float32").copy()
        valid = np.logical_and.reduce([image[i] != 0 for i in range(image.shape[0])])
        valid &= ~np.all(image == 0, axis=0)
        image[:, ~valid] = np.nan
        stack.append(image)
        valids.append(valid)

    stack_arr = np.stack(stack, axis=0)
    valid_stack = np.stack(valids, axis=0)
    valid_count = np.sum(valid_stack, axis=0).astype("uint16")

    with np.errstate(all="ignore"):
        median = np.nanmedian(stack_arr, axis=0).astype("float32")
        mad_per_band = np.nanmedian(np.abs(stack_arr - median[None, :, :, :]), axis=0)
        mad_rgb = np.nanmean(mad_per_band, axis=0).astype("float32")
        rmse = np.sqrt(np.nanmean((stack_arr - median[None, :, :, :]) ** 2, axis=(0, 1))).astype(
            "float32"
        )

    support_valid = valid_count > 0
    full_support = valid_count == len(arrays)
    stable_condition = full_support & (rmse <= threshold)
    unstable_condition = support_valid & ~stable_condition

    stable = np.full(valid_count.shape, 255, dtype="uint8")
    unstable = np.full(valid_count.shape, 255, dtype="uint8")
    stable[support_valid] = 0
    unstable[support_valid] = 0
    stable[stable_condition] = 1
    unstable[unstable_condition] = 1

    return {
        "valid_count": valid_count,
        "median": median,
        "mad_rgb": mad_rgb,
        "rmse": rmse,
        "stable": stable,
        "unstable": unstable,
    }


def finite_output(array: np.ndarray) -> np.ndarray:
    return np.where(array == -9999, np.nan, array)


def test_blockwise_analyzer_matches_full_array_semantics(tmp_path: Path) -> None:
    gdal.UseExceptions()
    threshold = 2.0
    ysize, xsize = 5, 6
    base = np.arange(1, 1 + 3 * ysize * xsize, dtype="float32").reshape(3, ysize, xsize)

    variant_arrays = {
        "variant_a": [base + 10, base + 12, base + 14],
        "variant_b": [base + 30, base + 31, base + 33],
    }
    variant_arrays["variant_a"][0][:, 0, 0] = 0
    variant_arrays["variant_a"][2][:, 1, 1] = 0
    variant_arrays["variant_b"][1][:, 2, 2] = 0

    rows = []
    for variant_id, arrays in variant_arrays.items():
        for index, array in enumerate(arrays, start=1):
            path = tmp_path / f"{variant_id}_{index}.tif"
            write_rgb_tif(path, array)
            rows.append(
                {
                    "experiment_id": "synthetic",
                    "variant_id": variant_id,
                    "replicate": f"rep{index}",
                    "status": "ok",
                    "return_code": "0",
                    "config_file": "",
                    "project_dir": "",
                    "output_dir": "",
                    "project_file": "",
                    "ortho_file": str(path),
                    "launcher_log": "",
                    "elapsed_sec": "0",
                }
            )

    manifest = tmp_path / "manifest.csv"
    with manifest.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    output_dir = tmp_path / "stability_union"
    subprocess.run(
        [
            sys.executable,
            str(ANALYZER),
            str(manifest),
            "--output-dir",
            str(output_dir),
            "--grid-mode",
            "union",
            "--bands",
            "3",
            "--stable-rmse-threshold",
            str(threshold),
            "--block-size",
            "2",
            "--overwrite",
        ],
        check=True,
    )

    for variant_id, arrays in variant_arrays.items():
        expected = expected_outputs(arrays, threshold)
        variant_dir = output_dir / "variants" / variant_id

        assert (output_dir / "aligned" / variant_id / "rep1_aligned.tif").is_file()
        assert np.array_equal(read_raster(variant_dir / "valid_count.tif"), expected["valid_count"])
        np.testing.assert_allclose(
            finite_output(read_raster(variant_dir / "median_ortho.tif")),
            expected["median"],
            equal_nan=True,
        )
        np.testing.assert_allclose(
            finite_output(read_raster(variant_dir / "mad_rgb.tif")),
            expected["mad_rgb"],
            equal_nan=True,
        )
        np.testing.assert_allclose(
            finite_output(read_raster(variant_dir / "rmse_to_median.tif")),
            expected["rmse"],
            equal_nan=True,
        )
        assert np.array_equal(
            read_raster(variant_dir / f"stable_mask_rmse{threshold:g}.tif"),
            expected["stable"],
        )
        assert np.array_equal(
            read_raster(variant_dir / f"unstable_mask_rmse{threshold:g}.tif"),
            expected["unstable"],
        )

    with (output_dir / "summary.csv").open(newline="") as handle:
        summary = {row["variant_id"]: row for row in csv.DictReader(handle)}

    for variant_id, arrays in variant_arrays.items():
        expected = expected_outputs(arrays, threshold)
        mad_values = expected["mad_rgb"][np.isfinite(expected["mad_rgb"])]
        rmse_values = expected["rmse"][np.isfinite(expected["rmse"])]
        row = summary[variant_id]
        assert math.isclose(
            float(row["mean_mad_rgb"]),
            float(np.mean(mad_values)),
            abs_tol=1e-6,
        )
        assert math.isclose(
            float(row["p95_mad_rgb"]),
            float(np.percentile(mad_values, 95)),
            abs_tol=1e-6,
        )
        assert math.isclose(
            float(row["mean_rmse_to_median"]),
            float(np.mean(rmse_values)),
            abs_tol=1e-6,
        )
        assert math.isclose(
            float(row["p95_rmse_to_median"]),
            float(np.percentile(rmse_values, 95)),
            abs_tol=1e-6,
        )


def test_evaluator_resolution_tolerance_groups_equivalent_values() -> None:
    spec = importlib.util.spec_from_file_location("evaluate_ortho_stability", EVALUATOR)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    near_a = (0.0299881894205, 0.0299881894205)
    near_b = (0.0299881895680, 0.0299881895680)
    true_other = (0.0499803157, 0.0499803157)

    assert module.resolutions_close(near_a, near_b)
    assert not module.resolutions_close(near_a, true_other)
