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
import math
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from osgeo import gdal


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
        "--no-overwrite",
        action="store_true",
        help="Do not pass --overwrite to ortho_stability_analyzer.py.",
    )
    return parser.parse_args()


def threshold_label(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return str(value).replace(".", "p")


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
    overwrite: bool,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    analyzer = repo_root / "python" / "ortho_stability_analyzer.py"
    manifest = experiment_dir / "manifest.csv"

    if not manifest.is_file():
        raise FileNotFoundError(f"Missing manifest file: {manifest}")
    if not analyzer.is_file():
        raise FileNotFoundError(f"Missing analyzer script: {analyzer}")

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
    ]

    if overwrite:
        cmd.append("--overwrite")

    print("Running Stability Analyzer")
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)


def read_raster_array(path: Path) -> np.ndarray:
    ds = gdal.Open(str(path), gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError(f"Could not open raster: {path}")

    arr = ds.ReadAsArray()
    if arr.ndim == 3:
        arr = arr[0]

    return arr.copy()


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
        f"stable_mask_rmse{suffix}.tif",
        f"unstable_mask_rmse{suffix}.tif",
    ]

    with path.open("w") as handle:
        for row in rows:
            variant = row["variant_id"]
            variant_dir = output_dir / "variants" / variant
            handle.write(f"[{variant}]\n")
            for layer_name in layer_names:
                handle.write(str(variant_dir / layer_name) + "\n")
            handle.write("\n")


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
        handle.write(f"Threshold-mask candidate: `{mask_best}`\n\n")
        handle.write(f"Support-persistence candidate: `{support_best}`\n\n")

        handle.write("The continuous stability candidate is ranked by:\n\n")
        handle.write("1. lower `p95_rmse_to_median`\n")
        handle.write("2. lower `mean_rmse_to_median`\n")
        handle.write("3. lower `p95_mad_rgb`\n")
        handle.write("4. lower `mean_mad_rgb`\n\n")

        handle.write(
            "The threshold-mask candidate is ranked by `stable_fraction_support_rmse`. "
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
            handle.write(f"### {variant}\n\n")
            handle.write(f"- `{variant_dir / 'median_ortho.tif'}`\n")
            handle.write(f"- `{variant_dir / 'valid_count.tif'}`\n")
            handle.write(f"- `{variant_dir / 'rmse_to_median.tif'}`\n")
            handle.write(f"- `{variant_dir / f'stable_mask_rmse{suffix}.tif'}`\n")
            handle.write(f"- `{variant_dir / f'unstable_mask_rmse{suffix}.tif'}`\n\n")

        handle.write("## Interpretation note\n\n")
        handle.write(
            "This report evaluates repeated-build stability of exported orthomosaic products. "
            "It does not prove geometric accuracy. Continuous deviation metrics, threshold-based "
            "masks, and support persistence metrics are reported separately because they answer "
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
            "`valid_count.tif`, `rmse_to_median.tif`, and the stable / unstable masks.\n"
        )


def main() -> None:
    args = parse_args()
    gdal.UseExceptions()

    experiment_dir = Path(args.experiment_dir).resolve()
    output_dir = experiment_dir / "stability_union"
    summary_file = output_dir / "summary.csv"

    if not args.skip_analyzer:
        run_analyzer(
            experiment_dir=experiment_dir,
            output_dir=output_dir,
            grid_mode=args.grid_mode,
            bands=args.bands,
            threshold=args.stable_rmse_threshold,
            overwrite=not args.no_overwrite,
        )

    if not summary_file.is_file():
        raise FileNotFoundError(f"Missing summary file: {summary_file}")

    summary_rows = read_csv_dicts(summary_file)
    support_by_variant = derive_support_rows(summary_rows, output_dir)
    compact_rows = build_compact_rows(summary_rows, support_by_variant)

    continuous_ranked = sorted(compact_rows, key=continuous_ranking_key)
    mask_ranked = sorted(compact_rows, key=mask_ranking_key)
    support_ranked = sorted(compact_rows, key=support_ranking_key)

    key_metrics_file = output_dir / "summary_key_metrics.tsv"
    support_histogram_file = output_dir / "support_valid_count_histogram.tsv"
    qgis_layers_file = output_dir / "qgis_layers.txt"
    report_file = output_dir / "evaluation_report.md"

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

    print()
    print("Candidate summary")
    print(f"Continuous stability candidate: {continuous_ranked[0]['variant_id']}")
    print(f"Threshold-mask candidate: {mask_ranked[0]['variant_id']}")
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


if __name__ == "__main__":
    main()
