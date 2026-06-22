#!/usr/bin/env python3
"""
Evaluate a completed orthomosaic reproducibility experiment.

Wrapper around python/ortho_stability_analyzer.py.

Use:
  python3 python/evaluate_ortho_stability.py <experiment_dir>

Reuse existing analyzer outputs:
  python3 python/evaluate_ortho_stability.py <experiment_dir> --skip-analyzer
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path, PureWindowsPath

import numpy as np
from osgeo import gdal


RESOLUTION_REL_TOL = 1e-6
RESOLUTION_ABS_TOL = 1e-7
DEFAULT_BLOCK_SIZE = 512

KEY_COLUMNS = [
    "variant_id",
    "n_orthos",
    "any_support_fraction_grid",
    "full_support_fraction_grid",
    "variable_support_fraction_grid",
    "support_persistence_footprint",
    "support_dropout_footprint",
    "mean_mad_rgb",
    "p95_mad_rgb",
    "mean_rmse_to_median",
    "p95_rmse_to_median",
    "stable_fraction_support_rmse",
    "unstable_fraction_support_rmse",
]

SUPPORT_COLUMNS = [
    "variant_id",
    "n_orthos",
    "no_support_fraction_grid",
    "any_support_fraction_grid",
    "full_support_fraction_grid",
    "variable_support_fraction_grid",
    "support_persistence_footprint",
    "support_dropout_footprint",
]

SUMMARY_COLUMNS = [
    "variant_id",
    "n_orthos",
    "mean_mad_rgb",
    "p95_mad_rgb",
    "mean_rmse_to_median",
    "p95_rmse_to_median",
    "stable_fraction_support_rmse",
    "unstable_fraction_support_rmse",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate an orthomosaic reproducibility experiment."
    )
    parser.add_argument(
        "experiment_dir",
        help="Experiment directory containing manifest.csv and/or stability_union/summary.csv.",
    )
    parser.add_argument(
        "--skip-analyzer",
        action="store_true",
        help="Reuse existing stability_union/summary.csv instead of running the analyzer.",
    )
    parser.add_argument(
        "--grid-mode",
        default="union",
        choices=["union", "intersection", "reference"],
        help="Canonical grid mode passed to ortho_stability_analyzer.py.",
    )
    parser.add_argument("--bands", type=int, default=3)
    parser.add_argument("--stable-rmse-threshold", type=float, default=15.0)
    parser.add_argument(
        "--block-size",
        type=int,
        default=DEFAULT_BLOCK_SIZE,
        help=(
            "Square processing block size in pixels passed to "
            f"ortho_stability_analyzer.py. Default: {DEFAULT_BLOCK_SIZE}."
        ),
    )
    parser.add_argument(
        "--thresholds",
        default="5,10,15,20,25,30",
        help=(
            "Comma-separated RMSE thresholds for cheap post-processing review. "
            "Use empty string or 'none' to disable."
        ),
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Do not pass --overwrite to ortho_stability_analyzer.py.",
    )
    return parser.parse_args()


def shell_join(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def print_review_commands(experiment_dir: Path, output_dir: Path) -> None:
    review_targets = [
        (experiment_dir / "selected_product.json", "xdg-open"),
        (output_dir / "evaluation_report.md", "xdg-open"),
        (output_dir / "summary_key_metrics.tsv", "xdg-open"),
        (experiment_dir / "qgis_open_selected.sh", "bash"),
        (experiment_dir / "qgis_open_threshold_review.sh", "bash"),
    ]

    commands = [
        [program, str(path)]
        for path, program in review_targets
        if path.exists()
    ]

    if not commands:
        return

    print()
    print("Review commands:")
    for command in commands:
        print(f"  {shell_join(command)}")


def threshold_label(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return str(value).replace(".", "p")


def parse_thresholds(value: str | None) -> list[float]:
    if value is None:
        return []
    stripped = value.strip()
    if not stripped or stripped.lower() == "none":
        return []

    thresholds: list[float] = []
    for item in stripped.split(","):
        item = item.strip()
        if not item:
            continue
        thresholds.append(float(item))
    return thresholds


def as_float(value: str | float | None) -> float:
    if value is None or value == "":
        return math.nan
    if isinstance(value, float):
        return value
    try:
        return float(value)
    except ValueError:
        return math.nan


def fmt(value: str | float | None, digits: int = 4) -> str:
    x = as_float(value)
    if math.isnan(x):
        return "NA"
    return f"{x:.{digits}f}"


def read_csv_dicts(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [col for col in SUMMARY_COLUMNS if col not in (reader.fieldnames or [])]
        if missing:
            raise RuntimeError(
                f"{path} is missing required columns: " + ", ".join(missing)
            )
        return list(reader)


def read_manifest_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def manifest_ortho_path(value: str, manifest: Path) -> Path:
    stripped = value.strip()
    path = Path(stripped)
    if path.is_absolute():
        return path

    win_path = PureWindowsPath(stripped)
    if win_path.is_absolute():
        return Path(stripped)

    return manifest.parent / path


def raster_projection_label(projection: str) -> str:
    return projection.strip() if projection.strip() else "<missing>"


def preflight_resolution_key(xres: float, yres: float) -> tuple[str, str]:
    return (f"{xres:.12g}", f"{yres:.12g}")


def resolutions_close(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return math.isclose(
        a[0],
        b[0],
        rel_tol=RESOLUTION_REL_TOL,
        abs_tol=RESOLUTION_ABS_TOL,
    ) and math.isclose(
        a[1],
        b[1],
        rel_tol=RESOLUTION_REL_TOL,
        abs_tol=RESOLUTION_ABS_TOL,
    )


def collect_usable_ortho_infos(manifest: Path) -> list[dict[str, object]]:
    rows = read_manifest_rows(manifest)
    infos: list[dict[str, object]] = []

    for row in rows:
        if row.get("status", "").strip() != "ok":
            continue

        ortho_file = row.get("ortho_file", "").strip()
        if not ortho_file:
            continue

        path = manifest_ortho_path(ortho_file, manifest)
        if not path.is_file():
            continue

        ds = gdal.Open(str(path), gdal.GA_ReadOnly)
        if ds is None:
            continue

        gt = ds.GetGeoTransform()
        infos.append(
            {
                "variant_id": row.get("variant_id", "").strip(),
                "replicate": row.get("replicate", "").strip(),
                "path": path,
                "xres": abs(float(gt[1])),
                "yres": abs(float(gt[5])),
                "projection": raster_projection_label(ds.GetProjection()),
                "rotated_or_sheared": bool(gt[2] != 0 or gt[4] != 0),
            }
        )
        ds = None

    return infos


def variant_examples(variant_ids: set[str], limit: int = 8) -> str:
    values = sorted(v for v in variant_ids if v)
    if not values:
        return "NA"
    shown = values[:limit]
    suffix = f", ... (+{len(values) - limit} more)" if len(values) > limit else ""
    return ", ".join(shown) + suffix


def projection_summary(projections: set[str]) -> str:
    if not projections:
        return "none"
    if len(projections) == 1:
        value = next(iter(projections))
        if value == "<missing>":
            return "missing"
        return "one projection string"
    return f"{len(projections)} distinct projection strings"


def format_resolution_preflight_error(
    manifest: Path,
    infos: list[dict[str, object]],
    groups: dict[tuple[str, str], list[dict[str, object]]],
) -> str:
    lines = [
        "Mixed raster resolutions detected.",
        f"Manifest: {manifest}",
        f"Usable orthomosaics: {len(infos)}",
        "",
        "Resolution groups:",
    ]

    for index, (key, group) in enumerate(
        sorted(groups.items(), key=lambda item: (float(item[0][0]), float(item[0][1]))),
        start=1,
    ):
        variants = {str(info.get("variant_id", "")) for info in group}
        variant_replicates = {
            (str(info.get("variant_id", "")), str(info.get("replicate", "")))
            for info in group
        }
        projections = {str(info.get("projection", "")) for info in group}
        rotated_count = sum(1 for info in group if bool(info.get("rotated_or_sheared")))

        lines.extend(
            [
                f"- Group {index}:",
                f"  x resolution: {key[0]}",
                f"  y resolution: {key[1]}",
                f"  rasters: {len(group)}",
                f"  variants: {len(variants)}",
                f"  variant-replicate pairs: {len(variant_replicates)}",
                f"  example variant ids: {variant_examples(variants)}",
                f"  projection compatibility: {projection_summary(projections)}",
                f"  rotated/sheared transforms: {rotated_count}",
            ]
        )

    lines.extend(
        [
            "",
            "Pixelwise stability analysis requires one common raster resolution.",
            "This is expected when buildOrthomosaic.orthoRes was varied in the matrix.",
            "Evaluate each resolution stratum separately, for example by running evaluation "
            "on manifests or run directories that contain only one orthoRes level.",
            "The evaluator does not silently resample rasters.",
        ]
    )
    return "\n".join(lines)


def preflight_manifest_raster_resolutions(manifest: Path) -> None:
    infos = collect_usable_ortho_infos(manifest)
    if not infos:
        return

    grouped: list[tuple[tuple[float, float], list[dict[str, object]]]] = []
    for info in infos:
        resolution = (float(info["xres"]), float(info["yres"]))
        for key, group in grouped:
            if resolutions_close(resolution, key):
                group.append(info)
                break
        else:
            grouped.append((resolution, [info]))

    groups = {
        preflight_resolution_key(key[0], key[1]): group
        for key, group in grouped
    }
    if len(groups) > 1:
        raise RuntimeError(format_resolution_preflight_error(manifest, infos, groups))


def write_tsv(rows: list[dict[str, str]], columns: list[str], path: Path) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in columns})


def table_text(rows: list[dict[str, str]], columns: list[str]) -> str:
    if not rows:
        return "No rows."

    widths = {
        col: max(len(col), *(len(str(row.get(col, ""))) for row in rows))
        for col in columns
    }

    lines = [
        "  ".join(col.ljust(widths[col]) for col in columns),
        "  ".join("-" * widths[col] for col in columns),
    ]

    for row in rows:
        lines.append("  ".join(str(row.get(col, "")).ljust(widths[col]) for col in columns))

    return "\n".join(lines)


def run_analyzer(
    experiment_dir: Path,
    output_dir: Path,
    grid_mode: str,
    bands: int,
    threshold: float,
    block_size: int,
    overwrite: bool,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    analyzer = repo_root / "python" / "ortho_stability_analyzer.py"
    manifest = experiment_dir / "manifest.csv"

    if not manifest.is_file():
        raise FileNotFoundError(f"Missing manifest file: {manifest}")
    if not analyzer.is_file():
        raise FileNotFoundError(f"Missing analyzer script: {analyzer}")

    preflight_manifest_raster_resolutions(manifest)

    cmd = [
        sys.executable,
        str(analyzer),
        str(manifest),
        "--output-dir",
        str(output_dir),
        "--grid-mode",
        grid_mode,
        "--bands",
        str(bands),
        "--stable-rmse-threshold",
        str(threshold),
        "--block-size",
        str(block_size),
    ]

    if overwrite:
        cmd.append("--overwrite")

    print("Running Stability Analyzer")
    print(" ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        quoted_cmd = " ".join(shlex.quote(part) for part in cmd)
        print(
            f"Analyzer failed with exit code {exc.returncode}.\n"
            "Rerun the analyzer command directly for full diagnostics:\n"
            f"{quoted_cmd}",
            file=sys.stderr,
        )
        raise SystemExit(exc.returncode) from exc


def read_raster_array(path: Path) -> np.ndarray:
    ds = gdal.Open(str(path), gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError(f"Could not open raster: {path}")

    arr = ds.ReadAsArray()
    if arr.ndim == 3:
        arr = arr[0]

    return arr.copy()


def read_raster_for_distance(path: Path, bands: int, reject_rgb_zero: bool) -> tuple[np.ndarray, np.ndarray]:
    ds = gdal.Open(str(path), gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError(f"Could not open raster: {path}")
    if ds.RasterCount < bands:
        raise RuntimeError(f"Raster has fewer than {bands} bands: {path}")

    arrays = []
    valids = []
    for b in range(1, bands + 1):
        rb = ds.GetRasterBand(b)
        arr = rb.ReadAsArray().astype("float32")
        valid = np.isfinite(arr)

        nodata = rb.GetNoDataValue()
        if nodata is not None:
            valid &= arr != nodata

        mask_band = rb.GetMaskBand()
        if mask_band is not None:
            valid &= mask_band.ReadAsArray() != 0

        arrays.append(arr)
        valids.append(valid)

    image = np.stack(arrays, axis=0)
    valid = np.logical_and.reduce(valids)

    if reject_rgb_zero:
        valid &= ~np.all(image == 0, axis=0)

    return image, valid


def raster_distance_to_median(aligned_file: Path, median_file: Path, bands: int) -> float:
    aligned, aligned_valid = read_raster_for_distance(
        aligned_file,
        bands=bands,
        reject_rgb_zero=True,
    )
    median, median_valid = read_raster_for_distance(
        median_file,
        bands=bands,
        reject_rgb_zero=False,
    )

    if aligned.shape != median.shape:
        raise RuntimeError(
            f"Raster shapes differ for medoid selection: {aligned_file} and {median_file}"
        )

    valid = aligned_valid & median_valid
    if not np.any(valid):
        return math.inf

    diff = aligned[:, valid] - median[:, valid]
    return float(np.sqrt(np.mean(diff * diff)))


def compute_support_metrics(variant_id: str, n_orthos: int, valid_count_file: Path) -> dict[str, str]:
    arr = read_raster_array(valid_count_file)

    values, counts = np.unique(arr, return_counts=True)
    hist = {int(v): int(c) for v, c in zip(values.tolist(), counts.tolist())}
    total = int(arr.size)

    no_support = hist.get(0, 0)
    any_support = sum(hist.get(i, 0) for i in range(1, n_orthos + 1))
    full_support = hist.get(n_orthos, 0)
    variable_support = sum(hist.get(i, 0) for i in range(1, n_orthos))

    no_support_fraction_grid = no_support / total if total else math.nan
    any_support_fraction_grid = any_support / total if total else math.nan
    full_support_fraction_grid = full_support / total if total else math.nan
    variable_support_fraction_grid = variable_support / total if total else math.nan

    if any_support:
        support_persistence_footprint = full_support / any_support
        support_dropout_footprint = variable_support / any_support
    else:
        support_persistence_footprint = math.nan
        support_dropout_footprint = math.nan

    row: dict[str, str] = {
        "variant_id": variant_id,
        "n_orthos": str(n_orthos),
        "total_pixels": str(total),
        "no_support_pixels": str(no_support),
        "any_support_pixels": str(any_support),
        "full_support_pixels": str(full_support),
        "variable_support_pixels": str(variable_support),
        "no_support_fraction_grid": fmt(no_support_fraction_grid),
        "any_support_fraction_grid": fmt(any_support_fraction_grid),
        "full_support_fraction_grid": fmt(full_support_fraction_grid),
        "variable_support_fraction_grid": fmt(variable_support_fraction_grid),
        "support_persistence_footprint": fmt(support_persistence_footprint),
        "support_dropout_footprint": fmt(support_dropout_footprint),
    }

    for i in range(0, n_orthos + 1):
        count = hist.get(i, 0)
        row[f"valid_count_{i}"] = str(count)
        row[f"valid_count_{i}_fraction_grid"] = fmt(count / total if total else math.nan)

    return row


def derive_support_rows(
    summary_rows: list[dict[str, str]],
    output_dir: Path,
) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}

    for row in summary_rows:
        variant = row["variant_id"]
        n_orthos = int(float(row["n_orthos"]))
        valid_count_file = output_dir / "variants" / variant / "valid_count.tif"

        if not valid_count_file.is_file():
            raise FileNotFoundError(f"Missing valid_count raster: {valid_count_file}")

        out[variant] = compute_support_metrics(variant, n_orthos, valid_count_file)

    return out


def build_compact_rows(
    summary_rows: list[dict[str, str]],
    support_by_variant: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    for row in summary_rows:
        variant = row["variant_id"]
        support = support_by_variant[variant]

        rows.append(
            {
                "variant_id": variant,
                "n_orthos": row.get("n_orthos", ""),
                "any_support_fraction_grid": support["any_support_fraction_grid"],
                "full_support_fraction_grid": support["full_support_fraction_grid"],
                "variable_support_fraction_grid": support["variable_support_fraction_grid"],
                "support_persistence_footprint": support["support_persistence_footprint"],
                "support_dropout_footprint": support["support_dropout_footprint"],
                "mean_mad_rgb": fmt(row.get("mean_mad_rgb")),
                "p95_mad_rgb": fmt(row.get("p95_mad_rgb")),
                "mean_rmse_to_median": fmt(row.get("mean_rmse_to_median")),
                "p95_rmse_to_median": fmt(row.get("p95_rmse_to_median")),
                "stable_fraction_support_rmse": fmt(row.get("stable_fraction_support_rmse")),
                "unstable_fraction_support_rmse": fmt(row.get("unstable_fraction_support_rmse")),
            }
        )

    return rows


def continuous_ranking_key(row: dict[str, str]) -> tuple[float, float, float, float]:
    return (
        as_float(row.get("p95_rmse_to_median")),
        as_float(row.get("mean_rmse_to_median")),
        as_float(row.get("p95_mad_rgb")),
        as_float(row.get("mean_mad_rgb")),
    )


def mask_ranking_key(row: dict[str, str]) -> tuple[float, float]:
    stable = as_float(row.get("stable_fraction_support_rmse"))
    unstable = as_float(row.get("unstable_fraction_support_rmse"))
    return (-stable if not math.isnan(stable) else math.inf, unstable)


def support_ranking_key(row: dict[str, str]) -> tuple[float, float, float]:
    dropout = as_float(row.get("support_dropout_footprint"))
    variable = as_float(row.get("variable_support_fraction_grid"))
    persistence = as_float(row.get("support_persistence_footprint"))
    return (dropout, variable, -persistence if not math.isnan(persistence) else math.inf)


def support_histogram_columns(support_rows: dict[str, dict[str, str]]) -> list[str]:
    max_n = max(int(row["n_orthos"]) for row in support_rows.values()) if support_rows else 0

    columns = [
        "variant_id",
        "n_orthos",
        "total_pixels",
        "no_support_pixels",
        "any_support_pixels",
        "full_support_pixels",
        "variable_support_pixels",
    ]

    for i in range(0, max_n + 1):
        columns.append(f"valid_count_{i}")
        columns.append(f"valid_count_{i}_fraction_grid")

    columns.extend(
        [
            "no_support_fraction_grid",
            "any_support_fraction_grid",
            "full_support_fraction_grid",
            "variable_support_fraction_grid",
            "support_persistence_footprint",
            "support_dropout_footprint",
        ]
    )

    return columns


def write_qgis_layers(
    rows: list[dict[str, str]],
    output_dir: Path,
    path: Path,
    threshold: float,
) -> None:
    suffix = threshold_label(threshold)
    layer_names = [
        "median_ortho.tif",
        "valid_count.tif",
        "rmse_to_median.tif",
    ]

    with path.open("w") as handle:
        for row in rows:
            variant = row["variant_id"]
            variant_dir = output_dir / "variants" / variant
            handle.write(f"[{variant}]\n")
            for layer_name in layer_names:
                handle.write(str(variant_dir / layer_name) + "\n")
            handle.write("\n")


def select_medoid_replicate(
    variant_id: str,
    manifest_rows: list[dict[str, str]],
    output_dir: Path,
    bands: int,
) -> tuple[dict[str, str | float | None] | None, list[str]]:
    warnings_out: list[str] = []
    median_file = output_dir / "variants" / variant_id / "median_ortho.tif"

    if not median_file.is_file():
        warnings_out.append(f"Missing selected variant median raster: {median_file}")
        return None, warnings_out

    candidates = []
    for row in manifest_rows:
        if row.get("variant_id", "").strip() != variant_id:
            continue
        if row.get("status", "").strip() != "ok":
            continue

        ortho_file = row.get("ortho_file", "").strip()
        replicate = row.get("replicate", "").strip()
        if not ortho_file or not replicate:
            continue
        if not Path(ortho_file).is_file():
            continue

        aligned_file = output_dir / "aligned" / variant_id / f"{replicate}_aligned.tif"
        if not aligned_file.is_file():
            warnings_out.append(
                f"Aligned raster missing for medoid candidate {variant_id}/{replicate}: "
                f"{aligned_file}"
            )
            continue

        try:
            distance = raster_distance_to_median(
                aligned_file=aligned_file,
                median_file=median_file,
                bands=bands,
            )
        except RuntimeError as exc:
            warnings_out.append(
                f"Could not score medoid candidate {variant_id}/{replicate}: {exc}"
            )
            continue
        if math.isinf(distance):
            warnings_out.append(
                f"No common valid pixels for medoid candidate {variant_id}/{replicate}: "
                f"{aligned_file}"
            )
            continue

        candidates.append(
            {
                "replicate": replicate,
                "ortho_file": str(Path(ortho_file).resolve()),
                "aligned_file": str(aligned_file),
                "distance_value": distance,
            }
        )

    if not candidates:
        warnings_out.append(f"No medoid replicate candidates found for variant: {variant_id}")
        return None, warnings_out

    selected = min(candidates, key=lambda item: item["distance_value"])

    return selected, warnings_out


def raster_valid_mask(band: gdal.Band, arr: np.ndarray) -> np.ndarray:
    valid = np.isfinite(arr)

    nodata = band.GetNoDataValue()
    if nodata is not None:
        valid &= arr != nodata

    mask_band = band.GetMaskBand()
    if mask_band is not None:
        valid &= mask_band.ReadAsArray() != 0

    return valid


def write_byte_mask(
    path: Path,
    values: np.ndarray,
    reference_ds: gdal.Dataset,
    nodata: int = 255,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(
        str(path),
        reference_ds.RasterXSize,
        reference_ds.RasterYSize,
        1,
        gdal.GDT_Byte,
        options=["COMPRESS=DEFLATE", "TILED=YES"],
    )
    if ds is None:
        raise RuntimeError(f"Could not create raster: {path}")

    ds.SetGeoTransform(reference_ds.GetGeoTransform())
    ds.SetProjection(reference_ds.GetProjection())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(nodata)
    band.WriteArray(values)
    band.FlushCache()
    ds.FlushCache()
    ds = None


def run_threshold_review(
    summary_rows: list[dict[str, str]],
    output_dir: Path,
    review_dir: Path,
    thresholds: list[float],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    sensitivity_rows: list[dict[str, str]] = []
    numeric_rows: list[dict[str, str | float]] = []

    if not thresholds:
        return sensitivity_rows, []

    for threshold in thresholds:
        suffix = threshold_label(threshold)
        for row in summary_rows:
            variant = row["variant_id"]
            rmse_file = output_dir / "variants" / variant / "rmse_to_median.tif"
            if not rmse_file.is_file():
                raise FileNotFoundError(f"Missing RMSE raster: {rmse_file}")

            ds = gdal.Open(str(rmse_file), gdal.GA_ReadOnly)
            if ds is None:
                raise RuntimeError(f"Could not open raster: {rmse_file}")

            band = ds.GetRasterBand(1)
            rmse = band.ReadAsArray().astype("float32")
            valid = raster_valid_mask(band, rmse)

            stable = valid & (rmse <= threshold)
            unstable = valid & (rmse > threshold)

            quality_flag = np.zeros(rmse.shape, dtype=np.uint8)
            quality_flag[stable] = 1
            quality_flag[unstable] = 2

            variant_review_dir = review_dir / f"rmse{suffix}" / "variants" / variant
            write_byte_mask(
                variant_review_dir / f"quality_flag_rmse{suffix}.tif",
                quality_flag,
                ds,
                nodata=0,
            )

            valid_pixels = int(np.count_nonzero(valid))
            stable_pixels = int(np.count_nonzero(stable))
            unstable_pixels = int(np.count_nonzero(unstable))
            stable_fraction = stable_pixels / valid_pixels if valid_pixels else math.nan
            unstable_fraction = unstable_pixels / valid_pixels if valid_pixels else math.nan

            out_row = {
                "threshold": threshold_label(threshold),
                "variant_id": variant,
                "valid_pixels": str(valid_pixels),
                "stable_pixels": str(stable_pixels),
                "unstable_pixels": str(unstable_pixels),
                "stable_fraction_valid": fmt(stable_fraction, digits=6),
                "unstable_fraction_valid": fmt(unstable_fraction, digits=6),
            }
            sensitivity_rows.append(out_row)
            numeric_rows.append(
                {
                    **out_row,
                    "_threshold": threshold,
                    "_stable_fraction": stable_fraction,
                    "_unstable_fraction": unstable_fraction,
                }
            )
            ds = None

    winner_rows: list[dict[str, str]] = []
    for threshold in thresholds:
        threshold_rows = [
            row for row in numeric_rows if row["_threshold"] == threshold
        ]
        if not threshold_rows:
            continue

        def winner_key(row: dict[str, str | float]) -> tuple[float, float, str]:
            stable = row["_stable_fraction"]
            unstable = row["_unstable_fraction"]
            stable_key = (
                -stable
                if isinstance(stable, float) and not math.isnan(stable)
                else math.inf
            )
            unstable_key = (
                unstable
                if isinstance(unstable, float) and not math.isnan(unstable)
                else math.inf
            )
            return (stable_key, unstable_key, str(row["variant_id"]))

        winner = sorted(threshold_rows, key=winner_key)[0]
        winner_rows.append(
            {
                "threshold": threshold_label(threshold),
                "winner_variant_id": str(winner["variant_id"]),
                "stable_fraction_valid": str(winner["stable_fraction_valid"]),
                "unstable_fraction_valid": str(winner["unstable_fraction_valid"]),
            }
        )

    return sensitivity_rows, winner_rows


def rel_from_experiment(path: Path | str, experiment_dir: Path) -> str:
    return os.path.relpath(Path(path), experiment_dir)


def qgis_posix_arg(relative_path: str) -> str:
    return '"$SCRIPT_DIR"/' + shlex.quote(relative_path)


def qgis_windows_arg(relative_path: str) -> str:
    win_path = str(PureWindowsPath(relative_path)).replace("%", "%%")
    return '"%SCRIPT_DIR%' + win_path.replace('"', '""') + '"'


def existing_relative_paths(paths: list[Path | str | None], experiment_dir: Path) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if not path:
            continue
        path_obj = Path(path)
        if not path_obj.is_file():
            continue
        relative = rel_from_experiment(path_obj, experiment_dir)
        if relative not in seen:
            out.append(relative)
            seen.add(relative)
    return out


def write_qgis_launchers(
    sh_path: Path,
    bat_path: Path,
    relative_paths: list[str],
) -> None:
    posix_args = " \\\n  ".join(qgis_posix_arg(path) for path in relative_paths)
    with sh_path.open("w", newline="\n") as handle:
        handle.write("#!/usr/bin/env bash\n")
        handle.write("set -euo pipefail\n")
        handle.write('SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n')
        if posix_args:
            handle.write("qgis \\\n  ")
            handle.write(posix_args)
            handle.write("\n")
        else:
            handle.write('qgis "$SCRIPT_DIR"\n')
    sh_path.chmod(0o755)

    windows_args = " ^\n  ".join(qgis_windows_arg(path) for path in relative_paths)
    with bat_path.open("w", newline="\r\n") as handle:
        handle.write("@echo off\n")
        handle.write("setlocal\n")
        handle.write("set \"SCRIPT_DIR=%~dp0\"\n")
        handle.write("if defined QGIS_BIN (\n")
        handle.write("  set \"QGIS_EXE=%QGIS_BIN%\"\n")
        handle.write(") else (\n")
        handle.write("  set \"QGIS_EXE=qgis-bin.exe\"\n")
        handle.write(")\n")
        if windows_args:
            handle.write("\"%QGIS_EXE%\" ^\n  ")
            handle.write(windows_args)
            handle.write("\n")
        else:
            handle.write("\"%QGIS_EXE%\" \"%SCRIPT_DIR%\"\n")


def selected_launcher_paths(
    selected_product: dict[str, object],
    experiment_dir: Path,
    output_dir: Path,
    review_dir: Path,
    threshold: float,
) -> list[str]:
    variant = str(selected_product["primary_variant_id"])
    suffix = threshold_label(threshold)
    variant_dir = output_dir / "variants" / variant
    review_variant_dir = review_dir / f"rmse{suffix}" / "variants" / variant
    product_modes = selected_product.get("product_modes", {})
    medoid = (
        product_modes.get("medoid_replicate")
        if isinstance(product_modes, dict)
        else None
    )

    medoid_aligned = None
    medoid_original = None
    if isinstance(medoid, dict):
        medoid_aligned = medoid.get("aligned_file")
        medoid_original = medoid.get("ortho_file")

    return existing_relative_paths(
        [
            variant_dir / "median_ortho.tif",
            variant_dir / "rmse_to_median.tif",
            variant_dir / "valid_count.tif",
            review_variant_dir / f"quality_flag_rmse{suffix}.tif",
            medoid_aligned,
            medoid_original,
        ],
        experiment_dir,
    )


def threshold_launcher_paths(
    selected_product: dict[str, object],
    experiment_dir: Path,
    output_dir: Path,
    review_dir: Path,
    thresholds: list[float],
) -> list[str]:
    variant = str(selected_product["primary_variant_id"])
    variant_dir = output_dir / "variants" / variant
    paths: list[Path | str | None] = [
        variant_dir / "median_ortho.tif",
        variant_dir / "rmse_to_median.tif",
        variant_dir / "valid_count.tif",
    ]

    for threshold in thresholds:
        suffix = threshold_label(threshold)
        review_variant_dir = review_dir / f"rmse{suffix}" / "variants" / variant
        paths.append(review_variant_dir / f"quality_flag_rmse{suffix}.tif")

    return existing_relative_paths(paths, experiment_dir)


def row_subset(row: dict[str, str], columns: list[str]) -> dict[str, str]:
    return {col: row.get(col, "") for col in columns}


def write_selected_product(
    continuous_ranked: list[dict[str, str]],
    mask_ranked: list[dict[str, str]],
    support_ranked: list[dict[str, str]],
    support_by_variant: dict[str, dict[str, str]],
    manifest_rows: list[dict[str, str]],
    experiment_dir: Path,
    output_dir: Path,
    path: Path,
    bands: int,
    threshold: float,
) -> dict[str, object]:
    if not continuous_ranked:
        raise RuntimeError("No continuous-stability candidates available for product selection.")

    primary = continuous_ranked[0]
    primary_variant = primary["variant_id"]
    support_candidate = support_ranked[0] if support_ranked else {}
    mask_candidate = mask_ranked[0] if mask_ranked else {}
    support_candidate_variant = support_candidate.get("variant_id", "")
    median_file = output_dir / "variants" / primary_variant / "median_ortho.tif"
    warnings_out: list[str] = []

    if support_candidate and support_candidate_variant != primary_variant:
        warnings_out.append(
            "Support-persistence candidate differs from the continuous-stability primary variant; "
            "review spatial support before product use."
        )

    if mask_candidate and mask_candidate.get("variant_id") != primary_variant:
        warnings_out.append(
            "Threshold quality-flag candidate differs from the continuous-stability primary variant; "
            "review threshold quality flags before product use."
        )

    medoid, medoid_warnings = select_medoid_replicate(
        variant_id=primary_variant,
        manifest_rows=manifest_rows,
        output_dir=output_dir,
        bands=bands,
    )
    warnings_out.extend(medoid_warnings)
    medoid_mode = None
    if medoid is not None:
        medoid_mode = {
            "variant_id": primary_variant,
            "replicate": medoid["replicate"],
            "ortho_file": medoid["ortho_file"],
            "aligned_file": medoid["aligned_file"],
            "distance_metric": "rgb_rmse_to_selected_variant_median_on_common_valid_pixels",
            "distance_value": medoid["distance_value"],
            "description": (
                "Use the original Metashape replicate orthomosaic whose existing aligned "
                "raster is closest to the selected variant's median_ortho.tif."
            ),
        }

    product = {
        "selection_policy": "continuous_first",
        "primary_variant_id": primary_variant,
        "primary_selection_category": "continuous_stability",
        "product_modes": {
            "median_ortho": {
                "path": str(median_file),
                "exists": median_file.is_file(),
                "missing": not median_file.is_file(),
                "description": (
                    "Use the selected continuous-stability variant's existing median_ortho.tif."
                ),
            },
            "medoid_replicate": medoid_mode,
        },
        "support_persistence_context": {
            "role": "feasibility_coverage_context",
            "candidate_variant_id": support_candidate_variant,
            "primary_variant_metrics": row_subset(
                support_by_variant.get(primary_variant, {}),
                SUPPORT_COLUMNS,
            ),
            "candidate_metrics": row_subset(
                support_by_variant.get(support_candidate_variant, {}),
                SUPPORT_COLUMNS,
            )
            if support_candidate_variant
            else {},
            "description": (
                "Support persistence marks reachable and evaluable output area and does not "
                "automatically override the continuous-stability primary variant."
            ),
        },
        "threshold_guard_context": {
            "role": "rejection_warning_guard",
            "stable_rmse_threshold": threshold,
            "candidate_variant_id": mask_candidate.get("variant_id", ""),
            "primary_variant_metrics": row_subset(primary, SUMMARY_COLUMNS),
            "candidate_metrics": row_subset(mask_candidate, SUMMARY_COLUMNS)
            if mask_candidate
            else {},
            "description": (
                "Threshold quality-flag metrics are used as a rejection or warning guard, not as the "
                "primary selection logic."
            ),
        },
        "source_files": {
            "manifest": str(experiment_dir / "manifest.csv"),
            "summary": str(output_dir / "summary.csv"),
            "summary_key_metrics": str(output_dir / "summary_key_metrics.tsv"),
            "support_valid_count_histogram": str(
                output_dir / "support_valid_count_histogram.tsv"
            ),
            "selected_variant_median_ortho": str(median_file),
        },
        "warnings": warnings_out,
    }

    with path.open("w", encoding="utf-8") as handle:
        json.dump(product, handle, indent=2, sort_keys=True)
        handle.write("\n")

    return product


def write_report(
    continuous_ranked: list[dict[str, str]],
    mask_ranked: list[dict[str, str]],
    support_ranked: list[dict[str, str]],
    support_by_variant: dict[str, dict[str, str]],
    experiment_dir: Path,
    output_dir: Path,
    report_file: Path,
    grid_mode: str,
    bands: int,
    threshold: float,
) -> None:
    continuous_best = continuous_ranked[0]["variant_id"] if continuous_ranked else "NA"
    mask_best = mask_ranked[0]["variant_id"] if mask_ranked else "NA"
    support_best = support_ranked[0]["variant_id"] if support_ranked else "NA"
    suffix = threshold_label(threshold)

    support_table_rows = [support_by_variant[v] for v in sorted(support_by_variant)]
    support_table = table_text(support_table_rows, SUPPORT_COLUMNS)
    compact_table = table_text(continuous_ranked, KEY_COLUMNS)

    with report_file.open("w") as handle:
        handle.write("# Orthomosaic Stability Evaluation Report\n\n")
        handle.write(f"Generated: {datetime.now().isoformat(timespec='seconds')}\n\n")
        handle.write(f"Experiment directory: `{experiment_dir}`\n\n")
        handle.write(f"Analysis directory: `{output_dir}`\n\n")

        handle.write("## Analyzer settings\n\n")
        handle.write(f"- grid mode: `{grid_mode}`\n")
        handle.write(f"- bands: `{bands}`\n")
        handle.write(f"- stable RMSE threshold: `{threshold}`\n\n")

        handle.write("## Candidate summary\n\n")
        handle.write(f"Continuous stability candidate: `{continuous_best}`\n\n")
        handle.write(f"Threshold quality-flag candidate: `{mask_best}`\n\n")
        handle.write(f"Support-persistence candidate: `{support_best}`\n\n")

        handle.write("The continuous stability candidate is ranked by:\n\n")
        handle.write("1. lower `p95_rmse_to_median`\n")
        handle.write("2. lower `mean_rmse_to_median`\n")
        handle.write("3. lower `p95_mad_rgb`\n")
        handle.write("4. lower `mean_mad_rgb`\n\n")

        handle.write(
            "The threshold quality-flag candidate is ranked by `stable_fraction_support_rmse`. "
            "This result depends on the selected RMSE threshold and is therefore reported separately.\n\n"
        )

        handle.write(
            "The support-persistence candidate is ranked by footprint-relative support dropout, "
            "not by the absolute rectangular-grid footprint. This avoids confusing the footprint "
            "shape inside the canonical rectangle with true replicate-to-replicate support loss.\n\n"
        )

        handle.write("## Support interpretation\n\n")
        handle.write(
            "`any_support_fraction_grid` is the fraction of the rectangular canonical grid "
            "with valid orthomosaic support in at least one replicate.\n\n"
        )
        handle.write(
            "`full_support_fraction_grid` is the fraction of the rectangular canonical grid "
            "with valid orthomosaic support in all replicates.\n\n"
        )
        handle.write(
            "`variable_support_fraction_grid` is the fraction of the rectangular canonical grid "
            "with support in some but not all replicates.\n\n"
        )
        handle.write(
            "`support_persistence_footprint = full_support / any_support` describes support "
            "persistence inside the actual orthomosaic footprint.\n\n"
        )
        handle.write(
            "`support_dropout_footprint = variable_support / any_support` describes replicate-to-replicate "
            "support dropout inside the actual orthomosaic footprint.\n\n"
        )

        handle.write("```text\n")
        handle.write(support_table)
        handle.write("\n```\n\n")

        handle.write("## Compact stability summary\n\n")
        handle.write("The table is sorted by continuous image-value stability.\n\n")
        handle.write("```text\n")
        handle.write(compact_table)
        handle.write("\n```\n\n")

        handle.write("## Spatial inspection layers\n\n")
        for row in continuous_ranked:
            variant = row["variant_id"]
            variant_dir = output_dir / "variants" / variant
            review_variant_dir = experiment_dir / "threshold_review" / f"rmse{suffix}" / "variants" / variant
            handle.write(f"### {variant}\n\n")
            handle.write(f"- `{variant_dir / 'median_ortho.tif'}`\n")
            handle.write(f"- `{variant_dir / 'valid_count.tif'}`\n")
            handle.write(f"- `{variant_dir / 'rmse_to_median.tif'}`\n")
            handle.write(f"- `{review_variant_dir / f'quality_flag_rmse{suffix}.tif'}`\n\n")

        handle.write("## Interpretation note\n\n")
        handle.write(
            "This report evaluates repeated-build stability of exported orthomosaic products. "
            "It does not prove geometric accuracy. Continuous deviation metrics, threshold-based "
            "quality flags, and support persistence metrics are reported separately because they answer "
            "different questions.\n\n"
        )
        handle.write(
            "A low absolute `full_support_fraction_grid` can simply reflect that the orthomosaic "
            "footprint occupies only part of the rectangular canonical grid. Replicate-to-replicate "
            "support loss is better described by `support_dropout_footprint` and by the "
            "`valid_count.tif` raster.\n\n"
        )
        handle.write(
            "Final interpretation should combine this table with spatial inspection of "
            "`valid_count.tif`, `rmse_to_median.tif`, and threshold quality flags.\n"
        )


def main() -> None:
    args = parse_args()
    gdal.UseExceptions()
    if args.block_size <= 0:
        raise RuntimeError("--block-size must be a positive integer.")

    experiment_dir = Path(args.experiment_dir).resolve()
    output_dir = experiment_dir / "stability_union"
    review_dir = experiment_dir / "threshold_review"
    summary_file = output_dir / "summary.csv"
    thresholds = parse_thresholds(args.thresholds)

    if not args.skip_analyzer:
        run_analyzer(
            experiment_dir=experiment_dir,
            output_dir=output_dir,
            grid_mode=args.grid_mode,
            bands=args.bands,
            threshold=args.stable_rmse_threshold,
            block_size=args.block_size,
            overwrite=not args.no_overwrite,
        )

    if not summary_file.is_file():
        raise FileNotFoundError(f"Missing summary file: {summary_file}")

    manifest_file = experiment_dir / "manifest.csv"
    if not manifest_file.is_file():
        raise FileNotFoundError(f"Missing manifest file: {manifest_file}")

    summary_rows = read_csv_dicts(summary_file)
    manifest_rows = read_manifest_rows(manifest_file)
    support_by_variant = derive_support_rows(summary_rows, output_dir)
    compact_rows = build_compact_rows(summary_rows, support_by_variant)

    continuous_ranked = sorted(compact_rows, key=continuous_ranking_key)
    mask_ranked = sorted(compact_rows, key=mask_ranking_key)
    support_ranked = sorted(compact_rows, key=support_ranking_key)

    key_metrics_file = output_dir / "summary_key_metrics.tsv"
    support_histogram_file = output_dir / "support_valid_count_histogram.tsv"
    qgis_layers_file = output_dir / "qgis_layers.txt"
    report_file = output_dir / "evaluation_report.md"
    selected_product_file = experiment_dir / "selected_product.json"
    qgis_selected_sh = experiment_dir / "qgis_open_selected.sh"
    qgis_selected_bat = experiment_dir / "qgis_open_selected.bat"
    threshold_sensitivity_file = review_dir / "threshold_sensitivity.tsv"
    threshold_winners_file = review_dir / "threshold_winners.tsv"
    qgis_threshold_sh = experiment_dir / "qgis_open_threshold_review.sh"
    qgis_threshold_bat = experiment_dir / "qgis_open_threshold_review.bat"

    write_tsv(continuous_ranked, KEY_COLUMNS, key_metrics_file)

    support_rows_sorted = [support_by_variant[v] for v in sorted(support_by_variant)]
    write_tsv(
        support_rows_sorted,
        support_histogram_columns(support_by_variant),
        support_histogram_file,
    )

    write_qgis_layers(
        continuous_ranked,
        output_dir,
        qgis_layers_file,
        args.stable_rmse_threshold,
    )

    write_report(
        continuous_ranked=continuous_ranked,
        mask_ranked=mask_ranked,
        support_ranked=support_ranked,
        support_by_variant=support_by_variant,
        experiment_dir=experiment_dir,
        output_dir=output_dir,
        report_file=report_file,
        grid_mode=args.grid_mode,
        bands=args.bands,
        threshold=args.stable_rmse_threshold,
    )

    selected_product = write_selected_product(
        continuous_ranked=continuous_ranked,
        mask_ranked=mask_ranked,
        support_ranked=support_ranked,
        support_by_variant=support_by_variant,
        manifest_rows=manifest_rows,
        experiment_dir=experiment_dir,
        output_dir=output_dir,
        path=selected_product_file,
        bands=args.bands,
        threshold=args.stable_rmse_threshold,
    )

    threshold_rows: list[dict[str, str]] = []
    threshold_winner_rows: list[dict[str, str]] = []
    if thresholds:
        threshold_rows, threshold_winner_rows = run_threshold_review(
            summary_rows=summary_rows,
            output_dir=output_dir,
            review_dir=review_dir,
            thresholds=thresholds,
        )
        write_tsv(
            threshold_rows,
            [
                "threshold",
                "variant_id",
                "valid_pixels",
                "stable_pixels",
                "unstable_pixels",
                "stable_fraction_valid",
                "unstable_fraction_valid",
            ],
            threshold_sensitivity_file,
        )
        write_tsv(
            threshold_winner_rows,
            [
                "threshold",
                "winner_variant_id",
                "stable_fraction_valid",
                "unstable_fraction_valid",
            ],
            threshold_winners_file,
        )
        write_qgis_launchers(
            sh_path=qgis_threshold_sh,
            bat_path=qgis_threshold_bat,
            relative_paths=threshold_launcher_paths(
                selected_product=selected_product,
                experiment_dir=experiment_dir,
                output_dir=output_dir,
                review_dir=review_dir,
                thresholds=thresholds,
            ),
        )

    write_qgis_launchers(
        sh_path=qgis_selected_sh,
        bat_path=qgis_selected_bat,
        relative_paths=selected_launcher_paths(
            selected_product=selected_product,
            experiment_dir=experiment_dir,
            output_dir=output_dir,
            review_dir=review_dir,
            threshold=args.stable_rmse_threshold,
        ),
    )

    print()
    print("Candidate summary")
    print(f"Continuous stability candidate: {continuous_ranked[0]['variant_id']}")
    print(f"Threshold quality-flag candidate: {mask_ranked[0]['variant_id']}")
    print(f"Support-persistence candidate: {support_ranked[0]['variant_id']}")

    print()
    print("Support summary")
    print(table_text(support_rows_sorted, SUPPORT_COLUMNS))

    print()
    print("Compact stability table")
    print(table_text(continuous_ranked, KEY_COLUMNS))

    print()
    print(f"Wrote: {key_metrics_file}")
    print(f"Wrote: {support_histogram_file}")
    print(f"Wrote: {qgis_layers_file}")
    print(f"Wrote: {report_file}")
    print(f"Wrote: {selected_product_file}")
    print(f"Wrote: {qgis_selected_sh}")
    print(f"Wrote: {qgis_selected_bat}")
    if thresholds:
        print(f"Wrote: {threshold_sensitivity_file}")
        print(f"Wrote: {threshold_winners_file}")
        print(f"Wrote: {qgis_threshold_sh}")
        print(f"Wrote: {qgis_threshold_bat}")
    print_review_commands(experiment_dir=experiment_dir, output_dir=output_dir)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc
