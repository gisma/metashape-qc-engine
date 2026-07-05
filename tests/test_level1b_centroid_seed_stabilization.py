from __future__ import annotations

from pathlib import Path

import numpy as np

from metashape_qc_engine import level1b_centroid_seed_stabilization as stabilization



def test_density_support_and_multiscale_tracks_recover_persistent_centres() -> None:
    rows = []
    point_sets = []
    for phase_index, phase in enumerate(("phase_00", "phase_01", "phase_02", "phase_03")):
        for ranger_index, ranger in enumerate((0.1, 0.2, 0.3)):
            rows.append(
                {
                    "seed_realization_id": phase,
                    "run_ranger": ranger,
                }
            )
            jitter = np.asarray(
                [phase_index % 2, ranger_index % 2], dtype=float
            )
            point_sets.append(
                np.asarray([[20.0, 20.0], [60.0, 60.0]]) + jitter
            )
    peaks, density = stabilization._density_peaks(point_sets, (90, 90), 4)
    supported = stabilization._supported_peaks(
        peaks,
        density,
        point_sets,
        rows,
        4,
        minimum_run_support=6,
        minimum_phase_support=3,
        minimum_ranger_support=2,
    )
    assert len(supported) == 2
    assert all(row["run_support"] == 12 for row in supported)

    second_scale = [
        {**row, "row": row["row"] + 1, "col": row["col"] + 1}
        for row in supported
    ]
    tracks = stabilization._mutual_scale_tracks(
        [supported, second_scale], [4, 7]
    )
    seeds = stabilization._stable_seed_points(tracks, [supported, second_scale], 0, 4)
    assert len(tracks) == 2
    assert len(seeds) == 2
    assert all(seed["scale_support"] == 2 for seed in seeds)


def test_seed_grid_uses_saga_nodata_and_unique_positive_seed_ids(
    tmp_path: Path,
) -> None:
    path = tmp_path / "seeds.sgrd"
    stabilization._write_seed_grid(
        path,
        (4, 5),
        [
            {"row": 1, "col": 1},
            {"row": 2, "col": 3},
        ],
    )
    values = np.fromfile(path.with_suffix(".sdat"), dtype="<f4").reshape(4, 5)
    assert values[1, 1] == 1
    assert values[2, 3] == 2
    assert np.sum(values != stabilization.SAGA_NODATA) == 2
