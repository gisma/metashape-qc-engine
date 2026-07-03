import csv
from dataclasses import fields
import json
from pathlib import Path
import sys

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import metashape_qc_engine.level1b_feature_range as feature_range
from metashape_qc_engine.level1b_feature_range import (
    ASSIGNMENT_RULE,
    RANGER_SELECTION_METHOD,
    RANGER_SOURCE,
    Level1BFeatureRangeConfig,
    assign_ranger_candidates_to_scale_candidates,
    build_level1b_feature_range_layout,
    build_ranger_candidate_from_knn_distances,
    compute_knn_distances,
    estimate_half_sample_mode,
    read_scale_candidates,
    run_feature_range_assignment_step,
    sample_valid_feature_vectors,
    subsample_for_distance,
    validate_feature_range_config,
)


def blocked_terms() -> list[str]:
    return [
        "ranger" + "_multiplier",
        "feature" + "_std" + "_l2" + "_times" + "_single" + "_multiplier",
        "DEFAULT" + "_RANGER" + "_MULTIPLIERS",
        "feature" + "_std" + "_l2" + "_times" + "_multiplier" + "_grid",
    ]


def make_stack(tmp_path: Path, name: str = "feature_stack.tif") -> Path:
    path = tmp_path / name
    path.touch()
    return path


def make_mask(tmp_path: Path, name: str = "valid_mask.tif") -> Path:
    path = tmp_path / name
    path.touch()
    return path


def scale_payload(count: int = 3) -> dict[str, object]:
    candidates = []
    for index in range(1, count + 1):
        candidates.append(
            {
                "candidate_id": f"candidate-1_scale_{index:03d}",
                "scale_index": index,
                "scale_mode": "metric_scale_sweep",
                "scale_source": "config.baseline_candidate_radii_m",
                "radius_m": float(index),
                "area_m2": float(index * 10),
                "pixel_size_m": 0.5,
                "pixel_area_m2": 0.25,
                "spatialr_px": index * 2,
                "minsize_px": index * 20,
                "ranger": None,
                "coupling_rule": "radius_m_to_spatialr_px__area_m2_to_minsize_px",
            }
        )
    return {
        "candidate_id": "candidate-1",
        "scale_mode": "metric_scale_sweep",
        "scale_source": "config.baseline_candidate_radii_m",
        "pixel_size_m": 0.5,
        "pixel_area_m2": 0.25,
        "candidate_count": count,
        "candidates": candidates,
    }


def make_scale_json(tmp_path: Path, payload: dict[str, object] | None = None) -> Path:
    path = tmp_path / "scale_candidates.json"
    path.write_text(json.dumps(payload if payload is not None else scale_payload()), encoding="utf-8")
    return path


def make_config(tmp_path: Path, **overrides: object) -> Level1BFeatureRangeConfig:
    values = {
        "candidate_id": "candidate-1",
        "output_dir": tmp_path / "out",
        "feature_space_stack_path": make_stack(tmp_path),
        "valid_mask_path": make_mask(tmp_path),
        "scale_candidates_json_path": make_scale_json(tmp_path),
        "feature_space_source": "scaled",
        "band_count": 2,
        "sample_n": 50,
        "knn_k": 2,
        "seed": 1,
        "max_distance_sample_n": 30,
    }
    values.update(overrides)
    return Level1BFeatureRangeConfig(**values)


def validate(config: Level1BFeatureRangeConfig):
    return validate_feature_range_config(config, build_level1b_feature_range_layout(config.output_dir))


def synthetic_vectors() -> np.ndarray:
    return np.array([[0.0, 0.0], [1.0, 0.0], [3.0, 0.0], [6.0, 0.0], [10.0, 0.0]], dtype=float)


def test_01_config_has_no_removed_range_fields(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    names = {field.name for field in fields(Level1BFeatureRangeConfig)}

    assert blocked_terms()[0] not in names
    assert "quantile_probs" not in names
    assert not hasattr(config, "quantile_probs")


def test_02_active_feature_range_source_has_no_quantile_ladder_or_tail_padding() -> None:
    module_source = (REPO_ROOT / "metashape_qc_engine" / "level1b_feature_range.py").read_text(encoding="utf-8")

    assert [term for term in blocked_terms() if term in module_source] == []
    assert "quantile_probs" not in module_source
    assert "np.quantile" not in module_source
    assert "tail_padding" not in module_source


def test_03_knn_distances_feed_one_half_sample_mode_ranger() -> None:
    distances = compute_knn_distances(synthetic_vectors(), knn_k=2)
    candidates, diagnostics = build_ranger_candidate_from_knn_distances(
        candidate_id="candidate-1",
        distances=distances,
        knn_k=2,
        sample_n_requested=50,
        sample_n_used=5,
        distance_sample_n=5,
        feature_space_source="scaled",
        band_count=2,
    )

    np.testing.assert_allclose(distances, np.array([3.0, 2.0, 3.0, 4.0, 7.0]))
    assert len(candidates) == 1
    assert candidates[0]["ranger"] == 3.0
    assert candidates[0]["ranger_id"] == "candidate-1_ranger_001"
    assert candidates[0]["ranger_source"] == RANGER_SOURCE
    assert diagnostics["selection_method"] == RANGER_SELECTION_METHOD
    assert diagnostics["modal_interval_lower"] == 2.0
    assert diagnostics["modal_interval_upper"] == 3.0


def test_04_half_sample_mode_ignores_distant_distribution_tails() -> None:
    central = estimate_half_sample_mode([10.0, 11.0, 12.0, 13.0])
    with_tails = estimate_half_sample_mode([1.0, 10.0, 11.0, 12.0, 13.0, 100.0])

    assert central["ranger"] == 10.5
    assert with_tails["ranger"] == 10.5
    assert with_tails["distance_min"] == 1.0
    assert with_tails["distance_max"] == 100.0


def test_05_sampling_and_distance_subsampling_are_deterministic_with_seed(tmp_path: Path, monkeypatch) -> None:
    vectors = np.arange(200, dtype=float).reshape(100, 2)
    feature_stack = np.moveaxis(vectors.reshape(10, 10, 2), -1, 0)
    valid_mask = np.ones((10, 10), dtype=np.uint8)
    monkeypatch.setattr(feature_range, "read_feature_stack_and_mask", lambda *_args: (feature_stack, valid_mask))

    first_sample, first_count = sample_valid_feature_vectors(make_config(tmp_path, sample_n=12, seed=7))
    second_sample, second_count = sample_valid_feature_vectors(make_config(tmp_path, sample_n=12, seed=7))
    different_sample, _ = sample_valid_feature_vectors(make_config(tmp_path, sample_n=12, seed=8))
    first = subsample_for_distance(vectors, max_distance_sample_n=12, seed=7)
    second = subsample_for_distance(vectors, max_distance_sample_n=12, seed=7)
    different = subsample_for_distance(vectors, max_distance_sample_n=12, seed=8)

    assert first_count == second_count == 100
    np.testing.assert_array_equal(first_sample, second_sample)
    assert not np.array_equal(first_sample, different_sample)
    np.testing.assert_array_equal(first, second)
    assert not np.array_equal(first, different)


def test_06_same_scene_ranger_is_assigned_to_every_explicit_spatial_baseline() -> None:
    scale_candidates = scale_payload(count=4)["candidates"]
    ranger = [{"ranger_id": "r1", "ranger": 2.5, "ranger_source": RANGER_SOURCE}]

    assigned = assign_ranger_candidates_to_scale_candidates(scale_candidates, ranger)

    assert len(assigned) == 4
    assert {candidate["ranger"] for candidate in assigned} == {2.5}
    assert {candidate["ranger_id"] for candidate in assigned} == {"r1"}
    assert {candidate["assignment_rule"] for candidate in assigned} == {ASSIGNMENT_RULE}
    assert [candidate["radius_m"] for candidate in assigned] == [1.0, 2.0, 3.0, 4.0]
    assert [candidate["spatialr_px"] for candidate in assigned] == [2, 4, 6, 8]
    assert [candidate["minsize_px"] for candidate in assigned] == [20, 40, 60, 80]


def test_07_assignment_rejects_a_ranger_ladder() -> None:
    rangers = [
        {"ranger_id": "r1", "ranger": 1.0, "ranger_source": RANGER_SOURCE},
        {"ranger_id": "r2", "ranger": 2.0, "ranger_source": RANGER_SOURCE},
    ]

    try:
        assign_ranger_candidates_to_scale_candidates(scale_payload(count=3)["candidates"], rangers)
    except ValueError as exc:
        assert "exactly one scene-specific ranger candidate" in str(exc)
    else:
        raise AssertionError("expected ranger-ladder rejection")


def test_08_output_schemas_record_half_sample_mode_and_one_ranger(tmp_path: Path, monkeypatch) -> None:
    vectors = synthetic_vectors()
    monkeypatch.setattr(feature_range, "sample_valid_feature_vectors", lambda _config: (vectors, len(vectors)))

    report = run_feature_range_assignment_step(make_config(tmp_path, sample_n=5, max_distance_sample_n=5))
    ranger_payload = json.loads(Path(report["output_ranger_json_path"]).read_text(encoding="utf-8"))
    assigned_payload = json.loads(Path(report["output_assigned_json_path"]).read_text(encoding="utf-8"))

    assert report["status"] == "ok"
    assert report["ranger_count"] == 1
    assert ranger_payload["ranger_count"] == 1
    assert ranger_payload["selection_method"] == RANGER_SELECTION_METHOD
    assert ranger_payload["ranger_source"] == RANGER_SOURCE
    assert "quantile_probs" not in ranger_payload
    assert len({candidate["ranger"] for candidate in assigned_payload["candidates"]}) == 1
    assert assigned_payload["ranger_candidate_count"] == 1


def test_09_read_scale_candidates_fails_clearly_for_missing_required_fields(tmp_path: Path) -> None:
    for field_name in ("candidate_id", "radius_m", "area_m2", "spatialr_px", "minsize_px"):
        candidate = scale_payload(count=1)["candidates"][0]
        del candidate[field_name]
        path = make_scale_json(tmp_path, {"candidates": [candidate]})

        try:
            read_scale_candidates(path)
        except ValueError as exc:
            assert f"lacks {field_name}" in str(exc)
        else:
            raise AssertionError("expected missing scale field failure")


def test_10_insufficient_valid_feature_vectors_fail_clearly(tmp_path: Path, monkeypatch) -> None:
    vectors = np.array([[0.0, 0.0], [1.0, 0.0]], dtype=float)
    monkeypatch.setattr(feature_range, "sample_valid_feature_vectors", lambda _config: (vectors, len(vectors)))

    report = run_feature_range_assignment_step(make_config(tmp_path, knn_k=2, max_distance_sample_n=3))

    assert report["status"] == "failed"
    assert any("not enough valid feature vectors" in reason for reason in report["failure_reasons"])


def test_11_invalid_knn_distance_distributions_fail_clearly() -> None:
    for distances, expected in (
        ([], "empty"),
        ([0.0, 0.0, 0.0], "no finite positive distance variation"),
        ([1.0, float("nan"), 2.0], "finite"),
        ([-1.0, 1.0, 2.0], "non-negative"),
        ([0.0, 0.0, 1.0], "positive"),
    ):
        try:
            estimate_half_sample_mode(distances)
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("expected invalid distance-distribution failure")


def test_12_run_function_is_testable_without_real_rasters_by_monkeypatching_sampler(tmp_path: Path, monkeypatch) -> None:
    vectors = synthetic_vectors()
    monkeypatch.setattr(feature_range, "sample_valid_feature_vectors", lambda _config: (vectors, len(vectors)))

    report = run_feature_range_assignment_step(make_config(tmp_path, sample_n=5, max_distance_sample_n=5))

    assert report["status"] == "ok"
    assert len(report["files_written"]) == 4
    assert all(Path(path).is_file() for path in report["files_written"])


def test_13_validation_rejects_required_bad_inputs(tmp_path: Path) -> None:
    cases = [
        ("feature_space_stack_path", tmp_path / "missing.tif", "feature_space_stack_path does not exist"),
        ("valid_mask_path", tmp_path / "missing_mask.tif", "valid_mask_path does not exist"),
        ("scale_candidates_json_path", tmp_path / "missing.json", "scale_candidates_json_path does not exist"),
        ("feature_space_source", "raw", "feature_space_source must be exactly scaled or pca"),
        ("band_count", 0, "band_count must be a positive integer"),
        ("sample_n", 0, "sample_n must be a positive integer"),
        ("knn_k", 0, "knn_k must be a positive integer"),
        ("max_distance_sample_n", 0, "max_distance_sample_n must be a positive integer"),
        ("max_distance_sample_n", 2, "max_distance_sample_n must be greater than knn_k"),
    ]

    for field_name, value, reason in cases:
        checks, reasons = validate(make_config(tmp_path, **{field_name: value}))
        assert any(reason in item for item in reasons), (checks, reasons)


def test_14_sampler_uses_valid_complete_vectors_and_configured_band_count(tmp_path: Path, monkeypatch) -> None:
    feature_stack = np.array(
        [
            [[1, 2, np.nan], [4, 5, 6]],
            [[10, 20, 30], [np.inf, 50, 60]],
            [[100, 200, 300], [400, 500, 600]],
        ],
        dtype=np.float32,
    )
    valid_mask = np.array([[1, 1, 1], [1, 0, 1]], dtype=np.uint8)
    monkeypatch.setattr(feature_range, "read_feature_stack_and_mask", lambda *_args: (feature_stack, valid_mask))
    vectors, valid_count = sample_valid_feature_vectors(make_config(tmp_path, band_count=2, sample_n=10))

    assert valid_count == 3
    np.testing.assert_array_equal(vectors, np.array([[1.0, 10.0], [2.0, 20.0], [6.0, 60.0]]))


def test_15_run_outputs_preserve_all_scale_rows_without_cartesian_product(tmp_path: Path, monkeypatch) -> None:
    vectors = synthetic_vectors()
    monkeypatch.setattr(feature_range, "sample_valid_feature_vectors", lambda _config: (vectors, len(vectors)))
    report = run_feature_range_assignment_step(make_config(tmp_path, sample_n=5, max_distance_sample_n=5))
    assigned_payload = json.loads(Path(report["output_assigned_json_path"]).read_text(encoding="utf-8"))
    with Path(report["output_assigned_csv_path"]).open(newline="", encoding="utf-8") as file_obj:
        rows = list(csv.DictReader(file_obj))

    assert report["status"] == "ok"
    assert report["ranger_count"] == 1
    assert report["assigned_candidate_count"] == 3
    assert [candidate["ranger_id"] for candidate in assigned_payload["candidates"]] == [
        "candidate-1_ranger_001",
        "candidate-1_ranger_001",
        "candidate-1_ranger_001",
    ]
    assert [candidate["radius_m"] for candidate in assigned_payload["candidates"]] == [1.0, 2.0, 3.0]
    assert len(rows) == 3
    assert rows[0]["radius_m"] == "1.0"
    assert rows[0]["area_m2"] == "10.0"
