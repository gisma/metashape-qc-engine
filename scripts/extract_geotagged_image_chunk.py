#!/usr/bin/env python3
"""Copy a balanced flight-line image grid around one WGS84 coordinate."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
from typing import Any, Sequence


IMAGE_EXTENSIONS = ("jpg", "jpeg", "tif", "tiff", "dng")
DATETIME_FORMAT = "%Y:%m:%d %H:%M:%S"


@dataclass(frozen=True)
class ImagePosition:
    source_path: Path
    latitude: float
    longitude: float
    altitude_m: float | None
    capture_time: datetime
    flight_yaw_deg: float
    east_m: float = 0.0
    north_m: float = 0.0
    along_track_m: float = 0.0
    cross_track_m: float = 0.0
    radial_distance_m: float = 0.0


@dataclass(frozen=True)
class FlightLine:
    sortie_index: int
    line_index: int
    direction_sign: int
    images: tuple[ImagePosition, ...]
    cross_track_m: float


@dataclass(frozen=True)
class SelectedImage:
    image: ImagePosition
    grid_line_rank: int
    image_rank_on_line: int
    source_sortie_index: int
    source_line_index: int


@dataclass(frozen=True)
class GridSelection:
    images: tuple[SelectedImage, ...]
    mission_index: int
    mission_start: datetime
    mission_end: datetime
    selected_sortie_indices: tuple[int, ...]
    flight_axis_bearing_deg: float
    detected_line_count: int
    eligible_line_count: int
    grid_lines: int
    images_per_line: int
    block_center_cross_track_m: float
    block_center_along_track_m: float
    farthest_radial_distance_m: float
    metres_per_degree_latitude: float
    metres_per_degree_longitude: float


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_capture_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) < 19:
        return None
    try:
        return datetime.strptime(value[:19], DATETIME_FORMAT)
    except ValueError:
        return None


def _metres_per_degree(latitude_deg: float) -> tuple[float, float]:
    latitude_rad = math.radians(latitude_deg)
    metres_per_degree_latitude = (
        111132.92
        - 559.82 * math.cos(2.0 * latitude_rad)
        + 1.175 * math.cos(4.0 * latitude_rad)
        - 0.0023 * math.cos(6.0 * latitude_rad)
    )
    metres_per_degree_longitude = (
        111412.84 * math.cos(latitude_rad)
        - 93.5 * math.cos(3.0 * latitude_rad)
        + 0.118 * math.cos(5.0 * latitude_rad)
    )
    return metres_per_degree_latitude, metres_per_degree_longitude


def _longitude_delta(longitude: float, center_longitude: float) -> float:
    return (longitude - center_longitude + 180.0) % 360.0 - 180.0


def _angular_difference_deg(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def _axis_difference_deg(left: float, right: float) -> float:
    difference = _angular_difference_deg(left, right)
    return min(difference, 180.0 - difference)


def _flight_axis_bearing(images: Sequence[ImagePosition]) -> float:
    # Doubling the yaw angles makes reciprocal headings (0/180 degrees) one axis.
    cosine = sum(math.cos(math.radians(2.0 * image.flight_yaw_deg)) for image in images)
    sine = sum(math.sin(math.radians(2.0 * image.flight_yaw_deg)) for image in images)
    if math.hypot(cosine, sine) < 1.0e-12:
        raise ValueError("Cannot determine a dominant flight axis from FlightYawDegree.")
    return (0.5 * math.degrees(math.atan2(sine, cosine))) % 180.0


def read_exif_positions(
    image_dir: Path,
    *,
    exiftool: str = "exiftool",
) -> tuple[list[ImagePosition], list[dict[str, str]], int]:
    executable = shutil.which(exiftool)
    if executable is None:
        raise RuntimeError(
            f"ExifTool executable not found: {exiftool!r}. "
            "Install ExifTool or pass --exiftool with its executable path."
        )

    command = [
        executable,
        "-json",
        "-n",
        "-r",
        "-GPSLatitude",
        "-GPSLongitude",
        "-GPSAltitude",
        "-DateTimeOriginal",
        "-FlightYawDegree",
    ]
    for extension in IMAGE_EXTENSIONS:
        command.extend(["-ext", extension])
    command.append(str(image_dir))

    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    decoded = json.loads(completed.stdout)
    if not isinstance(decoded, list):
        raise ValueError("ExifTool JSON output must be a list.")

    positioned: list[ImagePosition] = []
    excluded: list[dict[str, str]] = []
    for item in decoded:
        if not isinstance(item, dict) or not item.get("SourceFile"):
            continue
        source_path = Path(str(item["SourceFile"])).expanduser().resolve()
        latitude = _finite_float(item.get("GPSLatitude"))
        longitude = _finite_float(item.get("GPSLongitude"))
        altitude = _finite_float(item.get("GPSAltitude"))
        capture_time = _parse_capture_time(item.get("DateTimeOriginal"))
        flight_yaw = _finite_float(item.get("FlightYawDegree"))
        reasons = []
        if (
            latitude is None
            or longitude is None
            or not -90.0 <= latitude <= 90.0
            or not -180.0 <= longitude <= 180.0
        ):
            reasons.append("invalid_or_missing_gps")
        if capture_time is None:
            reasons.append("invalid_or_missing_datetime_original")
        if flight_yaw is None:
            reasons.append("invalid_or_missing_flight_yaw_degree")
        if reasons:
            excluded.append(
                {"source_path": str(source_path), "reason": ";".join(reasons)}
            )
            continue
        positioned.append(
            ImagePosition(
                source_path=source_path,
                latitude=latitude,
                longitude=longitude,
                altitude_m=altitude,
                capture_time=capture_time,
                flight_yaw_deg=flight_yaw % 360.0,
            )
        )
    positioned.sort(key=lambda image: (image.capture_time, str(image.source_path)))
    return positioned, excluded, len(decoded)


def split_sorties(
    positions: Sequence[ImagePosition], *, sortie_gap_seconds: float
) -> list[list[ImagePosition]]:
    if sortie_gap_seconds <= 0:
        raise ValueError("sortie_gap_seconds must be positive.")
    if not positions:
        return []
    ordered = sorted(positions, key=lambda image: (image.capture_time, str(image.source_path)))
    sorties: list[list[ImagePosition]] = [[ordered[0]]]
    for image in ordered[1:]:
        gap = (image.capture_time - sorties[-1][-1].capture_time).total_seconds()
        if gap > sortie_gap_seconds:
            sorties.append([image])
        else:
            sorties[-1].append(image)
    return sorties


def _localize_sortie(
    images: Sequence[ImagePosition],
    *,
    center_latitude: float,
    center_longitude: float,
    flight_axis_bearing_deg: float,
) -> tuple[list[ImagePosition], float, float]:
    metres_lat, metres_lon = _metres_per_degree(center_latitude)
    bearing_rad = math.radians(flight_axis_bearing_deg)
    along_east = math.sin(bearing_rad)
    along_north = math.cos(bearing_rad)
    cross_east = math.cos(bearing_rad)
    cross_north = -math.sin(bearing_rad)
    localized = []
    for image in images:
        east_m = _longitude_delta(image.longitude, center_longitude) * metres_lon
        north_m = (image.latitude - center_latitude) * metres_lat
        localized.append(
            ImagePosition(
                source_path=image.source_path,
                latitude=image.latitude,
                longitude=image.longitude,
                altitude_m=image.altitude_m,
                capture_time=image.capture_time,
                flight_yaw_deg=image.flight_yaw_deg,
                east_m=east_m,
                north_m=north_m,
                along_track_m=east_m * along_east + north_m * along_north,
                cross_track_m=east_m * cross_east + north_m * cross_north,
                radial_distance_m=math.hypot(east_m, north_m),
            )
        )
    return localized, metres_lat, metres_lon


def detect_flight_lines(
    images: Sequence[ImagePosition],
    *,
    sortie_index: int,
    flight_axis_bearing_deg: float,
    line_yaw_tolerance_deg: float,
) -> list[FlightLine]:
    if not 0 < line_yaw_tolerance_deg < 90:
        raise ValueError("line_yaw_tolerance_deg must be between 0 and 90.")
    ordered = sorted(images, key=lambda image: (image.capture_time, str(image.source_path)))
    positive_intervals = [
        (right.capture_time - left.capture_time).total_seconds()
        for left, right in zip(ordered, ordered[1:])
        if right.capture_time > left.capture_time
    ]
    median_interval = statistics.median(positive_intervals) if positive_intervals else 1.0
    same_line_gap_seconds = max(10.0, 5.0 * median_interval)

    groups: list[tuple[int, list[ImagePosition]]] = []
    current: list[ImagePosition] = []
    current_direction: int | None = None
    previous: ImagePosition | None = None

    def finish_current() -> None:
        nonlocal current, current_direction
        if current and current_direction is not None:
            groups.append((current_direction, current))
        current = []
        current_direction = None

    for image in ordered:
        if _axis_difference_deg(image.flight_yaw_deg, flight_axis_bearing_deg) > line_yaw_tolerance_deg:
            finish_current()
            previous = image
            continue
        forward_difference = _angular_difference_deg(
            image.flight_yaw_deg, flight_axis_bearing_deg
        )
        direction = 1 if forward_difference <= 90.0 else -1
        gap = (
            (image.capture_time - previous.capture_time).total_seconds()
            if previous is not None
            else 0.0
        )
        if (
            current
            and (direction != current_direction or gap > same_line_gap_seconds)
        ):
            finish_current()
        if not current:
            current_direction = direction
        current.append(image)
        previous = image
    finish_current()

    lines = []
    for line_index, (direction, group) in enumerate(groups, start=1):
        lines.append(
            FlightLine(
                sortie_index=sortie_index,
                line_index=line_index,
                direction_sign=direction,
                images=tuple(group),
                cross_track_m=statistics.median(
                    image.cross_track_m for image in group
                ),
            )
        )
    return lines


def _centered_image_window(
    images: Sequence[ImagePosition], images_per_line: int
) -> tuple[ImagePosition, ...] | None:
    eligible = sorted(
        images,
        key=lambda image: (image.along_track_m, image.capture_time, str(image.source_path)),
    )
    if len(eligible) < images_per_line:
        return None
    windows = []
    for start in range(0, len(eligible) - images_per_line + 1):
        window = tuple(eligible[start : start + images_per_line])
        along = [image.along_track_m for image in window]
        score = (
            abs((along[0] + along[-1]) / 2.0),
            max(abs(value) for value in along),
            along[-1] - along[0],
            tuple(str(image.source_path) for image in window),
        )
        windows.append((score, window))
    return min(windows, key=lambda item: item[0])[1]


def select_flight_grid_chunk(
    positions: Sequence[ImagePosition],
    *,
    center_latitude: float,
    center_longitude: float,
    grid_lines: int,
    images_per_line: int,
    sortie_gap_seconds: float,
    mission_gap_seconds: float,
    line_yaw_tolerance_deg: float,
    max_distance_m: float | None = None,
) -> GridSelection:
    if not -90.0 <= center_latitude <= 90.0:
        raise ValueError("center latitude must be between -90 and 90 degrees.")
    if not -180.0 <= center_longitude <= 180.0:
        raise ValueError("center longitude must be between -180 and 180 degrees.")
    if grid_lines < 1 or images_per_line < 1:
        raise ValueError("grid_lines and images_per_line must be at least one.")
    if mission_gap_seconds <= sortie_gap_seconds:
        raise ValueError("mission_gap_seconds must exceed sortie_gap_seconds.")
    if max_distance_m is not None and max_distance_m <= 0:
        raise ValueError("max_distance_m must be positive when provided.")

    candidate_blocks = []
    missions = split_sorties(positions, sortie_gap_seconds=mission_gap_seconds)
    diagnostics = []
    for mission_index, mission in enumerate(missions, start=1):
        axis = _flight_axis_bearing(mission)
        local_mission, metres_lat, metres_lon = _localize_sortie(
            mission,
            center_latitude=center_latitude,
            center_longitude=center_longitude,
            flight_axis_bearing_deg=axis,
        )
        sorties = split_sorties(
            local_mission, sortie_gap_seconds=sortie_gap_seconds
        )
        all_lines = []
        for sortie_index, sortie in enumerate(sorties, start=1):
            all_lines.extend(
                detect_flight_lines(
                    sortie,
                    sortie_index=sortie_index,
                    flight_axis_bearing_deg=axis,
                    line_yaw_tolerance_deg=line_yaw_tolerance_deg,
                )
            )

        line_windows = []
        for line in all_lines:
            eligible_images = [
                image
                for image in line.images
                if max_distance_m is None
                or image.radial_distance_m <= max_distance_m
            ]
            window = _centered_image_window(eligible_images, images_per_line)
            if window is not None:
                line_windows.append((line, window))
        line_windows.sort(
            key=lambda item: (
                item[0].cross_track_m,
                item[0].sortie_index,
                item[0].line_index,
            )
        )
        diagnostics.append(
            f"mission {mission_index}: sorties={len(sorties)}, "
            f"detected_lines={len(all_lines)}, eligible_lines={len(line_windows)}"
        )
        if len(line_windows) < grid_lines:
            continue

        for block_start in range(0, len(line_windows) - grid_lines + 1):
            block = line_windows[block_start : block_start + grid_lines]
            cross_values = [line.cross_track_m for line, _ in block]
            cross_center = (cross_values[0] + cross_values[-1]) / 2.0
            along_centers = [
                (window[0].along_track_m + window[-1].along_track_m) / 2.0
                for _, window in block
            ]
            along_center = statistics.median(along_centers)
            selected_positions = [image for _, window in block for image in window]
            farthest = max(image.radial_distance_m for image in selected_positions)
            score = (
                math.hypot(cross_center, along_center),
                farthest,
                abs(cross_center),
                mission[0].capture_time,
                block_start,
            )
            candidate_blocks.append(
                (
                    score,
                    mission_index,
                    mission,
                    axis,
                    metres_lat,
                    metres_lon,
                    all_lines,
                    line_windows,
                    block,
                    cross_center,
                    along_center,
                    farthest,
                )
            )

    if not candidate_blocks:
        detail = "; ".join(diagnostics) if diagnostics else "no missions detected"
        raise ValueError(
            f"No acquisition mission can provide a complete {grid_lines} x "
            f"{images_per_line} flight-line grid. {detail}."
        )

    (
        _,
        mission_index,
        mission,
        axis,
        metres_lat,
        metres_lon,
        all_lines,
        line_windows,
        block,
        cross_center,
        along_center,
        farthest,
    ) = min(candidate_blocks, key=lambda item: item[0])

    selected = []
    for grid_line_rank, (line, window) in enumerate(block, start=1):
        ordered_window = sorted(
            window,
            key=lambda image: (
                image.along_track_m,
                image.capture_time,
                str(image.source_path),
            ),
        )
        for image_rank, image in enumerate(ordered_window, start=1):
            selected.append(
                SelectedImage(
                    image=image,
                    grid_line_rank=grid_line_rank,
                    image_rank_on_line=image_rank,
                    source_sortie_index=line.sortie_index,
                    source_line_index=line.line_index,
                )
            )

    return GridSelection(
        images=tuple(selected),
        mission_index=mission_index,
        mission_start=mission[0].capture_time,
        mission_end=mission[-1].capture_time,
        selected_sortie_indices=tuple(
            sorted({item.source_sortie_index for item in selected})
        ),
        flight_axis_bearing_deg=axis,
        detected_line_count=len(all_lines),
        eligible_line_count=len(line_windows),
        grid_lines=grid_lines,
        images_per_line=images_per_line,
        block_center_cross_track_m=cross_center,
        block_center_along_track_m=along_center,
        farthest_radial_distance_m=farthest,
        metres_per_degree_latitude=metres_lat,
        metres_per_degree_longitude=metres_lon,
    )


def materialize_chunk(
    selection: GridSelection,
    *,
    output_dir: Path,
    source_image_dir: Path,
    center_latitude: float,
    center_longitude: float,
    images_scanned: int,
    excluded_images: Sequence[dict[str, str]],
    sortie_gap_seconds: float,
    mission_gap_seconds: float,
    line_yaw_tolerance_deg: float,
    max_distance_m: float | None,
    exiftool: str,
) -> dict[str, Any]:
    output_dir = Path(output_dir).expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output_dir}")
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows = []
    for selected in selection.images:
        image = selected.image
        destination = images_dir / (
            f"L{selected.grid_line_rank:02d}_I{selected.image_rank_on_line:02d}_"
            f"{image.source_path.name}"
        )
        shutil.copy2(image.source_path, destination)
        manifest_rows.append(
            {
                "grid_line_rank": selected.grid_line_rank,
                "image_rank_on_line": selected.image_rank_on_line,
                "source_sortie_index": selected.source_sortie_index,
                "source_line_index": selected.source_line_index,
                "source_path": str(image.source_path),
                "copied_path": str(destination),
                "capture_time": image.capture_time.isoformat(),
                "flight_yaw_deg": image.flight_yaw_deg,
                "latitude": image.latitude,
                "longitude": image.longitude,
                "altitude_m": "" if image.altitude_m is None else image.altitude_m,
                "east_m": image.east_m,
                "north_m": image.north_m,
                "along_track_m": image.along_track_m,
                "cross_track_m": image.cross_track_m,
                "radial_distance_m": image.radial_distance_m,
            }
        )

    manifest_path = output_dir / "selected_images.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(manifest_rows[0]))
        writer.writeheader()
        writer.writerows(manifest_rows)

    report = {
        "status": "geotagged_flight_grid_chunk_ready",
        "selection_geometry": "single_mission_balanced_flight_line_grid",
        "center_crs": "EPSG:4326",
        "center_latitude": center_latitude,
        "center_longitude": center_longitude,
        "grid_lines": selection.grid_lines,
        "images_per_line": selection.images_per_line,
        "selected_image_count": len(selection.images),
        "selected_mission_index": selection.mission_index,
        "selected_mission_start": selection.mission_start.isoformat(),
        "selected_mission_end": selection.mission_end.isoformat(),
        "selected_sortie_indices": list(selection.selected_sortie_indices),
        "flight_axis_bearing_deg": selection.flight_axis_bearing_deg,
        "detected_line_count": selection.detected_line_count,
        "eligible_line_count": selection.eligible_line_count,
        "block_center_cross_track_m": selection.block_center_cross_track_m,
        "block_center_along_track_m": selection.block_center_along_track_m,
        "farthest_radial_distance_m": selection.farthest_radial_distance_m,
        "sortie_gap_seconds": sortie_gap_seconds,
        "mission_gap_seconds": mission_gap_seconds,
        "line_yaw_tolerance_deg": line_yaw_tolerance_deg,
        "max_distance_m": max_distance_m,
        "source_image_dir": str(source_image_dir),
        "output_dir": str(output_dir),
        "images_dir": str(images_dir),
        "selected_images_csv": str(manifest_path),
        "images_scanned": images_scanned,
        "images_with_required_metadata": images_scanned - len(excluded_images),
        "excluded_image_count": len(excluded_images),
        "excluded_images": list(excluded_images),
        "metres_per_degree_latitude": selection.metres_per_degree_latitude,
        "metres_per_degree_longitude": selection.metres_per_degree_longitude,
        "exiftool": exiftool,
        "image_extensions": list(IMAGE_EXTENSIONS),
    }
    report_path = output_dir / "extraction_report.json"
    report["extraction_report_json"] = str(report_path)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def run_extraction(
    *,
    image_dir: Path,
    center_latitude: float,
    center_longitude: float,
    grid_lines: int,
    images_per_line: int,
    output_dir: Path,
    sortie_gap_seconds: float = 300.0,
    mission_gap_seconds: float = 3600.0,
    line_yaw_tolerance_deg: float = 20.0,
    max_distance_m: float | None = None,
    exiftool: str = "exiftool",
) -> dict[str, Any]:
    image_dir = Path(image_dir).expanduser().resolve()
    if not image_dir.is_dir():
        raise NotADirectoryError(f"Input image directory does not exist: {image_dir}")
    positions, excluded, scanned = read_exif_positions(image_dir, exiftool=exiftool)
    selection = select_flight_grid_chunk(
        positions,
        center_latitude=center_latitude,
        center_longitude=center_longitude,
        grid_lines=grid_lines,
        images_per_line=images_per_line,
        sortie_gap_seconds=sortie_gap_seconds,
        mission_gap_seconds=mission_gap_seconds,
        line_yaw_tolerance_deg=line_yaw_tolerance_deg,
        max_distance_m=max_distance_m,
    )
    return materialize_chunk(
        selection,
        output_dir=output_dir,
        source_image_dir=image_dir,
        center_latitude=center_latitude,
        center_longitude=center_longitude,
        images_scanned=scanned,
        excluded_images=excluded,
        sortie_gap_seconds=sortie_gap_seconds,
        mission_gap_seconds=mission_gap_seconds,
        line_yaw_tolerance_deg=line_yaw_tolerance_deg,
        max_distance_m=max_distance_m,
        exiftool=exiftool,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Copy a complete flight-line image grid from one DJI acquisition mission around "
            "an EPSG:4326 coordinate."
        )
    )
    parser.add_argument("--image-dir", required=True, type=Path)
    parser.add_argument("--lat", required=True, type=float)
    parser.add_argument("--lon", required=True, type=float)
    parser.add_argument("--grid-lines", required=True, type=int)
    parser.add_argument("--images-per-line", required=True, type=int)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--sortie-gap-seconds", type=float, default=300.0)
    parser.add_argument("--mission-gap-seconds", type=float, default=3600.0)
    parser.add_argument("--line-yaw-tolerance-deg", type=float, default=20.0)
    parser.add_argument(
        "--max-distance-m",
        type=float,
        help="Use only camera centers within this radius.",
    )
    parser.add_argument(
        "--exiftool",
        default="exiftool",
        help="ExifTool executable name or path (default: exiftool).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = run_extraction(
            image_dir=args.image_dir,
            center_latitude=args.lat,
            center_longitude=args.lon,
            grid_lines=args.grid_lines,
            images_per_line=args.images_per_line,
            output_dir=args.out_dir,
            sortie_gap_seconds=args.sortie_gap_seconds,
            mission_gap_seconds=args.mission_gap_seconds,
            line_yaw_tolerance_deg=args.line_yaw_tolerance_deg,
            max_distance_m=args.max_distance_m,
            exiftool=args.exiftool,
        )
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"extract_geotagged_image_chunk: error: {exc}", file=sys.stderr)
        return 1

    print(f"status={report['status']}")
    print(
        f"grid={report['grid_lines']}x{report['images_per_line']} "
        f"images={report['selected_image_count']}"
    )
    print(f"mission={report['selected_mission_start']}--{report['selected_mission_end']}")
    print(f"sorties={report['selected_sortie_indices']}")
    print(f"images={report['images_dir']}")
    print(f"manifest={report['selected_images_csv']}")
    print(f"report={report['extraction_report_json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
