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
import json
import math
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from osgeo import gdal


gdal.UseExceptions()

RESOLUTION_REL_TOL = 1e-6
RESOLUTION_ABS_TOL = 1e-7

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


def read_stack(paths: list[Path], bands: int) -> tuple[np.ndarray, np.ndarray]:
    arrays = []
    valids = []

    for path in paths:
        ds = gdal.Open(str(path))
        if ds is None:
            raise RuntimeError(f"Cannot open aligned raster: {path}")

        if ds.RasterCount < bands:
            raise RuntimeError(f"Raster has fewer than {bands} bands: {path}")

        band_arrays = []
        band_valids = []

        for b in range(1, bands + 1):
            rb = ds.GetRasterBand(b)
            arr = rb.ReadAsArray().astype("float32")

            mask = rb.GetMaskBand().ReadAsArray() != 0

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

        arrays.append(img)
        valids.append(valid)

    stack = np.stack(arrays, axis=0)
    valid_stack = np.stack(valids, axis=0)

    return stack, valid_stack


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


def safe_nanmedian(arr: np.ndarray, axis: int | tuple[int, ...]) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        return np.nanmedian(arr, axis=axis)


def safe_nanmean(arr: np.ndarray, axis: int | tuple[int, ...] | None = None) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        return np.nanmean(arr, axis=axis)


def safe_nanpercentile(arr: np.ndarray, q: float) -> float:
    vals = arr[np.isfinite(arr)]
    if vals.size == 0:
        return float("nan")
    return float(np.percentile(vals, q))


def analyze_variant(
    variant_id: str,
    rows: list[dict[str, str]],
    output_dir: Path,
    grid: dict[str, Any],
    bands: int,
    overwrite: bool,
    stable_rmse_threshold: float,
) -> dict[str, Any]:
    aligned_paths = []

    for row in rows:
        src = Path(row["ortho_file"])
        rep = row.get("replicate", src.stem)

        dst = output_dir / "aligned" / variant_id / f"{rep}_aligned.tif"
        warp_to_grid(src, dst, grid, overwrite=overwrite)
        aligned_paths.append(dst)

    stack, valid_stack = read_stack(aligned_paths, bands=bands)

    valid_count = np.sum(valid_stack, axis=0).astype("uint16")

    median = safe_nanmedian(stack, axis=0).astype("float32")

    abs_dev = np.abs(stack - median[None, :, :, :])
    mad_per_band = safe_nanmedian(abs_dev, axis=0)
    mad_rgb = safe_nanmean(mad_per_band, axis=0).astype("float32")

    sq_dev = (stack - median[None, :, :, :]) ** 2
    rmse_to_median = np.sqrt(safe_nanmean(sq_dev, axis=(0, 1))).astype("float32")

    n = len(rows)
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

    variant_out = output_dir / "variants" / variant_id

    write_raster(
        variant_out / "valid_count.tif",
        valid_count,
        grid,
        gdal.GDT_UInt16,
        nodata=None,
    )

    write_raster(
        variant_out / "median_ortho.tif",
        median,
        grid,
        gdal.GDT_Float32,
        nodata=-9999,
    )

    write_raster(
        variant_out / "mad_rgb.tif",
        mad_rgb,
        grid,
        gdal.GDT_Float32,
        nodata=-9999,
    )

    write_raster(
        variant_out / "rmse_to_median.tif",
        rmse_to_median,
        grid,
        gdal.GDT_Float32,
        nodata=-9999,
    )

    write_raster(
        variant_out / f"stable_mask_rmse{stable_rmse_threshold:g}.tif",
        stable_mask,
        grid,
        gdal.GDT_Byte,
        nodata=255,
    )

    write_raster(
        variant_out / f"unstable_mask_rmse{stable_rmse_threshold:g}.tif",
        unstable_mask,
        grid,
        gdal.GDT_Byte,
        nodata=255,
    )

    total_pixels = valid_count.size
    valid_pixels = int(np.sum(support_valid))
    nodata_pixels = int(np.sum(~support_valid))
    stable_pixels = int(np.sum(stable_mask == 1))
    unstable_pixels = int(np.sum(unstable_mask == 1))

    if valid_pixels > 0:
        stable_fraction_support = float(stable_pixels / valid_pixels)
        unstable_fraction_support = float(unstable_pixels / valid_pixels)
    else:
        stable_fraction_support = float("nan")
        unstable_fraction_support = float("nan")

    summary = {
        "variant_id": variant_id,
        "n_orthos": n,
        "grid_mode": grid["mode"],
        "xsize": grid["xsize"],
        "ysize": grid["ysize"],
        "any_support_fraction": float(np.sum(valid_count > 0) / total_pixels),
        "full_support_fraction": float(np.sum(valid_count == n) / total_pixels),
        "mean_valid_count": float(np.mean(valid_count)),
        "min_valid_count": int(np.min(valid_count)),
        "max_valid_count": int(np.max(valid_count)),
        "mean_mad_rgb": float(safe_nanmean(mad_rgb)),
        "p95_mad_rgb": safe_nanpercentile(mad_rgb, 95),
        "mean_rmse_to_median": float(safe_nanmean(rmse_to_median)),
        "p95_rmse_to_median": safe_nanpercentile(rmse_to_median, 95),
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

    args = parser.parse_args()

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

    for variant_id in sorted(grouped):
        print(f"Analyzing variant: {variant_id}")
        summary = analyze_variant(
            variant_id=variant_id,
            rows=grouped[variant_id],
            output_dir=args.output_dir,
            grid=grid,
            bands=args.bands,
            overwrite=args.overwrite,
            stable_rmse_threshold=args.stable_rmse_threshold,
        )
        summaries.append(summary)

    write_summary(args.output_dir / "summary.csv", summaries)

    print(f"Written: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
