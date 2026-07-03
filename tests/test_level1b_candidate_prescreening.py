from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

import metashape_qc_engine.level1b_feature_range as feature_range
import metashape_qc_engine.level1b_candidate_prescreening as prescreen
from metashape_qc_engine.level1b_candidate_prescreening import (
    Level1BCandidatePrescreeningConfig,
    build_logarithmic_lag_pixels,
    find_stable_sill_fraction_crossings,
    run_candidate_prescreening_step,
)
from metashape_qc_engine.level1b_candidate_response_surface import (
    group_rows_by_candidate_scale,
    source_candidate_radius_m,
)


def _config(tmp_path: Path, **overrides: object) -> Level1BCandidatePrescreeningConfig:
    stack = tmp_path / "scaled.tif"
    mask = tmp_path / "mask.tif"
    stack.write_bytes(b"stack")
    mask.write_bytes(b"mask")
    values: dict[str, object] = {
        "candidate_id": "scene",
        "output_dir": tmp_path,
        "feature_space_stack_path": stack,
        "valid_mask_path": mask,
        "pixel_size_m": 1.0,
        "band_count": 6,
        "radius_min_m": 1.0,
        "radius_max_m": 6.0,
        "lag_count": 6,
        "lag_spacing": "logarithmic",
        "directions": ((1, 0), (1, 1), (0, 1), (-1, 1)),
        "pair_sample_n_per_direction": 100,
        "min_valid_pairs_per_direction": 10,
        "sill_tail_fraction": 0.34,
        "sill_fraction_targets": (0.25, 0.5, 0.75, 0.95),
        "stable_crossing_window": 2,
        "plateau_rel_tol": 0.1,
        "anisotropy_ratio_threshold": 1.5,
        "candidate_budget": 12,
        "ranger_level_policy": "hsm_main_interval_lower_mode_upper",
        "sample_n": 100,
        "knn_k_policy": "auto_hsm_plateau",
        "knn_k_candidates": (8, 13, 21),
        "hsm_stability_rel_tol": 0.1,
        "hsm_plateau_window": 2,
        "max_distance_sample_n": 50,
        "seed": 1,
        "overwrite": False,
    }
    values.update(overrides)
    return Level1BCandidatePrescreeningConfig(**values)


def _curve() -> list[dict[str, object]]:
    values = (0.10, 0.30, 0.60, 0.90, 1.00, 1.00)
    rows = []
    for index, value in enumerate(values, start=1):
        rows.append(
            {
                "lag_index": index,
                "lag_px": index,
                "lag_m": float(index),
                "semivariance": value,
                "directional_semivariance": [
                    {
                        "direction": list(direction),
                        "offset_px": list(direction),
                        "actual_distance_m": float(index),
                        "pair_count": 100,
                        "semivariance": value,
                    }
                    for direction in ((1, 0), (1, 1), (0, 1), (-1, 1))
                ],
            }
        )
    return rows


def _install_data_stubs(monkeypatch) -> None:
    stack = np.arange(6 * 10 * 10, dtype=np.float32).reshape(6, 10, 10)
    mask = np.ones((10, 10), dtype=np.uint8)
    monkeypatch.setattr(
        prescreen,
        "read_feature_stack_and_mask",
        lambda *_args: (stack, mask),
    )
    monkeypatch.setattr(
        prescreen,
        "compute_multiband_variogram",
        lambda *_args: _curve(),
    )
    monkeypatch.setattr(
        prescreen,
        "derive_ranger_candidates",
        lambda *_args: (
            [
                {
                    "ranger": 2.0,
                    "modal_interval_lower": 1.5,
                    "modal_interval_upper": 2.5,
                }
            ],
            50,
            {
                "plateau_found": True,
                "selected_knn_k": 8,
                "hsm_ranger_curve": [],
                "hsm_plateau_windows": [],
            },
        ),
    )


def test_logarithmic_lags_stay_inside_domain_and_are_deterministic() -> None:
    first = build_logarithmic_lag_pixels(0.2, 3.87, 0.1, 32)
    second = build_logarithmic_lag_pixels(0.2, 3.87, 0.1, 32)
    assert first == second
    assert first == sorted(set(first))
    assert min(first) >= 2
    assert max(first) <= 38


def test_stable_sill_crossings_are_support_points_not_classes() -> None:
    crossings = find_stable_sill_fraction_crossings(
        _curve(), 1.0, (0.25, 0.5, 0.75, 0.95), 2
    )
    assert [row["lag_px"] for row in crossings] == [2, 3, 4, 5]
    assert all("class" not in key for row in crossings for key in row)


def test_step_materializes_step9_compatible_scene_adaptive_population(
    tmp_path: Path, monkeypatch
) -> None:
    _install_data_stubs(monkeypatch)
    report = run_candidate_prescreening_step(_config(tmp_path))
    assert report["status"] == "ok"
    assert report["scale_family_count"] == 4
    assert report["candidate_count"] == 12

    population_path = (
        tmp_path
        / "level1b"
        / "candidate_pre_screening"
        / "candidate_population.json"
    )
    payload = json.loads(population_path.read_text(encoding="utf-8"))
    rows = payload["candidates"]
    assert payload["no_segmentation_performed"] is True
    assert payload["no_ranking_performed"] is True
    assert payload["no_final_selection_performed"] is True
    assert len({row["candidate_id"] for row in rows}) == 12
    assert len({row["perturbation_id"] for row in rows}) == 12

    groups = group_rows_by_candidate_scale(rows)
    assert [group["candidate_scale_group_id"] for group in groups] == [
        "scale_001",
        "scale_002",
        "scale_003",
        "scale_004",
    ]
    for group in groups:
        assert len(group["rows"]) == 3
        assert sum(bool(row["is_baseline"]) for row in group["rows"]) == 1
        for row in group["rows"]:
            assert source_candidate_radius_m(row) == row["radius_m"]
            expected_area = math.pi * row["radius_m"] ** 2
            assert row["area_m2"] == expected_area
            assert row["minsize_px"] == round(expected_area)
            assert row["spatialr_px"] == round(row["radius_m"])


def test_candidate_budget_fails_instead_of_truncating(
    tmp_path: Path, monkeypatch
) -> None:
    _install_data_stubs(monkeypatch)
    report = run_candidate_prescreening_step(
        _config(tmp_path, candidate_budget=11)
    )
    assert report["status"] == "failed"
    assert report["candidate_count"] == 0
    assert any("candidate budget 11" in reason for reason in report["failure_reasons"])
    assert not (
        tmp_path
        / "level1b"
        / "candidate_pre_screening"
        / "candidate_population.json"
    ).exists()


def test_missing_stable_scale_support_fails_without_fixed_anchor_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    _install_data_stubs(monkeypatch)
    sparse_curve = _curve()
    for row in sparse_curve:
        row["semivariance"] = 0.1
        for direction in row["directional_semivariance"]:
            direction["semivariance"] = 0.1
    monkeypatch.setattr(
        prescreen,
        "find_stable_sill_fraction_crossings",
        lambda *_args: [
            {
                "sill_fraction_target": value,
                "stable_crossing_found": value == 0.25,
                **(
                    {"lag_px": 1, "radius_m": 1.0}
                    if value == 0.25
                    else {}
                ),
            }
            for value in (0.25, 0.5, 0.75, 0.95)
        ],
    )
    report = run_candidate_prescreening_step(_config(tmp_path))
    assert report["status"] == "failed"
    assert any("fewer than two distinct" in reason for reason in report["failure_reasons"])


def test_reused_hsm_helper_receives_scaled_feature_source(
    tmp_path: Path, monkeypatch
) -> None:
    config = _config(tmp_path)
    vectors = np.arange(60 * 6, dtype=np.float64).reshape(60, 6)
    shared_distances = np.linspace(0.1, 0.3, 50)
    monkeypatch.setattr(
        feature_range,
        "compute_knn_distance_distributions",
        lambda _vectors, candidates: {
            candidate: shared_distances.copy() for candidate in candidates
        },
    )

    candidates, distance_sample_n, diagnostics = (
        feature_range.derive_ranger_candidates(config, vectors)
    )

    assert diagnostics["plateau_found"] is True
    assert distance_sample_n == 50
    assert candidates[0]["feature_space_source"] == "scaled"
