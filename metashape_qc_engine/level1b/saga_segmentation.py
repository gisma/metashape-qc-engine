"""SAGA Seeded Region Growing backend for Level-1B label production."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Iterable

import numpy as np
import rasterio
from rasterio.windows import Window


SAGA_CMD = "saga_cmd"
SAGA_NODATA = -99999.0
SAGA_SEGMENTATION_BACKEND = "saga_seeded_region_growing"
CONTROLLED_SEED_POLICY = "hex_lattice_local_variance_minimum"
SEED_SNAP_RADIUS_FRACTION = 0.45
SEED_MIN_DISTANCE_FRACTION = 1.0
SEED_MAX_COVERAGE_FRACTION = 2.0


def discover_saga_cmd() -> str | None:
    explicit_command = os.environ.get("LEVEL1B_SAGA_CMD_ORIG")
    if explicit_command and Path(explicit_command).is_file():
        return explicit_command
    saved_path = os.environ.get("LEVEL1B_SAGA_PATH_ORIG")
    if saved_path:
        discovered = shutil.which(SAGA_CMD, path=saved_path)
        if discovered:
            return discovered
    return shutil.which(SAGA_CMD)


def saga_cli_env() -> dict[str, str]:
    """Return a system-oriented environment for the external SAGA process."""

    env = os.environ.copy()
    if os.environ.get("LEVEL1B_SAGA_PATH_ORIG"):
        env["PATH"] = os.environ["LEVEL1B_SAGA_PATH_ORIG"]
    for saved_name, runtime_name in (
        ("LEVEL1B_SAGA_GDAL_DATA_ORIG", "GDAL_DATA"),
        ("LEVEL1B_SAGA_PROJ_LIB_ORIG", "PROJ_LIB"),
    ):
        if os.environ.get(saved_name):
            env[runtime_name] = os.environ[saved_name]
    # OTB's bundled libraries and projection database are incompatible with the
    # system SAGA build. SAGA is a separate external CLI and must not inherit
    # those runtime overrides from an interactive OTB shell.
    env.pop("LD_LIBRARY_PATH", None)
    env.pop("PYTHONPATH", None)
    for name in ("GDAL_DATA", "PROJ_LIB"):
        if "otb" in env.get(name, "").lower():
            env.pop(name, None)
    return env


def saga_subprocess_command(command: Iterable[str | os.PathLike[str]]) -> list[str]:
    """Wrap Windows batch launchers explicitly for subprocess execution."""

    normalized = [os.fspath(part) for part in command]
    if os.name != "nt" or not normalized:
        return normalized
    if Path(normalized[0]).suffix.lower() not in {".bat", ".cmd"}:
        return normalized
    comspec = os.environ.get("COMSPEC") or shutil.which("cmd.exe") or "cmd.exe"
    return [
        comspec,
        "/d",
        "/s",
        "/c",
        subprocess.list2cmdline(normalized),
    ]


def _grid_paths(directory: Path, band_count: int) -> list[Path]:
    return [directory / f"feature_{index:03d}.sgrd" for index in range(1, band_count + 1)]


def _write_saga_grid_header(
    path: Path,
    *,
    name: str,
    width: int,
    height: int,
    data_format: str = "FLOAT",
    nodata_value: float = SAGA_NODATA,
    top_to_bottom: bool = True,
) -> None:
    path.write_text(
        "\n".join(
            [
                f"NAME\t= {name}",
                "DESCRIPTION\t=",
                "UNIT\t=",
                "DATAFILE_OFFSET\t= 0",
                f"DATAFORMAT\t= {data_format}",
                "BYTEORDER_BIG\t= FALSE",
                "POSITION_XMIN\t= 0.0000000000",
                "POSITION_YMIN\t= 0.0000000000",
                f"CELLCOUNT_X\t= {width}",
                f"CELLCOUNT_Y\t= {height}",
                "CELLSIZE\t= 1.0000000000",
                "Z_FACTOR\t= 1.000000",
                f"NODATA_VALUE\t= {nodata_value:.17g}",
                f"TOPTOBOTTOM\t= {'TRUE' if top_to_bottom else 'FALSE'}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _feature_grid_provenance(
    feature_stack_path: Path, valid_mask_path: Path, width: int, height: int, band_count: int
) -> dict[str, Any]:
    return {
        "feature_stack_path": str(feature_stack_path),
        "feature_stack_size_bytes": feature_stack_path.stat().st_size,
        "feature_stack_mtime_ns": feature_stack_path.stat().st_mtime_ns,
        "valid_mask_path": str(valid_mask_path),
        "valid_mask_size_bytes": valid_mask_path.stat().st_size,
        "valid_mask_mtime_ns": valid_mask_path.stat().st_mtime_ns,
        "width": width,
        "height": height,
        "band_count": band_count,
        "nodata_value": SAGA_NODATA,
        "grid_coordinates": "pixel_space",
        "top_to_bottom": True,
    }


def prepare_saga_feature_grids(
    feature_stack_path: str | Path,
    valid_mask_path: str | Path,
    output_dir: str | Path,
    *,
    overwrite: bool = False,
    block_rows: int = 256,
) -> dict[str, Any]:
    """Materialize one reusable SAGA grid per feature band without full-raster reads."""

    feature_stack_path = Path(feature_stack_path)
    valid_mask_path = Path(valid_mask_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "saga_feature_grids_report.json"

    with rasterio.open(feature_stack_path) as features, rasterio.open(valid_mask_path) as mask:
        if (features.width, features.height) != (mask.width, mask.height):
            raise ValueError("feature stack and valid mask dimensions differ")
        if features.count < 1:
            raise ValueError("feature stack has no bands")
        width, height, band_count = features.width, features.height, features.count
        provenance = _feature_grid_provenance(
            feature_stack_path, valid_mask_path, width, height, band_count
        )
        grid_paths = _grid_paths(output_dir, band_count)

        if not overwrite and report_path.is_file():
            try:
                previous = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                previous = None
            if (
                isinstance(previous, dict)
                and previous.get("provenance") == provenance
                and all(path.is_file() and path.stat().st_size > 0 for path in grid_paths)
                and all(
                    path.with_suffix(".sdat").is_file()
                    and path.with_suffix(".sdat").stat().st_size > 0
                    for path in grid_paths
                )
            ):
                return {**previous, "status": "ok", "preparation_status": "reused"}

        for band_index, header_path in enumerate(grid_paths, start=1):
            data_path = header_path.with_suffix(".sdat")
            temporary_data_path = data_path.with_name(f".{data_path.name}.tmp")
            if temporary_data_path.exists():
                temporary_data_path.unlink()
            with temporary_data_path.open("wb") as handle:
                for row_off in range(0, height, block_rows):
                    row_count = min(block_rows, height - row_off)
                    window = Window(0, row_off, width, row_count)
                    values = features.read(band_index, window=window, out_dtype="float32")
                    valid = mask.read(1, window=window) > 0
                    values[~valid] = SAGA_NODATA
                    handle.write(np.asarray(values, dtype="<f4").tobytes(order="C"))
            temporary_data_path.replace(data_path)
            _write_saga_grid_header(
                header_path,
                name=f"feature_{band_index:03d}",
                width=width,
                height=height,
            )

    report = {
        "status": "ok",
        "preparation_status": "computed",
        "provenance": provenance,
        "grid_paths": [str(path) for path in grid_paths],
        "report_path": str(report_path),
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def build_saga_variance_surface_command(
    saga_cmd_path: str,
    feature_grid_paths: Iterable[str | Path],
    output_dir: str | Path,
    spatial_radius_px: int,
) -> list[str]:
    output_dir = Path(output_dir)
    features = ";".join(str(Path(path)) for path in feature_grid_paths)
    return [
        saga_cmd_path,
        "-f=s",
        "imagery_segmentation",
        "2",
        "-FEATURES",
        features,
        "-VARIANCE",
        str(output_dir / "seed_variance.sgrd"),
        "-SEED_TYPE",
        "0",
        "-METHOD",
        "0",
        "-BAND_WIDTH",
        str(int(spatial_radius_px)),
        "-NORMALIZE",
        "0",
        "-DW_WEIGHTING",
        "0",
    ]


def build_saga_seed_proximity_command(
    saga_cmd_path: str,
    output_dir: str | Path,
) -> list[str]:
    output_dir = Path(output_dir)
    return [
        saga_cmd_path,
        "-f=s",
        "grid_tools",
        "26",
        "-FEATURES",
        str(output_dir / "seeds.sgrd"),
        "-DISTANCE",
        str(output_dir / "seed_distance.sgrd"),
    ]


def _saga_grid_view(header_path: Path) -> tuple[np.memmap, dict[str, str]]:
    header = _parse_saga_header(header_path)
    width = int(header["CELLCOUNT_X"])
    height = int(header["CELLCOUNT_Y"])
    values = np.memmap(
        header_path.with_suffix(".sdat"),
        dtype="<f4",
        mode="r",
        shape=(height, width),
    )
    if header.get("TOPTOBOTTOM", "FALSE").upper() == "TRUE":
        return values, header
    return values[::-1], header


def _near_existing_seed(
    row: int,
    col: int,
    *,
    seed_rows: list[int],
    seed_cols: list[int],
    buckets: dict[tuple[int, int], list[int]],
    bucket_size: int,
    minimum_distance_px: float,
) -> bool:
    bucket_row = row // bucket_size
    bucket_col = col // bucket_size
    bucket_radius = max(1, int(math.ceil(minimum_distance_px / bucket_size)))
    limit_sq = minimum_distance_px * minimum_distance_px
    for delta_row in range(-bucket_radius, bucket_radius + 1):
        for delta_col in range(-bucket_radius, bucket_radius + 1):
            for index in buckets.get((bucket_row + delta_row, bucket_col + delta_col), ()):
                distance_sq = (
                    (row - seed_rows[index]) * (row - seed_rows[index])
                    + (col - seed_cols[index]) * (col - seed_cols[index])
                )
                if distance_sq < limit_sq:
                    return True
    return False


def _append_seed(
    row: int,
    col: int,
    *,
    seed_rows: list[int],
    seed_cols: list[int],
    buckets: dict[tuple[int, int], list[int]],
    bucket_size: int,
) -> None:
    index = len(seed_rows)
    seed_rows.append(int(row))
    seed_cols.append(int(col))
    buckets.setdefault((row // bucket_size, col // bucket_size), []).append(index)


def _hex_centres(
    width: int,
    height: int,
    spacing_px: float,
    *,
    phase_u: float,
    phase_v: float,
) -> Iterable[tuple[float, float]]:
    """Yield one translated realization of the metric triangular lattice."""

    row_spacing = spacing_px * math.sqrt(3.0) / 2.0
    for lattice_row in range(-3, int(math.ceil(height / row_spacing)) + 4):
        row = (lattice_row + phase_v) * row_spacing
        column_max = int(math.ceil(width / spacing_px)) + 3
        for lattice_col in range(-3, column_max + 1):
            col = (
                lattice_col
                + 0.5 * lattice_row
                + phase_u
                + 0.5 * phase_v
            ) * spacing_px
            yield row, col


def materialize_controlled_seed_grid(
    variance_grid_path: str | Path,
    valid_mask_path: str | Path,
    output_seed_grid_path: str | Path,
    *,
    spatial_radius_px: int,
    seed_realization_id: str = "phase_00",
    seed_phase_u: float = 0.0,
    seed_phase_v: float = 0.0,
) -> dict[str, Any]:
    """Create deterministic, spatially controlled seeds for SAGA region growing."""

    variance_grid_path = Path(variance_grid_path)
    valid_mask_path = Path(valid_mask_path)
    output_seed_grid_path = Path(output_seed_grid_path)
    radius_px = float(max(1, int(spatial_radius_px)))
    seed_realization_id = str(seed_realization_id).strip()
    if not seed_realization_id:
        raise ValueError("seed_realization_id must be non-empty")
    for name, value in (("seed_phase_u", seed_phase_u), ("seed_phase_v", seed_phase_v)):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{name} must be numeric")
        if not math.isfinite(float(value)) or not 0.0 <= float(value) < 1.0:
            raise ValueError(f"{name} must be in [0, 1)")
    seed_phase_u = float(seed_phase_u)
    seed_phase_v = float(seed_phase_v)
    # One hexagonal support cell has the same area as the candidate's circular
    # footprint. This ties seed density explicitly to the candidate radius.
    spacing_px = math.sqrt(2.0 * math.pi / math.sqrt(3.0)) * radius_px
    snap_radius_px = max(1.0, SEED_SNAP_RADIUS_FRACTION * radius_px)
    minimum_distance_px = max(1.0, SEED_MIN_DISTANCE_FRACTION * radius_px)
    maximum_coverage_distance_px = SEED_MAX_COVERAGE_FRACTION * radius_px
    bucket_size = max(1, int(math.floor(minimum_distance_px)))

    variance, header = _saga_grid_view(variance_grid_path)
    width = int(header["CELLCOUNT_X"])
    height = int(header["CELLCOUNT_Y"])
    nodata = float(header.get("NODATA_VALUE", str(SAGA_NODATA)).split(";")[0])
    with rasterio.open(valid_mask_path) as mask_dataset:
        if (mask_dataset.width, mask_dataset.height) != (width, height):
            raise ValueError("valid mask dimensions differ from SAGA variance grid")
        valid = mask_dataset.read(1) > 0

    seed_rows: list[int] = []
    seed_cols: list[int] = []
    buckets: dict[tuple[int, int], list[int]] = {}
    nominal_count = 0
    centres_with_valid_support = 0
    rejected_for_minimum_distance = 0
    snap_radius_sq = snap_radius_px * snap_radius_px

    for nominal_row, nominal_col in _hex_centres(
        width,
        height,
        spacing_px,
        phase_u=seed_phase_u,
        phase_v=seed_phase_v,
    ):
        nominal_count += 1
        row_min = max(0, int(math.floor(nominal_row - snap_radius_px)))
        row_max = min(height, int(math.ceil(nominal_row + snap_radius_px)) + 1)
        col_min = max(0, int(math.floor(nominal_col - snap_radius_px)))
        col_max = min(width, int(math.ceil(nominal_col + snap_radius_px)) + 1)
        if row_min >= row_max or col_min >= col_max:
            continue
        rows, cols = np.ogrid[row_min:row_max, col_min:col_max]
        within_snap = (
            (rows - nominal_row) * (rows - nominal_row)
            + (cols - nominal_col) * (cols - nominal_col)
        ) <= snap_radius_sq
        window_variance = np.asarray(variance[row_min:row_max, col_min:col_max])
        eligible = (
            within_snap
            & valid[row_min:row_max, col_min:col_max]
            & np.isfinite(window_variance)
            & (window_variance != nodata)
        )
        if not np.any(eligible):
            continue
        centres_with_valid_support += 1
        ranked = np.where(eligible, window_variance, np.inf)
        local_index = int(np.argmin(ranked))
        local_row, local_col = np.unravel_index(local_index, ranked.shape)
        row = row_min + int(local_row)
        col = col_min + int(local_col)
        if _near_existing_seed(
            row,
            col,
            seed_rows=seed_rows,
            seed_cols=seed_cols,
            buckets=buckets,
            bucket_size=bucket_size,
            minimum_distance_px=minimum_distance_px,
        ):
            rejected_for_minimum_distance += 1
            continue
        _append_seed(
            row,
            col,
            seed_rows=seed_rows,
            seed_cols=seed_cols,
            buckets=buckets,
            bucket_size=bucket_size,
        )

    if not seed_rows:
        raise ValueError("controlled seed construction produced no valid seeds")

    output_seed_grid_path.parent.mkdir(parents=True, exist_ok=True)
    data_path = output_seed_grid_path.with_suffix(".sdat")
    seed_values = np.memmap(data_path, dtype="<f4", mode="w+", shape=(height, width))
    seed_values[:] = SAGA_NODATA
    seed_values[np.asarray(seed_rows), np.asarray(seed_cols)] = np.arange(
        1, len(seed_rows) + 1, dtype=np.float32
    )
    seed_values.flush()
    del seed_values
    _write_saga_grid_header(
        output_seed_grid_path,
        name="controlled_seeds",
        width=width,
        height=height,
        nodata_value=SAGA_NODATA,
        top_to_bottom=True,
    )

    return {
        "policy": CONTROLLED_SEED_POLICY,
        "target_footprint": "circular_candidate_radius",
        "lattice": "metric_hexagonal_translated_phase",
        "seed_realization_id": seed_realization_id,
        "seed_phase_u": seed_phase_u,
        "seed_phase_v": seed_phase_v,
        "spatial_radius_px": int(spatial_radius_px),
        "nominal_spacing_px": spacing_px,
        "snap_radius_px": snap_radius_px,
        "minimum_seed_distance_px": minimum_distance_px,
        "maximum_coverage_distance_px": maximum_coverage_distance_px,
        "nominal_centre_count": nominal_count,
        "centres_with_valid_support": centres_with_valid_support,
        "rejected_for_minimum_distance": rejected_for_minimum_distance,
        "seed_count": len(seed_rows),
        "seed_grid_path": str(output_seed_grid_path),
    }


def summarize_seed_coverage(
    distance_grid_path: str | Path,
    valid_mask_path: str | Path,
    *,
    maximum_coverage_distance_px: float,
) -> dict[str, Any]:
    distance, header = _saga_grid_view(Path(distance_grid_path))
    width = int(header["CELLCOUNT_X"])
    height = int(header["CELLCOUNT_Y"])
    with rasterio.open(valid_mask_path) as mask_dataset:
        if (mask_dataset.width, mask_dataset.height) != (width, height):
            raise ValueError("valid mask dimensions differ from seed distance grid")
        valid = mask_dataset.read(1) > 0
    values = np.asarray(distance)[valid]
    values = values[np.isfinite(values) & (values >= 0)]
    if values.size == 0:
        raise ValueError("seed proximity grid has no valid distances")
    quantiles = np.quantile(values, [0.50, 0.95, 0.99, 1.0])
    maximum = float(quantiles[3])
    return {
        "valid_distance_count": int(values.size),
        "distance_px_p50": float(quantiles[0]),
        "distance_px_p95": float(quantiles[1]),
        "distance_px_p99": float(quantiles[2]),
        "distance_px_max": maximum,
        "maximum_coverage_distance_px": float(maximum_coverage_distance_px),
        "coverage_within_limit": maximum <= float(maximum_coverage_distance_px),
    }


def complete_seed_coverage(
    seed_grid_path: str | Path,
    distance_grid_path: str | Path,
    valid_mask_path: str | Path,
    *,
    maximum_coverage_distance_px: float,
) -> dict[str, int]:
    """Add deterministic farthest-point seeds only where the coverage limit fails."""

    seed_grid_path = Path(seed_grid_path)
    seeds, seed_header = _saga_grid_view(seed_grid_path)
    distance, distance_header = _saga_grid_view(Path(distance_grid_path))
    width = int(seed_header["CELLCOUNT_X"])
    height = int(seed_header["CELLCOUNT_Y"])
    if (
        int(distance_header["CELLCOUNT_X"]),
        int(distance_header["CELLCOUNT_Y"]),
    ) != (width, height):
        raise ValueError("seed and seed-distance grid dimensions differ")
    with rasterio.open(valid_mask_path) as mask_dataset:
        if (mask_dataset.width, mask_dataset.height) != (width, height):
            raise ValueError("valid mask dimensions differ from seed grid")
        valid = mask_dataset.read(1) > 0

    distance_values = np.asarray(distance)
    uncovered = (
        valid
        & np.isfinite(distance_values)
        & (distance_values > float(maximum_coverage_distance_px))
    )
    if not np.any(uncovered):
        return {"coverage_completion_seed_count": 0}

    flat_indices = np.flatnonzero(uncovered)
    order = np.lexsort((flat_indices, -distance_values.ravel()[flat_indices]))
    radius = float(maximum_coverage_distance_px)
    radius_sq = radius * radius
    added: list[tuple[int, int]] = []
    for flat_index in flat_indices[order]:
        row, col = np.unravel_index(int(flat_index), uncovered.shape)
        if not uncovered[row, col]:
            continue
        added.append((int(row), int(col)))
        row_min = max(0, int(math.floor(row - radius)))
        row_max = min(height, int(math.ceil(row + radius)) + 1)
        col_min = max(0, int(math.floor(col - radius)))
        col_max = min(width, int(math.ceil(col + radius)) + 1)
        rows, cols = np.ogrid[row_min:row_max, col_min:col_max]
        covered = (
            (rows - row) * (rows - row) + (cols - col) * (cols - col)
        ) <= radius_sq
        uncovered[row_min:row_max, col_min:col_max][covered] = False

    writable = np.memmap(
        seed_grid_path.with_suffix(".sdat"),
        dtype="<f4",
        mode="r+",
        shape=(height, width),
    )
    top_to_bottom = seed_header.get("TOPTOBOTTOM", "FALSE").upper() == "TRUE"
    logical = writable if top_to_bottom else writable[::-1]
    existing = logical[np.isfinite(logical) & (logical > 0)]
    next_identifier = int(existing.max()) + 1 if existing.size else 1
    for offset, (row, col) in enumerate(added):
        logical[row, col] = float(next_identifier + offset)
    writable.flush()
    del logical
    del writable
    return {"coverage_completion_seed_count": len(added)}


def build_saga_region_growing_command(
    saga_cmd_path: str,
    feature_grid_paths: Iterable[str | Path],
    output_dir: str | Path,
    *,
    feature_variance: float,
    position_variance_px: float,
    seed_grid_path: str | Path | None = None,
) -> list[str]:
    output_dir = Path(output_dir)
    features = ";".join(str(Path(path)) for path in feature_grid_paths)
    return [
        saga_cmd_path,
        "-f=s",
        "imagery_segmentation",
        "3",
        "-SEEDS",
        str(Path(seed_grid_path) if seed_grid_path is not None else output_dir / "seeds.sgrd"),
        "-FEATURES",
        features,
        "-SEGMENTS",
        str(output_dir / "segments.sgrd"),
        "-SIMILARITY",
        str(output_dir / "similarity.sgrd"),
        "-NORMALIZE",
        "0",
        "-NEIGHBOUR",
        "0",
        "-METHOD",
        "0",
        "-SIG_1",
        f"{float(feature_variance):.17g}",
        "-SIG_2",
        f"{float(position_variance_px):.17g}",
        "-THRESHOLD",
        "0",
        "-REFRESH",
        "0",
        "-LEAFSIZE",
        "256",
    ]


def _parse_saga_header(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip().upper()] = value.strip()
    return values


def export_saga_segments_to_geotiff(
    segments_header_path: str | Path,
    reference_raster_path: str | Path,
    valid_mask_path: str | Path,
    output_path: str | Path,
    *,
    block_rows: int = 256,
) -> dict[str, int]:
    """Export SAGA labels while reserving label zero for invalid support."""

    segments_header_path = Path(segments_header_path)
    reference_raster_path = Path(reference_raster_path)
    valid_mask_path = Path(valid_mask_path)
    output_path = Path(output_path)
    header = _parse_saga_header(segments_header_path)
    width = int(header["CELLCOUNT_X"])
    height = int(header["CELLCOUNT_Y"])
    top_to_bottom = header.get("TOPTOBOTTOM", "FALSE").upper() == "TRUE"
    data_path = segments_header_path.with_suffix(".sdat")
    values = np.memmap(data_path, dtype="<f4", mode="r", shape=(height, width))

    with rasterio.open(reference_raster_path) as reference, rasterio.open(valid_mask_path) as mask:
        if (reference.width, reference.height) != (width, height):
            raise ValueError("SAGA segment dimensions differ from the reference raster")
        if (mask.width, mask.height) != (width, height):
            raise ValueError("valid mask dimensions differ from SAGA segments")
        profile = reference.profile.copy()
        profile.update(
            driver="GTiff",
            count=1,
            dtype="uint32",
            nodata=0,
            compress="deflate",
            BIGTIFF="IF_SAFER",
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        max_label = 0
        valid_pixel_count = 0
        with rasterio.open(output_path, "w", **profile) as output:
            for row_off in range(0, height, block_rows):
                row_count = min(block_rows, height - row_off)
                if top_to_bottom:
                    raw = np.asarray(values[row_off : row_off + row_count])
                else:
                    raw = np.asarray(
                        values[height - row_off - row_count : height - row_off][::-1]
                    )
                window = Window(0, row_off, width, row_count)
                valid = mask.read(1, window=window) > 0
                labels = np.zeros(raw.shape, dtype=np.uint32)
                assigned = valid & np.isfinite(raw) & (raw >= 0)
                shifted = np.rint(raw[assigned]).astype(np.uint64) + 1
                if shifted.size and int(shifted.max()) > np.iinfo(np.uint32).max:
                    raise ValueError("SAGA segment identifier exceeds uint32")
                labels[assigned] = shifted.astype(np.uint32)
                if shifted.size:
                    max_label = max(max_label, int(shifted.max()))
                valid_pixel_count += int(assigned.sum())
                output.write(labels, 1, window=window)
    return {"max_label": max_label, "valid_labelled_pixel_count": valid_pixel_count}


def run_saga_seeded_region_growing(
    *,
    saga_cmd_path: str,
    feature_grid_paths: Iterable[str | Path],
    work_dir: str | Path,
    reference_raster_path: str | Path,
    valid_mask_path: str | Path,
    output_labels_path: str | Path,
    spatial_radius_px: int,
    feature_variance: float,
    seed_realization_id: str = "phase_00",
    seed_phase_u: float = 0.0,
    seed_phase_v: float = 0.0,
    seed_scaffold_dir: str | Path | None = None,
) -> dict[str, Any]:
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    scaffold_dir = Path(seed_scaffold_dir) if seed_scaffold_dir is not None else work_dir
    scaffold_dir.mkdir(parents=True, exist_ok=True)
    feature_grid_paths = [Path(path) for path in feature_grid_paths]
    variance_command = build_saga_variance_surface_command(
        saga_cmd_path, feature_grid_paths, scaffold_dir, spatial_radius_px
    )
    proximity_command = build_saga_seed_proximity_command(saga_cmd_path, scaffold_dir)
    growing_command = build_saga_region_growing_command(
        saga_cmd_path,
        feature_grid_paths,
        work_dir,
        feature_variance=feature_variance,
        position_variance_px=spatial_radius_px,
        seed_grid_path=scaffold_dir / "seeds.sgrd",
    )
    commands: list[list[str]] = []
    command_results: list[dict[str, Any]] = []

    def run_command(command: list[str]) -> None:
        result = subprocess.run(
            saga_subprocess_command(command),
            capture_output=True,
            text=True,
            env=saga_cli_env(),
        )
        commands.append(command)
        command_results.append(
            {
                "command": command,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"SAGA command failed with returncode {result.returncode}: {' '.join(command[:4])}"
            )

    scaffold_provenance = {
        "feature_grids": [
            {
                "path": str(path),
                "size_bytes": path.with_suffix(".sdat").stat().st_size,
                "mtime_ns": path.with_suffix(".sdat").stat().st_mtime_ns,
            }
            for path in feature_grid_paths
        ],
        "valid_mask_path": str(Path(valid_mask_path)),
        "valid_mask_size_bytes": Path(valid_mask_path).stat().st_size,
        "valid_mask_mtime_ns": Path(valid_mask_path).stat().st_mtime_ns,
        "spatial_radius_px": int(spatial_radius_px),
        "seed_realization_id": str(seed_realization_id),
        "seed_phase_u": float(seed_phase_u),
        "seed_phase_v": float(seed_phase_v),
        "seed_policy": CONTROLLED_SEED_POLICY,
        "snap_radius_fraction": SEED_SNAP_RADIUS_FRACTION,
        "minimum_distance_fraction": SEED_MIN_DISTANCE_FRACTION,
        "maximum_coverage_fraction": SEED_MAX_COVERAGE_FRACTION,
    }
    seed_report_path = scaffold_dir / "controlled_seed_report.json"
    try:
        existing_seed_report = json.loads(seed_report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        existing_seed_report = None
    scaffold_files = [
        scaffold_dir / "seeds.sgrd",
        scaffold_dir / "seeds.sdat",
        scaffold_dir / "seed_distance.sgrd",
        scaffold_dir / "seed_distance.sdat",
    ]
    scaffold_reusable = (
        isinstance(existing_seed_report, dict)
        and existing_seed_report.get("provenance") == scaffold_provenance
        and existing_seed_report.get("coverage", {}).get("coverage_within_limit") is True
        and all(path.is_file() and path.stat().st_size > 0 for path in scaffold_files)
    )

    if scaffold_reusable:
        seed_report = dict(existing_seed_report)
        seed_report["preparation_status"] = "reused"
    else:
        # SAGA supplies only the multiband local-variance surface here. Its
        # unconstrained seed output is not requested; the controlled scaffold
        # below is the single operative seed source.
        run_command(variance_command)
        variance_path = scaffold_dir / "seed_variance.sgrd"
        if not variance_path.is_file() or not variance_path.with_suffix(".sdat").is_file():
            raise RuntimeError("SAGA Seed Generation did not create seed_variance.sgrd/.sdat")

        seed_report = materialize_controlled_seed_grid(
            variance_path,
            valid_mask_path,
            scaffold_dir / "seeds.sgrd",
            spatial_radius_px=spatial_radius_px,
            seed_realization_id=seed_realization_id,
            seed_phase_u=seed_phase_u,
            seed_phase_v=seed_phase_v,
        )

        run_command(proximity_command)
        coverage = summarize_seed_coverage(
            scaffold_dir / "seed_distance.sgrd",
            valid_mask_path,
            maximum_coverage_distance_px=seed_report[
                "maximum_coverage_distance_px"
            ],
        )
        completion = {"coverage_completion_seed_count": 0}
        if not coverage["coverage_within_limit"]:
            completion = complete_seed_coverage(
                scaffold_dir / "seeds.sgrd",
                scaffold_dir / "seed_distance.sgrd",
                valid_mask_path,
                maximum_coverage_distance_px=seed_report[
                    "maximum_coverage_distance_px"
                ],
            )
            for suffix in (".sgrd", ".sdat", ".mgrd"):
                distance_path = (scaffold_dir / "seed_distance.sgrd").with_suffix(
                    suffix
                )
                if distance_path.exists():
                    distance_path.unlink()
            run_command(proximity_command)
            coverage = summarize_seed_coverage(
                scaffold_dir / "seed_distance.sgrd",
                valid_mask_path,
                maximum_coverage_distance_px=seed_report[
                    "maximum_coverage_distance_px"
                ],
            )
        if not coverage["coverage_within_limit"]:
            raise RuntimeError(
                "controlled seed grid exceeds its maximum coverage distance"
            )

        seed_report.update(completion)
        seed_report["seed_count"] += completion["coverage_completion_seed_count"]
        seed_report["coverage"] = coverage
        seed_report["provenance"] = scaffold_provenance
        seed_report["preparation_status"] = "computed"
        seed_report_path.write_text(
            json.dumps(seed_report, indent=2), encoding="utf-8"
        )

    run_command(growing_command)
    segments_path = work_dir / "segments.sgrd"
    if not segments_path.is_file() or not segments_path.with_suffix(".sdat").is_file():
        raise RuntimeError("SAGA Seeded Region Growing did not create segments.sgrd/.sdat")
    export = export_saga_segments_to_geotiff(
        segments_path,
        reference_raster_path,
        valid_mask_path,
        output_labels_path,
    )
    return {
        "status": "ok",
        "backend": SAGA_SEGMENTATION_BACKEND,
        "commands": commands,
        "command_results": command_results,
        "seed_policy": CONTROLLED_SEED_POLICY,
        "seed_report": seed_report,
        "seed_report_path": str(seed_report_path),
        "variance_band_width_px": int(spatial_radius_px),
        "feature_variance": float(feature_variance),
        "position_variance_px": float(spatial_radius_px),
        "similarity_threshold": 0.0,
        "neighbourhood": 4,
        "direction": "feature_space_and_position",
        **export,
    }
