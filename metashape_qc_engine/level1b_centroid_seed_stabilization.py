"""Multiscale centroid-vote seed stabilization for Level-1B."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

import numpy as np
import rasterio
from scipy import ndimage
from scipy.spatial import cKDTree

from metashape_qc_engine.level1b_step_manifest import write_step_manifest
from metashape_qc_engine.level1b_saga_segmentation import (
    SAGA_NODATA,
    _write_saga_grid_header,
    build_saga_region_growing_command,
    export_saga_segments_to_geotiff,
    saga_cli_env,
)


STABILIZATION_RELATIVE_DIR = Path(
    "level1b/step10_materialization/centroid_seed_stabilization"
)


def _segment_centroids(label_path: Path) -> np.ndarray:
    """Return one raster-coordinate centre of mass for every non-zero label."""

    with rasterio.open(label_path) as dataset:
        labels = dataset.read(1)
    maximum = int(labels.max(initial=0))
    if maximum < 1:
        return np.empty((0, 2), dtype=np.float64)
    label_ids = np.unique(labels)
    label_ids = label_ids[label_ids > 0]
    centres = np.asarray(
        ndimage.center_of_mass(
            np.ones(labels.shape, dtype=np.uint8),
            labels=labels,
            index=label_ids.tolist(),
        ),
        dtype=np.float64,
    )
    return centres[np.all(np.isfinite(centres), axis=1)]


def _density_peaks(
    point_sets: list[np.ndarray],
    shape: tuple[int, int],
    radius_px: int,
) -> tuple[np.ndarray, np.ndarray]:
    impulses = np.zeros(shape, dtype=np.float32)
    for points in point_sets:
        if points.size == 0:
            continue
        pixels = np.rint(points).astype(np.int64)
        pixels[:, 0] = np.clip(pixels[:, 0], 0, shape[0] - 1)
        pixels[:, 1] = np.clip(pixels[:, 1], 0, shape[1] - 1)
        unique_pixels = np.unique(pixels, axis=0)
        np.add.at(impulses, (unique_pixels[:, 0], unique_pixels[:, 1]), 1.0)
    sigma = max(1.0, float(radius_px) / 2.0)
    density = ndimage.gaussian_filter(impulses, sigma=sigma, mode="constant")
    window = 2 * max(1, int(radius_px)) + 1
    local_maximum = density == ndimage.maximum_filter(
        density, size=window, mode="constant"
    )
    local_maximum &= density > 0
    plateau_labels, plateau_count = ndimage.label(local_maximum)
    peaks = []
    peak_density = []
    for plateau_id in range(1, plateau_count + 1):
        rows, cols = np.nonzero(plateau_labels == plateau_id)
        if rows.size == 0:
            continue
        values = density[rows, cols]
        best = int(np.argmax(values))
        peaks.append((int(rows[best]), int(cols[best])))
        peak_density.append(float(values[best]))
    return np.asarray(peaks, dtype=np.int64), np.asarray(peak_density, dtype=float)


def _supported_peaks(
    peaks: np.ndarray,
    density: np.ndarray,
    point_sets: list[np.ndarray],
    rows: list[dict[str, Any]],
    radius_px: int,
    *,
    minimum_run_support: int,
    minimum_phase_support: int,
    minimum_ranger_support: int,
) -> list[dict[str, Any]]:
    trees = [cKDTree(points[:, ::-1]) if len(points) else None for points in point_sets]
    supported = []
    for peak_index, (row, col) in enumerate(peaks):
        query = np.asarray([col, row], dtype=float)
        run_indices = [
            index
            for index, tree in enumerate(trees)
            if tree is not None and bool(tree.query_ball_point(query, r=radius_px))
        ]
        phases = {str(rows[index]["seed_realization_id"]) for index in run_indices}
        rangers = {
            round(float(rows[index]["run_ranger"]), 12) for index in run_indices
        }
        if (
            len(run_indices) < minimum_run_support
            or len(phases) < minimum_phase_support
            or len(rangers) < minimum_ranger_support
        ):
            continue
        supported.append(
            {
                "row": int(row),
                "col": int(col),
                "density": float(density[peak_index]),
                "run_support": len(run_indices),
                "phase_support": len(phases),
                "ranger_support": len(rangers),
            }
        )
    return supported


def _mutual_scale_tracks(
    peaks_by_scale: list[list[dict[str, Any]]],
    radii_by_scale: list[int],
) -> list[list[tuple[int, int]]]:
    nodes = [
        (scale_index, peak_index)
        for scale_index, peaks in enumerate(peaks_by_scale)
        for peak_index in range(len(peaks))
    ]
    parent = {node: node for node in nodes}

    def find(node: tuple[int, int]) -> tuple[int, int]:
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != node:
            next_node = parent[node]
            parent[node] = root
            node = next_node
        return root

    def union(left: tuple[int, int], right: tuple[int, int]) -> None:
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return
        keep, drop = sorted((left_root, right_root))
        parent[drop] = keep

    for scale_index in range(len(peaks_by_scale) - 1):
        left = peaks_by_scale[scale_index]
        right = peaks_by_scale[scale_index + 1]
        if not left or not right:
            continue
        left_points = np.asarray([[row["col"], row["row"]] for row in left])
        right_points = np.asarray([[row["col"], row["row"]] for row in right])
        right_tree = cKDTree(right_points)
        left_tree = cKDTree(left_points)
        left_distances, left_nearest = right_tree.query(left_points, k=1)
        _, right_nearest = left_tree.query(right_points, k=1)
        maximum_distance = max(radii_by_scale[scale_index : scale_index + 2])
        for left_index, (distance, right_index) in enumerate(
            zip(left_distances, left_nearest)
        ):
            right_index = int(right_index)
            if (
                float(distance) <= maximum_distance
                and int(right_nearest[right_index]) == left_index
            ):
                union((scale_index, left_index), (scale_index + 1, right_index))

    tracks: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for node in nodes:
        tracks.setdefault(find(node), []).append(node)
    return [
        sorted(track)
        for track in tracks.values()
        if len({scale_index for scale_index, _ in track}) >= 2
    ]


def _stable_seed_points(
    tracks: list[list[tuple[int, int]]],
    peaks_by_scale: list[list[dict[str, Any]]],
    selected_scale_index: int,
    minimum_distance_px: int,
) -> list[dict[str, Any]]:
    candidates = []
    for track_id, track in enumerate(tracks, start=1):
        if selected_scale_index not in {scale for scale, _ in track}:
            continue
        points = np.asarray(
            [
                [
                    peaks_by_scale[scale_index][peak_index]["row"],
                    peaks_by_scale[scale_index][peak_index]["col"],
                ]
                for scale_index, peak_index in track
            ],
            dtype=float,
        )
        centre = np.median(points, axis=0)
        total_support = sum(
            peaks_by_scale[scale_index][peak_index]["run_support"]
            for scale_index, peak_index in track
        )
        candidates.append(
            {
                "track_id": f"track_{track_id:06d}",
                "row": int(round(float(centre[0]))),
                "col": int(round(float(centre[1]))),
                "scale_support": len({scale for scale, _ in track}),
                "total_run_support": int(total_support),
                "track_members": [
                    {
                        "scale_index": scale,
                        "peak_index": peak,
                    }
                    for scale, peak in track
                ],
            }
        )
    candidates.sort(
        key=lambda row: (
            -row["scale_support"],
            -row["total_run_support"],
            row["row"],
            row["col"],
        )
    )
    selected = []
    minimum_sq = float(minimum_distance_px * minimum_distance_px)
    for candidate in candidates:
        if any(
            (candidate["row"] - existing["row"]) ** 2
            + (candidate["col"] - existing["col"]) ** 2
            < minimum_sq
            for existing in selected
        ):
            continue
        selected.append(candidate)
    return selected


def _write_seed_grid(
    path: Path,
    shape: tuple[int, int],
    seeds: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    values = np.memmap(
        path.with_suffix(".sdat"),
        dtype="<f4",
        mode="w+",
        shape=shape,
    )
    values[:] = SAGA_NODATA
    for seed_id, seed in enumerate(seeds, start=1):
        values[seed["row"], seed["col"]] = seed_id
    values.flush()
    del values
    _write_saga_grid_header(
        path,
        name="multiscale_centroid_seeds",
        width=shape[1],
        height=shape[0],
        nodata_value=SAGA_NODATA,
        top_to_bottom=True,
    )


def _write_seed_csv(
    path: Path,
    seeds: list[dict[str, Any]],
    transform: Any,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "seed_id",
        "row",
        "col",
        "x",
        "y",
        "scale_support",
        "total_run_support",
        "source_segment_id",
        "source_segment_pixel_count",
    ]
    with path.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        for seed_id, seed in enumerate(seeds, start=1):
            x, y = rasterio.transform.xy(
                transform, seed["row"], seed["col"], offset="center"
            )
            writer.writerow(
                {
                    "seed_id": seed_id,
                    "row": seed["row"],
                    "col": seed["col"],
                    "x": x,
                    "y": y,
                    "scale_support": seed.get("scale_support"),
                    "total_run_support": seed.get("total_run_support"),
                    "source_segment_id": seed.get("source_segment_id"),
                    "source_segment_pixel_count": seed.get(
                        "source_segment_pixel_count"
                    ),
                }
            )


def run_multiscale_centroid_seed_stabilization(
    output_dir: str | Path,
    *,
    minimum_run_support: int,
    minimum_phase_support: int,
    minimum_ranger_support: int,
) -> dict[str, Any]:
    root = Path(output_dir)

    response_dir = root / "level1b/candidate_response_surface"
    run_rows = json.loads(
        (response_dir / "run_population_summary.json").read_text(encoding="utf-8")
    )
    evidence_path = (
        root
        / "level1b/step10_materialization/decision_evidence/finalist_evidence.json"
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    selected_candidate_id = str(evidence["selected_candidate_id"])
    selected_run_id = str(evidence["selected_representative_run_id"])
    [selected_row] = [
        row
        for row in evidence["finalist_run_rows"]
        if str(row["run_id"]) == selected_run_id
        and row["step10_selected_candidate"] is True
    ]

    by_group: dict[str, list[dict[str, Any]]] = {}
    for row in run_rows:
        by_group.setdefault(str(row["candidate_scale_group_id"]), []).append(row)
    ordered_groups = sorted(
        by_group,
        key=lambda group_id: float(by_group[group_id][0]["source_candidate_radius_m"]),
    )
    selected_radius = float(selected_row["source_candidate_radius_m"])
    selected_scale_index = min(
        range(len(ordered_groups)),
        key=lambda index: abs(
            float(by_group[ordered_groups[index]][0]["source_candidate_radius_m"])
            - selected_radius
        ),
    )

    stabilization_dir = root / STABILIZATION_RELATIVE_DIR
    stabilization_dir.mkdir(parents=True, exist_ok=True)
    peaks_by_scale: list[list[dict[str, Any]]] = []
    radii_px: list[int] = []
    shape: tuple[int, int] | None = None
    transform = None
    for group_id in ordered_groups:
        rows = sorted(by_group[group_id], key=lambda row: str(row["run_id"]))
        point_sets = [
            _segment_centroids(Path(str(row["merged_labels_path"]))) for row in rows
        ]
        with rasterio.open(rows[0]["merged_labels_path"]) as dataset:
            current_shape = (dataset.height, dataset.width)
            if shape is None:
                shape = current_shape
                transform = dataset.transform
            elif shape != current_shape:
                raise ValueError("Step-9a label rasters do not share one grid")
        radius_px = max(1, int(round(float(rows[0]["spatialr_px"]))))
        peaks, density = _density_peaks(point_sets, current_shape, radius_px)
        supported = _supported_peaks(
            peaks,
            density,
            point_sets,
            rows,
            radius_px,
            minimum_run_support=minimum_run_support,
            minimum_phase_support=minimum_phase_support,
            minimum_ranger_support=minimum_ranger_support,
        )
        for peak in supported:
            peak["candidate_scale_group_id"] = group_id
            peak["spatialr_px"] = radius_px
        peaks_by_scale.append(supported)
        radii_px.append(radius_px)
    assert shape is not None and transform is not None

    tracks = _mutual_scale_tracks(peaks_by_scale, radii_px)
    seeds = _stable_seed_points(
        tracks,
        peaks_by_scale,
        selected_scale_index,
        max(1, int(round(float(selected_row["spatialr_px"])))),
    )
    if not seeds:
        raise ValueError("multiscale centroid support produced no stable seeds")

    valid_mask_path = root / "level1b/mask/valid_mask.tif"
    with rasterio.open(valid_mask_path) as mask_dataset:
        valid = mask_dataset.read(1) > 0
    invalid = [seed for seed in seeds if not valid[seed["row"], seed["col"]]]
    if invalid:
        indices = ndimage.distance_transform_edt(
            ~valid, return_distances=False, return_indices=True
        )
        for seed in invalid:
            source_row, source_col = seed["row"], seed["col"]
            seed["row"] = int(indices[0, source_row, source_col])
            seed["col"] = int(indices[1, source_row, source_col])

    feature_grids = sorted((response_dir / "saga_feature_grids").glob("feature_*.sgrd"))
    if not feature_grids:
        raise FileNotFoundError("canonical SAGA feature grids are missing")
    feature_stack_path = root / "level1b/scaling/scaled_feature_stack.tif"
    minimum_distance_px = max(1, int(round(float(selected_row["spatialr_px"]))))

    stabilized_seed_grid = stabilization_dir / "stabilized_seeds.sgrd"
    _write_seed_grid(stabilized_seed_grid, shape, seeds)
    seed_csv = stabilization_dir / "stabilized_seeds.csv"
    _write_seed_csv(seed_csv, seeds, transform)

    work_dir = stabilization_dir / "selected_scale_resegmentation"
    work_dir.mkdir(parents=True, exist_ok=True)
    command = build_saga_region_growing_command(
        "/usr/bin/saga_cmd",
        feature_grids,
        work_dir,
        feature_variance=float(selected_row["run_ranger"]),
        position_variance_px=float(selected_row["spatialr_px"]),
        seed_grid_path=stabilized_seed_grid,
    )
    process = subprocess.run(
        command,
        capture_output=True,
        text=True,
        env=saga_cli_env(),
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr or process.stdout)
    stabilized_labels = stabilization_dir / "stabilized_labels.tif"
    export = export_saga_segments_to_geotiff(
        work_dir / "segments.sgrd",
        feature_stack_path,
        valid_mask_path,
        stabilized_labels,
    )
    shutil.rmtree(work_dir)

    status = "multiscale_centroid_seed_stabilization_ready"
    report = {
        "status": status,
        "output_dir": str(root),
        "selected_candidate_id": selected_candidate_id,
        "selected_role": evidence["selected_role"],
        "selected_source_run_id": selected_run_id,
        "selected_spatialr_px": int(selected_row["spatialr_px"]),
        "selected_ranger": float(selected_row["run_ranger"]),
        "scale_group_ids": ordered_groups,
        "selected_support_scale_group_id": ordered_groups[selected_scale_index],
        "supported_peak_counts_by_scale": [len(rows) for rows in peaks_by_scale],
        "multiscale_track_count": len(tracks),
        "stable_seed_count": len(seeds),
        "output_segment_count": int(export["max_label"]),
        "minimum_seed_distance_px": minimum_distance_px,
        "minimum_run_support": minimum_run_support,
        "minimum_phase_support": minimum_phase_support,
        "minimum_ranger_support": minimum_ranger_support,
        "stabilized_seed_grid": str(stabilized_seed_grid),
        "stabilized_seed_csv": str(seed_csv),
        "stabilized_labels_tif": str(stabilized_labels),
        "source_finalist_evidence_json": str(evidence_path),
    }
    report_path = stabilization_dir / "centroid_seed_stabilization_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_step_manifest(
        root,
        step="centroid_seed_stabilization",
        status=status,
        inputs={
            "finalist_evidence_json": evidence_path,
            "step9a_run_population_json": response_dir / "run_population_summary.json",
            "scaled_feature_stack": feature_stack_path,
            "valid_mask": valid_mask_path,
        },
        artifacts={
            "stabilization_report_json": report_path,
            "stabilized_seed_grid": stabilized_seed_grid,
            "stabilized_seed_csv": seed_csv,
            "stabilized_labels_tif": stabilized_labels,
        },
        candidate_id=selected_candidate_id,
    )
    return {**report, "report_json": str(report_path)}
