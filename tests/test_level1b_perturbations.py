import csv
import json
import math
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from metashape_qc_engine.level1b_perturbations import (
    PERTURBATION_RULE,
    Level1BPerturbationConfig,
    build_level1b_perturbation_layout,
    build_perturbation_candidates,
    read_scale_candidates_with_ranger,
    run_local_perturbation_step,
    validate_perturbation_config,
    write_perturbation_candidates_csv,
)


def step7_payload(candidates: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "candidate_id": "candidate-1",
        "scale_candidates_json_path": "scale_candidates.json",
        "ranger_candidates_json_path": "ranger_candidates.json",
        "assignment_rule": "all_scale_candidates_assigned_scene_half_sample_mode_ranger",
        "scale_candidate_count": 2,
        "ranger_candidate_count": 1,
        "assigned_candidate_count": 2,
        "candidates": candidates
        if candidates is not None
        else [
            {
                "candidate_id": "candidate-1_scale_001_ranger_001",
                "scale_id": "candidate-1_scale_001",
                "radius_m": 1.5,
                "area_m2": 40.0,
                "spatialr_px": 10,
                "minsize_px": 100,
                "ranger_id": "candidate-1_ranger_001",
                "ranger": 2.0,
                "ranger_source": "knn_distance_half_sample_mode",
                "assignment_rule": "all_scale_candidates_assigned_scene_half_sample_mode_ranger",
            },
            {
                "candidate_id": "candidate-1_scale_002_ranger_002",
                "scale_id": "candidate-1_scale_002",
                "spatialr_px": 20,
                "minsize_px": 200,
                "ranger_id": "candidate-1_ranger_001",
                "ranger": 2.0,
                "ranger_source": "knn_distance_half_sample_mode",
                "assignment_rule": "all_scale_candidates_assigned_scene_half_sample_mode_ranger",
            },
        ],
    }


def make_step7_json(tmp_path: Path, payload: dict[str, object] | None = None, suffix: str = ".json") -> Path:
    path = tmp_path / f"scale_candidates_with_ranger{suffix}"
    path.write_text(json.dumps(payload if payload is not None else step7_payload()), encoding="utf-8")
    return path


def make_config(tmp_path: Path, **overrides: object) -> Level1BPerturbationConfig:
    values = {
        "candidate_id": "candidate-1",
        "output_dir": tmp_path / "out",
        "scale_candidates_with_ranger_json_path": make_step7_json(tmp_path),
    }
    values.update(overrides)
    return Level1BPerturbationConfig(**values)


def validate(config: Level1BPerturbationConfig) -> tuple[dict[str, bool], list[str]]:
    return validate_perturbation_config(config, build_level1b_perturbation_layout(config.output_dir))


def one_complete_candidate(**overrides: object) -> list[dict[str, object]]:
    candidate = {
        "candidate_id": "source-a",
        "scale_id": "scale-a",
        "spatialr_px": 10,
        "minsize_px": 100,
        "ranger": 2.0,
    }
    candidate.update(overrides)
    return [candidate]


def changed_axis_count(row: dict[str, object]) -> int:
    deltas = row["deltas"]
    return sum(value != 0 for value in (deltas["spatialr_px_delta"], deltas["minsize_px_delta"], deltas["ranger_delta"]))


def rows_by_source(rows: list[dict[str, object]], source_id: str) -> list[dict[str, object]]:
    return [row for row in rows if row["source_candidate_id"] == source_id]


def test_01_step8_consumes_scale_candidates_with_ranger_json_and_writes_outputs(tmp_path: Path) -> None:
    report = run_local_perturbation_step(make_config(tmp_path))

    assert report["status"] == "ok"
    assert Path(report["scale_candidates_with_ranger_json_path"]).name == "scale_candidates_with_ranger.json"
    assert Path(report["output_csv_path"]).is_file()
    assert Path(report["output_json_path"]).is_file()


def test_02_required_candidate_fields_are_validated(tmp_path: Path) -> None:
    for missing_field in ("candidate_id", "scale_id", "spatialr_px", "minsize_px", "ranger"):
        candidate = one_complete_candidate()[0]
        del candidate[missing_field]
        path = make_step7_json(tmp_path, step7_payload([candidate]))

        try:
            read_scale_candidates_with_ranger(path)
        except ValueError as exc:
            assert f"candidate field {missing_field} is missing" in str(exc)
        else:
            raise AssertionError(f"expected missing field failure for {missing_field}")


def test_03_optional_pass_through_fields_are_preserved(tmp_path: Path) -> None:
    candidate = read_scale_candidates_with_ranger(make_config(tmp_path).scale_candidates_with_ranger_json_path)[0]
    rows = build_perturbation_candidates(make_config(tmp_path), [candidate])

    for field in ("radius_m", "area_m2", "ranger_id", "ranger_source", "assignment_rule"):
        assert rows[0][field] == candidate[field]
        assert rows[1][field] == candidate[field]


def test_04_baseline_row_is_written_for_each_source_candidate_before_perturbations(tmp_path: Path) -> None:
    report = run_local_perturbation_step(make_config(tmp_path, K=3))
    payload = json.loads(Path(report["output_json_path"]).read_text(encoding="utf-8"))
    rows = payload["candidates"]

    assert report["baseline_row_count"] == 2
    assert rows_by_source(rows, "candidate-1_scale_001_ranger_001")[0]["is_baseline"] is True
    assert rows_by_source(rows, "candidate-1_scale_002_ranger_002")[0]["is_baseline"] is True


def test_05_baseline_row_has_baseline_id_true_flag_and_zero_deltas(tmp_path: Path) -> None:
    rows = build_perturbation_candidates(make_config(tmp_path), one_complete_candidate())

    assert rows[0]["perturbation_id"] == "source-a__baseline"
    assert rows[0]["is_baseline"] is True
    assert rows[0]["deltas"] == {
        "spatialr_px_delta": 0,
        "minsize_px_delta": 0,
        "ranger_delta": 0.0,
        "minsize_delta_fraction": 0.0,
        "ranger_delta_fraction": 0.0,
    }


def test_06_perturbation_ids_are_deterministic_and_start_at_one(tmp_path: Path) -> None:
    rows = build_perturbation_candidates(make_config(tmp_path, K=2), one_complete_candidate(candidate_id="source-id"))

    assert [row["perturbation_id"] for row in rows] == [
        "source-id__baseline",
        "source-id__perturb_001",
        "source-id__perturb_002",
    ]


def test_07_local_grid_is_created_from_spatialr_ranger_and_minsize_around_each_candidate(tmp_path: Path) -> None:
    rows = build_perturbation_candidates(make_config(tmp_path, K=99), one_complete_candidate(spatialr_px=10, minsize_px=100, ranger=2.0))
    non_baseline = rows[1:]

    assert len(rows) == 27
    assert {row["spatialr_px"] for row in non_baseline} == {9, 10, 11}
    assert {row["minsize_px"] for row in non_baseline} == {80, 100, 120}
    assert {row["ranger"] for row in non_baseline} == {1.8, 2.0, 2.2}


def test_08_one_axis_only_restriction_is_absent(tmp_path: Path) -> None:
    rows = build_perturbation_candidates(make_config(tmp_path, K=99), one_complete_candidate())

    assert any(changed_axis_count(row) > 1 for row in rows if not row["is_baseline"])


def test_09_small_scale_spatial_lock_forces_ds_zero(tmp_path: Path) -> None:
    rows = build_perturbation_candidates(make_config(tmp_path, K=99), one_complete_candidate(spatialr_px=3))

    assert {row["spatialr_px"] for row in rows} == {3}
    assert len(rows) == 9


def test_10_adaptive_dr_default_is_max_of_floor_and_ten_percent_ranger(tmp_path: Path) -> None:
    small = build_perturbation_candidates(make_config(tmp_path, K=99), one_complete_candidate(ranger=0.01))
    normal = build_perturbation_candidates(make_config(tmp_path, K=99), one_complete_candidate(ranger=2.0))

    assert {row["ranger"] for row in small} == {0.005, 0.01, 0.015}
    assert {row["ranger"] for row in normal} == {1.8, 2.0, 2.2}


def test_11_adaptive_dm_default_is_max_of_five_and_twenty_percent_minsize(tmp_path: Path) -> None:
    small = build_perturbation_candidates(make_config(tmp_path, K=99), one_complete_candidate(minsize_px=10))
    normal = build_perturbation_candidates(make_config(tmp_path, K=99), one_complete_candidate(minsize_px=100))

    assert {row["minsize_px"] for row in small} == {8, 10, 15}
    assert {row["minsize_px"] for row in normal} == {80, 100, 120}


def test_12_minsize_floor_clamp_applies_to_perturbations(tmp_path: Path) -> None:
    rows = build_perturbation_candidates(make_config(tmp_path, dm=50, K=99, minsize_floor_frac=0.8), one_complete_candidate(minsize_px=100))

    assert min(row["minsize_px"] for row in rows if not row["is_baseline"]) >= 80
    assert any(row["deltas"]["minsize_px_delta"] == -20 for row in rows if not row["is_baseline"])


def test_13_k_limits_non_baseline_perturbations_and_does_not_count_baseline(tmp_path: Path) -> None:
    rows = build_perturbation_candidates(make_config(tmp_path, K=5), one_complete_candidate())

    assert len([row for row in rows if not row["is_baseline"]]) == 5
    assert len(rows) == 6


def test_14_k_sampling_is_deterministic_with_seed(tmp_path: Path) -> None:
    first = build_perturbation_candidates(make_config(tmp_path, K=5, seed=7), one_complete_candidate())
    second = build_perturbation_candidates(make_config(tmp_path, K=5, seed=7), one_complete_candidate())
    different = build_perturbation_candidates(make_config(tmp_path, K=5, seed=8), one_complete_candidate())

    assert first == second
    assert first != different


def test_15_no_global_matrix_is_created_across_source_candidates(tmp_path: Path) -> None:
    rows = build_perturbation_candidates(
        make_config(tmp_path, K=99),
        [
            one_complete_candidate(candidate_id="source-a", scale_id="scale-a", spatialr_px=10, minsize_px=100, ranger=2.0)[0],
            one_complete_candidate(candidate_id="source-b", scale_id="scale-b", spatialr_px=20, minsize_px=200, ranger=4.0)[0],
        ],
    )

    source_a_rows = rows_by_source(rows, "source-a")
    source_b_rows = rows_by_source(rows, "source-b")
    assert {row["scale_id"] for row in source_a_rows} == {"scale-a"}
    assert {row["scale_id"] for row in source_b_rows} == {"scale-b"}
    assert {row["ranger"] for row in source_a_rows} == {1.8, 2.0, 2.2}
    assert {row["ranger"] for row in source_b_rows} == {3.6, 4.0, 4.4}


def test_16_json_and_csv_outputs_have_same_number_and_order_of_rows(tmp_path: Path) -> None:
    report = run_local_perturbation_step(make_config(tmp_path, K=4))
    payload = json.loads(Path(report["output_json_path"]).read_text(encoding="utf-8"))
    with Path(report["output_csv_path"]).open(newline="", encoding="utf-8") as file_obj:
        csv_rows = list(csv.DictReader(file_obj))

    assert len(csv_rows) == len(payload["candidates"])
    assert [row["perturbation_id"] for row in csv_rows] == [row["perturbation_id"] for row in payload["candidates"]]
    assert json.loads(csv_rows[0]["deltas"]) == payload["candidates"][0]["deltas"]


def test_17_report_flags_confirm_no_forbidden_processing(tmp_path: Path) -> None:
    report = run_local_perturbation_step(make_config(tmp_path))

    assert report["no_global_parameter_matrix_created"] is True
    assert report["no_cross_parameter_combinations_created"] is True
    assert report["no_segmentation_performed"] is True
    assert report["no_otb_used"] is True
    assert report["no_raster_read"] is True


def test_18_output_schema_contains_required_fields_and_rule(tmp_path: Path) -> None:
    report = run_local_perturbation_step(make_config(tmp_path, K=1))
    payload = json.loads(Path(report["output_json_path"]).read_text(encoding="utf-8"))
    required = {
        "perturbation_id",
        "source_candidate_id",
        "scale_id",
        "spatialr_px",
        "minsize_px",
        "ranger",
        "deltas",
        "is_baseline",
        "perturbation_rule",
    }

    assert payload["perturbation_rule"] == PERTURBATION_RULE
    assert required.issubset(payload["candidates"][0])
    assert isinstance(payload["candidates"][0]["deltas"], dict)


def test_19_config_validation_rejects_required_invalid_controls(tmp_path: Path) -> None:
    invalid_cases = (
        ({"scale_candidates_with_ranger_json_path": None}, "scale_candidates_with_ranger_json_path_present", "scale_candidates_with_ranger_json_path is missing"),
        ({"scale_candidates_with_ranger_json_path": tmp_path / "missing.json"}, "scale_candidates_with_ranger_json_path_exists", "scale_candidates_with_ranger_json_path does not exist"),
        ({"scale_candidates_with_ranger_json_path": make_step7_json(tmp_path, suffix=".txt")}, "scale_candidates_with_ranger_json_path_suffix_json", "scale_candidates_with_ranger_json_path suffix must be .json"),
        ({"K": 0}, "K_positive_integer", "K must be a positive integer"),
        ({"ds": -1}, "ds_non_negative_integer", "ds must be a non-negative integer"),
        ({"minsize_floor_frac": 0}, "minsize_floor_frac_valid", "minsize_floor_frac must be numeric and > 0 and <= 1"),
        ({"minsize_floor_frac": 1.01}, "minsize_floor_frac_valid", "minsize_floor_frac must be numeric and > 0 and <= 1"),
        ({"dr": 0}, "dr_positive_when_explicit", "dr must be positive when explicit"),
        ({"dm": 0}, "dm_positive_when_explicit", "dm must be positive when explicit"),
    )

    for overrides, check_key, reason in invalid_cases:
        checks, reasons = validate(make_config(tmp_path, **overrides))
        assert checks[check_key] is False
        assert reason in reasons


def test_20_invalid_output_dir_is_rejected(tmp_path: Path) -> None:
    output_file = tmp_path / "not-a-dir"
    output_file.write_text("x", encoding="utf-8")
    report = run_local_perturbation_step(make_config(tmp_path, output_dir=output_file))

    assert report["status"] == "failed"
    assert report["checks"]["output_dir_valid"] is False
    assert any("output_dir is invalid" in reason for reason in report["failure_reasons"])


def test_21_candidate_numeric_validation_rejects_non_positive_and_non_finite_values(tmp_path: Path) -> None:
    invalid_cases = (
        ("spatialr_px", 0),
        ("spatialr_px", math.inf),
        ("minsize_px", 0),
        ("minsize_px", float("nan")),
        ("ranger", 0),
        ("ranger", math.inf),
    )

    for field, value in invalid_cases:
        candidate = one_complete_candidate()[0]
        candidate[field] = value
        path = make_step7_json(tmp_path, step7_payload([candidate]))
        try:
            read_scale_candidates_with_ranger(path)
        except ValueError as exc:
            assert f"{field} must be finite and > 0" in str(exc)
        else:
            raise AssertionError(f"expected invalid value failure for {field}")


def test_22_if_no_perturbations_remain_baseline_is_still_written(tmp_path: Path) -> None:
    rows = build_perturbation_candidates(
        make_config(tmp_path, dr=5e-324, ds=0, dm=0.1, K=8, minsize_floor_frac=1.0),
        one_complete_candidate(spatialr_px=1, minsize_px=1, ranger=1e-6),
    )

    assert rows == [
        {
            "perturbation_id": "source-a__baseline",
            "source_candidate_id": "source-a",
            "scale_id": "scale-a",
            "spatialr_px": 1,
            "minsize_px": 1,
            "ranger": 1e-06,
            "deltas": {
                "spatialr_px_delta": 0,
                "minsize_px_delta": 0,
                "ranger_delta": 0.0,
                "minsize_delta_fraction": 0.0,
                "ranger_delta_fraction": 0.0,
            },
            "is_baseline": True,
            "perturbation_rule": PERTURBATION_RULE,
        }
    ]


def test_23_csv_deltas_are_compact_json_strings(tmp_path: Path) -> None:
    rows = build_perturbation_candidates(make_config(tmp_path, K=1), one_complete_candidate())
    csv_path = tmp_path / "perturbation_candidates.csv"
    write_perturbation_candidates_csv(rows, csv_path)

    with csv_path.open(newline="", encoding="utf-8") as file_obj:
        csv_rows = list(csv.DictReader(file_obj))

    assert csv_rows[0]["deltas"] == json.dumps(rows[0]["deltas"], sort_keys=True, separators=(",", ":"))


def test_24_run_report_contains_required_counts_and_controls(tmp_path: Path) -> None:
    report = run_local_perturbation_step(make_config(tmp_path, K=3, seed=9, minsize_floor_frac=0.7))

    assert report["input_candidate_count"] == 2
    assert report["output_row_count"] == 8
    assert report["baseline_row_count"] == 2
    assert report["perturbation_row_count"] == 6
    assert report["K"] == 3
    assert report["seed"] == 9
    assert report["minsize_floor_frac"] == 0.7
    assert report["perturbation_rule"] == PERTURBATION_RULE


def test_25_source_has_no_forbidden_raster_otb_segmentation_stability_or_global_grid_symbols() -> None:
    source = (REPO_ROOT / "metashape_qc_engine" / "level1b_perturbations.py").read_text(encoding="utf-8")
    blocked = [
        "rast" + "erio",
        "os" + "geo",
        "g" + "dal",
        "num" + "py",
        "sci" + "py",
        "ski" + "mage",
        "c" + "v2",
        "P" + "IL",
        "pan" + "das",
        "geopan" + "das",
        "x" + "array",
        "rio" + "x" + "array",
        "ter" + "ra",
        "sta" + "rs",
        "link" + "2GI",
        "sub" + "process",
        "sh" + "util",
        "otb" + "cli",
        "Band" + "MathX",
        "Compute" + "ImagesStatistics",
        "Mean" + "Shift",
        "LS" + "MS",
        "Ho" + "over",
        "stability" + "_evaluator",
        "run" + "_segmentation",
        "cartesian" + "_product",
        "itertools" + ".product",
        "parameter" + "_grid",
        "full" + "_grid",
        "quality" + "_flag",
    ]

    assert [symbol for symbol in blocked if symbol in source] == []


def test_26_protected_existing_files_are_present_and_step8_tests_do_not_import_them() -> None:
    protected_files = [
        "level1b_preflight.py",
        "level1b_valid_mask.py",
        "level1b_channels.py",
        "level1b_scaling.py",
        "level1b_pca.py",
        "level1b_scale_distribution.py",
        "level1b_feature_range.py",
        "cli.py",
    ]
    test_source = (REPO_ROOT / "tests" / "test_level1b_perturbations.py").read_text(encoding="utf-8")

    forbidden_import = "from metashape_qc_engine." + "level1b_feature_range"
    assert all((REPO_ROOT / "metashape_qc_engine" / filename).is_file() for filename in protected_files)
    assert forbidden_import not in test_source


def test_27_removed_single_axis_enforcement_is_absent_from_step8_files() -> None:
    module_source = (REPO_ROOT / "metashape_qc_engine" / "level1b_perturbations.py").read_text(encoding="utf-8")
    test_source = (REPO_ROOT / "tests" / "test_level1b_perturbations.py").read_text(encoding="utf-8")
    blocked = [
        "one" + "_at" + "_a" + "_time",
        "must change exactly " + "one axis",
        "non" + "_zero" + "_delta" + "_count != 1",
        "__perturb" + "_000",
        "baseline_plus_local_" + "one" + "_at" + "_a" + "_time" + "_axis_perturbations",
    ]

    assert [term for term in blocked if term in module_source + test_source] == []
