from dataclasses import dataclass
import csv
import json
import math
from pathlib import Path

import numpy as np


RASTER_SUFFIXES = {".tif", ".tiff", ".vrt", ".img", ".jp2"}
FEATURE_SPACE_SOURCES = {"scaled", "pca"}
RANGER_SOURCE = "knn_distance_quantile"
ASSIGNMENT_RULE = "ordered_scale_candidates_assigned_ordered_knn_distance_quantiles_with_tail_padding"
REQUIRED_SCALE_CANDIDATE_FIELDS = ("candidate_id", "radius_m", "area_m2", "spatialr_px", "minsize_px")
RANGER_FIELDS = (
    "ranger_id",
    "ranger_index",
    "ranger",
    "quantile_prob",
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
    "knn_k",
    "quantile_probs",
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
    "knn_k_positive_integer",
    "quantile_probs_non_empty",
    "quantile_probs_in_range",
    "max_distance_sample_n_positive_integer",
    "max_distance_sample_n_greater_than_knn_k",
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
    sample_n: int = 50000
    knn_k: int = 10
    quantile_probs: tuple[float, ...] = (0.25, 0.5, 0.75, 0.9)
    seed: int = 1
    max_distance_sample_n: int = 8000
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
    if not _is_positive_int(config.knn_k):
        checks["knn_k_positive_integer"] = False
        failure_reasons.append("knn_k must be a positive integer")
    if not _quantile_probs(config.quantile_probs):
        checks["quantile_probs_non_empty"] = False
        failure_reasons.append("quantile_probs must be non-empty")
    elif any(not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0 or value > 1 for value in config.quantile_probs):
        checks["quantile_probs_in_range"] = False
        failure_reasons.append("quantile_probs values must be in [0, 1]")
    if not _is_positive_int(config.max_distance_sample_n):
        checks["max_distance_sample_n_positive_integer"] = False
        failure_reasons.append("max_distance_sample_n must be a positive integer")
    elif _is_positive_int(config.knn_k) and config.max_distance_sample_n <= config.knn_k:
        checks["max_distance_sample_n_greater_than_knn_k"] = False
        failure_reasons.append("max_distance_sample_n must be greater than knn_k")
    if not config.overwrite:
        for check_key, output_path in output_paths.items():
            if output_path.exists():
                checks[check_key] = False
                failure_reasons.append(f"{output_path.name} already exists and overwrite is false")

    return checks, failure_reasons


def _is_positive_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _quantile_probs(values) -> tuple[float, ...]:
    if values is None:
        return ()
    return tuple(values)


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


def compute_knn_distances(vectors, knn_k: int) -> np.ndarray:
    vectors = np.asarray(vectors, dtype=np.float64)
    if vectors.ndim != 2:
        raise ValueError("feature vectors must be a two-dimensional array")
    if len(vectors) <= knn_k:
        raise ValueError("not enough valid feature vectors to compute knn_k nearest-neighbor distances")
    if not np.all(np.isfinite(vectors)):
        raise ValueError("feature vectors must be finite")

    kth_distances = np.empty(len(vectors), dtype=np.float64)
    for start in range(0, len(vectors), 512):
        stop = min(start + 512, len(vectors))
        delta = vectors[start:stop, None, :] - vectors[None, :, :]
        distances = np.sqrt(np.sum(delta * delta, axis=2))
        row_indices = np.arange(start, stop)
        distances[np.arange(stop - start), row_indices] = np.inf
        kth_distances[start:stop] = np.partition(distances, knn_k - 1, axis=1)[:, knn_k - 1]

    return kth_distances


def build_ranger_candidates_from_knn_distances(
    candidate_id: str,
    distances,
    quantile_probs,
    knn_k: int,
    sample_n_requested: int,
    sample_n_used: int,
    distance_sample_n: int,
    feature_space_source: str,
    band_count: int,
) -> list[dict[str, object]]:
    distances = np.asarray(distances, dtype=np.float64)
    if distances.size == 0:
        raise ValueError("kNN-distance distribution is empty")
    if not np.all(np.isfinite(distances)):
        raise ValueError("derived ranger values must be finite")
    if not np.any(distances > 0):
        raise ValueError("Feature Space has no finite positive distance variation")

    candidates: list[dict[str, object]] = []
    for ranger_index, quantile_prob in enumerate(tuple(quantile_probs), start=1):
        ranger = float(np.quantile(distances, float(quantile_prob)))
        if not math.isfinite(ranger):
            raise ValueError("derived ranger values must be finite")
        if ranger <= 0:
            raise ValueError("derived ranger values must be positive")
        candidates.append(
            {
                "ranger_id": f"{str(candidate_id).strip()}_ranger_{ranger_index:03d}",
                "ranger_index": ranger_index,
                "ranger": ranger,
                "quantile_prob": float(quantile_prob),
                "knn_k": int(knn_k),
                "sample_n_requested": int(sample_n_requested),
                "sample_n_used": int(sample_n_used),
                "distance_sample_n": int(distance_sample_n),
                "feature_space_source": feature_space_source,
                "band_count": int(band_count),
                "ranger_source": RANGER_SOURCE,
            }
        )
    return candidates


def derive_ranger_candidates(config, sampled_vectors) -> tuple[list[dict[str, object]], int]:
    if len(sampled_vectors) <= config.knn_k:
        raise ValueError("not enough valid feature vectors to compute knn_k nearest-neighbor distances")
    distance_vectors = subsample_for_distance(sampled_vectors, config.max_distance_sample_n, config.seed)
    if len(distance_vectors) <= config.knn_k:
        raise ValueError("not enough valid feature vectors to compute knn_k nearest-neighbor distances")
    distances = compute_knn_distances(distance_vectors, config.knn_k)
    candidates = build_ranger_candidates_from_knn_distances(
        candidate_id=config.candidate_id,
        distances=distances,
        quantile_probs=config.quantile_probs,
        knn_k=config.knn_k,
        sample_n_requested=config.sample_n,
        sample_n_used=len(sampled_vectors),
        distance_sample_n=len(distance_vectors),
        feature_space_source=config.feature_space_source,
        band_count=config.band_count,
    )
    return candidates, len(distance_vectors)


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
    if not ranger_candidates:
        raise ValueError("ranger candidates are empty")
    assigned_candidates: list[dict[str, object]] = []
    for index, scale_candidate in enumerate(scale_candidates):
        ranger_candidate = ranger_candidates[min(index, len(ranger_candidates) - 1)]
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


def write_ranger_candidates_json(config, candidates, sample_n_used, distance_sample_n, json_path) -> None:
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
        "knn_k": int(config.knn_k),
        "quantile_probs": [float(value) for value in config.quantile_probs],
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
    status = "failed"

    if not failure_reasons:
        try:
            sampled_vectors, valid_vector_count = sample_valid_feature_vectors(config)
            sampled_vector_count = len(sampled_vectors)
            ranger_candidates, distance_sample_n = derive_ranger_candidates(config, sampled_vectors)
            scale_candidates = read_scale_candidates(config.scale_candidates_json_path)
            assigned_candidates = assign_ranger_candidates_to_scale_candidates(scale_candidates, ranger_candidates)
            write_ranger_candidates_csv(ranger_candidates, ranger_csv_path)
            write_ranger_candidates_json(config, ranger_candidates, sampled_vector_count, distance_sample_n, ranger_json_path)
            write_assigned_candidates_csv(assigned_candidates, assigned_csv_path)
            write_assigned_candidates_json(config, len(ranger_candidates), assigned_candidates, assigned_json_path)
        except Exception as exc:
            failure_reasons.append(str(exc))
        else:
            ranger_count = len(ranger_candidates)
            scale_candidate_count = len(scale_candidates)
            assigned_candidate_count = len(assigned_candidates)
            files_written = [
                str(ranger_csv_path),
                str(ranger_json_path),
                str(assigned_csv_path),
                str(assigned_json_path),
            ]
            status = "ok"

    return {
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
        "knn_k": config.knn_k,
        "quantile_probs": tuple(config.quantile_probs),
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
