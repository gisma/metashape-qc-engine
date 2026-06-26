import csv
from dataclasses import fields
import json
from pathlib import Path
import subprocess
import sys

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import metashape_qc_engine.level1b_feature_range as feature_range
from metashape_qc_engine.level1b_feature_range import (
    ASSIGNMENT_RULE,
    RANGER_SOURCE,
    Level1BFeatureRangeConfig,
    assign_ranger_candidates_to_scale_candidates,
    build_level1b_feature_range_layout,
    build_ranger_candidates_from_knn_distances,
    compute_knn_distances,
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
                "scale_source": "metric_radius_m",
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
        "scale_source": "metric_radius_m",
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
        "quantile_probs": (0.25, 0.5, 0.75, 0.9),
        "seed": 1,
        "max_distance_sample_n": 30,
    }
    values.update(overrides)
    return Level1BFeatureRangeConfig(**values)


def validate(config: Level1BFeatureRangeConfig):
    return validate_feature_range_config(config, build_level1b_feature_range_layout(config.output_dir))


def synthetic_vectors() -> np.ndarray:
    return np.array([[0.0, 0.0], [1.0, 0.0], [3.0, 0.0], [6.0, 0.0], [10.0, 0.0]], dtype=float)


def test_01_config_has_no_old_range_scaling_field(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    names = {field.name for field in fields(Level1BFeatureRangeConfig)}

    assert blocked_terms()[0] not in names
    assert not hasattr(config, blocked_terms()[0])


def test_02_allowed_step7_files_do_not_contain_removed_old_logic_strings() -> None:
    module_source = (REPO_ROOT / "metashape_qc_engine" / "level1b_feature_range.py").read_text(encoding="utf-8")
    test_source = (REPO_ROOT / "tests" / "test_level1b_feature_range.py").read_text(encoding="utf-8")
    combined_source = module_source + "\n" + test_source

    assert [term for term in blocked_terms() if term in combined_source] == []


def test_03_knn_helper_derives_expected_quantile_ranger_candidates() -> None:
    distances = compute_knn_distances(synthetic_vectors(), knn_k=2)
    candidates = build_ranger_candidates_from_knn_distances(
        candidate_id="candidate-1",
        distances=distances,
        quantile_probs=(0.25, 0.5, 0.75),
        knn_k=2,
        sample_n_requested=50,
        sample_n_used=5,
        distance_sample_n=5,
        feature_space_source="scaled",
        band_count=2,
    )

    np.testing.assert_allclose(distances, np.array([3.0, 2.0, 3.0, 4.0, 7.0]))
    np.testing.assert_allclose([candidate["ranger"] for candidate in candidates], np.quantile(distances, [0.25, 0.5, 0.75]))
    assert [candidate["quantile_prob"] for candidate in candidates] == [0.25, 0.5, 0.75]
    assert {candidate["ranger_source"] for candidate in candidates} == {RANGER_SOURCE}


def test_04_sampling_and_distance_subsampling_are_deterministic_with_seed(tmp_path: Path, monkeypatch) -> None:
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


def test_05_assignment_preserves_scale_fields_including_radius_and_area() -> None:
    scale_candidates = scale_payload(count=1)["candidates"]
    rangers = [
        {
            "ranger_id": "r1",
            "ranger": 2.5,
            "ranger_source": RANGER_SOURCE,
        }
    ]

    assigned = assign_ranger_candidates_to_scale_candidates(scale_candidates, rangers)

    assert assigned[0]["radius_m"] == 1.0
    assert assigned[0]["area_m2"] == 10.0
    assert assigned[0]["spatialr_px"] == 2
    assert assigned[0]["minsize_px"] == 20
    assert assigned[0]["scale_id"] == "candidate-1_scale_001"


def test_06_assignment_uses_tail_padding_when_fewer_rangers_than_scales() -> None:
    scale_candidates = scale_payload(count=4)["candidates"]
    rangers = [
        {"ranger_id": "r1", "ranger": 1.0, "ranger_source": RANGER_SOURCE},
        {"ranger_id": "r2", "ranger": 2.0, "ranger_source": RANGER_SOURCE},
    ]

    assigned = assign_ranger_candidates_to_scale_candidates(scale_candidates, rangers)

    assert [candidate["ranger_id"] for candidate in assigned] == ["r1", "r2", "r2", "r2"]
    assert {candidate["assignment_rule"] for candidate in assigned} == {ASSIGNMENT_RULE}


def test_07_assignment_does_not_create_cartesian_products() -> None:
    scale_candidates = scale_payload(count=3)["candidates"]
    rangers = [
        {"ranger_id": "r1", "ranger": 1.0, "ranger_source": RANGER_SOURCE},
        {"ranger_id": "r2", "ranger": 2.0, "ranger_source": RANGER_SOURCE},
        {"ranger_id": "r3", "ranger": 3.0, "ranger_source": RANGER_SOURCE},
        {"ranger_id": "r4", "ranger": 4.0, "ranger_source": RANGER_SOURCE},
    ]

    assigned = assign_ranger_candidates_to_scale_candidates(scale_candidates, rangers)

    assert len(assigned) == len(scale_candidates)
    assert [candidate["ranger_id"] for candidate in assigned] == ["r1", "r2", "r3"]


def test_08_output_schemas_include_required_source_and_no_removed_scaling_field(tmp_path: Path, monkeypatch) -> None:
    vectors = np.array([[0.0, 0.0], [1.0, 0.0], [3.0, 0.0], [6.0, 0.0], [10.0, 0.0]], dtype=float)
    monkeypatch.setattr(feature_range, "sample_valid_feature_vectors", lambda _config: (vectors, len(vectors)))

    report = run_feature_range_assignment_step(make_config(tmp_path, sample_n=5, max_distance_sample_n=5))

    ranger_payload = json.loads(Path(report["output_ranger_json_path"]).read_text(encoding="utf-8"))
    assigned_payload = json.loads(Path(report["output_assigned_json_path"]).read_text(encoding="utf-8"))
    assert report["status"] == "ok"
    assert ranger_payload["ranger_source"] == RANGER_SOURCE
    assert {candidate["ranger_source"] for candidate in ranger_payload["ranger_candidates"]} == {RANGER_SOURCE}
    assert {candidate["ranger_source"] for candidate in assigned_payload["candidates"]} == {RANGER_SOURCE}
    forbidden = blocked_terms()[0]
    assert forbidden not in ranger_payload
    assert all(forbidden not in candidate for candidate in ranger_payload["ranger_candidates"])
    assert all(forbidden not in candidate for candidate in assigned_payload["candidates"])


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


def test_11_nonpositive_or_nonfinite_derived_ranger_values_fail_clearly() -> None:
    for distances, expected in (
        ([0.0, 0.0, 0.0], "no finite positive distance variation"),
        ([1.0, float("nan"), 2.0], "finite"),
        ([0.0, 0.0, 1.0], "positive"),
    ):
        try:
            build_ranger_candidates_from_knn_distances(
                candidate_id="candidate-1",
                distances=distances,
                quantile_probs=(0.0,),
                knn_k=2,
                sample_n_requested=3,
                sample_n_used=3,
                distance_sample_n=3,
                feature_space_source="scaled",
                band_count=2,
            )
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("expected invalid derived ranger failure")


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
        ("quantile_probs", (), "quantile_probs must be non-empty"),
        ("quantile_probs", (-0.1,), "quantile_probs values must be in [0, 1]"),
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
    vectors, valid_count = sample_valid_feature_vectors(
        make_config(
            tmp_path,
            band_count=2,
            sample_n=10,
        )
    )

    assert valid_count == 3
    np.testing.assert_array_equal(vectors, np.array([[1.0, 10.0], [2.0, 20.0], [6.0, 60.0]]))


def test_15_run_outputs_preserve_scale_fields_and_tail_padding_in_files(tmp_path: Path, monkeypatch) -> None:
    vectors = synthetic_vectors()
    monkeypatch.setattr(feature_range, "sample_valid_feature_vectors", lambda _config: (vectors, len(vectors)))
    config = make_config(tmp_path, quantile_probs=(0.25, 0.5), sample_n=5, max_distance_sample_n=5)

    report = run_feature_range_assignment_step(config)
    assigned_payload = json.loads(Path(report["output_assigned_json_path"]).read_text(encoding="utf-8"))
    with Path(report["output_assigned_csv_path"]).open(newline="", encoding="utf-8") as file_obj:
        rows = list(csv.DictReader(file_obj))

    assert report["status"] == "ok"
    assert report["ranger_count"] == 2
    assert report["assigned_candidate_count"] == 3
    assert [candidate["ranger_id"] for candidate in assigned_payload["candidates"]] == [
        "candidate-1_ranger_001",
        "candidate-1_ranger_002",
        "candidate-1_ranger_002",
    ]
    assert assigned_payload["candidates"][0]["radius_m"] == 1.0
    assert assigned_payload["candidates"][0]["area_m2"] == 10.0
    assert rows[0]["radius_m"] == "1.0"
    assert rows[0]["area_m2"] == "10.0"


def test_16_protected_step_boundaries_are_unchanged() -> None:
    protected = [
        "metashape_qc_engine/level1b_preflight.py",
        "metashape_qc_engine/level1b_valid_mask.py",
        "metashape_qc_engine/level1b_channels.py",
        "metashape_qc_engine/level1b_scaling.py",
        "metashape_qc_engine/level1b_pca.py",
        "metashape_qc_engine/level1b_scale_distribution.py",
        "metashape_qc_engine/cli.py",
    ]

    assert subprocess.run(["git", "diff", "--quiet", "--", *protected]).returncode == 0
