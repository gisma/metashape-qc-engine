#!/usr/bin/env python3
"""
Canonical-grid orthomosaic stability analyzer.

Input:
  manifest.csv from reproducibility_runner.py

Output:
  aligned orthomosaics on one canonical grid
  per-variant stability rasters:
    valid_count.tif
    median_ortho.tif
    mad_rgb.tif
    rmse_to_median.tif
    summary.csv

This script treats variable orthomosaic extent as part of product instability.
"""

from __future__ import annotations

import argparse
import csv
import heapq
import json
import math
import os
import tempfile
import warnings
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
from osgeo import gdal


gdal.UseExceptions()

RESOLUTION_REL_TOL = 1e-6
RESOLUTION_ABS_TOL = 1e-7
DEFAULT_BLOCK_SIZE = 512
PERCENTILE_CHUNK_VALUES = 4_000_000

PARALLEL_RUNTIME_DEFAULTS = {
    "GDAL_NUM_THREADS": "1",
    "GDAL_CACHEMAX": "512",
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}

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


def configure_parallel_runtime(workers: int) -> None:
    if workers <= 1:
        return

    applied = []
    preserved = []
    for key, value in PARALLEL_RUNTIME_DEFAULTS.items():
        if key in os.environ:
            preserved.append(f"{key}={os.environ[key]}")
        else:
            os.environ.setdefault(key, value)
            applied.append(f"{key}={value}")

    if applied:
        print(
            "Applied parallel runtime defaults: " + ", ".join(applied),
            flush=True,
        )
    if preserved:
        print(
            "Preserved external runtime values: " + ", ".join(preserved),
            flush=True,
        )

    gdal.SetConfigOption("GDAL_NUM_THREADS", os.environ.get("GDAL_NUM_THREADS"))
    gdal.SetConfigOption("GDAL_CACHEMAX", os.environ.get("GDAL_CACHEMAX"))


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = [col for col in MANIFEST_COLUMNS if col not in (reader.fieldnames or [])]
        if missing:
            raise RuntimeError(
                "Manifest is missing required columns: " + ", ".join(missing)
            )
        rows = list(reader)

    out = []
    for row in rows:
        ortho = row.get("ortho_file", "").strip()
        status = row.get("status", "").strip()
        if status != "ok":
            continue
        if not ortho:
            continue
        if not Path(ortho).is_file():
            continue
        missing_used = [
            col for col in ("variant_id", "replicate")
            if not row.get(col, "").strip()
        ]
        if missing_used:
            raise RuntimeError(
                "Manifest row used for analysis is missing required values: "
                + ", ".join(missing_used)
            )
        out.append(row)

    if not out:
        raise RuntimeError(f"No usable ortho_file rows found in manifest: {path}")

    return out


def raster_info(path: Path) -> dict[str, Any]:
    ds = gdal.Open(str(path))
    if ds is None:
        raise RuntimeError(f"Cannot open raster: {path}")

    gt = ds.GetGeoTransform()
    proj = ds.GetProjection()

    if gt[2] != 0 or gt[4] != 0:
        raise RuntimeError(f"Rotated/sheared geotransform is not supported: {path}")

    xsize = ds.RasterXSize
    ysize = ds.RasterYSize

    xres = gt[1]
    yres = abs(gt[5])

    xmin = gt[0]
    ymax = gt[3]
    xmax = xmin + xsize * xres
    ymin = ymax - ysize * yres

    return {
        "path": str(path),
        "xsize": xsize,
        "ysize": ysize,
        "bands": ds.RasterCount,
        "gt": gt,
        "proj": proj,
        "xres": xres,
        "yres": yres,
        "xmin": xmin,
        "ymin": ymin,
        "xmax": xmax,
        "ymax": ymax,
        "datatype": ds.GetRasterBand(1).DataType,
    }


def check_compatible(infos: list[dict[str, Any]]) -> None:
    base = infos[0]

    for info in infos[1:]:
        if info["proj"] != base["proj"]:
            raise RuntimeError(
                "Projection mismatch:\n"
                f"  {base['path']}\n"
                f"  {info['path']}"
            )

        if not math.isclose(
            info["xres"],
            base["xres"],
            rel_tol=RESOLUTION_REL_TOL,
            abs_tol=RESOLUTION_ABS_TOL,
        ):
            raise RuntimeError(
                f"X resolution mismatch: {base['xres']} vs {info['xres']} "
                f"(absolute difference: {abs(base['xres'] - info['xres'])}, "
                f"tolerance: abs_tol={RESOLUTION_ABS_TOL}, rel_tol={RESOLUTION_REL_TOL})"
            )

        if not math.isclose(
            info["yres"],
            base["yres"],
            rel_tol=RESOLUTION_REL_TOL,
            abs_tol=RESOLUTION_ABS_TOL,
        ):
            raise RuntimeError(
                f"Y resolution mismatch: {base['yres']} vs {info['yres']} "
                f"(absolute difference: {abs(base['yres'] - info['yres'])}, "
                f"tolerance: abs_tol={RESOLUTION_ABS_TOL}, rel_tol={RESOLUTION_REL_TOL})"
            )


def canonical_grid(
    infos: list[dict[str, Any]],
    mode: str,
    reference_path: Path | None,
) -> dict[str, Any]:
    if mode == "reference":
        if reference_path is None:
            ref = infos[0]
        else:
            matches = [i for i in infos if Path(i["path"]).resolve() == reference_path.resolve()]
            if not matches:
                raise RuntimeError(f"Reference ortho not found in manifest set: {reference_path}")
            ref = matches[0]

        xmin, ymin, xmax, ymax = ref["xmin"], ref["ymin"], ref["xmax"], ref["ymax"]

    elif mode == "union":
        xmin = min(i["xmin"] for i in infos)
        ymin = min(i["ymin"] for i in infos)
        xmax = max(i["xmax"] for i in infos)
        ymax = max(i["ymax"] for i in infos)

    elif mode == "intersection":
        xmin = max(i["xmin"] for i in infos)
        ymin = max(i["ymin"] for i in infos)
        xmax = min(i["xmax"] for i in infos)
        ymax = min(i["ymax"] for i in infos)

        if xmin >= xmax or ymin >= ymax:
            raise RuntimeError("Empty intersection grid.")

    else:
        raise RuntimeError(f"Unknown grid mode: {mode}")

    xres = infos[0]["xres"]
    yres = infos[0]["yres"]
    proj = infos[0]["proj"]

    if mode == "intersection":
        xsize = int(math.floor((xmax - xmin) / xres))
        ysize = int(math.floor((ymax - ymin) / yres))
    else:
        xsize = int(math.ceil((xmax - xmin) / xres))
        ysize = int(math.ceil((ymax - ymin) / yres))

    xmax = xmin + xsize * xres
    ymin = ymax - ysize * yres

    gt = (xmin, xres, 0.0, ymax, 0.0, -yres)

    return {
        "mode": mode,
        "xmin": xmin,
        "ymin": ymin,
        "xmax": xmax,
        "ymax": ymax,
        "xres": xres,
        "yres": yres,
        "xsize": xsize,
        "ysize": ysize,
        "gt": gt,
        "proj": proj,
    }


def warp_to_grid(src: Path, dst: Path, grid: dict[str, Any], overwrite: bool) -> None:
    if dst.exists() and not overwrite:
        return

    dst.parent.mkdir(parents=True, exist_ok=True)

    options = gdal.WarpOptions(
        format="GTiff",
        outputBounds=(grid["xmin"], grid["ymin"], grid["xmax"], grid["ymax"]),
        xRes=grid["xres"],
        yRes=grid["yres"],
        dstSRS=grid["proj"],
        resampleAlg="near",
        dstNodata=0,
        multithread=True,
        creationOptions=[
            "TILED=YES",
            "COMPRESS=LZW",
            "BIGTIFF=IF_SAFER",
        ],
    )

    result = gdal.Warp(str(dst), str(src), options=options)
    if result is None:
        raise RuntimeError(f"gdal.Warp failed: {src}")
    result = None


def write_raster(
    path: Path,
    array: np.ndarray,
    grid: dict[str, Any],
    gdal_type: int,
    nodata: float | int | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if array.ndim == 2:
        bands = 1
        ysize, xsize = array.shape
    elif array.ndim == 3:
        bands, ysize, xsize = array.shape
    else:
        raise RuntimeError(f"Unsupported array shape: {array.shape}")

    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(
        str(path),
        xsize,
        ysize,
        bands,
        gdal_type,
        options=[
            "TILED=YES",
            "COMPRESS=LZW",
            "BIGTIFF=IF_SAFER",
        ],
    )

    if ds is None:
        raise RuntimeError(f"Could not create raster: {path}")

    ds.SetGeoTransform(grid["gt"])
    ds.SetProjection(grid["proj"])

    if bands == 1:
        out_arrays = [array]
    else:
        out_arrays = [array[i] for i in range(bands)]

    for i, arr in enumerate(out_arrays, start=1):
        rb = ds.GetRasterBand(i)
        if nodata is not None:
            rb.SetNoDataValue(nodata)
            arr = np.where(np.isfinite(arr), arr, nodata)
        rb.WriteArray(arr)
        rb.FlushCache()

    ds.FlushCache()
    ds = None


def create_raster(
    path: Path,
    grid: dict[str, Any],
    bands: int,
    gdal_type: int,
    nodata: float | int | None,
) -> gdal.Dataset:
    path.parent.mkdir(parents=True, exist_ok=True)

    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(
        str(path),
        grid["xsize"],
        grid["ysize"],
        bands,
        gdal_type,
        options=[
            "TILED=YES",
            "COMPRESS=LZW",
            "BIGTIFF=IF_SAFER",
        ],
    )

    if ds is None:
        raise RuntimeError(f"Could not create raster: {path}")

    ds.SetGeoTransform(grid["gt"])
    ds.SetProjection(grid["proj"])

    if nodata is not None:
        for i in range(1, bands + 1):
            ds.GetRasterBand(i).SetNoDataValue(nodata)

    return ds


def write_block(
    ds: gdal.Dataset,
    array: np.ndarray,
    xoff: int,
    yoff: int,
    nodata: float | int | None,
) -> None:
    if array.ndim == 2:
        out_arrays = [array]
    elif array.ndim == 3:
        out_arrays = [array[i] for i in range(array.shape[0])]
    else:
        raise RuntimeError(f"Unsupported block array shape: {array.shape}")

    for i, arr in enumerate(out_arrays, start=1):
        if nodata is not None:
            arr = np.where(np.isfinite(arr), arr, nodata)
        ds.GetRasterBand(i).WriteArray(arr, xoff=xoff, yoff=yoff)


def iter_windows(xsize: int, ysize: int, block_size: int):
    for yoff in range(0, ysize, block_size):
        win_ysize = min(block_size, ysize - yoff)
        for xoff in range(0, xsize, block_size):
            win_xsize = min(block_size, xsize - xoff)
            yield xoff, yoff, win_xsize, win_ysize


def read_aligned_block(
    ds: gdal.Dataset,
    path: Path,
    bands: int,
    xoff: int,
    yoff: int,
    xsize: int,
    ysize: int,
) -> tuple[np.ndarray, np.ndarray]:
    if ds.RasterCount < bands:
        raise RuntimeError(f"Raster has fewer than {bands} bands: {path}")

    band_arrays = []
    band_valids = []

    for b in range(1, bands + 1):
        rb = ds.GetRasterBand(b)
        arr = rb.ReadAsArray(xoff, yoff, xsize, ysize).astype("float32")
        mask = rb.GetMaskBand().ReadAsArray(xoff, yoff, xsize, ysize) != 0

        nodata = rb.GetNoDataValue()
        if nodata is not None:
            mask &= arr != nodata

        band_arrays.append(arr)
        band_valids.append(mask)

    img = np.stack(band_arrays, axis=0)
    valid = np.logical_and.reduce(band_valids)

    # Metashape RGB nodata is normally black after warping.
    # This is kept explicit so the support layer is not silently inflated.
    valid &= ~np.all(img == 0, axis=0)

    img[:, ~valid] = np.nan
    return img, valid


def safe_nanmedian(arr: np.ndarray, axis: int | tuple[int, ...]) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        return np.nanmedian(arr, axis=axis)


def safe_nanmean(arr: np.ndarray, axis: int | tuple[int, ...] | None = None) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        return np.nanmean(arr, axis=axis)


def raster_band_valid_mask(
    band: gdal.Band,
    arr: np.ndarray,
    xoff: int,
    yoff: int,
    xsize: int,
    ysize: int,
) -> np.ndarray:
    valid = np.isfinite(arr)

    nodata = band.GetNoDataValue()
    if nodata is not None:
        valid &= arr != nodata

    mask_band = band.GetMaskBand()
    if mask_band is not None:
        valid &= mask_band.ReadAsArray(xoff, yoff, xsize, ysize) != 0

    return valid


def exact_raster_percentile(path: Path, q: float, block_size: int) -> float:
    ds = gdal.Open(str(path), gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError(f"Could not open raster for percentile: {path}")

    band = ds.GetRasterBand(1)
    chunk_paths: list[Path] = []
    buffer_parts: list[np.ndarray] = []
    buffer_count = 0
    total_count = 0

    def flush_buffer(tmpdir: Path) -> None:
        nonlocal buffer_parts, buffer_count
        if buffer_count == 0:
            return
        values = np.concatenate(buffer_parts).astype("float32", copy=False)
        values.sort()
        chunk_path = tmpdir / f"chunk_{len(chunk_paths):06d}.npy"
        np.save(chunk_path, values, allow_pickle=False)
        chunk_paths.append(chunk_path)
        buffer_parts = []
        buffer_count = 0

    with tempfile.TemporaryDirectory(prefix="ortho_stability_p95_") as tmp:
        tmpdir = Path(tmp)
        for xoff, yoff, xsize, ysize in iter_windows(
            ds.RasterXSize,
            ds.RasterYSize,
            block_size,
        ):
            arr = band.ReadAsArray(xoff, yoff, xsize, ysize).astype("float32")
            valid = raster_band_valid_mask(band, arr, xoff, yoff, xsize, ysize)
            vals = arr[valid]
            if vals.size == 0:
                continue

            buffer_parts.append(vals)
            buffer_count += int(vals.size)
            total_count += int(vals.size)

            if buffer_count >= PERCENTILE_CHUNK_VALUES:
                flush_buffer(tmpdir)

        flush_buffer(tmpdir)
        ds = None

        if total_count == 0:
            return float("nan")

        rank = (total_count - 1) * (q / 100.0)
        lower_index = int(math.floor(rank))
        upper_index = int(math.ceil(rank))
        lower_value, upper_value = merged_order_values(
            chunk_paths,
            {lower_index, upper_index},
        )

        if lower_index == upper_index:
            return float(lower_value)

        weight = rank - lower_index
        return float(lower_value + (upper_value - lower_value) * weight)


def merged_order_values(
    chunk_paths: list[Path],
    indexes: set[int],
) -> tuple[float, float]:
    if not chunk_paths:
        return float("nan"), float("nan")

    targets = sorted(indexes)
    values_by_index: dict[int, float] = {}
    chunks = [np.load(path, mmap_mode="r", allow_pickle=False) for path in chunk_paths]
    heap: list[tuple[float, int, int]] = []

    for chunk_index, chunk in enumerate(chunks):
        if chunk.size:
            heapq.heappush(heap, (float(chunk[0]), chunk_index, 0))

    current_index = -1
    target_pos = 0
    last_needed = targets[-1]

    while heap and current_index < last_needed:
        value, chunk_index, value_index = heapq.heappop(heap)
        current_index += 1

        if current_index == targets[target_pos]:
            values_by_index[current_index] = value
            target_pos += 1
            if target_pos >= len(targets):
                break

        next_index = value_index + 1
        chunk = chunks[chunk_index]
        if next_index < chunk.size:
            heapq.heappush(heap, (float(chunk[next_index]), chunk_index, next_index))

    if any(index not in values_by_index for index in targets):
        raise RuntimeError("Could not compute exact percentile from streamed chunks.")

    return values_by_index[targets[0]], values_by_index[targets[-1]]


def analyze_variant(
    variant_id: str,
    rows: list[dict[str, str]],
    output_dir: Path,
    grid: dict[str, Any],
    bands: int,
    overwrite: bool,
    stable_rmse_threshold: float,
    block_size: int,
) -> dict[str, Any]:
    aligned_paths = []

    for row in rows:
        src = Path(row["ortho_file"])
        rep = row.get("replicate", src.stem)

        dst = output_dir / "aligned" / variant_id / f"{rep}_aligned.tif"
        warp_to_grid(src, dst, grid, overwrite=overwrite)
        aligned_paths.append(dst)

    n = len(rows)
    variant_out = output_dir / "variants" / variant_id

    valid_count_ds = create_raster(
        variant_out / "valid_count.tif",
        grid,
        1,
        gdal.GDT_UInt16,
        nodata=None,
    )
    median_ds = create_raster(
        variant_out / "median_ortho.tif",
        grid,
        bands,
        gdal.GDT_Float32,
        nodata=-9999,
    )
    mad_ds = create_raster(
        variant_out / "mad_rgb.tif",
        grid,
        1,
        gdal.GDT_Float32,
        nodata=-9999,
    )
    rmse_ds = create_raster(
        variant_out / "rmse_to_median.tif",
        grid,
        1,
        gdal.GDT_Float32,
        nodata=-9999,
    )
    stable_ds = create_raster(
        variant_out / f"stable_mask_rmse{stable_rmse_threshold:g}.tif",
        grid,
        1,
        gdal.GDT_Byte,
        nodata=255,
    )
    unstable_ds = create_raster(
        variant_out / f"unstable_mask_rmse{stable_rmse_threshold:g}.tif",
        grid,
        1,
        gdal.GDT_Byte,
        nodata=255,
    )

    aligned_datasets = []
    for path in aligned_paths:
        ds = gdal.Open(str(path), gdal.GA_ReadOnly)
        if ds is None:
            raise RuntimeError(f"Cannot open aligned raster: {path}")
        aligned_datasets.append(ds)

    total_pixels = int(grid["xsize"] * grid["ysize"])
    valid_pixels = 0
    full_support_pixels = 0
    valid_count_sum = 0
    min_valid_count: int | None = None
    max_valid_count: int | None = None
    stable_pixels = 0
    unstable_pixels = 0
    mad_sum = 0.0
    mad_count = 0
    rmse_sum = 0.0
    rmse_count = 0

    try:
        for xoff, yoff, xsize, ysize in iter_windows(
            grid["xsize"],
            grid["ysize"],
            block_size,
        ):
            arrays = []
            valids = []
            for path, ds in zip(aligned_paths, aligned_datasets):
                img, valid = read_aligned_block(
                    ds,
                    path,
                    bands=bands,
                    xoff=xoff,
                    yoff=yoff,
                    xsize=xsize,
                    ysize=ysize,
                )
                arrays.append(img)
                valids.append(valid)

            stack = np.stack(arrays, axis=0)
            valid_stack = np.stack(valids, axis=0)

            valid_count = np.sum(valid_stack, axis=0).astype("uint16")
            median = safe_nanmedian(stack, axis=0).astype("float32")

            abs_dev = np.abs(stack - median[None, :, :, :])
            mad_per_band = safe_nanmedian(abs_dev, axis=0)
            mad_rgb = safe_nanmean(mad_per_band, axis=0).astype("float32")

            sq_dev = (stack - median[None, :, :, :]) ** 2
            rmse_to_median = np.sqrt(safe_nanmean(sq_dev, axis=(0, 1))).astype("float32")

            support_valid = valid_count > 0
            full_support = valid_count == n

            stable_mask = np.full(valid_count.shape, 255, dtype="uint8")
            unstable_mask = np.full(valid_count.shape, 255, dtype="uint8")

            stable_condition = full_support & (rmse_to_median <= stable_rmse_threshold)
            unstable_condition = support_valid & ~stable_condition

            stable_mask[support_valid] = 0
            unstable_mask[support_valid] = 0

            stable_mask[stable_condition] = 1
            unstable_mask[unstable_condition] = 1

            write_block(valid_count_ds, valid_count, xoff, yoff, nodata=None)
            write_block(median_ds, median, xoff, yoff, nodata=-9999)
            write_block(mad_ds, mad_rgb, xoff, yoff, nodata=-9999)
            write_block(rmse_ds, rmse_to_median, xoff, yoff, nodata=-9999)
            write_block(stable_ds, stable_mask, xoff, yoff, nodata=255)
            write_block(unstable_ds, unstable_mask, xoff, yoff, nodata=255)

            valid_pixels += int(np.count_nonzero(support_valid))
            full_support_pixels += int(np.count_nonzero(full_support))
            valid_count_sum += int(np.sum(valid_count, dtype=np.uint64))
            block_min = int(np.min(valid_count))
            block_max = int(np.max(valid_count))
            min_valid_count = (
                block_min if min_valid_count is None else min(min_valid_count, block_min)
            )
            max_valid_count = (
                block_max if max_valid_count is None else max(max_valid_count, block_max)
            )
            stable_pixels += int(np.count_nonzero(stable_mask == 1))
            unstable_pixels += int(np.count_nonzero(unstable_mask == 1))

            mad_valid = np.isfinite(mad_rgb)
            if np.any(mad_valid):
                mad_sum += float(np.sum(mad_rgb[mad_valid], dtype=np.float64))
                mad_count += int(np.count_nonzero(mad_valid))

            rmse_valid = np.isfinite(rmse_to_median)
            if np.any(rmse_valid):
                rmse_sum += float(np.sum(rmse_to_median[rmse_valid], dtype=np.float64))
                rmse_count += int(np.count_nonzero(rmse_valid))
    finally:
        for ds in [
            valid_count_ds,
            median_ds,
            mad_ds,
            rmse_ds,
            stable_ds,
            unstable_ds,
        ]:
            ds.FlushCache()
        valid_count_ds = None
        median_ds = None
        mad_ds = None
        rmse_ds = None
        stable_ds = None
        unstable_ds = None

        for ds in aligned_datasets:
            ds = None

    nodata_pixels = total_pixels - valid_pixels

    if valid_pixels > 0:
        stable_fraction_support = float(stable_pixels / valid_pixels)
        unstable_fraction_support = float(unstable_pixels / valid_pixels)
    else:
        stable_fraction_support = float("nan")
        unstable_fraction_support = float("nan")

    mad_file = variant_out / "mad_rgb.tif"
    rmse_file = variant_out / "rmse_to_median.tif"

    summary = {
        "variant_id": variant_id,
        "n_orthos": n,
        "grid_mode": grid["mode"],
        "xsize": grid["xsize"],
        "ysize": grid["ysize"],
        "any_support_fraction": float(valid_pixels / total_pixels),
        "full_support_fraction": float(full_support_pixels / total_pixels),
        "mean_valid_count": float(valid_count_sum / total_pixels),
        "min_valid_count": int(min_valid_count or 0),
        "max_valid_count": int(max_valid_count or 0),
        "mean_mad_rgb": float(mad_sum / mad_count) if mad_count else float("nan"),
        "p95_mad_rgb": exact_raster_percentile(mad_file, 95, block_size),
        "mean_rmse_to_median": float(rmse_sum / rmse_count) if rmse_count else float("nan"),
        "p95_rmse_to_median": exact_raster_percentile(rmse_file, 95, block_size),
        "stable_rmse_threshold": float(stable_rmse_threshold),
        "valid_pixels": valid_pixels,
        "nodata_pixels": nodata_pixels,
        "stable_pixels_rmse": stable_pixels,
        "unstable_pixels_rmse": unstable_pixels,
        "stable_fraction_support_rmse": stable_fraction_support,
        "unstable_fraction_support_rmse": unstable_fraction_support,
    }

    return summary


def write_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze orthomosaic stability on a canonical grid."
    )
    parser.add_argument(
        "manifest",
        type=Path,
        help="manifest.csv from reproducibility_runner.py",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output directory for aligned rasters and stability products.",
    )
    parser.add_argument(
        "--grid-mode",
        choices=["union", "intersection", "reference"],
        default="union",
        help="Canonical grid mode.",
    )
    parser.add_argument(
        "--reference-ortho",
        type=Path,
        default=None,
        help="Reference ortho for --grid-mode reference.",
    )
    parser.add_argument(
        "--bands",
        type=int,
        default=3,
        help="Number of bands to analyze.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite aligned rasters if they already exist.",
    )
    parser.add_argument(
        "--stable-rmse-threshold",
        type=float,
        default=15.0,
        help="RMSE-to-median threshold used to derive stable/unstable masks.",
    )
    parser.add_argument(
        "--block-size",
        type=int,
        default=DEFAULT_BLOCK_SIZE,
        help=(
            "Square processing block size in pixels for per-variant raster "
            f"computations. Default: {DEFAULT_BLOCK_SIZE}."
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of variant workers for process-based parallel execution. Default: 1.",
    )

    args = parser.parse_args()
    if args.block_size <= 0:
        raise RuntimeError("--block-size must be a positive integer.")
    if args.workers <= 0:
        raise RuntimeError("--workers must be a positive integer.")

    configure_parallel_runtime(args.workers)

    rows = read_manifest(args.manifest)
    infos = [raster_info(Path(r["ortho_file"])) for r in rows]
    check_compatible(infos)

    grid = canonical_grid(
        infos=infos,
        mode=args.grid_mode,
        reference_path=args.reference_ortho,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)

    grid_json = {
        k: v for k, v in grid.items()
        if k not in {"proj", "gt"}
    }
    grid_json["geotransform"] = list(grid["gt"])
    grid_json["projection"] = grid["proj"]

    with (args.output_dir / "canonical_grid.json").open("w", encoding="utf-8") as f:
        json.dump(grid_json, f, indent=2)

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["variant_id"]].append(row)

    summaries = []

    if args.workers == 1:
        for variant_id in sorted(grouped):
            print(f"Analyzing variant: {variant_id}", flush=True)
            summary = analyze_variant(
                variant_id=variant_id,
                rows=grouped[variant_id],
                output_dir=args.output_dir,
                grid=grid,
                bands=args.bands,
                overwrite=args.overwrite,
                stable_rmse_threshold=args.stable_rmse_threshold,
                block_size=args.block_size,
            )
            summaries.append(summary)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    analyze_variant,
                    variant_id,
                    grouped[variant_id],
                    args.output_dir,
                    grid,
                    args.bands,
                    args.overwrite,
                    args.stable_rmse_threshold,
                    args.block_size,
                ): variant_id
                for variant_id in sorted(grouped)
            }

            for future in as_completed(futures):
                variant_id = futures[future]
                try:
                    summary = future.result()
                except Exception as exc:
                    raise RuntimeError(f"Variant failed: {variant_id}") from exc
                print(f"Finished variant: {variant_id}", flush=True)
                summaries.append(summary)

    summaries = sorted(summaries, key=lambda row: row["variant_id"])
    write_summary(args.output_dir / "summary.csv", summaries)

    print(f"Written: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
