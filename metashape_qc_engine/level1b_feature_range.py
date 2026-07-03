from dataclasses import dataclass
import csv
import json
import math
from pathlib import Path

import numpy as np

from metashape_qc_engine.level1b_step_manifest import write_step_manifest


RASTER_SUFFIXES = {".tif", ".tiff", ".vrt", ".img", ".jp2"}
FEATURE_SPACE_SOURCES = {"scaled", "pca"}
RANGER_SOURCE = "knn_distance_half_sample_mode"
RANGER_SELECTION_METHOD = "half_sample_mode"
KNN_K_POLICY = "auto_hsm_plateau"
MIN_AUTO_KNN_K = 7
ASSIGNMENT_RULE = "all_scale_candidates_assigned_scene_half_sample_mode_ranger"
REQUIRED_SCALE_CANDIDATE_FIELDS = ("candidate_id", "radius_m", "area_m2", "spatialr_px", "minsize_px")
RANGER_FIELDS = (
    "ranger_id",
    "ranger_index",
    "ranger",
    "selection_method",
    "modal_interval_lower",
    "modal_interval_upper",
    "half_sample_iterations",
    "knn_k",
    "sample_n_requested",
    "sample_n_used",
    "distance_sample_n",
    "feature_space_source",
    "band_count",
    "ranger_source",
)
ASSIGNED_FIELDS = (
    "candidate_id",
    "scale_id",
    "radius_m",
    "area_m2",
    "spatialr_px",
    "minsize_px",
    "ranger_id",
    "ranger",
    "ranger_source",
    "assignment_rule",
)
RANGER_JSON_KEYS = (
    "candidate_id",
    "feature_space_stack_path",
    "valid_mask_path",
    "scale_candidates_json_path",
    "feature_space_source",
    "band_count",
    "sample_n_requested",
    "sample_n_used",
    "distance_sample_n",
    "knn_k_policy",
    "knn_k_candidates",
    "hsm_stability_rel_tol",
    "hsm_plateau_window",
    "selected_knn_k",
    "plateau_found",
    "selection_method",
    "distance_min",
    "distance_median",
    "distance_max",
    "modal_interval_lower",
    "modal_interval_upper",
    "half_sample_iterations",
    "hsm_ranger_curve",
    "hsm_plateau_windows",
    "ranger_source",
    "ranger_count",
    "ranger_candidates",
)
ASSIGNED_JSON_KEYS = (
    "candidate_id",
    "scale_candidates_json_path",
    "ranger_candidates_json_path",
    "assignment_rule",
    "scale_candidate_count",
    "ranger_candidate_count",
    "assigned_candidate_count",
    "candidates",
)
CHECK_KEYS = (
    "candidate_id_non_empty",
    "feature_space_stack_path_exists",
    "feature_space_stack_suffix_raster_like",
    "valid_mask_path_exists",
    "valid_mask_path_suffix_raster_like",
    "scale_candidates_json_path_exists",
    "scale_candidates_json_path_suffix_json",
    "feature_space_source_valid",
    "band_count_positive_integer",
    "sample_n_positive_integer",
    "knn_k_policy_valid",
    "knn_k_candidates_non_empty",
    "knn_k_candidates_valid",
    "knn_k_candidates_strictly_increasing",
    "sample_n_greater_than_max_knn_k",
    "hsm_stability_rel_tol_valid",
    "hsm_plateau_window_valid",
    "hsm_plateau_window_fits_candidates",
    "max_distance_sample_n_positive_integer",
    "max_distance_sample_n_greater_than_max_knn_k",
    "output_ranger_csv_path_available",
    "output_ranger_json_path_available",
    "output_assigned_csv_path_available",
    "output_assigned_json_path_available",
)


@dataclass
class Level1BFeatureRangeConfig:
    candidate_id: str
    output_dir: str | Path
    feature_space_stack_path: str | Path
    valid_mask_path: str | Path
    scale_candidates_json_path: str | Path
    feature_space_source: str
    band_count: int
    sample_n: int
    knn_k_policy: str
    knn_k_candidates: tuple[int, ...]
    hsm_stability_rel_tol: float
    hsm_plateau_window: int
    max_distance_sample_n: int
    seed: int = 1
    output_ranger_csv_filename: str = "ranger_candidates.csv"
    output_ranger_json_filename: str = "ranger_candidates.json"
    output_assigned_csv_filename: str = "scale_candidates_with_ranger.csv"
    output_assigned_json_filename: str = "scale_candidates_with_ranger.json"
    overwrite: bool = False


def build_level1b_feature_range_layout(output_dir) -> dict[str, Path]:
    level1b_dir = Path(output_dir) / "level1b"
    layout = {
        "ranger_dir": level1b_dir / "ranger",
        "tmp_ranger_dir": level1b_dir / "tmp" / "ranger",
    }
    for directory in layout.values():
        directory.mkdir(parents=True, exist_ok=True)
    return layout


def validate_feature_range_config(config, layout, apps=None) -> tuple[dict[str, bool], list[str]]:
    checks = {key: True for key in CHECK_KEYS}
    failure_reasons: list[str] = []
    feature_space_stack_path = Path(config.feature_space_stack_path)
    valid_mask_path = Path(config.valid_mask_path)
    scale_candidates_json_path = Path(config.scale_candidates_json_path)
    output_paths = {
        "output_ranger_csv_path_available": layout["ranger_dir"] / config.output_ranger_csv_filename,
        "output_ranger_json_path_available": layout["ranger_dir"] / config.output_ranger_json_filename,
        "output_assigned_csv_path_available": layout["ranger_dir"] / config.output_assigned_csv_filename,
        "output_assigned_json_path_available": layout["ranger_dir"] / config.output_assigned_json_filename,
    }

    if not str(config.candidate_id).strip():
        checks["candidate_id_non_empty"] = False
        failure_reasons.append("candidate_id is empty")
    if not feature_space_stack_path.exists():
        checks["feature_space_stack_path_exists"] = False
        failure_reasons.append("feature_space_stack_path does not exist")
    if feature_space_stack_path.suffix.lower() not in RASTER_SUFFIXES:
        checks["feature_space_stack_suffix_raster_like"] = False
        failure_reasons.append("feature_space_stack_path suffix must be one of .tif, .tiff, .vrt, .img, .jp2")
    if not valid_mask_path.exists():
        checks["valid_mask_path_exists"] = False
        failure_reasons.append("valid_mask_path does not exist")
    if valid_mask_path.suffix.lower() not in RASTER_SUFFIXES:
        checks["valid_mask_path_suffix_raster_like"] = False
        failure_reasons.append("valid_mask_path suffix must be one of .tif, .tiff, .vrt, .img, .jp2")
    if not scale_candidates_json_path.exists():
        checks["scale_candidates_json_path_exists"] = False
        failure_reasons.append("scale_candidates_json_path does not exist")
    if scale_candidates_json_path.suffix.lower() != ".json":
        checks["scale_candidates_json_path_suffix_json"] = False
        failure_reasons.append("scale_candidates_json_path suffix must be .json")
    if config.feature_space_source not in FEATURE_SPACE_SOURCES:
        checks["feature_space_source_valid"] = False
        failure_reasons.append("feature_space_source must be exactly scaled or pca")
    if not _is_positive_int(config.band_count):
        checks["band_count_positive_integer"] = False
        failure_reasons.append("band_count must be a positive integer")
    if not _is_positive_int(config.sample_n):
        checks["sample_n_positive_integer"] = False
        failure_reasons.append("sample_n must be a positive integer")

    if config.knn_k_policy != KNN_K_POLICY:
        checks["knn_k_policy_valid"] = False
        failure_reasons.append(f"knn_k_policy must be exactly {KNN_K_POLICY}")

    knn_k_candidates = (
        tuple(config.knn_k_candidates)
        if isinstance(config.knn_k_candidates, (list, tuple))
        else ()
    )
    if not knn_k_candidates:
        checks["knn_k_candidates_non_empty"] = False
        failure_reasons.append("knn_k_candidates must be non-empty")
    candidates_valid = bool(knn_k_candidates) and all(
        _is_positive_int(value) and value >= MIN_AUTO_KNN_K
        for value in knn_k_candidates
    )
    if knn_k_candidates and not candidates_valid:
        checks["knn_k_candidates_valid"] = False
        failure_reasons.append(
            f"knn_k_candidates must contain integers >= {MIN_AUTO_KNN_K}"
        )
    if candidates_valid and any(
        current <= previous
        for previous, current in zip(knn_k_candidates, knn_k_candidates[1:])
    ):
        checks["knn_k_candidates_strictly_increasing"] = False
        failure_reasons.append("knn_k_candidates must be strictly increasing")
    if candidates_valid and _is_positive_int(config.sample_n) and config.sample_n <= max(knn_k_candidates):
        checks["sample_n_greater_than_max_knn_k"] = False
        failure_reasons.append("sample_n must be greater than the largest knn_k candidate")

    if not _is_finite_number(config.hsm_stability_rel_tol) or not 0 < float(config.hsm_stability_rel_tol) <= 1:
        checks["hsm_stability_rel_tol_valid"] = False
        failure_reasons.append("hsm_stability_rel_tol must be finite and in (0, 1]")
    if not _is_positive_int(config.hsm_plateau_window) or config.hsm_plateau_window < 2:
        checks["hsm_plateau_window_valid"] = False
        failure_reasons.append("hsm_plateau_window must be an integer >= 2")
    elif knn_k_candidates and config.hsm_plateau_window > len(knn_k_candidates):
        checks["hsm_plateau_window_fits_candidates"] = False
        failure_reasons.append("hsm_plateau_window must not exceed the knn_k candidate count")

    if not _is_positive_int(config.max_distance_sample_n):
        checks["max_distance_sample_n_positive_integer"] = False
        failure_reasons.append("max_distance_sample_n must be a positive integer")
    elif candidates_valid and config.max_distance_sample_n <= max(knn_k_candidates):
        checks["max_distance_sample_n_greater_than_max_knn_k"] = False
        failure_reasons.append("max_distance_sample_n must be greater than the largest knn_k candidate")
    if not config.overwrite:
        for check_key, output_path in output_paths.items():
            if output_path.exists():
                checks[check_key] = False
                failure_reasons.append(f"{output_path.name} already exists and overwrite is false")

    return checks, failure_reasons


def _is_positive_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_finite_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def sample_valid_feature_vectors(config) -> tuple[np.ndarray, int]:
    feature_stack, valid_mask = read_feature_stack_and_mask(
        config.feature_space_stack_path,
        config.valid_mask_path,
        config.band_count,
    )
    if feature_stack.shape[0] < config.band_count:
        raise ValueError("feature_space_stack has fewer bands than configured band_count")
    feature_stack = feature_stack[: config.band_count]

    complete = valid_mask > 0
    complete &= np.all(np.isfinite(feature_stack), axis=0)
    vectors = np.moveaxis(feature_stack, 0, -1)[complete].astype(np.float64, copy=False)
    valid_count = int(vectors.shape[0])
    if valid_count == 0:
        return vectors.reshape(0, int(config.band_count)), valid_count
    if valid_count > config.sample_n:
        rng = np.random.default_rng(config.seed)
        selected = rng.choice(valid_count, size=config.sample_n, replace=False)
        vectors = vectors[selected]
    return vectors, valid_count


def read_feature_stack_and_mask(feature_space_stack_path, valid_mask_path, band_count: int) -> tuple[np.ndarray, np.ndarray]:
    try:
        return _read_feature_stack_and_mask_with_rasterio(feature_space_stack_path, valid_mask_path, band_count)
    except ImportError:
        return _read_feature_stack_and_mask_with_gdal(feature_space_stack_path, valid_mask_path, band_count)


def _read_feature_stack_and_mask_with_rasterio(feature_space_stack_path, valid_mask_path, band_count: int) -> tuple[np.ndarray, np.ndarray]:
    import rasterio

    with rasterio.open(feature_space_stack_path) as feature_dataset, rasterio.open(valid_mask_path) as mask_dataset:
        if feature_dataset.width != mask_dataset.width or feature_dataset.height != mask_dataset.height:
            raise ValueError("feature_space_stack and valid_mask dimensions are incompatible")
        if feature_dataset.count < band_count:
            raise ValueError("feature_space_stack has fewer bands than configured band_count")
        if mask_dataset.count < 1:
            raise ValueError("valid_mask has no bands")

        feature_stack = feature_dataset.read(indexes=list(range(1, band_count + 1)))
        valid_mask = mask_dataset.read(1)
    return feature_stack, valid_mask


def _read_feature_stack_and_mask_with_gdal(feature_space_stack_path, valid_mask_path, band_count: int) -> tuple[np.ndarray, np.ndarray]:
    from osgeo import gdal

    feature_dataset = gdal.Open(str(feature_space_stack_path), gdal.GA_ReadOnly)
    mask_dataset = gdal.Open(str(valid_mask_path), gdal.GA_ReadOnly)
    if feature_dataset is None:
        raise ValueError("feature_space_stack cannot be opened")
    if mask_dataset is None:
        raise ValueError("valid_mask cannot be opened")
    if feature_dataset.RasterXSize != mask_dataset.RasterXSize or feature_dataset.RasterYSize != mask_dataset.RasterYSize:
        raise ValueError("feature_space_stack and valid_mask dimensions are incompatible")
    if feature_dataset.RasterCount < band_count:
        raise ValueError("feature_space_stack has fewer bands than configured band_count")
    if mask_dataset.RasterCount < 1:
        raise ValueError("valid_mask has no bands")

    feature_stack = np.stack(
        [feature_dataset.GetRasterBand(index).ReadAsArray() for index in range(1, band_count + 1)],
        axis=0,
    )
    valid_mask = mask_dataset.GetRasterBand(1).ReadAsArray()
    return feature_stack, valid_mask


def subsample_for_distance(vectors: np.ndarray, max_distance_sample_n: int, seed: int) -> np.ndarray:
    if len(vectors) <= max_distance_sample_n:
        return vectors
    rng = np.random.default_rng(seed)
    selected = rng.choice(len(vectors), size=max_distance_sample_n, replace=False)
    return vectors[selected]


def compute_knn_distance_distributions(
    vectors,
    knn_k_candidates,
) -> dict[int, np.ndarray]:
    """Return one per-pixel kNN-distance distribution for every candidate k.

    The expensive pairwise distances are calculated once per row block. A
    single multi-index partition then exposes all requested neighbour ranks.
    This is methodologically important: every k is evaluated on the identical
    vector sample and differs only by neighbourhood order. The self-distance
    is replaced by infinity before partitioning, so k=1 means the nearest
    *other* valid feature vector.
    """
    vectors = np.asarray(vectors, dtype=np.float64)
    if vectors.ndim != 2:
        raise ValueError("feature vectors must be a two-dimensional array")
    candidates = tuple(knn_k_candidates)
    if not candidates or any(not _is_positive_int(value) for value in candidates):
        raise ValueError("knn_k candidates must be non-empty positive integers")
    if any(current <= previous for previous, current in zip(candidates, candidates[1:])):
        raise ValueError("knn_k candidates must be strictly increasing")
    if len(vectors) <= max(candidates):
        raise ValueError(
            "not enough valid feature vectors to compute the largest knn_k candidate"
        )
    if not np.all(np.isfinite(vectors)):
        raise ValueError("feature vectors must be finite")

    kth_indices = np.asarray([value - 1 for value in candidates], dtype=int)
    distributions = {
        value: np.empty(len(vectors), dtype=np.float64)
        for value in candidates
    }
    for start in range(0, len(vectors), 512):
        stop = min(start + 512, len(vectors))
        delta = vectors[start:stop, None, :] - vectors[None, :, :]
        distances = np.sqrt(np.sum(delta * delta, axis=2))
        row_indices = np.arange(start, stop)
        distances[np.arange(stop - start), row_indices] = np.inf
        partitioned = np.partition(distances, kth_indices, axis=1)
        for knn_k, kth_index in zip(candidates, kth_indices):
            distributions[knn_k][start:stop] = partitioned[:, kth_index]

    return distributions


def compute_knn_distances(vectors, knn_k: int) -> np.ndarray:
    return compute_knn_distance_distributions(vectors, (knn_k,))[knn_k]


def estimate_half_sample_mode(distances) -> dict[str, float | int | str]:
    """Estimate the dominant centre of a one-dimensional distribution.

    The shortest interval containing half of the remaining observations is
    selected repeatedly. Ties are resolved by the first interval in sorted
    order, which keeps the estimate deterministic.
    """
    values = np.asarray(distances, dtype=np.float64).reshape(-1)
    if values.size == 0:
        raise ValueError("kNN-distance distribution is empty")
    if not np.all(np.isfinite(values)):
        raise ValueError("kNN distances must be finite")
    if np.any(values < 0):
        raise ValueError("kNN distances must be non-negative")
    if not np.any(values > 0):
        raise ValueError("Feature Space has no finite positive distance variation")

    ordered = np.sort(values)
    distance_min = float(ordered[0])
    distance_median = float(np.median(ordered))
    distance_max = float(ordered[-1])
    modal_interval_lower = distance_min
    modal_interval_upper = distance_max
    iterations = 0
    current = ordered

    while current.size > 2:
        half_n = (current.size + 1) // 2
        widths = current[half_n - 1 :] - current[: current.size - half_n + 1]
        start = int(np.argmin(widths))
        current = current[start : start + half_n]
        iterations += 1
        if iterations == 1:
            modal_interval_lower = float(current[0])
            modal_interval_upper = float(current[-1])

    ranger = float(np.mean(current))
    if not math.isfinite(ranger):
        raise ValueError("derived Half-Sample Mode ranger must be finite")
    if ranger <= 0:
        raise ValueError("derived Half-Sample Mode ranger must be positive")

    return {
        "selection_method": RANGER_SELECTION_METHOD,
        "ranger": ranger,
        "distance_min": distance_min,
        "distance_median": distance_median,
        "distance_max": distance_max,
        "modal_interval_lower": modal_interval_lower,
        "modal_interval_upper": modal_interval_upper,
        "half_sample_iterations": iterations,
    }


def build_ranger_candidate_from_knn_distances(
    candidate_id: str,
    distances,
    knn_k: int,
    sample_n_requested: int,
    sample_n_used: int,
    distance_sample_n: int,
    feature_space_source: str,
    band_count: int,
) -> tuple[list[dict[str, object]], dict[str, float | int | str]]:
    diagnostics = estimate_half_sample_mode(distances)
    candidate = {
        "ranger_id": f"{str(candidate_id).strip()}_ranger_001",
        "ranger_index": 1,
        "ranger": diagnostics["ranger"],
        "selection_method": diagnostics["selection_method"],
        "modal_interval_lower": diagnostics["modal_interval_lower"],
        "modal_interval_upper": diagnostics["modal_interval_upper"],
        "half_sample_iterations": diagnostics["half_sample_iterations"],
        "knn_k": int(knn_k),
        "sample_n_requested": int(sample_n_requested),
        "sample_n_used": int(sample_n_used),
        "distance_sample_n": int(distance_sample_n),
        "feature_space_source": feature_space_source,
        "band_count": int(band_count),
        "ranger_source": RANGER_SOURCE,
    }
    return [candidate], diagnostics


def select_first_stable_hsm_plateau(
    hsm_ranger_curve,
    relative_tolerance: float,
    plateau_window: int,
) -> tuple[int | None, list[dict[str, object]]]:
    """Select the smallest k at the first stable HSM-ranger plateau.

    Stability is evaluated over consecutive configured k candidates, not over
    integer k values that were never requested. For each window the relative
    span is ``(max(ranger) - min(ranger)) / median(ranger)``. The first window
    at or below the configured tolerance is accepted and its smallest k is
    returned. Returning ``None`` is deliberate: callers must preserve the
    diagnostic curve and stop rather than substitute an arbitrary fixed k.
    """
    if plateau_window < 2:
        raise ValueError("hsm plateau window must contain at least two k candidates")
    if plateau_window > len(hsm_ranger_curve):
        raise ValueError("hsm plateau window exceeds the k-candidate curve")

    plateau_windows: list[dict[str, object]] = []
    selected_knn_k: int | None = None
    for start in range(0, len(hsm_ranger_curve) - plateau_window + 1):
        rows = hsm_ranger_curve[start : start + plateau_window]
        ranger_values = np.asarray([row["ranger"] for row in rows], dtype=np.float64)
        centre = float(np.median(ranger_values))
        relative_span = float((np.max(ranger_values) - np.min(ranger_values)) / centre)
        stable = relative_span <= float(relative_tolerance)
        window = {
            "window_index": start + 1,
            "knn_k_values": [int(row["knn_k"]) for row in rows],
            "ranger_values": [float(value) for value in ranger_values],
            "relative_span": relative_span,
            "relative_tolerance": float(relative_tolerance),
            "stable": stable,
        }
        plateau_windows.append(window)
        if selected_knn_k is None and stable:
            selected_knn_k = int(rows[0]["knn_k"])

    return selected_knn_k, plateau_windows


def derive_ranger_candidates(
    config,
    sampled_vectors,
) -> tuple[list[dict[str, object]], int, dict[str, object]]:
    """Run the pre-segmentation k diagnostic and build at most one ranger.

    Spatial baseline radii are intentionally absent from this function. It
    analyzes only valid scaled feature vectors, computes the k-to-HSM-ranger
    curve, and applies the plateau rule. A successful diagnostic returns one
    central ranger; the caller copies it to every already-defined spatial
    baseline. An unsuccessful diagnostic returns no ranger plus the complete
    curve/window evidence, with no fixed-k or tail-based fallback.
    """
    knn_k_candidates = tuple(config.knn_k_candidates)
    largest_knn_k = max(knn_k_candidates)
    if len(sampled_vectors) <= largest_knn_k:
        raise ValueError(
            "not enough valid feature vectors to compute the largest knn_k candidate"
        )
    distance_vectors = subsample_for_distance(
        sampled_vectors,
        config.max_distance_sample_n,
        config.seed,
    )
    if len(distance_vectors) <= largest_knn_k:
        raise ValueError(
            "not enough valid feature vectors to compute the largest knn_k candidate"
        )

    distance_distributions = compute_knn_distance_distributions(
        distance_vectors,
        knn_k_candidates,
    )
    hsm_ranger_curve: list[dict[str, object]] = []
    for knn_k in knn_k_candidates:
        row = {"knn_k": int(knn_k)}
        row.update(estimate_half_sample_mode(distance_distributions[knn_k]))
        hsm_ranger_curve.append(row)

    selected_knn_k, plateau_windows = select_first_stable_hsm_plateau(
        hsm_ranger_curve,
        config.hsm_stability_rel_tol,
        config.hsm_plateau_window,
    )
    diagnostics: dict[str, object] = {
        "knn_k_policy": config.knn_k_policy,
        "knn_k_candidates": [int(value) for value in knn_k_candidates],
        "hsm_stability_rel_tol": float(config.hsm_stability_rel_tol),
        "hsm_plateau_window": int(config.hsm_plateau_window),
        "selected_knn_k": selected_knn_k,
        "plateau_found": selected_knn_k is not None,
        "selection_method": RANGER_SELECTION_METHOD,
        "hsm_ranger_curve": hsm_ranger_curve,
        "hsm_plateau_windows": plateau_windows,
    }
    selected_diagnostics = next(
        (row for row in hsm_ranger_curve if row["knn_k"] == selected_knn_k),
        None,
    )
    for key in (
        "distance_min",
        "distance_median",
        "distance_max",
        "modal_interval_lower",
        "modal_interval_upper",
        "half_sample_iterations",
    ):
        diagnostics[key] = selected_diagnostics[key] if selected_diagnostics else None

    if selected_knn_k is None:
        return [], len(distance_vectors), diagnostics

    candidates, _ = build_ranger_candidate_from_knn_distances(
        candidate_id=config.candidate_id,
        distances=distance_distributions[selected_knn_k],
        knn_k=selected_knn_k,
        sample_n_requested=config.sample_n,
        sample_n_used=len(sampled_vectors),
        distance_sample_n=len(distance_vectors),
        feature_space_source=config.feature_space_source,
        band_count=config.band_count,
    )
    return candidates, len(distance_vectors), diagnostics


def read_scale_candidates(json_path) -> list[dict[str, object]]:
    with Path(json_path).open(encoding="utf-8") as file_obj:
        payload = json.load(file_obj)

    if "candidates" not in payload:
        raise ValueError("scale candidates are missing candidates")
    candidates = payload["candidates"]
    if not candidates:
        raise ValueError("scale candidates are empty")
    for index, candidate in enumerate(candidates, start=1):
        for field in REQUIRED_SCALE_CANDIDATE_FIELDS:
            if field not in candidate:
                raise ValueError(f"scale candidate {index} lacks {field}")
    return candidates


def assign_ranger_candidates_to_scale_candidates(scale_candidates, ranger_candidates) -> list[dict[str, object]]:
    if len(ranger_candidates) != 1:
        raise ValueError("exactly one scene-specific ranger candidate is required")
    ranger_candidate = ranger_candidates[0]
    assigned_candidates: list[dict[str, object]] = []
    for scale_candidate in scale_candidates:
        scale_id = scale_candidate.get("scale_id", scale_candidate["candidate_id"])
        assigned = dict(scale_candidate)
        assigned.update(
            {
                "candidate_id": scale_candidate["candidate_id"],
                "scale_id": scale_id,
                "ranger_id": ranger_candidate["ranger_id"],
                "ranger": ranger_candidate["ranger"],
                "ranger_source": ranger_candidate["ranger_source"],
                "assignment_rule": ASSIGNMENT_RULE,
            }
        )
        assigned_candidates.append(assigned)
    return assigned_candidates


def write_ranger_candidates_csv(candidates, csv_path) -> None:
    with Path(csv_path).open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=RANGER_FIELDS)
        writer.writeheader()
        writer.writerows({key: candidate[key] for key in RANGER_FIELDS} for candidate in candidates)


def write_ranger_candidates_json(config, candidates, sample_n_used, distance_sample_n, diagnostics, json_path) -> None:
    payload = {
        "candidate_id": str(config.candidate_id).strip(),
        "feature_space_stack_path": str(Path(config.feature_space_stack_path)),
        "valid_mask_path": str(Path(config.valid_mask_path)),
        "scale_candidates_json_path": str(Path(config.scale_candidates_json_path)),
        "feature_space_source": config.feature_space_source,
        "band_count": int(config.band_count),
        "sample_n_requested": int(config.sample_n),
        "sample_n_used": int(sample_n_used),
        "distance_sample_n": int(distance_sample_n),
        "knn_k_policy": config.knn_k_policy,
        "knn_k_candidates": [int(value) for value in config.knn_k_candidates],
        "hsm_stability_rel_tol": float(config.hsm_stability_rel_tol),
        "hsm_plateau_window": int(config.hsm_plateau_window),
        "selected_knn_k": diagnostics["selected_knn_k"],
        "plateau_found": diagnostics["plateau_found"],
        "selection_method": diagnostics["selection_method"],
        "distance_min": diagnostics["distance_min"],
        "distance_median": diagnostics["distance_median"],
        "distance_max": diagnostics["distance_max"],
        "modal_interval_lower": diagnostics["modal_interval_lower"],
        "modal_interval_upper": diagnostics["modal_interval_upper"],
        "half_sample_iterations": diagnostics["half_sample_iterations"],
        "hsm_ranger_curve": diagnostics["hsm_ranger_curve"],
        "hsm_plateau_windows": diagnostics["hsm_plateau_windows"],
        "ranger_source": RANGER_SOURCE,
        "ranger_count": len(candidates),
        "ranger_candidates": [{key: candidate[key] for key in RANGER_FIELDS} for candidate in candidates],
    }
    with Path(json_path).open("w", encoding="utf-8") as file_obj:
        json.dump({key: payload[key] for key in RANGER_JSON_KEYS}, file_obj, indent=2)


def write_assigned_candidates_csv(candidates, csv_path) -> None:
    extra_fields = [key for candidate in candidates for key in candidate if key not in ASSIGNED_FIELDS]
    fieldnames = list(ASSIGNED_FIELDS) + sorted(set(extra_fields))
    with Path(csv_path).open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(candidates)


def write_assigned_candidates_json(config, ranger_candidate_count, assigned_candidates, json_path) -> None:
    ranger_json_path = Path(config.output_dir) / "level1b" / "ranger" / config.output_ranger_json_filename
    payload = {
        "candidate_id": str(config.candidate_id).strip(),
        "scale_candidates_json_path": str(Path(config.scale_candidates_json_path)),
        "ranger_candidates_json_path": str(ranger_json_path),
        "assignment_rule": ASSIGNMENT_RULE,
        "scale_candidate_count": len(assigned_candidates),
        "ranger_candidate_count": int(ranger_candidate_count),
        "assigned_candidate_count": len(assigned_candidates),
        "candidates": assigned_candidates,
    }
    with Path(json_path).open("w", encoding="utf-8") as file_obj:
        json.dump({key: payload[key] for key in ASSIGNED_JSON_KEYS}, file_obj, indent=2)


def run_feature_range_assignment_step(config) -> dict[str, object]:
    layout = build_level1b_feature_range_layout(config.output_dir)
    checks, failure_reasons = validate_feature_range_config(config, layout)
    ranger_csv_path = layout["ranger_dir"] / config.output_ranger_csv_filename
    ranger_json_path = layout["ranger_dir"] / config.output_ranger_json_filename
    assigned_csv_path = layout["ranger_dir"] / config.output_assigned_csv_filename
    assigned_json_path = layout["ranger_dir"] / config.output_assigned_json_filename
    sampled_vector_count = 0
    valid_vector_count = 0
    distance_sample_n = 0
    ranger_count = 0
    scale_candidate_count = 0
    assigned_candidate_count = 0
    files_written: list[str] = []
    ranger_diagnostics: dict[str, object] = {}
    status = "failed"

    if not failure_reasons:
        try:
            sampled_vectors, valid_vector_count = sample_valid_feature_vectors(config)
            sampled_vector_count = len(sampled_vectors)
            ranger_candidates, distance_sample_n, ranger_diagnostics = derive_ranger_candidates(config, sampled_vectors)
            ranger_count = len(ranger_candidates)
            write_ranger_candidates_csv(ranger_candidates, ranger_csv_path)
            write_ranger_candidates_json(
                config,
                ranger_candidates,
                sampled_vector_count,
                distance_sample_n,
                ranger_diagnostics,
                ranger_json_path,
            )
            files_written = [str(ranger_csv_path), str(ranger_json_path)]
            # Preserve the complete pre-segmentation diagnostic before failing.
            # No scale assignment or perturbation input is written without a
            # stable plateau, and no historical fixed k is substituted.
            if not ranger_diagnostics["plateau_found"]:
                raise ValueError(
                    "no stable Half-Sample Mode plateau found for knn_k candidates"
                )
            scale_candidates = read_scale_candidates(config.scale_candidates_json_path)
            assigned_candidates = assign_ranger_candidates_to_scale_candidates(scale_candidates, ranger_candidates)
            write_assigned_candidates_csv(assigned_candidates, assigned_csv_path)
            write_assigned_candidates_json(config, len(ranger_candidates), assigned_candidates, assigned_json_path)
        except Exception as exc:
            failure_reasons.append(str(exc))
        else:
            scale_candidate_count = len(scale_candidates)
            assigned_candidate_count = len(assigned_candidates)
            files_written = [
                str(ranger_csv_path),
                str(ranger_json_path),
                str(assigned_csv_path),
                str(assigned_json_path),
            ]
            status = "ok"

    report = {
        "candidate_id": str(config.candidate_id).strip(),
        "output_dir": str(Path(config.output_dir)),
        "ranger_dir": str(layout["ranger_dir"]),
        "tmp_ranger_dir": str(layout["tmp_ranger_dir"]),
        "feature_space_stack_path": str(Path(config.feature_space_stack_path)),
        "valid_mask_path": str(Path(config.valid_mask_path)),
        "feature_space_source": config.feature_space_source,
        "scale_candidates_json_path": str(Path(config.scale_candidates_json_path)),
        "output_ranger_csv_path": str(ranger_csv_path),
        "output_ranger_json_path": str(ranger_json_path),
        "output_assigned_csv_path": str(assigned_csv_path),
        "output_assigned_json_path": str(assigned_json_path),
        "band_count": config.band_count,
        "sample_n_requested": config.sample_n,
        "sample_n_used": sampled_vector_count,
        "valid_vector_count": valid_vector_count,
        "distance_sample_n": distance_sample_n,
        "knn_k_policy": config.knn_k_policy,
        "knn_k_candidates": tuple(config.knn_k_candidates),
        "hsm_stability_rel_tol": config.hsm_stability_rel_tol,
        "hsm_plateau_window": config.hsm_plateau_window,
        "selected_knn_k": ranger_diagnostics.get("selected_knn_k"),
        "plateau_found": ranger_diagnostics.get("plateau_found", False),
        "selection_method": RANGER_SELECTION_METHOD,
        "ranger_diagnostics": ranger_diagnostics,
        "max_distance_sample_n": config.max_distance_sample_n,
        "ranger_source": RANGER_SOURCE,
        "assignment_rule": ASSIGNMENT_RULE,
        "checks": checks,
        "status": status,
        "failure_reasons": failure_reasons,
        "ranger_count": ranger_count,
        "scale_candidate_count": scale_candidate_count,
        "assigned_candidate_count": assigned_candidate_count,
        "files_written": files_written,
        "no_spatial_scale_candidates_created": True,
        "no_spatialr_or_minsize_modified": True,
        "no_ranger_grid_created": True,
        "no_segmentation_performed": True,
    }
    write_step_manifest(
        config.output_dir,
        step="feature_range",
        status=status,
        inputs={
            "feature_space_stack": config.feature_space_stack_path,
            "valid_mask": config.valid_mask_path,
            "scale_candidates_json": config.scale_candidates_json_path,
        },
        artifacts={
            "ranger_candidates_csv": ranger_csv_path,
            "ranger_candidates_json": ranger_json_path,
            "scale_candidates_with_ranger_csv": assigned_csv_path,
            "scale_candidates_with_ranger_json": assigned_json_path,
        },
        candidate_id=str(config.candidate_id).strip(),
    )
    return report
