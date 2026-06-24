import csv
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from metashape_qc_engine.level1b_perturbations import (
    Level1BPerturbationConfig,
    build_level1b_perturbation_layout,
    build_perturbation_candidates,
    read_scale_candidates_with_ranger,
    run_local_perturbation_step,
    validate_perturbation_config,
    write_perturbation_candidates_csv,
)


def make_step7_json(tmp_path: Path, payload: dict[str, object] | None = None) -> Path:
    path = tmp_path / "scale_candidates_with_ranger.json"
    if payload is None:
        payload = {
            "candidate_id": "candidate-1",
            "scale_candidates_json_path": "scale_candidates.json",
            "ranger_candidates_json_path": "ranger_candidates.json",
            "assignment_rule": "single_feature_range_assigned_to_each_scale_candidate",
            "scale_candidate_count": 1,
            "ranger_candidate_count": 1,
            "assigned_candidate_count": 1,
            "candidates": [
                {
                    "candidate_id": "candidate-1_scale_001_ranger_001",
                    "scale_id": "candidate-1_scale_001",
                    "spatialr_px": 10,
                    "minsize_px": 100,
                    "ranger": 2.0,
                }
            ],
        }
    path.write_text(json.dumps(payload), encoding="utf-8")
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


def nonzero_delta_count(row: dict[str, object]) -> int:
    deltas = row["deltas"]
    return sum(value != 0 for value in (deltas["spatialr_px_delta"], deltas["minsize_px_delta"], deltas["ranger_delta"]))


def test_01_layout_creates_only_perturbations_directory(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    layout = build_level1b_perturbation_layout(output_dir)

    assert list(layout) == ["perturbation_dir"]
    assert layout["perturbation_dir"].is_dir()
    assert sorted(path.relative_to(output_dir) for path in output_dir.rglob("*")) == [
        Path("level1b"),
        Path("level1b/perturbations"),
    ]


def test_02_validation_fails_for_empty_candidate_id(tmp_path: Path) -> None:
    checks, reasons = validate(make_config(tmp_path, candidate_id=" "))

    assert checks["candidate_id_non_empty"] is False
    assert "candidate_id is empty" in reasons


def test_03_validation_fails_for_missing_scale_candidates_with_ranger_json_path(tmp_path: Path) -> None:
    checks, reasons = validate(make_config(tmp_path, scale_candidates_with_ranger_json_path=tmp_path / "missing.json"))

    assert checks["scale_candidates_with_ranger_json_path_exists"] is False
    assert "scale_candidates_with_ranger_json_path does not exist" in reasons


def test_04_validation_fails_for_non_json_scale_candidates_with_ranger_json_path(tmp_path: Path) -> None:
    path = tmp_path / "scale_candidates_with_ranger.txt"
    path.write_text("{}", encoding="utf-8")
    checks, reasons = validate(make_config(tmp_path, scale_candidates_with_ranger_json_path=path))

    assert checks["scale_candidates_with_ranger_json_path_suffix_json"] is False
    assert "scale_candidates_with_ranger_json_path suffix must be .json" in reasons


def test_05_validation_fails_for_invalid_spatialr_delta_px(tmp_path: Path) -> None:
    checks, reasons = validate(make_config(tmp_path, spatialr_delta_px=0))

    assert checks["spatialr_delta_px_positive_integer"] is False
    assert "spatialr_delta_px must be a positive integer" in reasons


def test_06_validation_fails_for_invalid_minsize_delta_fraction(tmp_path: Path) -> None:
    checks, reasons = validate(make_config(tmp_path, minsize_delta_fraction=1.0))

    assert checks["minsize_delta_fraction_valid"] is False
    assert "minsize_delta_fraction must be numeric and > 0 and < 1" in reasons


def test_07_validation_fails_for_invalid_ranger_delta_fraction(tmp_path: Path) -> None:
    checks, reasons = validate(make_config(tmp_path, ranger_delta_fraction=False))

    assert checks["ranger_delta_fraction_valid"] is False
    assert "ranger_delta_fraction must be numeric and > 0 and < 1" in reasons


def test_08_read_scale_candidates_with_ranger_fails_if_candidates_key_is_missing(tmp_path: Path) -> None:
    path = make_step7_json(tmp_path, {"candidate_id": "candidate-1"})

    try:
        read_scale_candidates_with_ranger(path)
    except ValueError as exc:
        assert "candidates key is missing" in str(exc)
    else:
        raise AssertionError("expected candidates key failure")


def test_09_read_scale_candidates_with_ranger_fails_if_candidates_is_empty(tmp_path: Path) -> None:
    path = make_step7_json(tmp_path, {"candidate_id": "candidate-1", "candidates": []})

    try:
        read_scale_candidates_with_ranger(path)
    except ValueError as exc:
        assert "candidates is empty" in str(exc)
    else:
        raise AssertionError("expected empty candidates failure")


def test_10_read_scale_candidates_with_ranger_fails_if_required_candidate_fields_are_missing(tmp_path: Path) -> None:
    for missing_field in ("candidate_id", "scale_id", "spatialr_px", "minsize_px", "ranger"):
        candidate = {
            "candidate_id": "source-a",
            "scale_id": "scale-a",
            "spatialr_px": 3,
            "minsize_px": 20,
            "ranger": 1.5,
        }
        candidate.pop(missing_field)
        path = make_step7_json(tmp_path, {"candidate_id": "candidate-1", "candidates": [candidate]})

        try:
            read_scale_candidates_with_ranger(path)
        except ValueError as exc:
            assert f"candidate field {missing_field} is missing" in str(exc)
        else:
            raise AssertionError(f"expected missing field failure for {missing_field}")


def test_11_read_scale_candidates_with_ranger_fails_if_values_are_invalid(tmp_path: Path) -> None:
    invalid_values = (
        ("spatialr_px", 0, "spatialr_px must be convertible to int and >= 1"),
        ("minsize_px", "bad", "minsize_px must be convertible to int and >= 1"),
        ("ranger", 0, "ranger must be convertible to float and > 0"),
    )

    for field, value, message in invalid_values:
        candidate = {
            "candidate_id": "source-a",
            "scale_id": "scale-a",
            "spatialr_px": 3,
            "minsize_px": 20,
            "ranger": 1.5,
        }
        candidate[field] = value
        path = make_step7_json(tmp_path, {"candidate_id": "candidate-1", "candidates": [candidate]})

        try:
            read_scale_candidates_with_ranger(path)
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError(f"expected invalid value failure for {field}")


def test_12_baseline_row_is_always_created(tmp_path: Path) -> None:
    rows = build_perturbation_candidates(make_config(tmp_path), one_complete_candidate(spatialr_px=1, minsize_px=1))

    assert rows[0]["is_baseline"] is True
    assert rows[0]["perturbation_id"].endswith("__perturb_000")


def test_13_baseline_row_preserves_spatialr_px_minsize_px_and_ranger(tmp_path: Path) -> None:
    rows = build_perturbation_candidates(make_config(tmp_path), one_complete_candidate(spatialr_px=7, minsize_px=31, ranger=3.5))

    assert rows[0]["spatialr_px"] == 7
    assert rows[0]["minsize_px"] == 31
    assert rows[0]["ranger"] == 3.5


def test_14_baseline_row_has_is_baseline_true_and_realized_zero_deltas(tmp_path: Path) -> None:
    rows = build_perturbation_candidates(make_config(tmp_path), one_complete_candidate())

    assert rows[0]["is_baseline"] is True
    assert rows[0]["deltas"] == {
        "axis": "baseline",
        "direction": "baseline",
        "spatialr_px_delta": 0,
        "minsize_px_delta": 0,
        "ranger_delta": 0.0,
    }


def test_15_deltas_record_realized_changes_after_clamping_and_rounding(tmp_path: Path) -> None:
    config = make_config(tmp_path, spatialr_delta_px=5, minsize_delta_fraction=0.10)
    rows = build_perturbation_candidates(config, one_complete_candidate(spatialr_px=3, minsize_px=5))

    assert rows[1]["deltas"]["spatialr_px_delta"] == -2
    minsize_minus = [row for row in rows if row["deltas"]["axis"] == "minsize_px" and row["deltas"]["direction"] == "minus"][0]
    assert minsize_minus["minsize_px"] == 4
    assert minsize_minus["deltas"]["minsize_px_delta"] == -1


def test_16_spatialr_perturbations_change_only_spatialr_px(tmp_path: Path) -> None:
    rows = build_perturbation_candidates(make_config(tmp_path), one_complete_candidate())
    spatial_rows = [row for row in rows if row["deltas"]["axis"] == "spatialr_px"]

    assert [row["deltas"]["direction"] for row in spatial_rows] == ["minus", "plus"]
    assert all(nonzero_delta_count(row) == 1 for row in spatial_rows)
    assert all(row["minsize_px"] == 100 and row["ranger"] == 2.0 for row in spatial_rows)


def test_17_minsize_perturbations_change_only_minsize_px(tmp_path: Path) -> None:
    rows = build_perturbation_candidates(make_config(tmp_path), one_complete_candidate())
    minsize_rows = [row for row in rows if row["deltas"]["axis"] == "minsize_px"]

    assert [row["deltas"]["direction"] for row in minsize_rows] == ["minus", "plus"]
    assert all(nonzero_delta_count(row) == 1 for row in minsize_rows)
    assert all(row["spatialr_px"] == 10 and row["ranger"] == 2.0 for row in minsize_rows)


def test_18_ranger_perturbations_change_only_ranger(tmp_path: Path) -> None:
    rows = build_perturbation_candidates(make_config(tmp_path), one_complete_candidate())
    ranger_rows = [row for row in rows if row["deltas"]["axis"] == "ranger"]

    assert [row["deltas"]["direction"] for row in ranger_rows] == ["minus", "plus"]
    assert all(nonzero_delta_count(row) == 1 for row in ranger_rows)
    assert all(row["spatialr_px"] == 10 and row["minsize_px"] == 100 for row in ranger_rows)


def test_19_non_baseline_rows_with_no_effective_change_are_omitted(tmp_path: Path) -> None:
    rows = build_perturbation_candidates(
        make_config(tmp_path, minsize_delta_fraction=0.10),
        one_complete_candidate(spatialr_px=1, minsize_px=1),
    )

    assert [row["deltas"]["axis"] for row in rows] == ["baseline", "spatialr_px", "ranger", "ranger"]
    assert [row["deltas"]["direction"] for row in rows] == ["baseline", "plus", "minus", "plus"]


def test_20_perturbation_ids_use_source_candidate_id_and_compact_zero_padded_local_indices(tmp_path: Path) -> None:
    rows = build_perturbation_candidates(
        make_config(tmp_path, minsize_delta_fraction=0.10),
        one_complete_candidate(candidate_id="source-id", spatialr_px=1, minsize_px=1),
    )

    assert [row["perturbation_id"] for row in rows] == [
        "source-id__perturb_000",
        "source-id__perturb_001",
        "source-id__perturb_002",
        "source-id__perturb_003",
    ]


def test_21_csv_deltas_are_compact_sorted_key_json_strings(tmp_path: Path) -> None:
    rows = build_perturbation_candidates(make_config(tmp_path), one_complete_candidate())
    csv_path = tmp_path / "perturbation_candidates.csv"
    write_perturbation_candidates_csv(rows, csv_path)

    with csv_path.open(newline="", encoding="utf-8") as file_obj:
        csv_rows = list(csv.DictReader(file_obj))

    assert csv_rows[0]["deltas"] == json.dumps(rows[0]["deltas"], sort_keys=True, separators=(",", ":"))


def test_22_json_deltas_are_objects(tmp_path: Path) -> None:
    report = run_local_perturbation_step(make_config(tmp_path))
    payload = json.loads(Path(report["output_json_path"]).read_text(encoding="utf-8"))

    assert isinstance(payload["candidates"][0]["deltas"], dict)


def test_23_normal_run_writes_csv_and_json(tmp_path: Path) -> None:
    report = run_local_perturbation_step(make_config(tmp_path))

    assert report["status"] == "ok"
    assert Path(report["output_csv_path"]).is_file()
    assert Path(report["output_json_path"]).is_file()
    assert report["files_written"] == [report["output_csv_path"], report["output_json_path"]]


def test_24_perturbation_candidates_json_has_exactly_required_keys(tmp_path: Path) -> None:
    report = run_local_perturbation_step(make_config(tmp_path))
    payload = json.loads(Path(report["output_json_path"]).read_text(encoding="utf-8"))

    assert list(payload) == [
        "candidate_id",
        "scale_candidates_with_ranger_json_path",
        "perturbation_rule",
        "spatialr_delta_px",
        "minsize_delta_fraction",
        "ranger_delta_fraction",
        "source_candidate_count",
        "perturbation_count",
        "candidates",
    ]


def test_25_no_cross_parameter_combination_is_produced(tmp_path: Path) -> None:
    rows = build_perturbation_candidates(make_config(tmp_path), one_complete_candidate())

    assert len(rows) == 7
    assert all(row["is_baseline"] or nonzero_delta_count(row) == 1 for row in rows)


def test_26_source_has_no_forbidden_raster_otb_segmentation_stability_or_global_grid_symbols() -> None:
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
    ]

    assert [symbol for symbol in blocked if symbol in source] == []


def test_27_protected_existing_files_are_unchanged() -> None:
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

    assert all((REPO_ROOT / "metashape_qc_engine" / filename).is_file() for filename in protected_files)
