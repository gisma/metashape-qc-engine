from __future__ import annotations

from datetime import datetime, timedelta
import importlib.util
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "extract_geotagged_image_chunk.py"
SPEC = importlib.util.spec_from_file_location("extract_geotagged_image_chunk", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
chunk = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = chunk
SPEC.loader.exec_module(chunk)


def _synthetic_grid(
    tmp_path: Path,
    *,
    line_count: int = 9,
    images_per_line: int = 11,
    battery_break_after_line: int | None = None,
):
    tmp_path.mkdir(parents=True, exist_ok=True)
    center_lat = 50.0
    center_lon = 8.0
    metres_lat, metres_lon = chunk._metres_per_degree(center_lat)
    current_time = datetime(2024, 6, 7, 12, 0, 0)
    positions = []
    for line_index in range(line_count):
        if battery_break_after_line == line_index:
            current_time += timedelta(seconds=600)
        cross_m = (line_index - (line_count - 1) / 2.0) * 30.0
        direction = 1 if line_index % 2 == 0 else -1
        along_values = [
            (image_index - (images_per_line - 1) / 2.0) * 20.0
            for image_index in range(images_per_line)
        ]
        if direction < 0:
            along_values.reverse()
        for image_index, along_m in enumerate(along_values):
            path = tmp_path / f"L{line_index:02d}_I{image_index:02d}.JPG"
            path.write_bytes(f"{line_index}-{image_index}".encode())
            positions.append(
                chunk.ImagePosition(
                    source_path=path,
                    latitude=center_lat + along_m / metres_lat,
                    longitude=center_lon + cross_m / metres_lon,
                    altitude_m=100.0,
                    capture_time=current_time,
                    flight_yaw_deg=0.0 if direction > 0 else 180.0,
                )
            )
            current_time += timedelta(seconds=2)
        current_time += timedelta(seconds=10)
    return positions, center_lat, center_lon


def test_balanced_grid_selects_seven_lines_and_seven_images_each(
    tmp_path: Path,
) -> None:
    positions, latitude, longitude = _synthetic_grid(tmp_path)

    selection = chunk.select_flight_grid_chunk(
        positions,
        center_latitude=latitude,
        center_longitude=longitude,
        grid_lines=7,
        images_per_line=7,
        sortie_gap_seconds=300,
        mission_gap_seconds=3600,
        line_yaw_tolerance_deg=20,
        max_distance_m=500,
    )

    assert len(selection.images) == 49
    assert {
        rank: sum(item.grid_line_rank == rank for item in selection.images)
        for rank in range(1, 8)
    } == {rank: 7 for rank in range(1, 8)}
    assert abs(selection.block_center_cross_track_m) < 1.0e-6
    assert abs(selection.block_center_along_track_m) < 1.0e-6


def test_adjacent_battery_sorties_can_form_one_centered_mission_grid(
    tmp_path: Path,
) -> None:
    positions, latitude, longitude = _synthetic_grid(
        tmp_path, battery_break_after_line=4
    )

    selection = chunk.select_flight_grid_chunk(
        positions,
        center_latitude=latitude,
        center_longitude=longitude,
        grid_lines=7,
        images_per_line=7,
        sortie_gap_seconds=300,
        mission_gap_seconds=3600,
        line_yaw_tolerance_deg=20,
        max_distance_m=500,
    )

    assert selection.selected_sortie_indices == (1, 2)
    assert len(selection.images) == 49
    assert abs(selection.block_center_cross_track_m) < 1.0e-6


def test_incomplete_grid_fails_instead_of_mixing_unrelated_missions(
    tmp_path: Path,
) -> None:
    first, latitude, longitude = _synthetic_grid(tmp_path / "first", line_count=3)
    second, _, _ = _synthetic_grid(tmp_path / "second", line_count=3)
    offset = timedelta(hours=2)
    second = [
        chunk.ImagePosition(
            source_path=image.source_path,
            latitude=image.latitude,
            longitude=image.longitude,
            altitude_m=image.altitude_m,
            capture_time=image.capture_time + offset,
            flight_yaw_deg=image.flight_yaw_deg,
        )
        for image in second
    ]

    with pytest.raises(ValueError, match="No acquisition mission can provide"):
        chunk.select_flight_grid_chunk(
            [*first, *second],
            center_latitude=latitude,
            center_longitude=longitude,
            grid_lines=5,
            images_per_line=5,
            sortie_gap_seconds=300,
            mission_gap_seconds=3600,
            line_yaw_tolerance_deg=20,
            max_distance_m=500,
        )


def test_exiftool_reads_required_dji_line_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    valid = tmp_path / "DJI_0001.JPG"
    invalid = tmp_path / "DJI_0002.JPG"
    payload = [
        {
            "SourceFile": str(valid),
            "GPSLatitude": 50.0,
            "GPSLongitude": 8.0,
            "GPSAltitude": 120.0,
            "DateTimeOriginal": "2024:06:07 12:00:00",
            "FlightYawDegree": 179.0,
        },
        {
            "SourceFile": str(invalid),
            "GPSLatitude": 50.0,
            "GPSLongitude": 8.0,
        },
    ]
    captured = {}
    monkeypatch.setattr(chunk.shutil, "which", lambda name: "/usr/bin/exiftool")

    def fake_run(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(stdout=json.dumps(payload))

    monkeypatch.setattr(chunk.subprocess, "run", fake_run)

    positions, excluded, scanned = chunk.read_exif_positions(tmp_path)

    assert scanned == 2
    assert len(positions) == 1
    assert positions[0].flight_yaw_deg == 179.0
    assert positions[0].capture_time == datetime(2024, 6, 7, 12, 0, 0)
    assert excluded == [
        {
            "source_path": str(invalid.resolve()),
            "reason": (
                "invalid_or_missing_datetime_original;"
                "invalid_or_missing_flight_yaw_degree"
            ),
        }
    ]
    assert "-DateTimeOriginal" in captured["command"]
    assert "-FlightYawDegree" in captured["command"]
    assert "-r" in captured["command"]


def test_materialization_writes_balanced_grid_names_and_provenance(
    tmp_path: Path,
) -> None:
    positions, latitude, longitude = _synthetic_grid(tmp_path / "source")
    selection = chunk.select_flight_grid_chunk(
        positions,
        center_latitude=latitude,
        center_longitude=longitude,
        grid_lines=3,
        images_per_line=3,
        sortie_gap_seconds=300,
        mission_gap_seconds=3600,
        line_yaw_tolerance_deg=20,
        max_distance_m=500,
    )
    output = tmp_path / "chunk"

    report = chunk.materialize_chunk(
        selection,
        output_dir=output,
        source_image_dir=tmp_path / "source",
        center_latitude=latitude,
        center_longitude=longitude,
        images_scanned=len(positions),
        excluded_images=[],
        sortie_gap_seconds=300,
        mission_gap_seconds=3600,
        line_yaw_tolerance_deg=20,
        max_distance_m=500,
        exiftool="exiftool",
    )

    copied = sorted((output / "images").iterdir())
    assert len(copied) == 9
    assert copied[0].name.startswith("L01_I01_")
    decoded = json.loads((output / "extraction_report.json").read_text())
    assert decoded["selection_geometry"] == "single_mission_balanced_flight_line_grid"
    assert decoded["grid_lines"] == 3
    assert decoded["images_per_line"] == 3
    assert decoded["selected_image_count"] == 9
    assert decoded["selected_sortie_indices"] == [1]
    assert report["status"] == "geotagged_flight_grid_chunk_ready"


def test_nonempty_output_directory_is_refused(tmp_path: Path) -> None:
    positions, latitude, longitude = _synthetic_grid(tmp_path / "source")
    selection = chunk.select_flight_grid_chunk(
        positions,
        center_latitude=latitude,
        center_longitude=longitude,
        grid_lines=1,
        images_per_line=1,
        sortie_gap_seconds=300,
        mission_gap_seconds=3600,
        line_yaw_tolerance_deg=20,
    )
    output = tmp_path / "existing"
    output.mkdir()
    (output / "old.txt").write_text("old")

    with pytest.raises(FileExistsError, match="not empty"):
        chunk.materialize_chunk(
            selection,
            output_dir=output,
            source_image_dir=tmp_path / "source",
            center_latitude=latitude,
            center_longitude=longitude,
            images_scanned=len(positions),
            excluded_images=[],
            sortie_gap_seconds=300,
            mission_gap_seconds=3600,
            line_yaw_tolerance_deg=20,
            max_distance_m=None,
            exiftool="exiftool",
        )
