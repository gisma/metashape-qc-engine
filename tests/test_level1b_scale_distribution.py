import csv
import json
from math import pi
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from metashape_qc_engine.level1b_scale_distribution import (
    Level1BScaleDistributionConfig,
    build_level1b_scale_distribution_layout,
    build_scale_candidates,
    run_scale_distribution_step,
    validate_scale_distribution_config,
)


def make_metric_config(tmp_path: Path, **overrides: object) -> Level1BScaleDistributionConfig:
    values = {
        "candidate_id": "test",
        "output_dir": tmp_path / "out",
        "pixel_size_m": 0.5,
        "scale_mode": "metric_scale_sweep",
        "metric_radius_m": (2.0, 1.0, 2.0),
    }
    values.update(overrides)
    return Level1BScaleDistributionConfig(**values)


def make_structure_config(tmp_path: Path, **overrides: object) -> Level1BScaleDistributionConfig:
    values = {
        "candidate_id": "test",
        "output_dir": tmp_path / "out",
        "pixel_size_m": 0.25,
        "scale_mode": "structure_derived_scale_distribution",
        "structure_radius_m": (0.5, 1.0, 0.5),
    }
    values.update(overrides)
    return Level1BScaleDistributionConfig(**values)


def validate(config: Level1BScaleDistributionConfig) -> tuple[dict[str, bool], list[str]]:
    return validate_scale_distribution_config(config, build_level1b_scale_distribution_layout(config.output_dir))


def test_01_layout_creates_only_scales_directory(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    layout = build_level1b_scale_distribution_layout(output_dir)

    assert list(layout) == ["scales_dir"]
    assert layout["scales_dir"].is_dir()
    assert sorted(path.relative_to(output_dir) for path in output_dir.rglob("*")) == [
        Path("level1b"),
        Path("level1b/scales"),
    ]


def test_02_metric_scale_sweep_builds_one_candidate_per_unique_sorted_radius(tmp_path: Path) -> None:
    candidates = build_scale_candidates(make_metric_config(tmp_path, metric_radius_m=(4, 2, 4, 1)))

    assert [candidate["radius_m"] for candidate in candidates] == [1.0, 2.0, 4.0]
    assert len(candidates) == 3


def test_03_structure_derived_scale_distribution_builds_one_candidate_per_unique_sorted_radius(tmp_path: Path) -> None:
    candidates = build_scale_candidates(make_structure_config(tmp_path, structure_radius_m=(3, 1, 3, 2)))

    assert [candidate["radius_m"] for candidate in candidates] == [1.0, 2.0, 3.0]
    assert len(candidates) == 3


def test_04_radius_m_derives_area_m2(tmp_path: Path) -> None:
    candidate = build_scale_candidates(make_metric_config(tmp_path, metric_radius_m=(2.0,)))[0]

    assert candidate["area_m2"] == pi * 2.0**2


def test_05_radius_m_derives_spatialr_px(tmp_path: Path) -> None:
    candidate = build_scale_candidates(make_metric_config(tmp_path, pixel_size_m=0.6, metric_radius_m=(0.2,)))[0]

    assert candidate["spatialr_px"] == max(1, round(0.2 / 0.6))


def test_06_area_m2_derives_minsize_px(tmp_path: Path) -> None:
    candidate = build_scale_candidates(make_metric_config(tmp_path, pixel_size_m=0.5, metric_radius_m=(1.0,)))[0]

    assert candidate["minsize_px"] == max(1, round((pi * 1.0**2) / (0.5**2)))


def test_07_candidate_ids_use_zero_padded_scale_index(tmp_path: Path) -> None:
    candidates = build_scale_candidates(make_metric_config(tmp_path, metric_radius_m=(2.0, 1.0)))

    assert [candidate["candidate_id"] for candidate in candidates] == ["test_scale_001", "test_scale_002"]


def test_08_metric_scale_source_is_metric_radius_m(tmp_path: Path) -> None:
    candidates = build_scale_candidates(make_metric_config(tmp_path))

    assert {candidate["scale_source"] for candidate in candidates} == {"metric_radius_m"}


def test_09_structure_scale_source_is_structure_radius_m(tmp_path: Path) -> None:
    candidates = build_scale_candidates(make_structure_config(tmp_path))

    assert {candidate["scale_source"] for candidate in candidates} == {"structure_radius_m"}


def test_10_json_ranger_is_none(tmp_path: Path) -> None:
    report = run_scale_distribution_step(make_metric_config(tmp_path))
    payload = json.loads(Path(report["output_json_path"]).read_text(encoding="utf-8"))

    assert payload["candidates"][0]["ranger"] is None


def test_11_csv_ranger_is_na(tmp_path: Path) -> None:
    report = run_scale_distribution_step(make_metric_config(tmp_path))

    with Path(report["output_csv_path"]).open(newline="", encoding="utf-8") as file_obj:
        rows = list(csv.DictReader(file_obj))

    assert rows[0]["ranger"] == "NA"


def test_12_validation_fails_for_empty_candidate_id(tmp_path: Path) -> None:
    checks, reasons = validate(make_metric_config(tmp_path, candidate_id=" "))

    assert checks["candidate_id_non_empty"] is False
    assert "candidate_id is empty" in reasons


def test_13_validation_fails_for_nonpositive_pixel_size_m(tmp_path: Path) -> None:
    checks, reasons = validate(make_metric_config(tmp_path, pixel_size_m=0))

    assert checks["pixel_size_m_valid"] is False
    assert "pixel_size_m must be numeric and > 0" in reasons


def test_14_validation_fails_for_invalid_scale_mode(tmp_path: Path) -> None:
    checks, reasons = validate(make_metric_config(tmp_path, scale_mode="invalid"))

    assert checks["scale_mode_valid"] is False
    assert any("scale_mode must be exactly" in reason for reason in reasons)


def test_15_validation_fails_if_metric_mode_has_no_metric_radius_m(tmp_path: Path) -> None:
    checks, reasons = validate(make_metric_config(tmp_path, metric_radius_m=None))

    assert checks["metric_radius_m_present"] is False
    assert "metric_radius_m is required for metric_scale_sweep" in reasons


def test_16_validation_fails_if_metric_mode_also_receives_structure_radius_m(tmp_path: Path) -> None:
    checks, reasons = validate(make_metric_config(tmp_path, structure_radius_m=(1.0,)))

    assert checks["metric_structure_radius_m_absent"] is False
    assert "structure_radius_m must be None for metric_scale_sweep" in reasons


def test_17_validation_fails_if_structure_mode_has_no_structure_radius_m(tmp_path: Path) -> None:
    checks, reasons = validate(make_structure_config(tmp_path, structure_radius_m=None))

    assert checks["structure_radius_m_present"] is False
    assert "structure_radius_m is required for structure_derived_scale_distribution" in reasons


def test_18_validation_fails_if_structure_mode_also_receives_metric_radius_m(tmp_path: Path) -> None:
    checks, reasons = validate(make_structure_config(tmp_path, metric_radius_m=(1.0,)))

    assert checks["structure_metric_radius_m_absent"] is False
    assert "metric_radius_m must be None for structure_derived_scale_distribution" in reasons


def test_19_validation_fails_for_invalid_radius_values(tmp_path: Path) -> None:
    metric_checks, metric_reasons = validate(make_metric_config(tmp_path, metric_radius_m=(1.0, 0.0)))
    structure_checks, structure_reasons = validate(make_structure_config(tmp_path, structure_radius_m=(1.0, "bad")))

    assert metric_checks["metric_radius_m_values_valid"] is False
    assert "metric_radius_m values must be numeric and > 0" in metric_reasons
    assert structure_checks["structure_radius_m_values_valid"] is False
    assert "structure_radius_m values must be numeric and > 0" in structure_reasons


def test_20_normal_run_writes_csv_and_json(tmp_path: Path) -> None:
    report = run_scale_distribution_step(make_metric_config(tmp_path))

    assert report["status"] == "ok"
    assert Path(report["output_csv_path"]).is_file()
    assert Path(report["output_json_path"]).is_file()
    assert report["files_written"] == [report["output_csv_path"], report["output_json_path"]]


def test_21_output_json_has_exactly_required_keys(tmp_path: Path) -> None:
    report = run_scale_distribution_step(make_metric_config(tmp_path))
    payload = json.loads(Path(report["output_json_path"]).read_text(encoding="utf-8"))

    assert list(payload) == [
        "candidate_id",
        "scale_mode",
        "scale_source",
        "pixel_size_m",
        "pixel_area_m2",
        "candidate_count",
        "candidates",
    ]


def test_22_source_has_no_forbidden_workflow_symbols() -> None:
    source = (REPO_ROOT / "metashape_qc_engine" / "level1b_scale_distribution.py").read_text(encoding="utf-8")
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
        "Dimensionality" + "Reduction",
        "Compute" + "ImagesStatistics",
        "Local" + "StatisticExtraction",
        "Mean" + "Shift",
        "LS" + "MS",
        "Ho" + "over",
        "feature" + "_stack",
        "scaled" + "_feature_stack",
        "pca" + "_feature_stack",
        "valid" + "_mask",
        "ranger" + "_assignment",
        "estimate" + "_ranger",
        "full" + "_grid",
        "parameter" + "_grid",
    ]

    assert [symbol for symbol in blocked if symbol in source] == []


def test_23_protected_existing_files_are_unchanged(tmp_path: Path) -> None:
    config = make_metric_config(tmp_path)
    first = run_scale_distribution_step(config)
    csv_path = Path(first["output_csv_path"])
    json_path = Path(first["output_json_path"])
    csv_before = csv_path.read_text(encoding="utf-8")
    json_before = json_path.read_text(encoding="utf-8")

    second = run_scale_distribution_step(config)

    assert second["status"] == "failed"
    assert second["files_written"] == []
    assert csv_path.read_text(encoding="utf-8") == csv_before
    assert json_path.read_text(encoding="utf-8") == json_before
