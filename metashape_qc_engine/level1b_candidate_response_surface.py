from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import csv
import json
import math
from pathlib import Path
import statistics
import time
from typing import Any

import numpy as np

from metashape_qc_engine.level1b_one_scale_segmentation import (
    Level1BOneScaleSegmentationConfig,
    run_one_scale_segmentation_smoke,
)
from metashape_qc_engine.level1b_perturbations import (
    Level1BPerturbationConfig,
    build_perturbation_candidates,
)


SIZE_CLASSES = ("micro", "small", "in_scale", "large", "oversize")
TAIL_CLASSES = ("lower_tail", "central", "upper_tail")
Q_HISTOGRAM_BINS = (0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, math.inf)
SUMMARY_DISTANCE_WEIGHTS = {
    "distribution": 1.0,
    "histogram": 1.0,
    "spatial": 1.0,
}
OUTPUT_FILENAMES = {
    "report": "candidate_response_surface_report.json",
    "run_population_csv": "run_population_summary.csv",
    "run_population_json": "run_population_summary.json",
    "group_csv": "candidate_group_response_summary.csv",
    "group_json": "candidate_group_response_summary.json",
    "matrix_csv": "analysis_matrix_summary.csv",
    "matrix_json": "analysis_matrix_summary.json",
    "spatial_csv": "spatial_response_stability.csv",
    "spatial_json": "spatial_response_stability.json",
    "space_csv": "candidate_space_distribution_summary.csv",
    "space_json": "candidate_space_distribution_summary.json",
    "ranked_csv": "ranked_candidate_scales.csv",
    "ranked_json": "ranked_candidate_scales.json",
    "representatives": "stable_representative_combinations.json",
    "accepted": "accepted_scale_candidates.json",
    "removed": "removed_scale_candidates.json",
    "failed": "failed_runs.json",
}

SCALE_COORDINATE_FIELDS = (
    "source_candidate_radius_m",
    "source_spatial_radius",
    "run_spatial_radius_m",
    "run_spatial_radius",
)

STEP9B_OUTPUT_FILENAMES = {
    "preflight": "step9b_interval_preflight.json",
    "local_candidates": "step9b_local_candidate_table.csv",
    "response_csv": "step9b_local_response_surface.csv",
    "response_json": "step9b_local_response_surface.json",
    "supported_alternatives_csv": "step9b_supported_scale_alternatives.csv",
    "supported_alternatives_json": "step9b_supported_scale_alternatives.json",
    "midpoint_probe_csv": "step9b_midpoint_probe_candidate.csv",
    "midpoint_probe_json": "step9b_midpoint_probe_candidate.json",
    "midpoint_perturbations_csv": "step9b_midpoint_perturbation_candidates.csv",
    "midpoint_perturbations_json": "step9b_midpoint_perturbation_candidates.json",
    "gain_share_handoff": "step9b_midpoint_gain_share_handoff.json",
}

STEP9B_GATE_METADATA_FIELDS = (
    "top_pair_scale_continuity_status",
    "top_pair_is_scale_adjacent",
    "top_pair_rank1_candidate_scale_group_id",
    "top_pair_rank2_candidate_scale_group_id",
    "top_pair_lower_scale_candidate_group_id",
    "top_pair_upper_scale_candidate_group_id",
    "top_pair_scale_coordinate_name",
    "top_pair_lower_scale_coordinate_value",
    "top_pair_upper_scale_coordinate_value",
    "top_pair_intervening_candidate_scale_group_ids",
    "top_pair_rank1_at_scale_boundary",
    "top_pair_rank1_boundary_side",
    "top_pair_rank1_upper_extrapolation_not_tested",
    "top_pair_boundary_constrained",
)


@dataclass
class Level1BCandidateResponseSurfaceConfig:
    candidate_id: str
    output_dir: Path
    perturbation_candidates_json_path: Path
    feature_space_stack_path: Path | None = None
    valid_mask_path: Path | None = None
    segmentation_stack_path: Path | None = None
    segmentation_stack_source: str | None = None
    otb_bin_dir: str | None = None
    ram_mb: int = 8192
    overwrite: bool = False
    dry_run: bool = False
    debug_command_output: bool = False
    max_candidate_scale_groups: int | None = None
    max_runs_per_group: int | None = None
    run_hoover_audit: bool = False
    hoover_audit_max_scale_groups: int = 1
    hoover_audit_max_runs_per_group: int = 1
    analysis_cell_size_mode: str = "scale_adaptive"
    analysis_cell_size_m: float | None = None
    analysis_cell_size_factor: float = 4.0
    analysis_cell_min_m: float = 5.0
    analysis_cell_max_m: float | None = None
    micro_upper_ratio: float = 0.25
    small_upper_ratio: float = 0.5
    in_scale_upper_ratio: float = 2.0
    large_upper_ratio: float = 4.0
    min_central_area_share: float | None = 0.5
    max_lower_tail_area_share: float | None = 0.35
    max_upper_tail_area_share: float | None = 0.35
    max_edge_loaded_area_share: float | None = 0.5
    max_response_spread_q: float | None = 1.5
    max_response_skewness_abs: float | None = 1.5
    max_distribution_flutter: float | None = 1.0
    max_scale_jump_distance: float | None = 1.5
    max_spatial_pattern_distance: float | None = 1.0
    min_dominant_cell_class_agreement: float | None = 0.6
    medoid_distribution_weight: float = 1.0
    medoid_histogram_weight: float = 1.0
    medoid_spatial_weight: float = 1.0


def response_surface_output_dir(output_dir: str | Path) -> Path:
    return Path(output_dir) / "level1b" / "candidate_response_surface"


def local_transition_refinement_output_dir(output_dir: str | Path) -> Path:
    return Path(output_dir) / "level1b" / "local_transition_refinement"


def resolve_segmentation_stack(cfg: Level1BCandidateResponseSurfaceConfig) -> tuple[Path, str]:
    """Resolve Step-9 input without silently treating PCA as the default."""
    if cfg.segmentation_stack_path is not None:
        path = Path(cfg.segmentation_stack_path)
        source = cfg.segmentation_stack_source or "explicit_segmentation_stack"
    elif cfg.feature_space_stack_path is not None:
        path = Path(cfg.feature_space_stack_path)
        source = cfg.segmentation_stack_source or "explicit_feature_space_stack_compat"
    else:
        path = Path(cfg.output_dir) / "level1b" / "channels" / "proxy_stack.tif"
        source = cfg.segmentation_stack_source or "proxy_stack"
    return path, source


def resolve_valid_mask_path(cfg: Level1BCandidateResponseSurfaceConfig) -> Path:
    return Path(cfg.valid_mask_path) if cfg.valid_mask_path is not None else Path(cfg.output_dir) / "level1b" / "mask" / "valid_mask.tif"


def read_step8_local_parameter_combinations(json_path: str | Path) -> list[dict[str, Any]]:
    with Path(json_path).open(encoding="utf-8") as file_obj:
        payload = json.load(file_obj)
    rows = payload if isinstance(payload, list) else payload.get("candidates")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Step-8 perturbation candidate table is empty or missing")
    return [dict(row) for row in rows]


def candidate_scale_group_key(row: dict[str, Any]) -> str:
    for key in ("candidate_scale_group_id", "source_scale_id", "scale_id", "source_candidate_id"):
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value)
    raise ValueError("row has no deterministic candidate-scale group key")


def group_rows_by_candidate_scale(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        row = dict(row)
        row.setdefault("_step8_row_index", index)
        grouped.setdefault(candidate_scale_group_key(row), []).append(row)
    groups = []
    for group_id in sorted(grouped):
        group_rows = sorted(grouped[group_id], key=lambda item: str(item.get("perturbation_id", item["_step8_row_index"])))
        groups.append({"candidate_scale_group_id": group_id, "rows": group_rows})
    return groups


def source_candidate_radius_m(row: dict[str, Any]) -> float:
    for key in ("source_candidate_radius_m", "candidate_radius_m", "radius_m", "r_candidate_source_m"):
        value = row.get(key)
        if _finite_positive(value):
            return float(value)
    if _finite_positive(row.get("area_m2")):
        return math.sqrt(float(row["area_m2"]) / math.pi)
    if _finite_positive(row.get("spatialr_m")):
        return float(row["spatialr_m"])
    if _finite_positive(row.get("spatialr_px")) and _finite_positive(row.get("pixel_size_m")):
        return float(row["spatialr_px"]) * float(row["pixel_size_m"])
    raise ValueError("row lacks source candidate radius metadata")


def run_radius_m(row: dict[str, Any], pixel_size_m: float | None = None) -> float | None:
    for key in ("run_spatial_radius_m", "spatialr_m", "spatial_radius_m"):
        value = row.get(key)
        if _finite_positive(value):
            return float(value)
    if _finite_positive(row.get("spatialr_px")) and _finite_positive(pixel_size_m):
        return float(row["spatialr_px"]) * float(pixel_size_m)
    return None


def count_segment_sizes(labels: np.ndarray, pixel_size_m: float) -> dict[str, Any]:
    values, counts = np.unique(labels, return_counts=True)
    keep = values != 0
    return _counts_report_from_values(values[keep], counts[keep], pixel_size_m, "sparse_unique")


def count_segment_sizes_from_raster(labels_path: str | Path, valid_mask_path: str | Path, pixel_size_m: float) -> dict[str, Any]:
    label_counts: dict[int, int] = {}
    window_count = 0
    for labels in _iter_masked_label_blocks(labels_path, valid_mask_path):
        window_count += 1
        labelled = labels[labels != 0]
        if labelled.size == 0:
            continue
        values, counts = np.unique(labelled, return_counts=True)
        for label, count in zip(values, counts):
            label_int = int(label)
            label_counts[label_int] = label_counts.get(label_int, 0) + int(count)
    if label_counts:
        values = np.fromiter(sorted(label_counts), dtype=np.int64)
        counts = np.asarray([label_counts[int(label)] for label in values], dtype=np.int64)
    else:
        values = np.asarray([], dtype=np.int64)
        counts = np.asarray([], dtype=np.int64)
    report = _counts_report_from_values(values, counts, pixel_size_m, "windowed_sparse_unique")
    report["memory_strategy"] = dict(
        report["memory_strategy"],
        strategy="windowed_sparse_unique",
        raster_array_loaded_whole=False,
        raster_window_count=window_count,
    )
    return report


def _counts_report_from_values(values: np.ndarray, counts: np.ndarray, pixel_size_m: float, strategy: str) -> dict[str, Any]:
    values = np.asarray(values, dtype=np.int64)
    counts = np.asarray(counts, dtype=np.int64)
    max_label = int(values.max()) if values.size else 0
    dense_memory_bytes = (max_label + 1) * np.dtype(np.int64).itemsize if max_label >= 0 else 0
    area_px = counts.astype(np.int64)
    area_m2 = area_px.astype(float) * float(pixel_size_m) ** 2
    return {
        "labels": values.astype(np.int64),
        "area_px": area_px,
        "area_m2": area_m2,
        "max_label": max_label,
        "unique_label_count": int(values.size),
        "label_count_strategy": strategy,
        "memory_strategy": {
            "strategy": strategy,
            "dense_count_bytes_if_used": int(dense_memory_bytes),
        },
    }


def equivalent_radii(area_m2: np.ndarray) -> np.ndarray:
    return np.sqrt(np.asarray(area_m2, dtype=float) / math.pi)


def assign_scale_relative_size_classes(q_values: np.ndarray, cfg: Level1BCandidateResponseSurfaceConfig) -> np.ndarray:
    q = np.asarray(q_values, dtype=float)
    classes = np.full(q.shape, "oversize", dtype=object)
    classes[q < cfg.micro_upper_ratio] = "micro"
    classes[(q >= cfg.micro_upper_ratio) & (q < cfg.small_upper_ratio)] = "small"
    classes[(q >= cfg.small_upper_ratio) & (q <= cfg.in_scale_upper_ratio)] = "in_scale"
    classes[(q > cfg.in_scale_upper_ratio) & (q <= cfg.large_upper_ratio)] = "large"
    return classes


def compute_class_summaries(classes: np.ndarray, area_m2: np.ndarray, radii_m: np.ndarray) -> dict[str, Any]:
    total_area = float(np.sum(area_m2))
    summary: dict[str, Any] = {}
    for cls in SIZE_CLASSES:
        mask = classes == cls
        cls_area = float(np.sum(area_m2[mask]))
        cls_radii = radii_m[mask]
        summary[cls] = {
            "segment_count": int(np.sum(mask)),
            "area_sum_m2": cls_area,
            "area_share": cls_area / total_area if total_area else 0.0,
            "median_radius_m": _quantile(cls_radii, 0.5),
            "q90_radius_m": _quantile(cls_radii, 0.9),
        }
    lower = summary["micro"]["area_share"] + summary["small"]["area_share"]
    central = summary["in_scale"]["area_share"]
    upper = summary["large"]["area_share"] + summary["oversize"]["area_share"]
    summary["lower_tail_area_share"] = lower
    summary["central_area_share"] = central
    summary["upper_tail_area_share"] = upper
    summary["edge_loaded_area_share"] = lower + upper
    return summary


def compute_run_population_summary(
    run_id: str,
    group_id: str,
    row: dict[str, Any],
    labels: np.ndarray,
    pixel_size_m: float,
    cfg: Level1BCandidateResponseSurfaceConfig,
) -> dict[str, Any]:
    counts = count_segment_sizes(labels, pixel_size_m)
    return compute_run_population_summary_from_counts(run_id, group_id, row, counts, pixel_size_m, cfg)


def compute_run_population_summary_from_counts(
    run_id: str,
    group_id: str,
    row: dict[str, Any],
    counts: dict[str, Any],
    pixel_size_m: float,
    cfg: Level1BCandidateResponseSurfaceConfig,
) -> dict[str, Any]:
    area_m2 = counts["area_m2"]
    radii_m = equivalent_radii(area_m2)
    r_source = source_candidate_radius_m(row)
    q = radii_m / r_source
    q_run = None
    r_run = run_radius_m(row, pixel_size_m)
    if r_run:
        q_run = radii_m / r_run
    classes = assign_scale_relative_size_classes(q, cfg)
    class_summary = compute_class_summaries(classes, area_m2, radii_m)
    total_area = float(np.sum(area_m2))
    weighted_q = _weighted_quantiles(q, area_m2, (0.1, 0.25, 0.5, 0.75, 0.9, 0.95))
    hist = area_weighted_q_histogram(q, area_m2, Q_HISTOGRAM_BINS)
    size_distribution = [class_summary[cls]["area_share"] for cls in SIZE_CLASSES]
    summary = {
        "run_id": run_id,
        "candidate_scale_group_id": group_id,
        "source_candidate_id": str(row.get("source_candidate_id", "")),
        "source_scale_id": str(row.get("source_scale_id", row.get("scale_id", ""))),
        "source_candidate_radius_m": r_source,
        "source_spatial_radius": row.get("source_spatial_radius_m", row.get("spatialr_m", row.get("spatialr_px"))),
        "source_minsize": row.get("source_minsize_px", row.get("minsize_px")),
        "source_ranger": row.get("source_ranger", row.get("ranger")),
        "run_spatial_radius_m": r_run,
        "run_minsize": row.get("minsize_px"),
        "run_ranger": row.get("ranger"),
        "parameter_offsets": row.get("deltas", row.get("offsets", {})),
        "original_row_metadata": row,
        "segment_count": int(counts["unique_label_count"]),
        "segment_density_per_ha": int(counts["unique_label_count"]) / (total_area / 10000.0) if total_area else 0.0,
        "total_labelled_area_m2": total_area,
        "mean_area_m2": _mean(area_m2),
        "median_area_m2": _quantile(area_m2, 0.5),
        "q10_area_m2": _quantile(area_m2, 0.1),
        "q25_area_m2": _quantile(area_m2, 0.25),
        "q50_area_m2": _quantile(area_m2, 0.5),
        "q75_area_m2": _quantile(area_m2, 0.75),
        "q90_area_m2": _quantile(area_m2, 0.9),
        "q95_area_m2": _quantile(area_m2, 0.95),
        "mean_equivalent_radius_m": _mean(radii_m),
        "median_equivalent_radius_m": _quantile(radii_m, 0.5),
        "q10_equivalent_radius_m": _quantile(radii_m, 0.1),
        "q25_equivalent_radius_m": _quantile(radii_m, 0.25),
        "q50_equivalent_radius_m": _quantile(radii_m, 0.5),
        "q75_equivalent_radius_m": _quantile(radii_m, 0.75),
        "q90_equivalent_radius_m": _quantile(radii_m, 0.9),
        "q95_equivalent_radius_m": _quantile(radii_m, 0.95),
        "area_weighted_q_mean": float(np.average(q, weights=area_m2)) if total_area else 0.0,
        "area_weighted_q_median": weighted_q[0.5],
        "area_weighted_q_q10": weighted_q[0.1],
        "area_weighted_q_q25": weighted_q[0.25],
        "area_weighted_q_q50": weighted_q[0.5],
        "area_weighted_q_q75": weighted_q[0.75],
        "area_weighted_q_q90": weighted_q[0.9],
        "area_weighted_q_q95": weighted_q[0.95],
        "q_run_area_weighted_median": _weighted_quantiles(q_run, area_m2, (0.5,))[0.5] if q_run is not None else None,
        "diagnostic_size_classes": class_summary,
        "size_class_area_distribution": size_distribution,
        "q_histogram_bins": _json_bins(Q_HISTOGRAM_BINS),
        "q_histogram_area_distribution": hist,
        "max_label": counts["max_label"],
        "unique_label_count": counts["unique_label_count"],
        "label_count_strategy": counts["label_count_strategy"],
        "memory_strategy": counts["memory_strategy"],
    }
    for cls in SIZE_CLASSES:
        summary[f"{cls}_area_share"] = class_summary[cls]["area_share"]
        summary[f"{cls}_segment_count"] = class_summary[cls]["segment_count"]
    for key in ("lower_tail_area_share", "central_area_share", "upper_tail_area_share", "edge_loaded_area_share"):
        summary[key] = class_summary[key]
    return summary


def area_weighted_q_histogram(q_values: np.ndarray, area_m2: np.ndarray, bins: tuple[float, ...]) -> list[float]:
    q = np.asarray(q_values, dtype=float)
    weights = np.asarray(area_m2, dtype=float)
    total = float(np.sum(weights))
    if total <= 0:
        return [0.0 for _ in range(len(bins) - 1)]
    shares = []
    for low, high in zip(bins[:-1], bins[1:]):
        if math.isinf(high):
            mask = q >= low
        else:
            mask = (q >= low) & (q < high)
        shares.append(float(np.sum(weights[mask]) / total))
    return shares


def ordinal_cumulative_distribution_distance(p: list[float], q: list[float]) -> float:
    p_cdf = np.cumsum(np.asarray(p, dtype=float))
    q_cdf = np.cumsum(np.asarray(q, dtype=float))
    return float(np.sum(np.abs(p_cdf - q_cdf)))


def vector_l1_distance(p: list[float], q: list[float]) -> float:
    return float(np.sum(np.abs(np.asarray(p, dtype=float) - np.asarray(q, dtype=float))))


def radius_quantile_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    keys = ("area_weighted_q_q50", "area_weighted_q_q75", "area_weighted_q_q90", "area_weighted_q_q95")
    return float(sum(abs(float(a.get(key, 0.0)) - float(b.get(key, 0.0))) for key in keys))


def tail_share_distance(a: dict[str, Any], b: dict[str, Any]) -> float:
    keys = ("lower_tail_area_share", "central_area_share", "upper_tail_area_share")
    return float(sum(abs(float(a.get(key, 0.0)) - float(b.get(key, 0.0))) for key in keys))


def compute_normal_response_diagnostics(run_summaries: list[dict[str, Any]], cfg: Level1BCandidateResponseSurfaceConfig) -> dict[str, Any]:
    centers = [float(item.get("area_weighted_q_median", 0.0)) for item in run_summaries]
    spreads = [float(item.get("area_weighted_q_q90", 0.0)) - float(item.get("area_weighted_q_q10", 0.0)) for item in run_summaries]
    lower = [float(item.get("lower_tail_area_share", 0.0)) for item in run_summaries]
    central = [float(item.get("central_area_share", 0.0)) for item in run_summaries]
    upper = [float(item.get("upper_tail_area_share", 0.0)) for item in run_summaries]
    response_center = statistics.median(centers) if centers else 0.0
    response_spread = statistics.median(spreads) if spreads else 0.0
    skewness = _robust_skew(run_summaries)
    central_mean = _mean(central)
    lower_mean = _mean(lower)
    upper_mean = _mean(upper)
    edge_mean = lower_mean + upper_mean
    dominant_classes = [dominant_size_class(item) for item in run_summaries]
    multimodal = len(set(dominant_classes)) >= 3 or ("small" in dominant_classes and "large" in dominant_classes)
    return {
        "response_center_q": response_center,
        "response_spread_q": response_spread,
        "response_skewness_q": skewness,
        "lower_tail_area_share_mean": lower_mean,
        "lower_tail_area_share_sd": _sd(lower),
        "central_area_share_mean": central_mean,
        "central_area_share_sd": _sd(central),
        "upper_tail_area_share_mean": upper_mean,
        "upper_tail_area_share_sd": _sd(upper),
        "centered": 0.5 <= response_center <= 2.0 and central_mean >= (cfg.min_central_area_share or 0.0),
        "lower_tail_dominated": lower_mean > central_mean and lower_mean > upper_mean,
        "upper_tail_dominated": upper_mean > central_mean and upper_mean > lower_mean,
        "edge_loaded_flag": cfg.max_edge_loaded_area_share is not None and edge_mean > cfg.max_edge_loaded_area_share,
        "one_sided_lower_tail_flag": cfg.max_lower_tail_area_share is not None and lower_mean > cfg.max_lower_tail_area_share and lower_mean > upper_mean * 1.5,
        "one_sided_upper_tail_flag": cfg.max_upper_tail_area_share is not None and upper_mean > cfg.max_upper_tail_area_share and upper_mean > lower_mean * 1.5,
        "missing_central_mass_flag": cfg.min_central_area_share is not None and central_mean < cfg.min_central_area_share,
        "strongly_skewed": cfg.max_response_skewness_abs is not None and abs(skewness) > cfg.max_response_skewness_abs,
        "multimodal_response_flag": multimodal,
        "unstably_spread": cfg.max_response_spread_q is not None and response_spread > cfg.max_response_spread_q,
    }


def compute_distributional_distances(run_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    pairs = []
    for i, left in enumerate(run_summaries):
        for j in range(i + 1, len(run_summaries)):
            right = run_summaries[j]
            pairs.append(
                {
                    "left_run_id": left["run_id"],
                    "right_run_id": right["run_id"],
                    "ordinal_distribution_distance": ordinal_cumulative_distribution_distance(
                        left["size_class_area_distribution"], right["size_class_area_distribution"]
                    ),
                    "q_histogram_distance": vector_l1_distance(
                        left["q_histogram_area_distribution"], right["q_histogram_area_distribution"]
                    ),
                    "radius_quantile_distance": radius_quantile_distance(left, right),
                    "tail_share_distance": tail_share_distance(left, right),
                }
            )
    combined = [
        item["ordinal_distribution_distance"] + item["q_histogram_distance"] + item["tail_share_distance"]
        for item in pairs
    ]
    return {
        "pairwise_distances": pairs,
        "pairwise_distribution_distance_mean": _mean(combined),
        "pairwise_distribution_distance_max": max(combined) if combined else 0.0,
    }


def select_medoid_run(
    run_summaries: list[dict[str, Any]],
    matrix_summaries: list[dict[str, Any]] | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    weights = weights or SUMMARY_DISTANCE_WEIGHTS
    matrix_by_run = {item["run_id"]: item for item in matrix_summaries or []}
    best: dict[str, Any] | None = None
    for candidate in run_summaries:
        distances = []
        for other in run_summaries:
            if other["run_id"] == candidate["run_id"]:
                continue
            spatial = matrix_distribution_distance(matrix_by_run.get(candidate["run_id"]), matrix_by_run.get(other["run_id"]))
            distance = (
                weights["distribution"]
                * ordinal_cumulative_distribution_distance(
                    candidate["size_class_area_distribution"], other["size_class_area_distribution"]
                )
                + weights["histogram"]
                * vector_l1_distance(candidate["q_histogram_area_distribution"], other["q_histogram_area_distribution"])
                + weights["spatial"] * spatial
            )
            distances.append(distance)
        mean_distance = _mean(distances)
        item = {
            "medoid_run_id": candidate["run_id"],
            "medoid_parameters": {
                "spatial_radius_m": candidate.get("run_spatial_radius_m"),
                "minsize": candidate.get("run_minsize"),
                "ranger": candidate.get("run_ranger"),
                "parameter_offsets": candidate.get("parameter_offsets"),
            },
            "mean_distance_to_medoid": mean_distance,
            "max_distance_to_medoid": max(distances) if distances else 0.0,
        }
        if best is None or item["mean_distance_to_medoid"] < best["mean_distance_to_medoid"]:
            best = item
    return best or {
        "medoid_run_id": "",
        "medoid_parameters": {},
        "mean_distance_to_medoid": 0.0,
        "max_distance_to_medoid": 0.0,
    }


def compute_analysis_cell_size_m(row: dict[str, Any], cfg: Level1BCandidateResponseSurfaceConfig) -> float:
    if cfg.analysis_cell_size_m is not None:
        cell = float(cfg.analysis_cell_size_m)
    else:
        support = row.get("effective_structure_support_max_m")
        candidates = [cfg.analysis_cell_min_m, cfg.analysis_cell_size_factor * source_candidate_radius_m(row)]
        if _finite_positive(support):
            candidates.append(float(support))
        cell = max(candidates)
    if cfg.analysis_cell_max_m is not None:
        cell = min(cell, float(cfg.analysis_cell_max_m))
    return cell


def aggregate_analysis_matrix(
    labels: np.ndarray,
    label_classes: dict[int, str],
    pixel_size_m: float,
    cell_size_m: float,
    run_id: str = "",
    group_id: str = "",
) -> dict[str, Any]:
    cell_px = max(1, int(math.ceil(cell_size_m / pixel_size_m)))
    rows, cols = labels.shape
    cell_records = []
    for r0 in range(0, rows, cell_px):
        for c0 in range(0, cols, cell_px):
            block = labels[r0 : r0 + cell_px, c0 : c0 + cell_px]
            labelled = block[block != 0]
            if labelled.size == 0:
                continue
            class_area = {cls: 0.0 for cls in SIZE_CLASSES}
            values, counts = np.unique(labelled, return_counts=True)
            for label, count in zip(values, counts):
                cls = label_classes.get(int(label))
                if cls:
                    class_area[cls] += float(count) * pixel_size_m**2
            labelled_area = sum(class_area.values())
            shares = {cls: class_area[cls] / labelled_area if labelled_area else 0.0 for cls in SIZE_CLASSES}
            dominant = max(SIZE_CLASSES, key=lambda cls: shares[cls])
            lower = shares["micro"] + shares["small"]
            central = shares["in_scale"]
            upper = shares["large"] + shares["oversize"]
            if central >= lower and central >= upper:
                tail = "central"
            elif lower >= upper:
                tail = "lower_tail"
            else:
                tail = "upper_tail"
            cell_records.append(
                {
                    "run_id": run_id,
                    "candidate_scale_group_id": group_id,
                    "cell_row": r0 // cell_px,
                    "cell_col": c0 // cell_px,
                    "labelled_area_m2": labelled_area,
                    "micro_area_share": shares["micro"],
                    "small_area_share": shares["small"],
                    "in_scale_area_share": shares["in_scale"],
                    "large_area_share": shares["large"],
                    "oversize_area_share": shares["oversize"],
                    "lower_tail_area_share": lower,
                    "central_area_share": central,
                    "upper_tail_area_share": upper,
                    "dominant_size_class": dominant,
                    "dominant_tail_class": tail,
                    "problem_class_dominance": tail != "central",
                }
            )
    summary = spatial_dominance_summary(cell_records, run_id, group_id)
    return {"cell_records": cell_records, "summary": summary, "cell_size_m": cell_size_m, "cell_size_px": cell_px}


def aggregate_analysis_matrix_from_raster(
    labels_path: str | Path,
    valid_mask_path: str | Path,
    label_classes: dict[int, str],
    pixel_size_m: float,
    cell_size_m: float,
    run_id: str = "",
    group_id: str = "",
) -> dict[str, Any]:
    import rasterio
    from rasterio.windows import Window

    cell_px = max(1, int(math.ceil(cell_size_m / pixel_size_m)))
    cell_records = []
    with rasterio.open(labels_path) as label_dataset, rasterio.open(valid_mask_path) as mask_dataset:
        _validate_raster_pair(label_dataset, mask_dataset, "valid mask and label raster dimensions are incompatible")
        rows, cols = label_dataset.height, label_dataset.width
        for r0 in range(0, rows, cell_px):
            height = min(cell_px, rows - r0)
            for c0 in range(0, cols, cell_px):
                width = min(cell_px, cols - c0)
                window = Window(c0, r0, width, height)
                block = label_dataset.read(1, window=window)
                mask = mask_dataset.read(1, window=window)
                block = np.asarray(block).copy()
                block[mask <= 0] = 0
                labelled = block[block != 0]
                if labelled.size == 0:
                    continue
                class_area = {cls: 0.0 for cls in SIZE_CLASSES}
                values, counts = np.unique(labelled, return_counts=True)
                for label, count in zip(values, counts):
                    cls = label_classes.get(int(label))
                    if cls:
                        class_area[cls] += float(count) * pixel_size_m**2
                labelled_area = sum(class_area.values())
                shares = {cls: class_area[cls] / labelled_area if labelled_area else 0.0 for cls in SIZE_CLASSES}
                dominant = max(SIZE_CLASSES, key=lambda cls: shares[cls])
                lower = shares["micro"] + shares["small"]
                central = shares["in_scale"]
                upper = shares["large"] + shares["oversize"]
                if central >= lower and central >= upper:
                    tail = "central"
                elif lower >= upper:
                    tail = "lower_tail"
                else:
                    tail = "upper_tail"
                cell_records.append(
                    {
                        "run_id": run_id,
                        "candidate_scale_group_id": group_id,
                        "cell_row": r0 // cell_px,
                        "cell_col": c0 // cell_px,
                        "labelled_area_m2": labelled_area,
                        "micro_area_share": shares["micro"],
                        "small_area_share": shares["small"],
                        "in_scale_area_share": shares["in_scale"],
                        "large_area_share": shares["large"],
                        "oversize_area_share": shares["oversize"],
                        "lower_tail_area_share": lower,
                        "central_area_share": central,
                        "upper_tail_area_share": upper,
                        "dominant_size_class": dominant,
                        "dominant_tail_class": tail,
                        "problem_class_dominance": tail != "central",
                    }
                )
    summary = spatial_dominance_summary(cell_records, run_id, group_id)
    return {"cell_records": cell_records, "summary": summary, "cell_size_m": cell_size_m, "cell_size_px": cell_px}


def spatial_dominance_summary(cell_records: list[dict[str, Any]], run_id: str = "", group_id: str = "") -> dict[str, Any]:
    count = len(cell_records)
    if count == 0:
        return {
            "run_id": run_id,
            "candidate_scale_group_id": group_id,
            "analysis_cell_count": 0,
            "dominant_central_cell_share": 0.0,
            "dominant_lower_tail_cell_share": 0.0,
            "dominant_upper_tail_cell_share": 0.0,
            "problem_cell_area_share": 0.0,
            "micro_dominated_cell_share": 0.0,
            "small_dominated_cell_share": 0.0,
            "large_dominated_cell_share": 0.0,
            "oversize_dominated_cell_share": 0.0,
            "dominant_size_distribution": [0.0] * len(SIZE_CLASSES),
            "dominant_tail_distribution": [0.0] * len(TAIL_CLASSES),
        }
    tail_counts = {tail: sum(1 for cell in cell_records if cell["dominant_tail_class"] == tail) for tail in TAIL_CLASSES}
    size_counts = {cls: sum(1 for cell in cell_records if cell["dominant_size_class"] == cls) for cls in SIZE_CLASSES}
    total_area = sum(float(cell["labelled_area_m2"]) for cell in cell_records)
    problem_area = sum(float(cell["labelled_area_m2"]) for cell in cell_records if cell["problem_class_dominance"])
    return {
        "run_id": run_id,
        "candidate_scale_group_id": group_id,
        "analysis_cell_count": count,
        "dominant_central_cell_share": tail_counts["central"] / count,
        "dominant_lower_tail_cell_share": tail_counts["lower_tail"] / count,
        "dominant_upper_tail_cell_share": tail_counts["upper_tail"] / count,
        "problem_cell_area_share": problem_area / total_area if total_area else 0.0,
        "micro_dominated_cell_share": size_counts["micro"] / count,
        "small_dominated_cell_share": size_counts["small"] / count,
        "large_dominated_cell_share": size_counts["large"] / count,
        "oversize_dominated_cell_share": size_counts["oversize"] / count,
        "dominant_size_distribution": [size_counts[cls] / count for cls in SIZE_CLASSES],
        "dominant_tail_distribution": [tail_counts[tail] / count for tail in TAIL_CLASSES],
    }


def matrix_distribution_distance(left: dict[str, Any] | None, right: dict[str, Any] | None) -> float:
    if not left or not right:
        return 0.0
    return vector_l1_distance(left.get("dominant_size_distribution", [0.0] * 5), right.get("dominant_size_distribution", [0.0] * 5)) + vector_l1_distance(
        left.get("dominant_tail_distribution", [0.0] * 3), right.get("dominant_tail_distribution", [0.0] * 3)
    )


def compute_spatial_response_stability(matrix_summaries: list[dict[str, Any]], cfg: Level1BCandidateResponseSurfaceConfig) -> dict[str, Any]:
    if not matrix_summaries:
        return {"matrix_distribution_distance": 0.0, "spatial_scale_jump_flag": False}
    distances = []
    for i, left in enumerate(matrix_summaries):
        for j in range(i + 1, len(matrix_summaries)):
            distances.append(matrix_distribution_distance(left, matrix_summaries[j]))
    central = [float(item.get("dominant_central_cell_share", 0.0)) for item in matrix_summaries]
    lower = [float(item.get("dominant_lower_tail_cell_share", 0.0)) for item in matrix_summaries]
    upper = [float(item.get("dominant_upper_tail_cell_share", 0.0)) for item in matrix_summaries]
    problem = [float(item.get("problem_cell_area_share", 0.0)) for item in matrix_summaries]
    size_distributions = np.asarray([item.get("dominant_size_distribution", [0.0] * 5) for item in matrix_summaries], dtype=float)
    agreement = float(np.max(np.mean(size_distributions, axis=0))) if len(size_distributions) else 0.0
    max_distance = max(distances) if distances else 0.0
    return {
        "dominant_size_class_agreement": agreement,
        "dominant_tail_class_agreement": _dominant_tail_agreement(matrix_summaries),
        "central_area_dominance_change": _range(central),
        "lower_tail_dominance_change": _range(lower),
        "upper_tail_dominance_change": _range(upper),
        "problem_cell_area_share_change": _range(problem),
        "lower_tail_cell_persistence": _mean(lower),
        "upper_tail_cell_persistence": _mean(upper),
        "matrix_distribution_distance": _mean(distances),
        "matrix_distribution_distance_max": max_distance,
        "spatial_scale_jump_flag": (
            (cfg.max_spatial_pattern_distance is not None and max_distance > cfg.max_spatial_pattern_distance)
            or (cfg.min_dominant_cell_class_agreement is not None and agreement < cfg.min_dominant_cell_class_agreement)
        ),
    }


def compute_candidate_group_response_summary(
    group_id: str,
    run_summaries: list[dict[str, Any]],
    matrix_summaries: list[dict[str, Any]],
    cfg: Level1BCandidateResponseSurfaceConfig,
) -> dict[str, Any]:
    diagnostics = compute_normal_response_diagnostics(run_summaries, cfg)
    distances = compute_distributional_distances(run_summaries)
    spatial = compute_spatial_response_stability(matrix_summaries, cfg)
    medoid = select_medoid_run(
        run_summaries,
        matrix_summaries,
        {
            "distribution": cfg.medoid_distribution_weight,
            "histogram": cfg.medoid_histogram_weight,
            "spatial": cfg.medoid_spatial_weight,
        },
    )
    dominant_switches = max(0, len(set(dominant_size_class(item) for item in run_summaries)) - 1)
    regime_switches = max(0, len(set(dominant_tail_regime(item) for item in run_summaries)) - 1)
    flutter = distances["pairwise_distribution_distance_mean"] + 0.5 * dominant_switches + 0.5 * regime_switches
    scale_jump = (
        diagnostics["missing_central_mass_flag"]
        or diagnostics["multimodal_response_flag"]
        or (cfg.max_scale_jump_distance is not None and distances["pairwise_distribution_distance_max"] > cfg.max_scale_jump_distance)
        or spatial["spatial_scale_jump_flag"]
    )
    compatible = [
        item
        for item in run_summaries
        if ordinal_cumulative_distribution_distance(
            item["size_class_area_distribution"],
            next((run["size_class_area_distribution"] for run in run_summaries if run["run_id"] == medoid["medoid_run_id"]), item["size_class_area_distribution"]),
        )
        <= (cfg.max_distribution_flutter or math.inf)
    ]
    summary = {
        "candidate_scale_group_id": group_id,
        "run_count": len(run_summaries),
        **diagnostics,
        **{key: value for key, value in distances.items() if key != "pairwise_distances"},
        "regime_switch_count": regime_switches,
        "dominant_class_switch_count": dominant_switches,
        "distribution_flutter_score": flutter,
        "distribution_flutter_flag": cfg.max_distribution_flutter is not None and flutter > cfg.max_distribution_flutter,
        "scale_jump_flag": scale_jump,
        "flurry_like": cfg.max_distribution_flutter is not None and flutter > cfg.max_distribution_flutter and dominant_switches > 0,
        **spatial,
        **medoid,
        "distributional_spread_around_medoid": medoid["mean_distance_to_medoid"],
        "spatial_pattern_spread_around_medoid": spatial.get("matrix_distribution_distance", 0.0),
        "compatible_combination_count": len(compatible),
        "incompatible_combination_count": max(0, len(run_summaries) - len(compatible)),
    }
    summary["stability_score_raw"] = stability_score_raw(summary)
    summary["stability_score"] = stability_score(summary)
    summary["candidate_outcome"] = classify_candidate_outcome(summary)
    summary["decision_reasons"] = decision_reasons(summary)
    return summary


def analyze_full_candidate_space(group_summaries: list[dict[str, Any]], run_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    stable = [g for g in group_summaries if g.get("candidate_outcome") in ("stable_representative_candidate", "stable_candidate_mode", "stable_with_warnings")]
    radii = [float(r["source_candidate_radius_m"]) for r in run_summaries if _finite_positive(r.get("source_candidate_radius_m"))]
    scores = [float(g.get("stability_score", 0.0)) for g in group_summaries]
    centers = [float(g.get("response_center_q", 0.0)) for g in group_summaries]
    spreads = [float(g.get("response_spread_q", 0.0)) for g in group_summaries]
    central = [float(g.get("central_area_share_mean", 0.0)) for g in group_summaries]
    tail = [float(g.get("lower_tail_area_share_mean", 0.0)) + float(g.get("upper_tail_area_share_mean", 0.0)) for g in group_summaries]
    modes = stable_candidate_modes(stable)
    outliers = isolated_outlier_candidates(group_summaries, radii)
    unstable_ranges = unstable_candidate_ranges(group_summaries)
    return {
        "all_run_count": len(run_summaries),
        "all_candidate_group_count": len(group_summaries),
        "candidate_radius_distribution": _distribution_summary(radii),
        "stability_score_distribution": _distribution_summary(scores),
        "response_center_distribution": _distribution_summary(centers),
        "response_spread_distribution": _distribution_summary(spreads),
        "central_mass_distribution": _distribution_summary(central),
        "tail_dominance_distribution": _distribution_summary(tail),
        "scale_jump_count": sum(1 for g in group_summaries if g.get("scale_jump_flag")),
        "flurry_count": sum(1 for g in group_summaries if g.get("flurry_like")),
        "stable_mode_count": len(modes),
        "stable_candidate_modes": modes,
        "isolated_outlier_candidates": outliers,
        "unstable_candidate_ranges": unstable_ranges,
    }


def compute_top_pair_scale_continuity_and_boundary_gate(
    run_summaries: list[dict[str, Any]],
    ranked_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    group_ids = [str(item.get("candidate_scale_group_id", "")) for item in ranked_summaries if str(item.get("candidate_scale_group_id", ""))]
    if len(group_ids) < 2:
        return {
            "selected_scale_coordinate_name": None,
            "usable_scale_coordinate_fields": [],
            "scale_coordinate_order_agreement": None,
            "scale_coordinate_value_by_group": {},
            "scale_ladder_rank_by_group": {},
            "scale_ladder": [],
            "top_pair_scale_continuity_status": "cannot_determine_missing_top_pair",
            "top_pair_is_scale_adjacent": False,
            "top_pair_rank1_candidate_scale_group_id": group_ids[0] if group_ids else None,
            "top_pair_rank2_candidate_scale_group_id": group_ids[1] if len(group_ids) > 1 else None,
            "top_pair_lower_scale_candidate_group_id": None,
            "top_pair_upper_scale_candidate_group_id": None,
            "top_pair_scale_coordinate_name": None,
            "top_pair_lower_scale_coordinate_value": None,
            "top_pair_upper_scale_coordinate_value": None,
            "top_pair_intervening_candidate_scale_group_ids": [],
            "top_pair_rank1_at_scale_boundary": False,
            "top_pair_rank1_boundary_side": "cannot_determine",
            "top_pair_rank1_upper_extrapolation_not_tested": False,
            "top_pair_boundary_constrained": False,
        }

    group_order = []
    seen_groups = set()
    for item in ranked_summaries:
        group_id = str(item.get("candidate_scale_group_id", ""))
        if group_id and group_id not in seen_groups:
            group_order.append(group_id)
            seen_groups.add(group_id)

    def scale_coordinate_values(field_name: str) -> dict[str, float] | None:
        values_by_group: dict[str, float] = {}
        for row in run_summaries:
            group_id = str(row.get("candidate_scale_group_id", ""))
            if not group_id:
                return None
            try:
                value = float(row.get(field_name))
            except (TypeError, ValueError):
                return None
            if not math.isfinite(value):
                return None
            existing = values_by_group.get(group_id)
            if existing is None:
                values_by_group[group_id] = value
            elif not math.isclose(existing, value, rel_tol=0.0, abs_tol=1e-12):
                return None
        if set(values_by_group) != set(group_order):
            return None
        if len(set(values_by_group.values())) != len(values_by_group):
            return None
        return values_by_group

    usable_fields: list[dict[str, Any]] = []
    for field_name in SCALE_COORDINATE_FIELDS:
        values_by_group = scale_coordinate_values(field_name)
        if values_by_group is None:
            continue
        ordered_groups = [group_id for group_id, _ in sorted(values_by_group.items(), key=lambda item: item[1])]
        usable_fields.append(
            {
                "name": field_name,
                "value_by_group": values_by_group,
                "ordered_groups": ordered_groups,
            }
        )

    if not usable_fields:
        return {
            "selected_scale_coordinate_name": None,
            "usable_scale_coordinate_fields": [],
            "scale_coordinate_order_agreement": None,
            "scale_coordinate_value_by_group": {},
            "scale_ladder_rank_by_group": {},
            "scale_ladder": [],
            "top_pair_scale_continuity_status": "cannot_determine_no_explicit_scale_coordinate",
            "top_pair_is_scale_adjacent": False,
            "top_pair_rank1_candidate_scale_group_id": group_order[0],
            "top_pair_rank2_candidate_scale_group_id": group_order[1],
            "top_pair_lower_scale_candidate_group_id": None,
            "top_pair_upper_scale_candidate_group_id": None,
            "top_pair_scale_coordinate_name": None,
            "top_pair_lower_scale_coordinate_value": None,
            "top_pair_upper_scale_coordinate_value": None,
            "top_pair_intervening_candidate_scale_group_ids": [],
            "top_pair_rank1_at_scale_boundary": False,
            "top_pair_rank1_boundary_side": "cannot_determine",
            "top_pair_rank1_upper_extrapolation_not_tested": False,
            "top_pair_boundary_constrained": False,
        }

    selected_field = usable_fields[0]
    order_agreement = all(item["ordered_groups"] == selected_field["ordered_groups"] for item in usable_fields[1:])
    if not order_agreement:
        return {
            "selected_scale_coordinate_name": None,
            "usable_scale_coordinate_fields": [item["name"] for item in usable_fields],
            "scale_coordinate_order_agreement": False,
            "scale_coordinate_value_by_group": {},
            "scale_ladder_rank_by_group": {},
            "scale_ladder": [],
            "top_pair_scale_continuity_status": "cannot_determine_scale_order_disagreement",
            "top_pair_is_scale_adjacent": False,
            "top_pair_rank1_candidate_scale_group_id": group_order[0],
            "top_pair_rank2_candidate_scale_group_id": group_order[1],
            "top_pair_lower_scale_candidate_group_id": None,
            "top_pair_upper_scale_candidate_group_id": None,
            "top_pair_scale_coordinate_name": None,
            "top_pair_lower_scale_coordinate_value": None,
            "top_pair_upper_scale_coordinate_value": None,
            "top_pair_intervening_candidate_scale_group_ids": [],
            "top_pair_rank1_at_scale_boundary": False,
            "top_pair_rank1_boundary_side": "cannot_determine",
            "top_pair_rank1_upper_extrapolation_not_tested": False,
            "top_pair_boundary_constrained": False,
        }

    scale_ladder = [
        {
            "scale_ladder_rank": index + 1,
            "candidate_scale_group_id": group_id,
            "scale_coordinate_name": selected_field["name"],
            "scale_coordinate_value": selected_field["value_by_group"][group_id],
        }
        for index, group_id in enumerate(selected_field["ordered_groups"])
    ]
    ladder_rank_by_group = {item["candidate_scale_group_id"]: item["scale_ladder_rank"] for item in scale_ladder}
    value_by_group = {item["candidate_scale_group_id"]: item["scale_coordinate_value"] for item in scale_ladder}

    rank1_group = group_order[0]
    rank2_group = group_order[1]
    rank1_pos = ladder_rank_by_group.get(rank1_group)
    rank2_pos = ladder_rank_by_group.get(rank2_group)
    if rank1_pos is None or rank2_pos is None:
        return {
            "selected_scale_coordinate_name": selected_field["name"],
            "usable_scale_coordinate_fields": [item["name"] for item in usable_fields],
            "scale_coordinate_order_agreement": True,
            "scale_coordinate_value_by_group": value_by_group,
            "scale_ladder_rank_by_group": ladder_rank_by_group,
            "scale_ladder": scale_ladder,
            "top_pair_scale_continuity_status": "cannot_determine_missing_top_pair",
            "top_pair_is_scale_adjacent": False,
            "top_pair_rank1_candidate_scale_group_id": rank1_group,
            "top_pair_rank2_candidate_scale_group_id": rank2_group,
            "top_pair_lower_scale_candidate_group_id": None,
            "top_pair_upper_scale_candidate_group_id": None,
            "top_pair_scale_coordinate_name": selected_field["name"],
            "top_pair_lower_scale_coordinate_value": None,
            "top_pair_upper_scale_coordinate_value": None,
            "top_pair_intervening_candidate_scale_group_ids": [],
            "top_pair_rank1_at_scale_boundary": False,
            "top_pair_rank1_boundary_side": "cannot_determine",
            "top_pair_rank1_upper_extrapolation_not_tested": False,
            "top_pair_boundary_constrained": False,
        }

    lower_pos = min(rank1_pos, rank2_pos)
    upper_pos = max(rank1_pos, rank2_pos)
    lower_group = scale_ladder[lower_pos - 1]["candidate_scale_group_id"]
    upper_group = scale_ladder[upper_pos - 1]["candidate_scale_group_id"]
    intervening = [item["candidate_scale_group_id"] for item in scale_ladder[lower_pos:upper_pos - 1]]
    is_adjacent = abs(rank1_pos - rank2_pos) == 1
    status = (
        "adjacent_top_pair_confirmed"
        if is_adjacent
        else "non_adjacent_top_pair_possible_bimodal_or_multimodal"
    )
    rank1_at_lower_boundary = rank1_pos == 1
    rank1_at_upper_boundary = rank1_pos == len(scale_ladder)
    if rank1_at_lower_boundary:
        boundary_side = "lower"
    elif rank1_at_upper_boundary:
        boundary_side = "upper"
    else:
        boundary_side = "none"
    return {
        "selected_scale_coordinate_name": selected_field["name"],
        "usable_scale_coordinate_fields": [item["name"] for item in usable_fields],
        "scale_coordinate_order_agreement": True,
        "scale_coordinate_value_by_group": value_by_group,
        "scale_ladder_rank_by_group": ladder_rank_by_group,
        "scale_ladder": scale_ladder,
        "top_pair_scale_continuity_status": status,
        "top_pair_is_scale_adjacent": is_adjacent,
        "top_pair_rank1_candidate_scale_group_id": rank1_group,
        "top_pair_rank2_candidate_scale_group_id": rank2_group,
        "top_pair_lower_scale_candidate_group_id": lower_group,
        "top_pair_upper_scale_candidate_group_id": upper_group,
        "top_pair_scale_coordinate_name": selected_field["name"],
        "top_pair_lower_scale_coordinate_value": value_by_group[lower_group],
        "top_pair_upper_scale_coordinate_value": value_by_group[upper_group],
        "top_pair_intervening_candidate_scale_group_ids": intervening,
        "top_pair_rank1_at_scale_boundary": rank1_at_lower_boundary or rank1_at_upper_boundary,
        "top_pair_rank1_boundary_side": boundary_side,
        "top_pair_rank1_upper_extrapolation_not_tested": rank1_at_upper_boundary,
        "top_pair_boundary_constrained": rank1_at_lower_boundary or rank1_at_upper_boundary,
    }


def validate_step9b_local_transition_refinement(
    step9a_gate_metadata: dict[str, Any],
    local_scale_coordinate_values: list[Any] | tuple[Any, ...] | None,
    source_step9a_directory: str | Path,
) -> dict[str, Any]:
    result = {
        "step9b_status": None,
        "step9b_status_reason": None,
        "step9b_interval_id": None,
        "source_step9a_directory": str(source_step9a_directory),
        **{field: step9a_gate_metadata.get(field) for field in STEP9B_GATE_METADATA_FIELDS},
        "local_scale_coordinate_values": list(local_scale_coordinate_values) if isinstance(local_scale_coordinate_values, (list, tuple)) else None,
        "local_scale_coordinate_count": len(local_scale_coordinate_values) if isinstance(local_scale_coordinate_values, (list, tuple)) else 0,
        "local_candidate_count": 0,
        "local_coordinate_plan": [],
        "step9b_no_extrapolation_beyond_interval": False,
    }

    def blocked(status: str, reason: str) -> dict[str, Any]:
        result["step9b_status"] = status
        result["step9b_status_reason"] = reason
        return result

    continuity_status = step9a_gate_metadata.get("top_pair_scale_continuity_status")
    if continuity_status == "non_adjacent_top_pair_possible_bimodal_or_multimodal":
        result["step9b_status"] = "step9b_user_choice_required_bimodal_or_multimodal"
        result["step9b_status_reason"] = "Step-9a supports two non-adjacent scale alternatives for analyst choice"
        result["user_choice_required"] = True
        result["supported_alternative_count"] = 2
        result["supported_alternative_candidate_scale_group_ids"] = [
            step9a_gate_metadata.get("top_pair_rank1_candidate_scale_group_id"),
            step9a_gate_metadata.get("top_pair_rank2_candidate_scale_group_id"),
        ]
        return result
    if continuity_status in {
        "cannot_determine_no_explicit_scale_coordinate",
        "cannot_determine_scale_order_disagreement",
        "cannot_determine_missing_top_pair",
    }:
        return blocked(
            "step9b_blocked_cannot_determine_scale_continuity",
            f"Step-9a scale continuity status is {continuity_status}",
        )

    required_text_fields = (
        "top_pair_rank1_candidate_scale_group_id",
        "top_pair_rank2_candidate_scale_group_id",
        "top_pair_lower_scale_candidate_group_id",
        "top_pair_upper_scale_candidate_group_id",
        "top_pair_scale_coordinate_name",
    )
    if (
        continuity_status != "adjacent_top_pair_confirmed"
        or step9a_gate_metadata.get("top_pair_is_scale_adjacent") is not True
        or any(not str(step9a_gate_metadata.get(field, "")).strip() for field in required_text_fields)
        or "top_pair_lower_scale_coordinate_value" not in step9a_gate_metadata
        or "top_pair_upper_scale_coordinate_value" not in step9a_gate_metadata
    ):
        return blocked(
            "step9b_blocked_missing_top_pair_metadata",
            "Step-9a adjacent top-pair status, adjacency flag, endpoint IDs, coordinate name, or interval bounds are missing",
        )

    try:
        lower_value = float(step9a_gate_metadata["top_pair_lower_scale_coordinate_value"])
        upper_value = float(step9a_gate_metadata["top_pair_upper_scale_coordinate_value"])
    except (TypeError, ValueError):
        return blocked(
            "step9b_blocked_invalid_interval_bounds",
            "Step-9a lower and upper scale-coordinate bounds must be numeric",
        )
    if not math.isfinite(lower_value) or not math.isfinite(upper_value) or lower_value >= upper_value:
        return blocked(
            "step9b_blocked_invalid_interval_bounds",
            "Step-9a scale-coordinate bounds must be finite and strictly increasing",
        )

    result["step9b_interval_id"] = "step9b_interval_000"
    if not isinstance(local_scale_coordinate_values, (list, tuple)) or not local_scale_coordinate_values:
        return blocked(
            "step9b_blocked_missing_explicit_local_scale_coordinates",
            "An explicit non-empty local scale-coordinate list is required",
        )

    local_values: list[float] = []
    for value in local_scale_coordinate_values:
        if isinstance(value, bool):
            return blocked(
                "step9b_blocked_local_coordinate_not_strictly_ordered",
                "Every local scale coordinate must be a finite numeric value",
            )
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return blocked(
                "step9b_blocked_local_coordinate_not_strictly_ordered",
                "Every local scale coordinate must be a finite numeric value",
            )
        if not math.isfinite(numeric_value):
            return blocked(
                "step9b_blocked_local_coordinate_not_strictly_ordered",
                "Every local scale coordinate must be a finite numeric value",
            )
        local_values.append(numeric_value)

    result["local_scale_coordinate_values"] = local_values
    if len(set(local_values)) != len(local_values):
        return blocked(
            "step9b_blocked_local_coordinate_duplicate",
            "Explicit local scale coordinates must not contain duplicates",
        )
    if any(left >= right for left, right in zip(local_values, local_values[1:])):
        return blocked(
            "step9b_blocked_local_coordinate_not_strictly_ordered",
            "Explicit local scale coordinates must be strictly increasing",
        )
    if any(value < lower_value or value > upper_value for value in local_values):
        return blocked(
            "step9b_blocked_local_coordinate_outside_interval",
            "Every local scale coordinate must be inside the closed confirmed Step-9a interval",
        )
    if local_values[0] != lower_value or local_values[-1] != upper_value:
        return blocked(
            "step9b_blocked_missing_explicit_local_scale_coordinates",
            "Explicit local scale coordinates must include both confirmed interval endpoints exactly",
        )

    result["step9b_no_extrapolation_beyond_interval"] = True
    result["local_coordinate_plan"] = [
        {
            "step9b_local_candidate_id": f"local_{index:03d}",
            "step9b_interval_id": result["step9b_interval_id"],
            "source_step9a_rank1_candidate_scale_group_id": step9a_gate_metadata.get("top_pair_rank1_candidate_scale_group_id"),
            "source_step9a_rank2_candidate_scale_group_id": step9a_gate_metadata.get("top_pair_rank2_candidate_scale_group_id"),
            "source_step9a_lower_candidate_scale_group_id": step9a_gate_metadata["top_pair_lower_scale_candidate_group_id"],
            "source_step9a_upper_candidate_scale_group_id": step9a_gate_metadata["top_pair_upper_scale_candidate_group_id"],
            "scale_coordinate_name": step9a_gate_metadata["top_pair_scale_coordinate_name"],
            "scale_coordinate_value": value,
        }
        for index, value in enumerate(local_values)
    ]
    result["step9b_status"] = "step9b_ready_adjacent_interval"
    result["step9b_status_reason"] = "Adjacent Step-9a interval and explicit local scale coordinates are valid"
    return result


def run_step9b_local_transition_refinement_preflight(
    output_dir: str | Path,
    source_step9a_directory: str | Path,
    step9a_gate_metadata: dict[str, Any],
    local_scale_coordinate_values: list[Any] | tuple[Any, ...] | None,
) -> dict[str, Any]:
    result = validate_step9b_local_transition_refinement(
        step9a_gate_metadata,
        local_scale_coordinate_values,
        source_step9a_directory,
    )
    if result["step9b_status"] == "step9b_ready_adjacent_interval":
        result["step9b_status"] = "step9b_blocked_parameter_construction_unavailable"
        result["step9b_status_reason"] = (
            "The current module has no deterministic explicit scale-coordinate mapping to all required "
            "segmentation and perturbation parameters"
        )

    step9b_dir = local_transition_refinement_output_dir(output_dir)
    _write_json(step9b_dir / STEP9B_OUTPUT_FILENAMES["preflight"], result)
    return result


def compute_step9b_gain_share_handoff(
    no1_candidate_scale_group_id: str,
    no2_candidate_scale_group_id: str,
    midpoint_candidate_id: str,
    S1: Any,
    S2: Any,
    SM: Any,
) -> dict[str, Any]:
    def finite_number(value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    s1 = finite_number(S1)
    s2 = finite_number(S2)
    sm = finite_number(SM)
    total_gain = s1 - s2 if s1 is not None and s2 is not None else None
    result = {
        "no1_candidate_scale_group_id": str(no1_candidate_scale_group_id),
        "no2_candidate_scale_group_id": str(no2_candidate_scale_group_id),
        "midpoint_candidate_id": str(midpoint_candidate_id),
        "S1": s1,
        "S2": s2,
        "SM": sm,
        "total_gain": total_gain,
        "midpoint_gain": None,
        "midpoint_gain_share": None,
        "gain_share_threshold": 0.5,
        "gain_share_comparator": ">",
        "handoff_candidate_id": str(no1_candidate_scale_group_id),
        "handoff_reason": None,
        "warning": False,
        "status": None,
    }
    if total_gain is None or total_gain <= 0:
        result["status"] = "step9b_no1_retained_invalid_reference_gain"
        result["handoff_reason"] = "Reference raw-support gain is not positive"
        result["warning"] = True
        return result
    if sm is None:
        result["status"] = "step9b_no1_retained_midpoint_uninterpretable"
        result["handoff_reason"] = "Midpoint-family raw support is missing or non-finite"
        result["warning"] = True
        return result

    midpoint_gain = sm - s2
    midpoint_gain_share = midpoint_gain / total_gain
    result["midpoint_gain"] = midpoint_gain
    result["midpoint_gain_share"] = midpoint_gain_share
    if midpoint_gain_share > 0.5:
        result["status"] = "step9b_midpoint_gain_share_handoff"
        result["handoff_candidate_id"] = str(midpoint_candidate_id)
        result["handoff_reason"] = "Midpoint-family raw support delivers more than half of the local reference gain"
    else:
        result["status"] = "step9b_no1_retained_gain_share"
        result["handoff_reason"] = "Midpoint-family raw support does not deliver more than half of the local reference gain"
    return result


def select_step9_handoff_candidate(handoff: dict) -> dict:
    selected = handoff["handoff_candidate_id"]

    if selected == handoff["midpoint_candidate_id"]:
        selected_source = "midpoint"
    elif selected == handoff["no1_candidate_scale_group_id"]:
        selected_source = "upper_bound"
    else:
        raise ValueError(
            f"Invalid Step-9 handoff candidate: {selected!r}. "
            "Expected midpoint_candidate_id or no1_candidate_scale_group_id."
        )

    return {
        "selected_candidate_id": selected,
        "selected_source": selected_source,
        "warning": handoff.get("warning"),
        "handoff_reason": handoff.get("handoff_reason"),
        "S1": handoff.get("S1"),
        "S2": handoff.get("S2"),
        "SM": handoff.get("SM"),
        "midpoint_gain_share": handoff.get("midpoint_gain_share"),
    }


def _step9b_metadata_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _step9b_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value in (0, 1):
        return bool(value)
    return None


def _step9b_central_boundary_row(
    run_population_rows: list[dict[str, Any]],
    candidate_scale_group_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    central_rows: list[dict[str, Any]] = []
    for row in run_population_rows:
        if str(row.get("candidate_scale_group_id", "")) != str(candidate_scale_group_id):
            continue
        original_metadata = _step9b_metadata_dict(row.get("original_row_metadata"))
        original_flag = _step9b_bool(original_metadata.get("is_baseline")) if "is_baseline" in original_metadata else None
        top_level_flag = _step9b_bool(row.get("is_baseline")) if "is_baseline" in row else None
        if original_flag is not None and top_level_flag is not None and original_flag is not top_level_flag:
            return None, "step9b_blocked_conflicting_baseline_metadata"
        baseline_flag = original_flag if original_flag is not None else top_level_flag
        if baseline_flag is True:
            central_rows.append(row)
    if len(central_rows) != 1:
        return None, "step9b_blocked_missing_central_boundary_rows"
    return central_rows[0], None


def _step9b_ranked_candidate_row(
    ranked_candidate_rows: list[dict[str, Any]],
    candidate_scale_group_id: str,
) -> dict[str, Any] | None:
    matches = [
        row
        for row in ranked_candidate_rows
        if str(row.get("candidate_scale_group_id", "")) == str(candidate_scale_group_id)
    ]
    return matches[0] if len(matches) == 1 else None


def _step9b_raw_support(row: dict[str, Any] | None) -> float | None:
    if row is None or "stability_score_raw" not in row or isinstance(row["stability_score_raw"], bool):
        return None
    try:
        value = float(row["stability_score_raw"])
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def run_step9b_midpoint_support_probe(
    output_dir: str | Path,
    source_step9a_directory: str | Path,
    step9a_gate_metadata: dict[str, Any],
    ranked_candidate_rows: list[dict[str, Any]],
    run_population_rows: list[dict[str, Any]],
    perturbation_config: Level1BPerturbationConfig | None,
    midpoint_family_support_raw: Any = None,
) -> dict[str, Any]:
    step9b_dir = local_transition_refinement_output_dir(output_dir)
    result = {
        "step9b_status": None,
        "step9b_status_reason": None,
        "source_step9a_directory": str(source_step9a_directory),
        **{field: step9a_gate_metadata.get(field) for field in STEP9B_GATE_METADATA_FIELDS},
        "user_choice_required": False,
        "supported_alternative_count": 0,
        "midpoint_candidate_count": 0,
        "midpoint_perturbation_candidate_count": 0,
        "step9b_no_extrapolation_beyond_interval": False,
        "real_midpoint_family_support_available": midpoint_family_support_raw is not None,
    }

    def finish(status: str, reason: str) -> dict[str, Any]:
        result["step9b_status"] = status
        result["step9b_status_reason"] = reason
        _write_json(step9b_dir / STEP9B_OUTPUT_FILENAMES["preflight"], result)
        return result

    continuity_status = step9a_gate_metadata.get("top_pair_scale_continuity_status")
    if continuity_status in {
        "cannot_determine_no_explicit_scale_coordinate",
        "cannot_determine_scale_order_disagreement",
        "cannot_determine_missing_top_pair",
    }:
        return finish(
            "step9b_blocked_cannot_determine_scale_continuity",
            f"Step-9a scale continuity status is {continuity_status}",
        )

    no1_id = str(step9a_gate_metadata.get("top_pair_rank1_candidate_scale_group_id", "")).strip()
    no2_id = str(step9a_gate_metadata.get("top_pair_rank2_candidate_scale_group_id", "")).strip()
    if not no1_id or not no2_id:
        return finish(
            "step9b_blocked_missing_top_pair_or_boundary_metadata",
            "Step-9a No1 or No2 candidate metadata is missing",
        )

    if (
        continuity_status == "non_adjacent_top_pair_possible_bimodal_or_multimodal"
        or step9a_gate_metadata.get("top_pair_is_scale_adjacent") is False
    ):
        lower_id = step9a_gate_metadata.get("top_pair_lower_scale_candidate_group_id")
        upper_id = step9a_gate_metadata.get("top_pair_upper_scale_candidate_group_id")
        coordinate_name = step9a_gate_metadata.get("top_pair_scale_coordinate_name")
        coordinate_by_id = {
            str(lower_id): step9a_gate_metadata.get("top_pair_lower_scale_coordinate_value"),
            str(upper_id): step9a_gate_metadata.get("top_pair_upper_scale_coordinate_value"),
        }
        alternatives = []
        for rank, candidate_id in ((1, no1_id), (2, no2_id)):
            ranked_row = _step9b_ranked_candidate_row(ranked_candidate_rows, candidate_id)
            alternative = {
                "rank": rank,
                "candidate_scale_group_id": candidate_id,
                "stability_score_raw": _step9b_raw_support(ranked_row),
                "scale_coordinate_name": coordinate_name,
                "scale_coordinate_value": coordinate_by_id.get(candidate_id),
                "requires_step9b_execution": False,
                "source_step9a_metrics_reused": True,
            }
            if ranked_row is not None:
                alternative.update(
                    {
                        key: value
                        for key, value in ranked_row.items()
                        if str(key).endswith("_path") and value not in (None, "")
                    }
                )
            alternatives.append(alternative)
        result["user_choice_required"] = True
        result["supported_alternative_count"] = 2
        result["supported_alternatives"] = alternatives
        _write_csv(step9b_dir / STEP9B_OUTPUT_FILENAMES["supported_alternatives_csv"], alternatives)
        _write_json(step9b_dir / STEP9B_OUTPUT_FILENAMES["supported_alternatives_json"], alternatives)
        return finish(
            "step9b_user_choice_required_bimodal_or_multimodal",
            "Step-9a supports two non-adjacent scale alternatives for analyst choice",
        )

    required_boundary_fields = (
        "top_pair_lower_scale_candidate_group_id",
        "top_pair_upper_scale_candidate_group_id",
        "top_pair_scale_coordinate_name",
        "top_pair_lower_scale_coordinate_value",
        "top_pair_upper_scale_coordinate_value",
    )
    if (
        continuity_status != "adjacent_top_pair_confirmed"
        or step9a_gate_metadata.get("top_pair_is_scale_adjacent") is not True
        or any(
            field not in step9a_gate_metadata or step9a_gate_metadata.get(field) in (None, "")
            for field in required_boundary_fields
        )
    ):
        return finish(
            "step9b_blocked_missing_top_pair_or_boundary_metadata",
            "Confirmed adjacent top-pair boundary metadata is incomplete",
        )

    lower_id = str(step9a_gate_metadata["top_pair_lower_scale_candidate_group_id"])
    upper_id = str(step9a_gate_metadata["top_pair_upper_scale_candidate_group_id"])
    coordinate_name = str(step9a_gate_metadata["top_pair_scale_coordinate_name"])
    try:
        lower_coordinate = float(step9a_gate_metadata["top_pair_lower_scale_coordinate_value"])
        upper_coordinate = float(step9a_gate_metadata["top_pair_upper_scale_coordinate_value"])
    except (TypeError, ValueError):
        return finish(
            "step9b_blocked_invalid_interval_bounds",
            "Step-9a boundary coordinates must be finite numeric values",
        )
    if not math.isfinite(lower_coordinate) or not math.isfinite(upper_coordinate) or lower_coordinate >= upper_coordinate:
        return finish(
            "step9b_blocked_invalid_interval_bounds",
            "Step-9a boundary coordinates must be finite and strictly increasing",
        )

    lower_row, lower_error = _step9b_central_boundary_row(run_population_rows, lower_id)
    upper_row, upper_error = _step9b_central_boundary_row(run_population_rows, upper_id)
    boundary_error = lower_error or upper_error
    if boundary_error is not None:
        reason = (
            "Original and top-level baseline metadata disagree"
            if boundary_error == "step9b_blocked_conflicting_baseline_metadata"
            else "Exactly one central baseline row is required for each Step-9a boundary"
        )
        return finish(boundary_error, reason)
    assert lower_row is not None and upper_row is not None

    required_central_fields = ("source_candidate_radius_m", "spatialr_px", "minsize_px", "ranger")
    if any(field not in lower_row or field not in upper_row for field in required_central_fields):
        return finish(
            "step9b_blocked_missing_central_boundary_rows",
            "Central Step-9a boundary rows lack required midpoint parameters",
        )
    try:
        lower_radius = float(lower_row["source_candidate_radius_m"])
        upper_radius = float(upper_row["source_candidate_radius_m"])
        lower_spatialr = float(lower_row["spatialr_px"])
        upper_spatialr = float(upper_row["spatialr_px"])
        lower_minsize = float(lower_row["minsize_px"])
        upper_minsize = float(upper_row["minsize_px"])
        lower_ranger = float(lower_row["ranger"])
        upper_ranger = float(upper_row["ranger"])
    except (TypeError, ValueError):
        return finish(
            "step9b_blocked_missing_central_boundary_rows",
            "Central Step-9a boundary midpoint parameters must be numeric",
        )
    numeric_values = (
        lower_radius,
        upper_radius,
        lower_spatialr,
        upper_spatialr,
        lower_minsize,
        upper_minsize,
        lower_ranger,
        upper_ranger,
    )
    if not all(math.isfinite(value) for value in numeric_values):
        return finish(
            "step9b_blocked_missing_central_boundary_rows",
            "Central Step-9a boundary midpoint parameters must be finite",
        )

    midpoint_coordinate = (lower_coordinate + upper_coordinate) / 2.0
    if not lower_coordinate < midpoint_coordinate < upper_coordinate:
        return finish(
            "step9b_blocked_invalid_interval_bounds",
            "Arithmetic midpoint must lie strictly inside the confirmed interval",
        )
    midpoint_radius = (lower_radius + upper_radius) / 2.0
    midpoint_spatialr = math.floor(((lower_spatialr + upper_spatialr) / 2.0) + 0.5)
    midpoint_minsize = math.floor(((lower_minsize + upper_minsize) / 2.0) + 0.5)
    midpoint_ranger = (lower_ranger + upper_ranger) / 2.0
    lower_candidate_id = str(lower_row.get("source_candidate_id", lower_row.get("candidate_id", ""))).strip()
    upper_candidate_id = str(upper_row.get("source_candidate_id", upper_row.get("candidate_id", ""))).strip()
    if not lower_candidate_id or not upper_candidate_id:
        return finish(
            "step9b_blocked_missing_central_boundary_rows",
            "Central Step-9a boundary rows lack source candidate IDs",
        )

    midpoint_candidate = {
        "step9b_row_role": "new_midpoint_probe",
        "candidate_id": "local_midpoint",
        "scale_id": "local_midpoint",
        "candidate_scale_group_id": "local_midpoint",
        "scale_coordinate_name": coordinate_name,
        "scale_coordinate_value": midpoint_coordinate,
        "source_candidate_radius_m": midpoint_radius,
        "radius_m": midpoint_radius,
        "spatialr_px": midpoint_spatialr,
        "minsize_px": midpoint_minsize,
        "ranger": midpoint_ranger,
        "source_lower_candidate_scale_group_id": lower_id,
        "source_upper_candidate_scale_group_id": upper_id,
        "source_lower_candidate_id": lower_candidate_id,
        "source_upper_candidate_id": upper_candidate_id,
        "requires_step9b_execution": True,
        "source_step9a_metrics_reused": False,
    }
    if perturbation_config is None:
        return finish(
            "step9b_blocked_missing_perturbation_config",
            "A perturbation configuration is required for the midpoint family",
        )
    midpoint_perturbations = build_perturbation_candidates(perturbation_config, [midpoint_candidate])
    midpoint_metadata = {
        "candidate_scale_group_id": "local_midpoint",
        "scale_coordinate_name": coordinate_name,
        "scale_coordinate_value": midpoint_coordinate,
        "source_candidate_radius_m": midpoint_radius,
        "source_lower_candidate_scale_group_id": lower_id,
        "source_upper_candidate_scale_group_id": upper_id,
        "source_lower_candidate_id": lower_candidate_id,
        "source_upper_candidate_id": upper_candidate_id,
        "requires_step9b_execution": True,
        "source_step9a_metrics_reused": False,
    }
    midpoint_perturbations = [dict(row, **midpoint_metadata) for row in midpoint_perturbations]
    anchor_references = [
        {
            "step9b_row_role": "existing_lower_anchor",
            "candidate_scale_group_id": lower_id,
            "requires_step9b_execution": False,
            "source_step9a_metrics_reused": True,
        },
        {
            "step9b_row_role": "existing_upper_anchor",
            "candidate_scale_group_id": upper_id,
            "requires_step9b_execution": False,
            "source_step9a_metrics_reused": True,
        },
    ]
    result.update(
        {
            "midpoint_candidate_count": 1,
            "midpoint_perturbation_candidate_count": len(midpoint_perturbations),
            "midpoint_probe_candidate": midpoint_candidate,
            "anchor_references": anchor_references,
            "step9b_no_extrapolation_beyond_interval": True,
        }
    )
    _write_csv(step9b_dir / STEP9B_OUTPUT_FILENAMES["midpoint_probe_csv"], [midpoint_candidate])
    _write_json(step9b_dir / STEP9B_OUTPUT_FILENAMES["midpoint_probe_json"], midpoint_candidate)
    _write_csv(step9b_dir / STEP9B_OUTPUT_FILENAMES["midpoint_perturbations_csv"], midpoint_perturbations)
    _write_json(step9b_dir / STEP9B_OUTPUT_FILENAMES["midpoint_perturbations_json"], midpoint_perturbations)

    no1_row = _step9b_ranked_candidate_row(ranked_candidate_rows, no1_id)
    no2_row = _step9b_ranked_candidate_row(ranked_candidate_rows, no2_id)
    s1 = _step9b_raw_support(no1_row)
    s2 = _step9b_raw_support(no2_row)
    if midpoint_family_support_raw is not None and s1 is not None and s2 is not None:
        handoff = compute_step9b_gain_share_handoff(
            no1_id,
            no2_id,
            "local_midpoint",
            s1,
            s2,
            midpoint_family_support_raw,
        )
        result["gain_share_handoff"] = handoff
        _write_json(step9b_dir / STEP9B_OUTPUT_FILENAMES["gain_share_handoff"], handoff)
        return finish(handoff["status"], handoff["handoff_reason"])

    return finish(
        "step9b_midpoint_probe_ready",
        "Exactly one midpoint probe family is prepared inside the confirmed adjacent interval",
    )


def run_step9b_prepare_from_existing_step9a(
    run_root: Path,
    candidate_id: str,
    perturbation_config: Level1BPerturbationConfig,
) -> dict:
    run_root = Path(run_root)
    step9a_dir = run_root / "level1b" / "candidate_response_surface"
    run_population_rows = json.loads(
        (step9a_dir / "run_population_summary.json").read_text(encoding="utf-8")
    )
    candidate_group_rows = json.loads(
        (step9a_dir / "candidate_group_response_summary.json").read_text(encoding="utf-8")
    )
    step9a_report = json.loads(
        (step9a_dir / "candidate_response_surface_report.json").read_text(encoding="utf-8")
    )
    if not isinstance(run_population_rows, list):
        raise ValueError("run_population_summary.json must decode to a list")
    if not isinstance(candidate_group_rows, list):
        raise ValueError("candidate_group_response_summary.json must decode to a list")
    if not isinstance(step9a_report, dict):
        raise ValueError("candidate_response_surface_report.json must decode to a dict")

    ranked_candidate_rows = []
    for source_row in candidate_group_rows:
        row = deepcopy(source_row)
        row["stability_score_raw"] = stability_score_raw(row)
        row["stability_score"] = stability_score(row)
        ranked_candidate_rows.append(row)
    ranked_candidate_rows.sort(
        key=lambda row: (
            -float(row["stability_score_raw"]),
            -float(row["stability_score"]),
            str(row.get("candidate_scale_group_id", "")),
        )
    )

    step9a_gate_metadata = compute_top_pair_scale_continuity_and_boundary_gate(
        run_population_rows,
        ranked_candidate_rows,
    )
    source_step9a_report = step9a_dir / "candidate_response_surface_report.json"
    step9a_gate_report = {
        "status": step9a_report.get("status"),
        "candidate_id": step9a_report.get("candidate_id", candidate_id),
        "source_candidate_response_surface_report": str(source_step9a_report),
        **step9a_gate_metadata,
    }

    step9b_prepare_inputs_dir = run_root / "level1b" / "step9b_prepare_inputs"
    step9b_prepare_inputs_dir.mkdir(parents=True, exist_ok=True)
    _write_json(step9b_prepare_inputs_dir / "run_population_summary.json", run_population_rows)
    _write_json(step9b_prepare_inputs_dir / "ranked_candidate_scales.json", ranked_candidate_rows)
    _write_json(
        step9b_prepare_inputs_dir / "candidate_response_surface_report.json",
        step9a_gate_report,
    )

    step9b_result = run_step9b_midpoint_support_probe(
        output_dir=run_root,
        source_step9a_directory=step9b_prepare_inputs_dir,
        step9a_gate_metadata=step9a_gate_report,
        ranked_candidate_rows=ranked_candidate_rows,
        run_population_rows=run_population_rows,
        perturbation_config=perturbation_config,
        midpoint_family_support_raw=None,
    )
    step9b_prepare_result_json = step9b_prepare_inputs_dir / "step9b_prepare_result.json"
    _write_json(step9b_prepare_result_json, step9b_result)

    return {
        "status": step9b_result.get("status"),
        "run_root": str(run_root),
        "candidate_id": candidate_id,
        "step9a_dir": str(step9a_dir),
        "step9b_prepare_inputs_dir": str(step9b_prepare_inputs_dir),
        "local_transition_refinement_dir": str(
            Path(run_root) / "level1b" / "local_transition_refinement"
        ),
        "step9b_prepare_result_json": str(step9b_prepare_result_json),
        "step9b_result": step9b_result,
    }


def run_step9b_midpoint_response_surface_and_handoff_from_prepare(
    run_root: Path,
    candidate_id: str,
    candidate_response_surface_config: Level1BCandidateResponseSurfaceConfig,
) -> dict:
    run_root = Path(run_root)
    step9b_prepare_inputs_dir = run_root / "level1b" / "step9b_prepare_inputs"
    local_transition_refinement_dir = run_root / "level1b" / "local_transition_refinement"
    midpoint_response_surface_output_dir = (
        local_transition_refinement_dir / "midpoint_response_surface_eval"
    )

    ranked_candidate_rows = json.loads(
        (step9b_prepare_inputs_dir / "ranked_candidate_scales.json").read_text(
            encoding="utf-8"
        )
    )
    midpoint_probe_candidate = json.loads(
        (local_transition_refinement_dir / "step9b_midpoint_probe_candidate.json").read_text(
            encoding="utf-8"
        )
    )
    midpoint_perturbation_candidates_json = (
        local_transition_refinement_dir / "step9b_midpoint_perturbation_candidates.json"
    )
    json.loads(midpoint_perturbation_candidates_json.read_text(encoding="utf-8"))

    midpoint_response_surface_config = deepcopy(candidate_response_surface_config)
    midpoint_response_surface_config.output_dir = midpoint_response_surface_output_dir
    midpoint_response_surface_config.perturbation_candidates_json_path = (
        midpoint_perturbation_candidates_json
    )
    midpoint_response_surface_config.candidate_id = candidate_id
    midpoint_response_surface_result = run_candidate_response_surface_step(
        midpoint_response_surface_config
    )
    if midpoint_response_surface_result.get("status") != "ok":
        raise RuntimeError(
            "Midpoint response surface failed with status "
            f"{midpoint_response_surface_result.get('status')!r}"
        )

    midpoint_candidate_response_surface_dir = response_surface_output_dir(
        midpoint_response_surface_output_dir
    )
    midpoint_candidate_group_summary_json = (
        midpoint_candidate_response_surface_dir / "candidate_group_response_summary.json"
    )
    midpoint_run_population_json = (
        midpoint_candidate_response_surface_dir / "run_population_summary.json"
    )
    midpoint_candidate_group_rows = json.loads(
        midpoint_candidate_group_summary_json.read_text(encoding="utf-8")
    )
    json.loads(midpoint_run_population_json.read_text(encoding="utf-8"))

    probe_midpoint_id = str(midpoint_probe_candidate["candidate_scale_group_id"])
    if len(midpoint_candidate_group_rows) == 1:
        selected_midpoint_row = midpoint_candidate_group_rows[0]
    else:
        midpoint_matches = [
            row
            for row in midpoint_candidate_group_rows
            if str(row["candidate_scale_group_id"]) == probe_midpoint_id
        ]
        if len(midpoint_matches) != 1:
            raise ValueError(
                "Midpoint candidate group summary must contain exactly one row matching "
                f"candidate_scale_group_id {probe_midpoint_id!r}"
            )
        selected_midpoint_row = midpoint_matches[0]

    no1_row = ranked_candidate_rows[0]
    no2_row = ranked_candidate_rows[1]
    no1_id = str(no1_row["candidate_scale_group_id"])
    no2_id = str(no2_row["candidate_scale_group_id"])
    midpoint_id = str(selected_midpoint_row["candidate_scale_group_id"])
    s1 = float(no1_row["stability_score_raw"])
    s2 = float(no2_row["stability_score_raw"])
    sm = float(selected_midpoint_row["stability_score_raw"])
    handoff = compute_step9b_gain_share_handoff(
        no1_candidate_scale_group_id=no1_id,
        no2_candidate_scale_group_id=no2_id,
        midpoint_candidate_id=midpoint_id,
        S1=s1,
        S2=s2,
        SM=sm,
    )

    step9b_midpoint_gain_share_handoff_json = (
        local_transition_refinement_dir / "step9b_midpoint_gain_share_handoff.json"
    )
    _write_json(step9b_midpoint_gain_share_handoff_json, handoff)

    return {
        "status": "step9b_midpoint_response_surface_and_handoff_ready",
        "run_root": str(run_root),
        "candidate_id": candidate_id,
        "midpoint_response_surface_output_dir": str(
            midpoint_response_surface_output_dir
        ),
        "midpoint_candidate_group_summary_json": str(
            midpoint_candidate_group_summary_json
        ),
        "midpoint_run_population_json": str(midpoint_run_population_json),
        "step9b_midpoint_gain_share_handoff_json": str(
            step9b_midpoint_gain_share_handoff_json
        ),
        "handoff": handoff,
    }


def run_candidate_response_surface_step(cfg: Level1BCandidateResponseSurfaceConfig) -> dict[str, Any]:
    started = time.time()
    out_dir = response_surface_output_dir(cfg.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    failed_runs: list[dict[str, Any]] = []
    omitted_runs: list[dict[str, Any]] = []
    try:
        rows = read_step8_local_parameter_combinations(cfg.perturbation_candidates_json_path)
        groups = group_rows_by_candidate_scale(rows)
    except Exception as exc:  # noqa: BLE001 - top-level report must capture validation failures.
        report = _top_report(
            cfg,
            out_dir,
            [],
            [],
            [],
            [],
            [],
            [{"status": "failed", "reason": str(exc)}],
            [],
            started,
        )
        report["status"] = "failed"
        _write_json(out_dir / OUTPUT_FILENAMES["report"], report)
        return report

    planned_group_count = len(groups)
    if cfg.max_candidate_scale_groups is not None:
        for group in groups[cfg.max_candidate_scale_groups :]:
            for row in group["rows"]:
                omitted_runs.append(_omitted(row, group["candidate_scale_group_id"], "max_candidate_scale_groups"))
        groups = groups[: cfg.max_candidate_scale_groups]

    run_summaries: list[dict[str, Any]] = []
    matrix_cell_records: list[dict[str, Any]] = []
    matrix_summaries: list[dict[str, Any]] = []
    group_summaries: list[dict[str, Any]] = []
    segmentation_reports: list[dict[str, Any]] = []

    segmentation_stack_path, segmentation_stack_source = resolve_segmentation_stack(cfg)
    valid_mask_path = resolve_valid_mask_path(cfg)
    pixel_size = _pixel_size_m(segmentation_stack_path)
    for group in groups:
        group_id = group["candidate_scale_group_id"]
        rows_for_group = list(group["rows"])
        if cfg.max_runs_per_group is not None:
            for row in rows_for_group[cfg.max_runs_per_group :]:
                omitted_runs.append(_omitted(row, group_id, "max_runs_per_group"))
            rows_for_group = rows_for_group[: cfg.max_runs_per_group]

        group_run_summaries: list[dict[str, Any]] = []
        group_matrix_summaries: list[dict[str, Any]] = []
        for row in rows_for_group:
            run_id = str(row.get("perturbation_id", f"{group_id}__row_{row.get('_step8_row_index', 0)}"))
            status_recorded = False
            try:
                if cfg.dry_run:
                    segmentation_report = {"status": "dry_run", "output_artifacts": {}, "failure_reasons": []}
                    labels = np.zeros((0, 0), dtype=np.int32)
                else:
                    segmentation_report = _run_or_reuse_segmentation(cfg, out_dir, group_id, row, run_id)
                    segmentation_reports.append(
                        {
                            "run_id": run_id,
                            "candidate_scale_group_id": group_id,
                            "status": segmentation_report.get(
                                "step9_run_status", "computed"
                            ),
                            "report_path": str(
                                _run_artifact_paths(out_dir, group_id, run_id)[
                                    "report"
                                ]
                            ),
                        }
                    )
                    status_recorded = True
                    if segmentation_report.get("status") != "ok":
                        raise RuntimeError("one-scale segmentation failed: " + "; ".join(segmentation_report.get("failure_reasons", [])))
                    labels_path = _merged_labels_path(segmentation_report)
                    if not labels_path:
                        raise RuntimeError("merged label raster missing from segmentation report")
                    label_counts = count_segment_sizes_from_raster(labels_path, valid_mask_path, pixel_size)
                if cfg.dry_run:
                    segmentation_reports.append(
                        {
                            "run_id": run_id,
                            "candidate_scale_group_id": group_id,
                            "status": "skipped_dry_run",
                            "report_path": str(
                                _run_artifact_paths(out_dir, group_id, run_id)[
                                    "report"
                                ]
                            ),
                        }
                    )
                    status_recorded = True
                if cfg.dry_run:
                    failed_runs.append({"run_id": run_id, "candidate_scale_group_id": group_id, "status": "omitted", "reason": "dry_run"})
                    continue
                if segmentation_report.get("step9_run_status") == "reused":
                    run_summary = _read_run_q_summary(_run_artifact_paths(out_dir, group_id, run_id)["summary_json"])
                else:
                    run_summary = compute_run_population_summary_from_counts(run_id, group_id, row, label_counts, pixel_size, cfg)
                    run_summary = _write_incremental_run_q_statistics_from_counts(out_dir, group_id, run_id, row, label_counts, pixel_size, cfg, run_summary)
                run_summaries.append(run_summary)
                group_run_summaries.append(run_summary)
                label_classes = label_classes_from_counts(label_counts, row, pixel_size, cfg)
                matrix = aggregate_analysis_matrix_from_raster(
                    labels_path,
                    valid_mask_path,
                    label_classes,
                    pixel_size,
                    compute_analysis_cell_size_m(row, cfg),
                    run_id,
                    group_id,
                )
                matrix_cell_records.extend(matrix["cell_records"])
                matrix_summary = dict(matrix["summary"], analysis_cell_size_m=matrix["cell_size_m"], analysis_cell_size_px=matrix["cell_size_px"])
                matrix_summaries.append(matrix_summary)
                group_matrix_summaries.append(matrix_summary)
            except Exception as exc:  # noqa: BLE001 - every failed planned run is reported.
                failed_runs.append({"run_id": run_id, "candidate_scale_group_id": group_id, "status": "failed", "reason": str(exc), "row": row})
                if status_recorded:
                    segmentation_reports[-1]["status"] = "failed"
                    segmentation_reports[-1]["reason"] = str(exc)
                else:
                    segmentation_reports.append(
                        {
                            "run_id": run_id,
                            "candidate_scale_group_id": group_id,
                            "status": "failed",
                            "reason": str(exc),
                            "report_path": str(
                                _run_artifact_paths(out_dir, group_id, run_id)[
                                    "report"
                                ]
                            ),
                        }
                    )
        if group_run_summaries:
            group_summaries.append(compute_candidate_group_response_summary(group_id, group_run_summaries, group_matrix_summaries, cfg))

    space_summary = analyze_full_candidate_space(group_summaries, run_summaries)
    ranked = sorted(
        group_summaries,
        key=lambda item: (
            -float(item["stability_score_raw"]),
            -float(item["stability_score"]),
            str(item["candidate_scale_group_id"]),
        ),
    )
    scale_gate = compute_top_pair_scale_continuity_and_boundary_gate(run_summaries, ranked)
    if scale_gate["selected_scale_coordinate_name"] is not None:
        selected_scale_coordinate_name = scale_gate["selected_scale_coordinate_name"]
        scale_coordinate_value_by_group = scale_gate["scale_coordinate_value_by_group"]
        scale_ladder_rank_by_group = scale_gate["scale_ladder_rank_by_group"]
        for item in group_summaries:
            group_id = str(item["candidate_scale_group_id"])
            item["scale_coordinate_name"] = selected_scale_coordinate_name
            item["scale_coordinate_value"] = scale_coordinate_value_by_group.get(group_id)
            item["scale_ladder_rank"] = scale_ladder_rank_by_group.get(group_id)
        for item in ranked:
            group_id = str(item["candidate_scale_group_id"])
            item["scale_coordinate_name"] = selected_scale_coordinate_name
            item["scale_coordinate_value"] = scale_coordinate_value_by_group.get(group_id)
            item["scale_ladder_rank"] = scale_ladder_rank_by_group.get(group_id)
    else:
        for item in group_summaries:
            item["scale_coordinate_name"] = None
            item["scale_coordinate_value"] = None
            item["scale_ladder_rank"] = None
        for item in ranked:
            item["scale_coordinate_name"] = None
            item["scale_coordinate_value"] = None
            item["scale_ladder_rank"] = None
    accepted = [item for item in ranked if item.get("candidate_outcome") in ("stable_representative_candidate", "stable_candidate_mode", "stable_with_warnings")]
    removed = [item for item in ranked if item.get("candidate_outcome") not in ("stable_representative_candidate", "stable_candidate_mode", "stable_with_warnings")]

    _write_outputs(out_dir, run_summaries, group_summaries, matrix_cell_records, matrix_summaries, space_summary, ranked, accepted, removed, failed_runs)
    report = _top_report(
        cfg,
        out_dir,
        rows,
        groups,
        run_summaries,
        group_summaries,
        space_summary,
        failed_runs,
        omitted_runs,
        started,
        planned_group_count=planned_group_count,
    )
    report["segmentation_stack_path"] = str(segmentation_stack_path)
    report["segmentation_stack_source"] = segmentation_stack_source
    report["valid_mask_path"] = str(valid_mask_path)
    report["invalid_support_excluded_from_q_statistics"] = True
    report["perturbation_statuses"] = segmentation_reports
    report.update(scale_gate)
    _write_json(out_dir / OUTPUT_FILENAMES["report"], report)
    return report


def dominant_size_class(summary: dict[str, Any]) -> str:
    return max(SIZE_CLASSES, key=lambda cls: float(summary.get(f"{cls}_area_share", 0.0)))


def dominant_tail_regime(summary: dict[str, Any]) -> str:
    values = {
        "lower_tail": float(summary.get("lower_tail_area_share", 0.0)),
        "central": float(summary.get("central_area_share", 0.0)),
        "upper_tail": float(summary.get("upper_tail_area_share", 0.0)),
    }
    return max(values, key=values.get)


def stability_score_raw(summary: dict[str, Any]) -> float:
    score = 1.0
    score -= 0.35 * float(summary.get("edge_loaded_flag", False))
    score -= 0.35 * float(summary.get("scale_jump_flag", False))
    score -= 0.2 * float(summary.get("distribution_flutter_flag", False))
    score -= 0.2 * float(summary.get("spatial_scale_jump_flag", False))
    score += 0.5 * float(summary.get("central_area_share_mean", 0.0))
    score -= 0.1 * float(summary.get("response_spread_q", 0.0))
    return score


def stability_score(summary: dict[str, Any]) -> float:
    raw_score = float(summary["stability_score_raw"]) if "stability_score_raw" in summary else stability_score_raw(summary)
    return max(0.0, min(1.0, raw_score))


def classify_candidate_outcome(summary: dict[str, Any]) -> str:
    if summary.get("scale_jump_flag"):
        return "scale_jump_detected"
    if summary.get("spatial_scale_jump_flag"):
        return "unstable_spatial_response"
    if summary.get("distribution_flutter_flag") or summary.get("edge_loaded_flag"):
        return "unstable_distribution_response"
    if summary.get("centered") and float(summary.get("stability_score", 0.0)) >= 0.75:
        return "stable_representative_candidate"
    if summary.get("centered"):
        return "stable_with_warnings"
    return "unstable_distribution_response"


def decision_reasons(summary: dict[str, Any]) -> list[str]:
    reasons = [
        f"central_area_share_mean={summary.get('central_area_share_mean', 0.0):.6f}",
        f"response_spread_q={summary.get('response_spread_q', 0.0):.6f}",
        f"distribution_flutter_score={summary.get('distribution_flutter_score', 0.0):.6f}",
        f"matrix_distribution_distance={summary.get('matrix_distribution_distance', 0.0):.6f}",
        f"scale_jump_flag={summary.get('scale_jump_flag')}",
    ]
    return reasons


def stable_candidate_modes(stable_summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not stable_summaries:
        return []
    ordered = sorted(stable_summaries, key=lambda item: str(item["candidate_scale_group_id"]))
    return [
        {
            "mode_id": "stable_mode_001",
            "candidate_scale_group_ids": [str(item["candidate_scale_group_id"]) for item in ordered],
            "member_count": len(ordered),
            "mean_stability_score": _mean([float(item.get("stability_score", 0.0)) for item in ordered]),
        }
    ]


def isolated_outlier_candidates(group_summaries: list[dict[str, Any]], radii: list[float]) -> list[str]:
    if len(group_summaries) < 3 or not radii:
        return []
    q1 = _quantile(np.asarray(radii), 0.25)
    q3 = _quantile(np.asarray(radii), 0.75)
    iqr = q3 - q1
    return [
        str(item["candidate_scale_group_id"])
        for item in group_summaries
        if _finite_positive(item.get("response_center_q"))
        and (float(item["response_center_q"]) < q1 - 1.5 * iqr or float(item["response_center_q"]) > q3 + 1.5 * iqr)
    ]


def unstable_candidate_ranges(group_summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "candidate_scale_group_id": str(item["candidate_scale_group_id"]),
            "outcome": item.get("candidate_outcome"),
            "stability_score": item.get("stability_score"),
        }
        for item in group_summaries
        if str(item.get("candidate_outcome", "")).startswith("unstable") or item.get("scale_jump_flag")
    ]


def _run_or_reuse_segmentation(
    cfg: Level1BCandidateResponseSurfaceConfig,
    out_dir: Path,
    group_id: str,
    row: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    run_dir = out_dir / "segmentations" / _safe_name(group_id)
    artifact_paths = _run_artifact_paths(out_dir, group_id, run_id)
    expected_metadata = _expected_run_metadata(cfg, artifact_paths, group_id, row, run_id)
    run_artifacts_exist = _run_has_any_artifacts(artifact_paths)
    if not cfg.overwrite and _is_complete_run(artifact_paths, expected_metadata, group_id):
        report = json.loads(artifact_paths["report"].read_text(encoding="utf-8"))
        report["step9_run_status"] = "reused"
        return report
    segmentation_stack_path, segmentation_stack_source = resolve_segmentation_stack(cfg)
    segmentation_cfg = Level1BOneScaleSegmentationConfig(
        candidate_id=str(row.get("source_candidate_id", row.get("candidate_id", cfg.candidate_id))),
        output_dir=run_dir,
        feature_space_stack_path=segmentation_stack_path,
        segmentation_stack_path=segmentation_stack_path,
        segmentation_stack_source=segmentation_stack_source,
        valid_mask_path=resolve_valid_mask_path(cfg),
        perturbation_candidates_json_path=cfg.perturbation_candidates_json_path,
        perturbation_id=run_id,
        ram_mb=cfg.ram_mb,
        overwrite=cfg.overwrite or run_artifacts_exist,
        debug_command_output=cfg.debug_command_output,
    )
    report = run_one_scale_segmentation_smoke(segmentation_cfg)
    if report.get("status") != "ok":
        report["step9_run_status"] = "failed"
    elif run_artifacts_exist and not cfg.overwrite:
        report["step9_run_status"] = "recomputed_incomplete"
    else:
        report["step9_run_status"] = "computed"
    return report


def _run_artifact_paths(out_dir: Path, group_id: str, run_id: str) -> dict[str, Path]:
    run_path = out_dir / "segmentations" / _safe_name(group_id) / "level1b" / "segmentation_smoke" / run_id
    return {
        "labels": run_path / "merged_labels.tif",
        "report": run_path / "one_scale_segmentation_report.json",
        "segments_csv": run_path / "run_q_segments.csv",
        "summary_json": run_path / "run_q_summary.json",
        "summary_csv": run_path / "run_q_summary.csv",
    }


def _run_has_any_artifacts(paths: dict[str, Path]) -> bool:
    run_path = paths["labels"].parent
    return run_path.exists() and any(path.is_file() for path in run_path.rglob("*"))


def _expected_run_metadata(
    cfg: Level1BCandidateResponseSurfaceConfig,
    paths: dict[str, Path],
    group_id: str,
    row: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    stack_path, stack_source = resolve_segmentation_stack(cfg)
    return {
        "perturbation_id": run_id,
        "candidate_id": str(row.get("source_candidate_id", row.get("candidate_id", cfg.candidate_id))),
        "scale_id": str(row.get("scale_id", row.get("source_scale_id", group_id))),
        "radius_m": source_candidate_radius_m(row),
        "spatialr_px": int(row["spatialr_px"]),
        "minsize_px": int(row["minsize_px"]),
        "ranger": float(row["ranger"]),
        "segmentation_stack_path": str(stack_path),
        "segmentation_stack_source": stack_source,
        "valid_mask_path": str(resolve_valid_mask_path(cfg)),
        "masked_segmentation_stack_path": str(paths["labels"].parent / "masked_segmentation_stack.tif"),
        "pre_lsms_mask_applied": True,
        "post_mask_applied": True,
    }


def _metadata_matches(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    for key, expected_value in expected.items():
        actual_value = actual.get(key)
        if isinstance(expected_value, bool):
            if actual_value is not expected_value:
                return False
        elif isinstance(expected_value, (int, float)) and not isinstance(expected_value, bool):
            try:
                if not math.isclose(float(actual_value), float(expected_value), rel_tol=1e-12, abs_tol=1e-12):
                    return False
            except (TypeError, ValueError):
                return False
        elif str(actual_value) != str(expected_value):
            return False
    return True


def _summary_csv_matches_json(csv_row: dict[str, str], summary: dict[str, Any]) -> bool:
    if set(csv_row) != set(summary):
        return False
    for key, json_value in summary.items():
        csv_value = csv_row.get(key, "")
        if json_value is None:
            if csv_value != "":
                return False
        elif isinstance(json_value, bool):
            if csv_value.lower() != str(json_value).lower():
                return False
        elif isinstance(json_value, (int, float)) and not isinstance(json_value, bool):
            try:
                csv_number = float(csv_value)
                json_number = float(json_value)
                if not (math.isnan(csv_number) and math.isnan(json_number)) and not math.isclose(
                    csv_number, json_number, rel_tol=1e-12, abs_tol=1e-12
                ):
                    return False
            except (TypeError, ValueError):
                return False
        elif isinstance(json_value, (dict, list)):
            try:
                if json.loads(csv_value) != json_value:
                    return False
            except (TypeError, ValueError, json.JSONDecodeError):
                return False
        elif csv_value != str(json_value):
            return False
    return True


def _is_complete_run(paths: dict[str, Path], expected_metadata: dict[str, Any], group_id: str) -> bool:
    if any(not path.exists() or path.stat().st_size == 0 for path in paths.values()):
        return False
    try:
        report = json.loads(paths["report"].read_text(encoding="utf-8"))
        summary = json.loads(paths["summary_json"].read_text(encoding="utf-8"))
        with paths["segments_csv"].open(newline="", encoding="utf-8") as file_obj:
            segment_reader = csv.DictReader(file_obj)
            segment_rows = list(segment_reader)
            segment_fields = set(segment_reader.fieldnames or [])
        with paths["summary_csv"].open(newline="", encoding="utf-8") as file_obj:
            summary_rows = list(csv.DictReader(file_obj))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    required_segment_fields = {"scale_id", "candidate_id", "perturbation_id", "area_m2", "req_m", "q", "q_class"}
    run_id = str(expected_metadata["perturbation_id"])
    return bool(
        report.get("status") == "ok"
        and _metadata_matches(report, expected_metadata)
        and _metadata_matches(summary, expected_metadata)
        and summary.get("run_id") == run_id
        and summary.get("candidate_scale_group_id") == str(group_id)
        and int(summary.get("n_segments", -1)) == len(segment_rows)
        and len(summary_rows) == 1
        and _summary_csv_matches_json(summary_rows[0], summary)
        and required_segment_fields.issubset(segment_fields)
        and all(item.get("perturbation_id") == run_id for item in segment_rows)
        and str(report.get("output_artifacts", {}).get("merged_labels", "")) == str(paths["labels"])
    )


def label_classes_from_counts(
    counts: dict[str, Any],
    row: dict[str, Any],
    pixel_size_m: float,
    cfg: Level1BCandidateResponseSurfaceConfig,
) -> dict[int, str]:
    radii = equivalent_radii(counts["area_m2"])
    q = radii / source_candidate_radius_m(row)
    classes = assign_scale_relative_size_classes(q, cfg)
    return {int(label): str(cls) for label, cls in zip(counts["labels"], classes)}


def _apply_valid_mask_to_labels(labels: np.ndarray, valid_mask_path: str | Path) -> np.ndarray:
    mask = _read_label_raster(valid_mask_path)
    if mask.shape != labels.shape:
        raise ValueError("valid mask and label raster dimensions are incompatible")
    masked = np.asarray(labels).copy()
    masked[mask <= 0] = 0
    return masked


def _read_run_q_summary(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _write_incremental_run_q_statistics(
    out_dir: Path,
    group_id: str,
    run_id: str,
    row: dict[str, Any],
    labels: np.ndarray,
    pixel_size_m: float,
    cfg: Level1BCandidateResponseSurfaceConfig,
    run_summary: dict[str, Any],
) -> dict[str, Any]:
    counts = count_segment_sizes(labels, pixel_size_m)
    return _write_incremental_run_q_statistics_from_counts(out_dir, group_id, run_id, row, counts, pixel_size_m, cfg, run_summary)


def _write_incremental_run_q_statistics_from_counts(
    out_dir: Path,
    group_id: str,
    run_id: str,
    row: dict[str, Any],
    counts: dict[str, Any],
    pixel_size_m: float,
    cfg: Level1BCandidateResponseSurfaceConfig,
    run_summary: dict[str, Any],
) -> dict[str, Any]:
    req_m = equivalent_radii(counts["area_m2"])
    radius_m = source_candidate_radius_m(row)
    q_values = req_m / radius_m
    classes = assign_scale_relative_size_classes(q_values, cfg)
    common = {
        "scale_id": str(row.get("scale_id", row.get("source_scale_id", group_id))),
        "candidate_id": str(row.get("source_candidate_id", row.get("candidate_id", cfg.candidate_id))),
        "perturbation_id": run_id,
        "radius_m": radius_m,
        "spatialr_px": row.get("spatialr_px"),
        "minsize_px": row.get("minsize_px"),
        "ranger": row.get("ranger"),
    }
    paths = _run_artifact_paths(out_dir, group_id, run_id)
    expected_metadata = _expected_run_metadata(cfg, paths, group_id, row, run_id)
    segment_rows = [
        dict(common, label=int(label), area_m2=float(area), req_m=float(req), q=float(q_value), q_class=str(q_class))
        for label, area, req, q_value, q_class in zip(counts["labels"], counts["area_m2"], req_m, q_values, classes)
    ]
    n_segments = len(segment_rows)
    total_area = float(np.sum(counts["area_m2"]))
    summary = dict(run_summary)
    summary.update(common)
    summary.update(
        {
            "n_segments": n_segments,
            "q_p10": _quantile(q_values, 0.10),
            "q_p25": _quantile(q_values, 0.25),
            "q_median": _quantile(q_values, 0.50),
            "q_p75": _quantile(q_values, 0.75),
            "q_p90": _quantile(q_values, 0.90),
            "valid_mask_path": str(resolve_valid_mask_path(cfg)),
            "segmentation_stack_path": expected_metadata["segmentation_stack_path"],
            "segmentation_stack_source": expected_metadata["segmentation_stack_source"],
            "masked_segmentation_stack_path": expected_metadata["masked_segmentation_stack_path"],
            "pre_lsms_mask_applied": True,
            "post_mask_applied": True,
            "label_invalid_support_value": 0,
            "labels_postmasked": True,
            "invalid_support_excluded_from_q_statistics": True,
        }
    )
    for cls in SIZE_CLASSES:
        cls_mask = classes == cls
        summary[f"{cls}_frac_n"] = float(np.sum(cls_mask) / n_segments) if n_segments else 0.0
        summary[f"{cls}_frac_area"] = float(np.sum(counts["area_m2"][cls_mask]) / total_area) if total_area else 0.0
    segment_fields = [*common, "label", "area_m2", "req_m", "q", "q_class"]
    _write_csv(paths["segments_csv"], segment_rows, fieldnames=segment_fields)
    _write_json(paths["summary_json"], summary)
    _write_csv(paths["summary_csv"], [summary])
    return summary


def _read_label_raster(path: str | Path) -> np.ndarray:
    raise RuntimeError("Full-raster label reads are disabled in Step 9; use windowed helpers instead")


def _iter_windows(width: int, height: int, block_size: int = 1024):
    import rasterio
    from rasterio.windows import Window

    for row_off in range(0, height, block_size):
        win_height = min(block_size, height - row_off)
        for col_off in range(0, width, block_size):
            win_width = min(block_size, width - col_off)
            yield Window(col_off, row_off, win_width, win_height)


def _iter_masked_label_blocks(labels_path: str | Path, valid_mask_path: str | Path):
    import rasterio

    with rasterio.open(labels_path) as label_dataset, rasterio.open(valid_mask_path) as mask_dataset:
        _validate_raster_pair(label_dataset, mask_dataset, "valid mask and label raster dimensions are incompatible")
        for window in _iter_windows(label_dataset.width, label_dataset.height):
            labels = label_dataset.read(1, window=window)
            mask = mask_dataset.read(1, window=window)
            labels = np.asarray(labels).copy()
            labels[mask <= 0] = 0
            yield labels


def _validate_raster_pair(left, right, message: str) -> None:
    if left.width != right.width or left.height != right.height:
        raise ValueError(message)


def _pixel_size_m(path: str | Path) -> float:
    import rasterio

    with rasterio.open(path) as src:
        return float(abs(src.transform.a))


def _merged_labels_path(report: dict[str, Any]) -> str:
    artifacts = report.get("output_artifacts", {}) if isinstance(report, dict) else {}
    if isinstance(artifacts, dict) and artifacts.get("merged_labels"):
        return str(artifacts["merged_labels"])
    return str(report.get("merged_labels_path", "")) if isinstance(report, dict) else ""


def _write_outputs(
    out_dir: Path,
    run_summaries: list[dict[str, Any]],
    group_summaries: list[dict[str, Any]],
    matrix_cell_records: list[dict[str, Any]],
    matrix_summaries: list[dict[str, Any]],
    space_summary: dict[str, Any],
    ranked: list[dict[str, Any]],
    accepted: list[dict[str, Any]],
    removed: list[dict[str, Any]],
    failed_runs: list[dict[str, Any]],
) -> None:
    _write_csv(out_dir / OUTPUT_FILENAMES["run_population_csv"], run_summaries)
    _write_json(out_dir / OUTPUT_FILENAMES["run_population_json"], run_summaries)
    _write_csv(out_dir / OUTPUT_FILENAMES["group_csv"], group_summaries)
    _write_json(out_dir / OUTPUT_FILENAMES["group_json"], group_summaries)
    _write_csv(out_dir / OUTPUT_FILENAMES["matrix_csv"], matrix_cell_records)
    _write_json(out_dir / OUTPUT_FILENAMES["matrix_json"], matrix_cell_records)
    _write_csv(out_dir / OUTPUT_FILENAMES["spatial_csv"], matrix_summaries)
    _write_json(out_dir / OUTPUT_FILENAMES["spatial_json"], matrix_summaries)
    _write_csv(out_dir / OUTPUT_FILENAMES["space_csv"], [space_summary])
    _write_json(out_dir / OUTPUT_FILENAMES["space_json"], space_summary)
    _write_csv(out_dir / OUTPUT_FILENAMES["ranked_csv"], ranked)
    _write_json(out_dir / OUTPUT_FILENAMES["ranked_json"], ranked)
    _write_json(out_dir / OUTPUT_FILENAMES["representatives"], [item for item in ranked if item.get("medoid_run_id")])
    _write_json(out_dir / OUTPUT_FILENAMES["accepted"], accepted)
    _write_json(out_dir / OUTPUT_FILENAMES["removed"], removed)
    _write_json(out_dir / OUTPUT_FILENAMES["failed"], failed_runs)


def _top_report(
    cfg: Level1BCandidateResponseSurfaceConfig,
    out_dir: Path,
    rows: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    run_summaries: list[dict[str, Any]],
    group_summaries: list[dict[str, Any]],
    space_summary: dict[str, Any] | list[Any],
    failed_runs: list[dict[str, Any]],
    omitted_runs: list[dict[str, Any]],
    started: float,
    planned_group_count: int | None = None,
) -> dict[str, Any]:
    planned_runs = sum(len(group.get("rows", [])) for group in groups) + len(omitted_runs)
    segmentation_stack_path, segmentation_stack_source = resolve_segmentation_stack(cfg)
    valid_mask_path = resolve_valid_mask_path(cfg)
    return {
        "candidate_id": cfg.candidate_id,
        "status": "ok" if not any(item.get("status") == "failed" for item in failed_runs) else "partial",
        "active_step9": "candidate-scale response surface analysis",
        "not_segmentation_truth_assessment": True,
        "active_step9_does_not_run_full_hoover_by_default": True,
        "hoover_audit_run": bool(cfg.run_hoover_audit),
        "hoover_audit_note": (
            "Hoover audit support is disabled by default and not used by the active criterion."
            if not cfg.run_hoover_audit
            else "Hoover audit was requested, but the active response-surface criterion remains distributional and does not call Hoover by default."
        ),
        "input_paths": {
            "perturbation_candidates_json_path": str(cfg.perturbation_candidates_json_path),
            "feature_space_stack_path": str(cfg.feature_space_stack_path) if cfg.feature_space_stack_path else None,
            "segmentation_stack_path": str(segmentation_stack_path),
            "segmentation_stack_source": segmentation_stack_source,
            "valid_mask_path": str(valid_mask_path),
        },
        "config_values": _json_ready(asdict(cfg)),
        "thresholds": _thresholds(cfg),
        "diagnostic_class_definitions": {
            "micro": f"q < {cfg.micro_upper_ratio}",
            "small": f"{cfg.micro_upper_ratio} <= q < {cfg.small_upper_ratio}",
            "in_scale": f"{cfg.small_upper_ratio} <= q <= {cfg.in_scale_upper_ratio}",
            "large": f"{cfg.in_scale_upper_ratio} < q <= {cfg.large_upper_ratio}",
            "oversize": f"q > {cfg.large_upper_ratio}",
        },
        "analysis_cell_derivation": {
            "mode": cfg.analysis_cell_size_mode,
            "explicit_analysis_cell_size_m": cfg.analysis_cell_size_m,
            "formula": "max(analysis_cell_min_m, analysis_cell_size_factor * r_candidate_source, effective_structure_support_max_m if available), capped by analysis_cell_max_m",
        },
        "number_of_candidate_scale_groups": len(groups),
        "number_of_candidate_scale_groups_planned_before_limits": planned_group_count if planned_group_count is not None else len(groups),
        "number_of_planned_runs": planned_runs,
        "number_of_successful_runs": len(run_summaries),
        "number_of_failed_runs": len([item for item in failed_runs if item.get("status") == "failed"]),
        "number_of_omitted_runs_due_to_explicit_safety_limits": len(omitted_runs),
        "explicit_safety_limits_used": {
            "max_candidate_scale_groups": cfg.max_candidate_scale_groups,
            "max_runs_per_group": cfg.max_runs_per_group,
        },
        "run_level_summary_overview": _distribution_summary([float(item.get("central_area_share", 0.0)) for item in run_summaries]),
        "candidate_group_summary_overview": {
            "group_count": len(group_summaries),
            "outcomes": _value_counts([str(item.get("candidate_outcome", "")) for item in group_summaries]),
        },
        "full_candidate_space_summary": space_summary,
        "output_dir": str(out_dir),
        "required_outputs": {key: str(out_dir / filename) for key, filename in OUTPUT_FILENAMES.items()},
        "failed_runs": failed_runs,
        "omitted_runs": omitted_runs,
        "runtime_metadata": {"started_epoch": started, "finished_epoch": time.time(), "runtime_seconds": time.time() - started},
    }


def _thresholds(cfg: Level1BCandidateResponseSurfaceConfig) -> dict[str, Any]:
    keys = (
        "min_central_area_share",
        "max_lower_tail_area_share",
        "max_upper_tail_area_share",
        "max_edge_loaded_area_share",
        "max_response_spread_q",
        "max_response_skewness_abs",
        "max_distribution_flutter",
        "max_scale_jump_distance",
        "max_spatial_pattern_distance",
        "min_dominant_cell_class_agreement",
    )
    return {key: getattr(cfg, key) for key in keys}


def _omitted(row: dict[str, Any], group_id: str, reason: str) -> dict[str, Any]:
    return {
        "run_id": str(row.get("perturbation_id", row.get("_step8_row_index", ""))),
        "candidate_scale_group_id": group_id,
        "status": "omitted",
        "reason": reason,
        "row": row,
    }


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_ready(obj), indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(fieldnames or [])
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(_json_ready(value), sort_keys=True)
    if isinstance(value, Path):
        return str(value)
    return value


def _json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and math.isinf(value):
        return "inf"
    return value


def _json_bins(bins: tuple[float, ...]) -> list[Any]:
    return ["inf" if math.isinf(value) else value for value in bins]


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)


def _finite_positive(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def _mean(values: Any) -> float:
    arr = np.asarray(list(values), dtype=float)
    arr = arr[np.isfinite(arr)]
    return float(np.mean(arr)) if arr.size else 0.0


def _sd(values: list[float]) -> float:
    return float(statistics.stdev(values)) if len(values) > 1 else 0.0


def _range(values: list[float]) -> float:
    return float(max(values) - min(values)) if values else 0.0


def _quantile(values: Any, q: float) -> float:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    return float(np.quantile(arr, q)) if arr.size else 0.0


def _weighted_quantiles(values: Any, weights: Any, qs: tuple[float, ...]) -> dict[float, float]:
    if values is None:
        return {q: 0.0 for q in qs}
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    keep = np.isfinite(values) & np.isfinite(weights) & (weights >= 0)
    values = values[keep]
    weights = weights[keep]
    if values.size == 0 or float(np.sum(weights)) <= 0:
        return {q: 0.0 for q in qs}
    order = np.argsort(values)
    values = values[order]
    weights = weights[order]
    cdf = np.cumsum(weights) / float(np.sum(weights))
    return {q: float(values[np.searchsorted(cdf, q, side="left").clip(0, values.size - 1)]) for q in qs}


def _robust_skew(run_summaries: list[dict[str, Any]]) -> float:
    values = [
        float(item.get("area_weighted_q_q90", 0.0))
        + float(item.get("area_weighted_q_q10", 0.0))
        - 2.0 * float(item.get("area_weighted_q_median", 0.0))
        for item in run_summaries
    ]
    return _mean(values)


def _distribution_summary(values: list[float]) -> dict[str, float]:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    return {
        "count": int(arr.size),
        "min": float(np.min(arr)) if arr.size else 0.0,
        "q25": _quantile(arr, 0.25),
        "median": _quantile(arr, 0.5),
        "q75": _quantile(arr, 0.75),
        "max": float(np.max(arr)) if arr.size else 0.0,
    }


def _value_counts(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _dominant_tail_agreement(matrix_summaries: list[dict[str, Any]]) -> float:
    if not matrix_summaries:
        return 0.0
    distributions = np.asarray([item.get("dominant_tail_distribution", [0.0] * 3) for item in matrix_summaries], dtype=float)
    return float(np.max(np.mean(distributions, axis=0))) if len(distributions) else 0.0
