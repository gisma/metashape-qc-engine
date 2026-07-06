from __future__ import annotations

from dataclasses import dataclass
import argparse
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np
import rasterio
from rasterio.windows import Window


@dataclass(frozen=True)
class GlobalRegionMergeConfig:
    feature_stack_path: str | Path
    valid_mask_path: str | Path
    output_dir: str | Path
    max_region_rms: float
    max_spatial_rms_px: float
    initial_block_size_px: int = 2
    window: tuple[int, int, int, int] | None = None
    overwrite: bool = False


def _region_rms(values: np.ndarray) -> float:
    if values.shape[1] <= 1:
        return 0.0
    center = values.mean(axis=1, keepdims=True)
    return float(np.sqrt(np.square(values - center).sum() / values.shape[1]))


def build_initial_regions(
    feature_stack: np.ndarray,
    valid_mask: np.ndarray,
    block_size_px: int,
    max_region_rms: float,
) -> np.ndarray:
    """Create connected grid seeds that already satisfy the global RMS limit."""
    if feature_stack.ndim != 3:
        raise ValueError("feature_stack must have shape [band, row, column]")
    if valid_mask.shape != feature_stack.shape[1:]:
        raise ValueError("valid_mask shape does not match feature stack")
    if block_size_px < 1:
        raise ValueError("block_size_px must be >= 1")
    if not math.isfinite(max_region_rms) or max_region_rms <= 0:
        raise ValueError("max_region_rms must be finite and > 0")

    height, width = valid_mask.shape
    labels = np.zeros((height, width), dtype=np.uint32)
    next_label = 1

    for row0 in range(0, height, block_size_px):
        for col0 in range(0, width, block_size_px):
            row1 = min(height, row0 + block_size_px)
            col1 = min(width, col0 + block_size_px)
            local_valid = valid_mask[row0:row1, col0:col1].astype(bool)
            seen = np.zeros(local_valid.shape, dtype=bool)

            for local_row, local_col in zip(*np.nonzero(local_valid)):
                if seen[local_row, local_col]:
                    continue
                stack = [(int(local_row), int(local_col))]
                seen[local_row, local_col] = True
                component: list[tuple[int, int]] = []
                while stack:
                    current_row, current_col = stack.pop()
                    component.append((current_row, current_col))
                    for delta_row, delta_col in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        neighbour_row = current_row + delta_row
                        neighbour_col = current_col + delta_col
                        if (
                            0 <= neighbour_row < local_valid.shape[0]
                            and 0 <= neighbour_col < local_valid.shape[1]
                            and local_valid[neighbour_row, neighbour_col]
                            and not seen[neighbour_row, neighbour_col]
                        ):
                            seen[neighbour_row, neighbour_col] = True
                            stack.append((neighbour_row, neighbour_col))

                rows = np.asarray([row0 + row for row, _ in component])
                cols = np.asarray([col0 + col for _, col in component])
                values = feature_stack[:, rows, cols]
                if _region_rms(values) <= max_region_rms:
                    labels[rows, cols] = next_label
                    next_label += 1
                else:
                    for row, col in zip(rows, cols):
                        labels[row, col] = next_label
                        next_label += 1

    return labels


def _adjacent_pairs(labels: np.ndarray) -> np.ndarray:
    pairs: list[np.ndarray] = []
    for first, second in (
        (labels[:, :-1], labels[:, 1:]),
        (labels[:-1, :], labels[1:, :]),
    ):
        keep = (first > 0) & (second > 0) & (first != second)
        if np.any(keep):
            left = np.minimum(first[keep], second[keep]).astype(np.int64)
            right = np.maximum(first[keep], second[keep]).astype(np.int64)
            pairs.append(np.column_stack((left, right)))
    if not pairs:
        return np.empty((0, 2), dtype=np.int64)
    return np.unique(np.concatenate(pairs, axis=0), axis=0)


def _region_statistics(
    labels: np.ndarray,
    feature_stack: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    positive = labels > 0
    rows, cols = np.nonzero(positive)
    flat_labels = labels[positive]
    region_count = int(labels.max())
    values = feature_stack[:, positive].astype(np.float64, copy=False)
    counts = np.bincount(flat_labels, minlength=region_count + 1).astype(np.int64)
    sums = np.zeros((region_count + 1, feature_stack.shape[0]), dtype=np.float64)
    for band in range(feature_stack.shape[0]):
        sums[:, band] = np.bincount(
            flat_labels,
            weights=values[band],
            minlength=region_count + 1,
        )
    sum_squares = np.bincount(
        flat_labels,
        weights=np.square(values).sum(axis=0),
        minlength=region_count + 1,
    )
    coordinate_sums = np.column_stack(
        (
            np.bincount(flat_labels, weights=cols, minlength=region_count + 1),
            np.bincount(flat_labels, weights=rows, minlength=region_count + 1),
        )
    )
    coordinate_sum_squares = np.bincount(
        flat_labels,
        weights=np.square(cols.astype(np.float64)) + np.square(rows.astype(np.float64)),
        minlength=region_count + 1,
    )
    return counts, sums, sum_squares, coordinate_sums, coordinate_sum_squares


def _compact_labels(labels: np.ndarray) -> np.ndarray:
    positive = labels > 0
    active = np.unique(labels[positive])
    lookup = np.zeros(int(active.max()) + 1, dtype=np.uint32)
    lookup[active] = np.arange(1, len(active) + 1, dtype=np.uint32)
    compact = np.zeros(labels.shape, dtype=np.uint32)
    compact[positive] = lookup[labels[positive]]
    return compact


def merge_regions_global_rms(
    initial_labels: np.ndarray,
    feature_stack: np.ndarray,
    max_region_rms: float,
    max_spatial_rms_px: float | None = None,
) -> tuple[np.ndarray, dict[str, object]]:
    """Merge adjacent regions in deterministic, memory-bounded rounds.

    Every accepted pair is disjoint within its round. The RMS test uses the
    complete statistics of both current regions, so every resulting region
    satisfies the same global feature-dispersion contract. Adjacency is
    rebuilt from the label raster each round; no Python neighbour graph or
    all-history priority queue is retained in memory.
    """
    if initial_labels.shape != feature_stack.shape[1:]:
        raise ValueError("label shape does not match feature stack")
    if not math.isfinite(max_region_rms) or max_region_rms <= 0:
        raise ValueError("max_region_rms must be finite and > 0")
    if max_spatial_rms_px is not None and (
        not math.isfinite(max_spatial_rms_px) or max_spatial_rms_px <= 0
    ):
        raise ValueError("max_spatial_rms_px must be finite and > 0 when set")

    labels = _compact_labels(initial_labels)
    initial_region_count = int(labels.max())
    initial_edge_count = int(len(_adjacent_pairs(labels)))
    total_merge_count = 0
    rejected_current_edges = 0
    iteration_count = 0

    while True:
        iteration_count += 1
        (
            counts,
            sums,
            sum_squares,
            coordinate_sums,
            coordinate_sum_squares,
        ) = _region_statistics(labels, feature_stack)
        pairs = _adjacent_pairs(labels)
        if len(pairs) == 0:
            break

        first = pairs[:, 0]
        second = pairs[:, 1]
        pair_counts = counts[first] + counts[second]
        pair_sums = sums[first] + sums[second]
        pair_sum_squares = sum_squares[first] + sum_squares[second]
        pair_sse = np.maximum(
            0.0,
            pair_sum_squares
            - np.einsum("ij,ij->i", pair_sums, pair_sums) / pair_counts,
        )
        pair_rms = np.sqrt(pair_sse / pair_counts)
        pair_coordinate_sums = coordinate_sums[first] + coordinate_sums[second]
        pair_coordinate_sum_squares = (
            coordinate_sum_squares[first] + coordinate_sum_squares[second]
        )
        pair_spatial_sse = np.maximum(
            0.0,
            pair_coordinate_sum_squares
            - np.einsum(
                "ij,ij->i", pair_coordinate_sums, pair_coordinate_sums
            ) / pair_counts,
        )
        pair_spatial_rms = np.sqrt(pair_spatial_sse / pair_counts)
        eligible = pair_rms <= max_region_rms
        if max_spatial_rms_px is not None:
            eligible &= pair_spatial_rms <= max_spatial_rms_px
        eligible_indices = np.flatnonzero(eligible)
        rejected_current_edges += int(len(pairs) - len(eligible_indices))
        if len(eligible_indices) == 0:
            break

        normalized_cost = pair_rms / max_region_rms
        if max_spatial_rms_px is not None:
            normalized_cost = np.maximum(
                normalized_cost,
                pair_spatial_rms / max_spatial_rms_px,
            )
        order = eligible_indices[
            np.lexsort(
                (
                    second[eligible_indices],
                    first[eligible_indices],
                    normalized_cost[eligible_indices],
                )
            )
        ]
        used = np.zeros(len(counts), dtype=bool)
        selected_first: list[int] = []
        selected_second: list[int] = []
        for index in order:
            left = int(first[index])
            right = int(second[index])
            if used[left] or used[right]:
                continue
            used[left] = True
            used[right] = True
            selected_first.append(left)
            selected_second.append(right)

        if not selected_first:
            break
        lookup = np.arange(len(counts), dtype=np.uint32)
        keep = np.minimum(selected_first, selected_second)
        drop = np.maximum(selected_first, selected_second)
        lookup[drop] = keep
        labels = lookup[labels]
        labels = _compact_labels(labels)
        total_merge_count += len(selected_first)

    (
        counts,
        sums,
        sum_squares,
        coordinate_sums,
        coordinate_sum_squares,
    ) = _region_statistics(labels, feature_stack)
    active = np.flatnonzero(counts > 0)
    active = active[active > 0]
    sse = np.maximum(
        0.0,
        sum_squares[active]
        - np.einsum("ij,ij->i", sums[active], sums[active]) / counts[active],
    )
    final_rms = np.sqrt(sse / counts[active])
    spatial_sse = np.maximum(
        0.0,
        coordinate_sum_squares[active]
        - np.einsum(
            "ij,ij->i", coordinate_sums[active], coordinate_sums[active]
        ) / counts[active],
    )
    final_spatial_rms = np.sqrt(spatial_sse / counts[active])
    final_sizes = counts[active]
    diagnostics: dict[str, object] = {
        "merge_strategy": "round_based_disjoint_vectorized",
        "initial_region_count": int(initial_region_count),
        "final_region_count": int(len(active)),
        "merge_count": int(total_merge_count),
        "merge_iteration_count": int(iteration_count),
        "initial_adjacency_edge_count": int(initial_edge_count),
        "rejected_current_edge_count": int(rejected_current_edges),
        "max_region_rms": float(max_region_rms),
        "max_spatial_rms_px": (
            float(max_spatial_rms_px) if max_spatial_rms_px is not None else None
        ),
        "final_rms_max": float(final_rms.max()) if len(final_rms) else 0.0,
        "final_rms_median": float(np.median(final_rms)) if len(final_rms) else 0.0,
        "final_spatial_rms_px_max": (
            float(final_spatial_rms.max()) if len(final_spatial_rms) else 0.0
        ),
        "final_spatial_rms_px_median": (
            float(np.median(final_spatial_rms)) if len(final_spatial_rms) else 0.0
        ),
        "final_region_size_px_max": int(final_sizes.max()) if len(final_sizes) else 0,
        "final_region_size_px_median": (
            float(np.median(final_sizes)) if len(final_sizes) else 0.0
        ),
        "global_rms_contract_satisfied": bool(
            (not len(final_rms) or final_rms.max() <= max_region_rms + 1e-10)
            and (
                max_spatial_rms_px is None
                or not len(final_spatial_rms)
                or final_spatial_rms.max() <= max_spatial_rms_px + 1e-10
            )
        ),
    }
    return labels, diagnostics


def _window_from_config(
    window_spec: tuple[int, int, int, int] | None,
    width: int,
    height: int,
) -> Window:
    if window_spec is None:
        return Window(0, 0, width, height)
    col_off, row_off, window_width, window_height = window_spec
    if min(col_off, row_off) < 0 or min(window_width, window_height) < 1:
        raise ValueError("window values must define a positive in-bounds window")
    if col_off + window_width > width or row_off + window_height > height:
        raise ValueError("window exceeds raster bounds")
    return Window(col_off, row_off, window_width, window_height)


def run_global_region_merge_poc(config: GlobalRegionMergeConfig) -> dict[str, object]:
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    labels_path = output_dir / "global_region_merge_labels.tif"
    report_path = output_dir / "global_region_merge_report.json"
    if not config.overwrite:
        for path in (labels_path, report_path):
            if path.exists():
                raise FileExistsError(path)

    with rasterio.open(config.feature_stack_path) as feature_source:
        window = _window_from_config(
            config.window,
            feature_source.width,
            feature_source.height,
        )
        features = feature_source.read(window=window)
        profile = feature_source.profile.copy()
        profile.update(
            count=1,
            dtype="uint32",
            nodata=0,
            width=int(window.width),
            height=int(window.height),
            transform=feature_source.window_transform(window),
        )
    with rasterio.open(config.valid_mask_path) as mask_source:
        mask = mask_source.read(1, window=window) > 0

    finite = np.all(np.isfinite(features), axis=0)
    valid = mask & finite
    initial = build_initial_regions(
        features,
        valid,
        config.initial_block_size_px,
        config.max_region_rms,
    )
    merged, diagnostics = merge_regions_global_rms(
        initial,
        features,
        config.max_region_rms,
        config.max_spatial_rms_px,
    )

    with rasterio.open(labels_path, "w", **profile) as destination:
        destination.write(merged, 1)

    report: dict[str, object] = {
        "status": "global_region_merge_poc_ready",
        "method": "adjacent_greedy_merge_with_global_region_rms_limit",
        "feature_stack_path": str(config.feature_stack_path),
        "valid_mask_path": str(config.valid_mask_path),
        "labels_path": str(labels_path),
        "window": {
            "col_off": int(window.col_off),
            "row_off": int(window.row_off),
            "width": int(window.width),
            "height": int(window.height),
        },
        "initial_block_size_px": int(config.initial_block_size_px),
        "max_spatial_rms_px": float(config.max_spatial_rms_px),
        **diagnostics,
        "workflow_integrated": False,
        "step9_or_step10_modified": False,
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Global-RMS region merge proof of concept")
    parser.add_argument("--feature-stack", required=True, type=Path)
    parser.add_argument("--valid-mask", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-region-rms", required=True, type=float)
    parser.add_argument("--max-spatial-rms-px", required=True, type=float)
    parser.add_argument("--initial-block-size-px", type=int, default=2)
    parser.add_argument("--window", nargs=4, type=int, metavar=("COL", "ROW", "WIDTH", "HEIGHT"))
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    result = run_global_region_merge_poc(
        GlobalRegionMergeConfig(
            feature_stack_path=args.feature_stack,
            valid_mask_path=args.valid_mask,
            output_dir=args.output_dir,
            max_region_rms=args.max_region_rms,
            max_spatial_rms_px=args.max_spatial_rms_px,
            initial_block_size_px=args.initial_block_size_px,
            window=tuple(args.window) if args.window else None,
            overwrite=args.overwrite,
        )
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
