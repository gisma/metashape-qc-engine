from __future__ import annotations

from dataclasses import dataclass
import csv
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from metashape_qc_engine.level1b.feature_range import (
    KNN_K_POLICY,
    derive_ranger_candidates,
    read_feature_stack_and_mask,
)
from metashape_qc_engine.level1b.step_manifest import write_step_manifest


PRESCREENING_METHOD = "multiband_variogram_sill_fraction_support"
VARIOGRAM_ESTIMATOR = "median_half_squared_euclidean_feature_distance"
RANGER_LEVEL_POLICY = "hsm_main_interval_lower_mode_upper"
COUPLING_RULE = (
    "candidate_radius_m_to_spatialr_px__"
    "domain_min_radius_m_to_common_technical_minsize_px"
)
PERTURBATION_RULE = "scene_adaptive_variogram_scale__hsm_main_interval_ranger"


@dataclass
class Level1BCandidatePrescreeningConfig:
    candidate_id: str
    output_dir: str | Path
    feature_space_stack_path: str | Path
    valid_mask_path: str | Path
    pixel_size_m: float
    band_count: int
    radius_min_m: float
    radius_max_m: float
    lag_count: int
    lag_spacing: str
    directions: tuple[tuple[int, int], ...]
    pair_sample_n_per_direction: int
    min_valid_pairs_per_direction: int
    sill_tail_fraction: float
    sill_fraction_targets: tuple[float, ...]
    stable_crossing_window: int
    plateau_rel_tol: float
    anisotropy_ratio_threshold: float
    candidate_budget: int
    seed_phase_offsets: tuple[tuple[float, float], ...]
    ranger_level_policy: str
    sample_n: int
    knn_k_policy: str
    knn_k_candidates: tuple[int, ...]
    hsm_stability_rel_tol: float
    hsm_plateau_window: int
    max_distance_sample_n: int
    seed: int
    overwrite: bool = False


    @property
    def feature_space_source(self) -> str:
        """Identify the scaled stack for the reused HSM ranger helper."""
        return "scaled"

def candidate_prescreening_output_dir(output_dir: str | Path) -> Path:
    path = Path(output_dir) / "level1b" / "candidate_pre_screening"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _finite_positive(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0
    )


def validate_candidate_prescreening_config(
    config: Level1BCandidatePrescreeningConfig,
) -> list[str]:
    failures: list[str] = []
    if not str(config.candidate_id).strip():
        failures.append("candidate_id is empty")
    for name in ("feature_space_stack_path", "valid_mask_path"):
        if not Path(getattr(config, name)).is_file():
            failures.append(f"{name} does not exist")
    if not _finite_positive(config.pixel_size_m):
        failures.append("pixel_size_m must be finite and > 0")
    if not isinstance(config.band_count, int) or isinstance(config.band_count, bool) or config.band_count < 1:
        failures.append("band_count must be a positive integer")
    if not _finite_positive(config.radius_min_m) or not _finite_positive(config.radius_max_m):
        failures.append("radius domain bounds must be finite and > 0")
    elif float(config.radius_min_m) >= float(config.radius_max_m):
        failures.append("radius_min_m must be smaller than radius_max_m")
    if not isinstance(config.lag_count, int) or config.lag_count < 2:
        failures.append("lag_count must be an integer >= 2")
    if config.lag_spacing != "logarithmic":
        failures.append("lag_spacing must be exactly logarithmic")
    if not config.directions or any(
        len(direction) != 2
        or not all(isinstance(value, int) and not isinstance(value, bool) for value in direction)
        or tuple(direction) == (0, 0)
        for direction in config.directions
    ):
        failures.append("directions must contain non-zero integer [x, y] offsets")
    for name in (
        "pair_sample_n_per_direction",
        "min_valid_pairs_per_direction",
        "stable_crossing_window",
        "candidate_budget",
        "sample_n",
        "max_distance_sample_n",
        "seed",
    ):
        value = getattr(config, name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            failures.append(f"{name} must be a positive integer")
    if config.min_valid_pairs_per_direction > config.pair_sample_n_per_direction:
        failures.append("min_valid_pairs_per_direction must not exceed pair_sample_n_per_direction")
    if not 0 < float(config.sill_tail_fraction) <= 1:
        failures.append("sill_tail_fraction must be in (0, 1]")
    targets = tuple(config.sill_fraction_targets)
    if (
        len(targets) < 2
        or any(not _finite_positive(value) or float(value) > 1 for value in targets)
        or any(current <= previous for previous, current in zip(targets, targets[1:]))
    ):
        failures.append("sill_fraction_targets must be strictly increasing values in (0, 1]")
    if config.stable_crossing_window > config.lag_count:
        failures.append("stable_crossing_window must not exceed lag_count")
    if not 0 < float(config.plateau_rel_tol) <= 1:
        failures.append("plateau_rel_tol must be in (0, 1]")
    if not _finite_positive(config.anisotropy_ratio_threshold) or float(config.anisotropy_ratio_threshold) < 1:
        failures.append("anisotropy_ratio_threshold must be finite and >= 1")
    phases = tuple(config.seed_phase_offsets)
    if (
        not phases
        or any(
            len(phase) != 2
            or any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                or not 0.0 <= float(value) < 1.0
                for value in phase
            )
            for phase in phases
        )
        or len({(float(phase[0]), float(phase[1])) for phase in phases}) != len(phases)
        or (0.0, 0.0) not in {
            (float(phase[0]), float(phase[1])) for phase in phases
        }
    ):
        failures.append(
            "seed_phase_offsets must contain unique [u, v] pairs in [0, 1) including [0, 0]"
        )
    if config.ranger_level_policy != RANGER_LEVEL_POLICY:
        failures.append(f"ranger_level_policy must be exactly {RANGER_LEVEL_POLICY}")
    if config.knn_k_policy != KNN_K_POLICY:
        failures.append(f"knn_k_policy must be exactly {KNN_K_POLICY}")
    if not config.knn_k_candidates:
        failures.append("knn_k_candidates must be non-empty")
    return failures


def build_logarithmic_lag_pixels(
    radius_min_m: float,
    radius_max_m: float,
    pixel_size_m: float,
    lag_count: int,
) -> list[int]:
    lower_px = max(1, int(math.ceil(float(radius_min_m) / float(pixel_size_m))))
    upper_px = max(lower_px, int(math.floor(float(radius_max_m) / float(pixel_size_m))))
    if upper_px <= lower_px:
        raise ValueError("radius domain contains fewer than two distinct pixel lags")
    raw = np.geomspace(lower_px, upper_px, int(lag_count))
    lags = sorted({int(round(value)) for value in raw})
    lags = [value for value in lags if lower_px <= value <= upper_px]
    if len(lags) < 2:
        raise ValueError("logarithmic lag policy produced fewer than two distinct pixel lags")
    return lags


def technical_minsize_from_radius_domain(
    radius_min_m: float,
    pixel_size_m: float,
) -> tuple[int, int, int]:
    """Return the common technical minsize derived from the domain floor.

    ``radius_min_m`` is the smallest admissible spatial radius. Its diameter
    defines a square pixel support used only to suppress spurious tiny
    regions. The result is independent of every materialized candidate
    radius, so larger candidates do not force progressively stronger merging.
    """
    minimum_radius_px = max(
        1,
        int(math.floor(float(radius_min_m) / float(pixel_size_m) + 0.5)),
    )
    minimum_diameter_px = 2 * minimum_radius_px
    minsize_px = minimum_diameter_px**2
    return minimum_radius_px, minimum_diameter_px, minsize_px


def _direction_offset(direction: tuple[int, int], lag_px: int) -> tuple[int, int]:
    x, y = direction
    norm = math.hypot(x, y)
    dx = int(round(lag_px * x / norm))
    dy = int(round(lag_px * y / norm))
    if dx == 0 and dy == 0:
        dx = 1 if x > 0 else -1 if x < 0 else 0
        dy = 1 if y > 0 else -1 if y < 0 else 0
    return dx, dy


def _sample_direction_semivariance(
    feature_stack: np.ndarray,
    complete: np.ndarray,
    dx: int,
    dy: int,
    sample_n: int,
    rng: np.random.Generator,
) -> np.ndarray:
    height, width = complete.shape
    x_low = max(0, -dx)
    x_high = min(width, width - dx)
    y_low = max(0, -dy)
    y_high = min(height, height - dy)
    if x_low >= x_high or y_low >= y_high:
        return np.empty(0, dtype=np.float64)

    samples: list[np.ndarray] = []
    collected = 0
    for _ in range(20):
        if collected >= sample_n:
            break
        draw_n = max(1024, 4 * (sample_n - collected))
        xs = rng.integers(x_low, x_high, size=draw_n)
        ys = rng.integers(y_low, y_high, size=draw_n)
        keep = complete[ys, xs] & complete[ys + dy, xs + dx]
        if not np.any(keep):
            continue
        xs = xs[keep]
        ys = ys[keep]
        remaining = sample_n - collected
        xs = xs[:remaining]
        ys = ys[:remaining]
        delta = (
            feature_stack[:, ys, xs].astype(np.float64, copy=False)
            - feature_stack[:, ys + dy, xs + dx].astype(np.float64, copy=False)
        )
        values = 0.5 * np.mean(delta * delta, axis=0)
        samples.append(values)
        collected += len(values)
    if not samples:
        return np.empty(0, dtype=np.float64)
    return np.concatenate(samples)[:sample_n]


def compute_multiband_variogram(
    feature_stack: np.ndarray,
    valid_mask: np.ndarray,
    config: Level1BCandidatePrescreeningConfig,
) -> list[dict[str, Any]]:
    feature_stack = np.asarray(feature_stack)
    valid_mask = np.asarray(valid_mask)
    if feature_stack.ndim != 3 or feature_stack.shape[0] < config.band_count:
        raise ValueError("feature stack has fewer bands than configured band_count")
    feature_stack = feature_stack[: config.band_count]
    if valid_mask.shape != feature_stack.shape[1:]:
        raise ValueError("feature stack and valid mask dimensions are incompatible")
    complete = (valid_mask > 0) & np.all(np.isfinite(feature_stack), axis=0)
    if not np.any(complete):
        raise ValueError("no valid complete feature vectors are available")

    lag_pixels = build_logarithmic_lag_pixels(
        config.radius_min_m,
        config.radius_max_m,
        config.pixel_size_m,
        config.lag_count,
    )
    rng = np.random.default_rng(config.seed)
    curve: list[dict[str, Any]] = []
    for lag_index, lag_px in enumerate(lag_pixels, start=1):
        direction_rows: list[dict[str, Any]] = []
        for direction in config.directions:
            dx, dy = _direction_offset(direction, lag_px)
            semivariances = _sample_direction_semivariance(
                feature_stack,
                complete,
                dx,
                dy,
                config.pair_sample_n_per_direction,
                rng,
            )
            if len(semivariances) < config.min_valid_pairs_per_direction:
                raise ValueError(
                    "insufficient valid pixel pairs for lag/direction "
                    f"lag_px={lag_px}, direction={direction}, count={len(semivariances)}"
                )
            direction_rows.append(
                {
                    "direction": [int(direction[0]), int(direction[1])],
                    "offset_px": [dx, dy],
                    "actual_distance_m": math.hypot(dx, dy) * float(config.pixel_size_m),
                    "pair_count": int(len(semivariances)),
                    "semivariance": float(np.median(semivariances)),
                }
            )
        curve.append(
            {
                "lag_index": lag_index,
                "lag_px": int(lag_px),
                "lag_m": float(lag_px) * float(config.pixel_size_m),
                "semivariance": float(np.median([row["semivariance"] for row in direction_rows])),
                "directional_semivariance": direction_rows,
            }
        )
    return curve


def estimate_variogram_sill(
    curve: list[dict[str, Any]],
    tail_fraction: float,
) -> tuple[float, int, float, bool]:
    tail_n = max(2, int(math.ceil(len(curve) * float(tail_fraction))))
    tail = np.asarray([row["semivariance"] for row in curve[-tail_n:]], dtype=np.float64)
    sill = float(np.median(tail))
    if not math.isfinite(sill) or sill <= 0:
        raise ValueError("estimated multiband variogram sill must be finite and positive")
    relative_span = float((np.max(tail) - np.min(tail)) / sill)
    return sill, tail_n, relative_span, False


def find_stable_sill_fraction_crossings(
    curve: list[dict[str, Any]],
    sill: float,
    targets: tuple[float, ...],
    window: int,
) -> list[dict[str, Any]]:
    values = np.asarray([row["semivariance"] for row in curve], dtype=np.float64)
    results: list[dict[str, Any]] = []
    for target in targets:
        threshold = float(target) * float(sill)
        crossing_index: int | None = None
        for index in range(0, len(curve) - window + 1):
            if np.all(values[index : index + window] >= threshold):
                crossing_index = index
                break
        row: dict[str, Any] = {
            "sill_fraction_target": float(target),
            "threshold_semivariance": threshold,
            "stable_crossing_found": crossing_index is not None,
            "stable_crossing_window": int(window),
        }
        if crossing_index is not None:
            row.update(
                {
                    "curve_index": crossing_index,
                    "lag_px": int(curve[crossing_index]["lag_px"]),
                    "radius_m": float(curve[crossing_index]["lag_m"]),
                    "semivariance": float(curve[crossing_index]["semivariance"]),
                    "normalized_semivariance": float(curve[crossing_index]["semivariance"]) / sill,
                }
            )
        results.append(row)
    return results


def _variogram_diagnostics(
    curve: list[dict[str, Any]],
    sill: float,
    config: Level1BCandidatePrescreeningConfig,
) -> dict[str, Any]:
    x = np.log(np.asarray([row["lag_m"] for row in curve], dtype=np.float64))
    x = (x - x[0]) / (x[-1] - x[0])
    y = np.asarray([row["semivariance"] / sill for row in curve], dtype=np.float64)
    y_span = float(np.max(y) - np.min(y))
    y_unit = (y - np.min(y)) / y_span if y_span > 0 else np.zeros_like(y)
    knee_index = int(np.argmax(y_unit - x))

    directional_ranges: list[dict[str, Any]] = []
    for direction_index, direction in enumerate(config.directions):
        direction_curve = [
            {
                "lag_px": row["lag_px"],
                "lag_m": row["lag_m"],
                "semivariance": row["directional_semivariance"][direction_index]["semivariance"],
            }
            for row in curve
        ]
        direction_sill, _, _, _ = estimate_variogram_sill(
            direction_curve,
            config.sill_tail_fraction,
        )
        crossing = find_stable_sill_fraction_crossings(
            direction_curve,
            direction_sill,
            (0.95,),
            config.stable_crossing_window,
        )[0]
        directional_ranges.append(
            {
                "direction": [int(direction[0]), int(direction[1])],
                "sill": direction_sill,
                "range_95_m": crossing.get("radius_m"),
                "range_95_found": crossing["stable_crossing_found"],
            }
        )
    ranges = [float(row["range_95_m"]) for row in directional_ranges if row["range_95_m"] is not None]
    anisotropy_ratio = max(ranges) / min(ranges) if len(ranges) >= 2 else None
    return {
        "knee_lag_px": int(curve[knee_index]["lag_px"]),
        "knee_radius_m": float(curve[knee_index]["lag_m"]),
        "directional_ranges": directional_ranges,
        "directional_range_ratio": anisotropy_ratio,
        "directional_anisotropy_present": (
            anisotropy_ratio is not None
            and anisotropy_ratio >= float(config.anisotropy_ratio_threshold)
        ),
    }


def _ranger_levels(
    ranger_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(ranger_candidates) != 1:
        raise ValueError("pre-screening requires exactly one selected HSM ranger")
    source = ranger_candidates[0]
    centre = float(source["ranger"])
    proposed = [
        ("mode", centre, True),
        ("main_interval_lower", float(source["modal_interval_lower"]), False),
        ("main_interval_upper", float(source["modal_interval_upper"]), False),
    ]
    levels: list[dict[str, Any]] = []
    seen: set[float] = set()
    for position, value, is_baseline in proposed:
        if not math.isfinite(value) or value <= 0:
            continue
        key = round(value, 15)
        if key in seen:
            continue
        seen.add(key)
        levels.append(
            {
                "ranger_position": position,
                "ranger": value,
                "is_baseline": is_baseline,
            }
        )
    if not levels or sum(1 for row in levels if row["is_baseline"]) != 1:
        raise ValueError("HSM ranger policy did not produce one central baseline")
    return levels


def materialize_candidate_population(
    config: Level1BCandidatePrescreeningConfig,
    crossings: list[dict[str, Any]],
    ranger_levels: list[dict[str, Any]],
    diagnostics: dict[str, Any],
) -> list[dict[str, Any]]:
    reached = [row for row in crossings if row["stable_crossing_found"]]
    by_lag: dict[int, list[dict[str, Any]]] = {}
    for row in reached:
        by_lag.setdefault(int(row["lag_px"]), []).append(row)
    if len(by_lag) < 2:
        raise ValueError("fewer than two distinct stable sill-fraction scale candidates were found")
    phases = [
        {
            "seed_realization_id": f"phase_{index:02d}",
            "seed_phase_u": float(offset[0]),
            "seed_phase_v": float(offset[1]),
            "seed_realization_is_reference": index == 0,
        }
        for index, offset in enumerate(config.seed_phase_offsets)
    ]
    planned_count = len(by_lag) * len(ranger_levels) * len(phases)
    if planned_count > config.candidate_budget:
        raise ValueError(
            f"candidate budget {config.candidate_budget} is smaller than planned population {planned_count}"
        )

    (
        technical_minsize_radius_px,
        technical_minsize_diameter_px,
        common_minsize_px,
    ) = technical_minsize_from_radius_domain(
        config.radius_min_m,
        config.pixel_size_m,
    )

    candidates: list[dict[str, Any]] = []
    for scale_index, (lag_px, support_rows) in enumerate(sorted(by_lag.items()), start=1):
        scale_id = f"scale_{scale_index:03d}"
        radius_m = float(support_rows[0]["radius_m"])
        area_m2 = math.pi * radius_m**2
        source_candidate_id = f"{config.candidate_id}__{scale_id}"
        targets = [float(row["sill_fraction_target"]) for row in support_rows]
        for ranger_index, ranger_level in enumerate(ranger_levels, start=1):
            ranger = float(ranger_level["ranger"])
            for phase in phases:
                is_baseline = bool(ranger_level["is_baseline"]) and bool(
                    phase["seed_realization_is_reference"]
                )
                run_id = (
                    f"{source_candidate_id}__ranger_{ranger_index:03d}__"
                    f"{phase['seed_realization_id']}"
                )
                candidates.append(
                    {
                        "candidate_id": run_id,
                        "perturbation_id": run_id,
                        "source_candidate_id": source_candidate_id,
                        "candidate_scale_group_id": scale_id,
                        "scale_id": scale_id,
                        "scale_index": scale_index,
                        "spatialr_px": int(lag_px),
                        "minsize_px": int(common_minsize_px),
                        "ranger": ranger,
                        "deltas": {
                            "spatialr_px_delta": 0,
                            "minsize_px_delta": 0,
                            "ranger_delta": ranger - float(ranger_levels[0]["ranger"]),
                            "minsize_delta_fraction": 0.0,
                            "ranger_delta_fraction": ranger
                            / float(ranger_levels[0]["ranger"])
                            - 1.0,
                            "seed_phase_u_delta": float(phase["seed_phase_u"]),
                            "seed_phase_v_delta": float(phase["seed_phase_v"]),
                        },
                        "is_baseline": is_baseline,
                        "perturbation_rule": PERTURBATION_RULE,
                        "radius_m": radius_m,
                        "source_candidate_radius_m": radius_m,
                        "area_m2": area_m2,
                        "pixel_size_m": float(config.pixel_size_m),
                        "pixel_area_m2": float(config.pixel_size_m) ** 2,
                        "technical_minsize_source_radius_m": float(
                            config.radius_min_m
                        ),
                        "technical_minsize_radius_px": int(
                            technical_minsize_radius_px
                        ),
                        "technical_minsize_diameter_px": int(
                            technical_minsize_diameter_px
                        ),
                        "coupling_rule": COUPLING_RULE,
                        "scale_source": PRESCREENING_METHOD,
                        "sill_fraction_targets": targets,
                        "primary_sill_fraction_target": min(targets),
                        "ranger_position": ranger_level["ranger_position"],
                        **phase,
                        "near_variogram_knee": int(lag_px)
                        == int(diagnostics["knee_lag_px"]),
                        "in_variogram_saturation_region": max(targets) >= 0.95,
                        "directional_anisotropy_present": diagnostics[
                            "directional_anisotropy_present"
                        ],
                    }
                )
    return candidates


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        for source in rows:
            row = dict(source)
            for key, value in row.items():
                if isinstance(value, (dict, list, tuple)):
                    row[key] = json.dumps(value, sort_keys=True, separators=(",", ":"))
            writer.writerow(row)


def run_candidate_prescreening_step(
    config: Level1BCandidatePrescreeningConfig,
) -> dict[str, Any]:
    output_dir = candidate_prescreening_output_dir(config.output_dir)
    candidate_json = output_dir / "candidate_population.json"
    candidate_csv = output_dir / "candidate_population.csv"
    variogram_json = output_dir / "variogram_diagnostics.json"
    variogram_csv = output_dir / "variogram_curve.csv"
    report_json = output_dir / "candidate_pre_screening_report.json"
    failures = validate_candidate_prescreening_config(config)
    if not config.overwrite:
        for path in (candidate_json, candidate_csv, variogram_json, variogram_csv, report_json):
            if path.exists():
                failures.append(f"{path.name} already exists and overwrite is false")

    curve: list[dict[str, Any]] = []
    crossings: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    ranger_diagnostics: dict[str, Any] = {}
    variogram_diagnostics: dict[str, Any] = {}
    valid_vector_count = 0
    if not failures:
        try:
            feature_stack, valid_mask = read_feature_stack_and_mask(
                config.feature_space_stack_path,
                config.valid_mask_path,
                config.band_count,
            )
            complete = (valid_mask > 0) & np.all(np.isfinite(feature_stack[: config.band_count]), axis=0)
            valid_vector_count = int(np.count_nonzero(complete))
            curve = compute_multiband_variogram(feature_stack, valid_mask, config)
            sill, tail_n, tail_relative_span, _ = estimate_variogram_sill(
                curve,
                config.sill_tail_fraction,
            )
            plateau_detected = tail_relative_span <= float(config.plateau_rel_tol)
            crossings = find_stable_sill_fraction_crossings(
                curve,
                sill,
                config.sill_fraction_targets,
                config.stable_crossing_window,
            )
            variogram_diagnostics = _variogram_diagnostics(curve, sill, config)
            variogram_diagnostics.update(
                {
                    "method": PRESCREENING_METHOD,
                    "estimator": VARIOGRAM_ESTIMATOR,
                    "sill": sill,
                    "sill_tail_count": tail_n,
                    "sill_tail_fraction": float(config.sill_tail_fraction),
                    "tail_relative_span": tail_relative_span,
                    "plateau_rel_tol": float(config.plateau_rel_tol),
                    "plateau_detected": plateau_detected,
                    "crossings": crossings,
                    "curve": curve,
                }
            )

            _write_json(variogram_json, variogram_diagnostics)
            _write_rows_csv(
                variogram_csv,
                [
                    {
                        "lag_index": row["lag_index"],
                        "lag_px": row["lag_px"],
                        "lag_m": row["lag_m"],
                        "semivariance": row["semivariance"],
                    }
                    for row in curve
                ],
            )

            sampled_vectors = np.moveaxis(feature_stack[: config.band_count], 0, -1)[complete].astype(np.float64, copy=False)
            if len(sampled_vectors) > config.sample_n:
                rng = np.random.default_rng(config.seed)
                sampled_vectors = sampled_vectors[
                    rng.choice(len(sampled_vectors), size=config.sample_n, replace=False)
                ]
            ranger_candidates, distance_sample_n, ranger_diagnostics = derive_ranger_candidates(
                config,
                sampled_vectors,
            )
            ranger_diagnostics["sample_n_used"] = len(sampled_vectors)
            ranger_diagnostics["distance_sample_n"] = distance_sample_n
            ranger_levels = _ranger_levels(ranger_candidates)
            candidates = materialize_candidate_population(
                config,
                crossings,
                ranger_levels,
                variogram_diagnostics,
            )
            candidate_payload = {
                "candidate_id": config.candidate_id,
                "method": PRESCREENING_METHOD,
                "feature_space_stack_path": str(config.feature_space_stack_path),
                "valid_mask_path": str(config.valid_mask_path),
                "radius_domain_m": [float(config.radius_min_m), float(config.radius_max_m)],
                "candidate_budget": int(config.candidate_budget),
                "ranger_selection_status": ranger_diagnostics.get("ranger_selection_status", "stable_plateau"),
                "ranger_selection_warning": ranger_diagnostics.get("ranger_selection_warning"),
                "scale_family_count": len({row["candidate_scale_group_id"] for row in candidates}),
                "candidate_count": len(candidates),
                "no_segmentation_performed": True,
                "no_ranking_performed": True,
                "no_final_selection_performed": True,
                "candidates": candidates,
            }
            _write_json(candidate_json, candidate_payload)
            _write_rows_csv(candidate_csv, candidates)
        except Exception as exc:
            failures.append(str(exc))

    status = "failed" if failures else "ok"
    report = {
        "status": status,
        "candidate_id": config.candidate_id,
        "method": PRESCREENING_METHOD,
        "feature_space_stack_path": str(config.feature_space_stack_path),
        "valid_mask_path": str(config.valid_mask_path),
        "pixel_size_m": float(config.pixel_size_m),
        "band_count": int(config.band_count),
        "radius_domain_m": [float(config.radius_min_m), float(config.radius_max_m)],
        "valid_vector_count": valid_vector_count,
        "lag_count_requested": int(config.lag_count),
        "lag_count_used": len(curve),
        "sill_fraction_targets": [float(value) for value in config.sill_fraction_targets],
        "stable_crossing_count": sum(1 for row in crossings if row.get("stable_crossing_found")),
        "scale_family_count": len({row["candidate_scale_group_id"] for row in candidates}),
        "candidate_count": len(candidates),
        "candidate_budget": int(config.candidate_budget),
        "ranger_level_policy": config.ranger_level_policy,
        "ranger_diagnostics": ranger_diagnostics,
        "variogram_diagnostics_path": str(variogram_json),
        "candidate_population_json": str(candidate_json),
        "candidate_population_csv": str(candidate_csv),
        "failure_reasons": failures,
        "warnings": ([ranger_diagnostics["ranger_selection_warning"]] if ranger_diagnostics.get("ranger_selection_warning") else []),
        "no_segmentation_performed": True,
        "no_ranking_performed": True,
        "no_final_selection_performed": True,
    }
    _write_json(report_json, report)
    artifacts: dict[str, Path] = {"report": report_json}
    if variogram_json.exists() and variogram_csv.exists():
        artifacts.update(
            {
                "variogram_diagnostics_json": variogram_json,
                "variogram_curve_csv": variogram_csv,
            }
        )
    if not failures:
        artifacts.update(
            {
                "candidate_population_json": candidate_json,
                "candidate_population_csv": candidate_csv,
            }
        )
    manifest = write_step_manifest(
        config.output_dir,
        step="candidate_pre_screening",
        status=status,
        inputs={
            "feature_space_stack": config.feature_space_stack_path,
            "valid_mask": config.valid_mask_path,
        },
        artifacts=artifacts,
        candidate_id=config.candidate_id,
    )
    report["manifest"] = str(manifest)
    return report
