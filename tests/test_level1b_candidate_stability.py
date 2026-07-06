import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from metashape_qc_engine.level1b import candidate_stability as stability
from metashape_qc_engine.level1b.candidate_stability import (
    Level1BCandidateStabilityConfig,
    group_perturbation_candidates,
    read_perturbation_candidates,
    run_candidate_stability,
)


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    return path


def rows() -> list[dict[str, object]]:
    return [
        {
            "perturbation_id": "cand-b__perturb_002",
            "source_candidate_id": "cand-b",
            "scale_id": "scale-b",
            "spatialr_px": 8,
            "minsize_px": 80,
            "ranger": 0.8,
            "is_baseline": False,
        },
        {
            "perturbation_id": "cand-a__perturb_002",
            "source_candidate_id": "cand-a",
            "scale_id": "scale-a",
            "spatialr_px": 7,
            "minsize_px": 70,
            "ranger": 0.7,
            "is_baseline": False,
        },
        {
            "perturbation_id": "cand-a__baseline",
            "source_candidate_id": "cand-a",
            "scale_id": "scale-a",
            "spatialr_px": 5,
            "minsize_px": 50,
            "ranger": 0.5,
            "is_baseline": True,
            "radius_m": 1.5,
            "area_m2": 25.0,
            "ranger_id": "range-a",
            "ranger_source": "feature",
            "assignment_rule": "nearest",
            "perturbation_rule": "local",
            "deltas": {"spatialr_px": 0},
        },
        {
            "perturbation_id": "cand-b__baseline",
            "source_candidate_id": "cand-b",
            "scale_id": "scale-b",
            "spatialr_px": 6,
            "minsize_px": 60,
            "ranger": 0.6,
            "is_baseline": True,
        },
        {
            "perturbation_id": "cand-a__perturb_001",
            "source_candidate_id": "cand-a",
            "scale_id": "scale-a",
            "spatialr_px": 4,
            "minsize_px": 40,
            "ranger": 0.4,
            "is_baseline": False,
        },
    ]


def write_candidates(tmp_path: Path, candidate_rows: list[dict[str, object]] | None = None) -> Path:
    path = tmp_path / "perturbation_candidates.json"
    path.write_text(json.dumps({"candidates": candidate_rows if candidate_rows is not None else rows()}), encoding="utf-8")
    return path


def make_config(tmp_path: Path, candidate_rows: list[dict[str, object]] | None = None, **overrides: object) -> Level1BCandidateStabilityConfig:
    feature = touch(tmp_path / "features.tif")
    values = {
        "candidate_id": "run-1",
        "output_dir": tmp_path / "out",
        "perturbation_candidates_json_path": write_candidates(tmp_path, candidate_rows),
        "feature_space_stack_path": feature,
        "overwrite": True,
    }
    values.update(overrides)
    return Level1BCandidateStabilityConfig(**values)


def fake_segmentation_factory(calls: list[object], fail_ids: set[str] | None = None):
    fail_ids = fail_ids or set()

    def fake_run(config):
        calls.append(config)
        report_path = Path(config.output_dir) / "level1b" / "segmentation_smoke" / config.perturbation_id / "one_scale_segmentation_report.json"
        merged_path = report_path.with_name("merged_labels.tif")
        if config.perturbation_id in fail_ids:
            return {
                "status": "failed",
                "failure_reasons": ["segmentation failed"],
                "output_artifacts": {"report": str(report_path), "merged_labels": str(merged_path)},
            }
        return {
            "status": "ok",
            "failure_reasons": [],
            "output_artifacts": {"report": str(report_path), "merged_labels": str(merged_path)},
        }

    return fake_run


def fake_hoover_factory(calls: list[object], empty_for: set[str] | None = None, fail_for: set[str] | None = None):
    empty_for = empty_for or set()
    fail_for = fail_for or set()

    def fake_run(config):
        calls.append(config)
        raw_path = Path(config.output_dir) / "level1b" / "hoover" / config.comparison_id / "hoover_raw.txt"
        if config.perturbation_labels_path in fail_for or config.comparison_id in fail_for:
            return {
                "status": "failed",
                "failure_reasons": ["hoover failed"],
                "raw_output_path": str(raw_path),
                "parser_status": "not_run",
                "parsed_metrics": {},
            }
        if config.comparison_id in empty_for:
            metrics = {}
            parser_status = "raw_only_no_safe_numeric_schema"
        else:
            metrics = {"correct_detection_score": 0.5, "over_segmentation_score": 0.25}
            parser_status = "parsed_numeric_key_values"
        return {
            "status": "ok",
            "failure_reasons": [],
            "raw_output_path": str(raw_path),
            "parser_status": parser_status,
            "parsed_metrics": metrics,
        }

    return fake_run


def test_01_reads_perturbation_candidates_json(tmp_path: Path) -> None:
    path = write_candidates(tmp_path)

    loaded = read_perturbation_candidates(path)

    assert [row["perturbation_id"] for row in loaded] == [row["perturbation_id"] for row in rows()]


def test_02_groups_by_source_candidate_and_scale_with_one_baseline() -> None:
    groups = group_perturbation_candidates(rows())

    assert [(group["source_candidate_id"], group["scale_id"]) for group in groups] == [
        ("cand-a", "scale-a"),
        ("cand-b", "scale-b"),
    ]
    assert [group["baseline"]["perturbation_id"] for group in groups] == ["cand-a__baseline", "cand-b__baseline"]


def test_03_missing_baseline_fails(tmp_path: Path) -> None:
    candidate_rows = [row for row in rows() if row["source_candidate_id"] != "cand-a" or not row["is_baseline"]]
    report = run_candidate_stability(make_config(tmp_path, candidate_rows))

    assert report["groups_failed"] == 1
    assert "without exactly one baseline row" in report["failure_reasons"][0]


def test_04_multiple_baselines_fail(tmp_path: Path) -> None:
    candidate_rows = rows()
    duplicate = dict(candidate_rows[2], perturbation_id="cand-a__baseline_2")
    candidate_rows.append(duplicate)

    report = run_candidate_stability(make_config(tmp_path, candidate_rows))

    assert report["groups_failed"] == 1
    assert "with multiple baseline rows" in report["failure_reasons"][0]


def test_05_runs_baseline_first_and_perturbations_in_id_order(tmp_path: Path, monkeypatch) -> None:
    segmentation_calls: list[object] = []
    hoover_calls: list[object] = []
    monkeypatch.setattr(stability, "run_one_scale_segmentation_smoke", fake_segmentation_factory(segmentation_calls))
    monkeypatch.setattr(stability, "run_hoover_compare", fake_hoover_factory(hoover_calls))

    run_candidate_stability(make_config(tmp_path))

    assert [call.perturbation_id for call in segmentation_calls] == [
        "cand-a__baseline",
        "cand-a__perturb_001",
        "cand-a__perturb_002",
        "cand-b__baseline",
        "cand-b__perturb_002",
    ]


def test_06_segmentation_uses_existing_helper_and_passes_only_existing_config_fields(tmp_path: Path, monkeypatch) -> None:
    segmentation_calls: list[object] = []
    monkeypatch.setattr(stability, "run_one_scale_segmentation_smoke", fake_segmentation_factory(segmentation_calls))
    monkeypatch.setattr(stability, "run_hoover_compare", fake_hoover_factory([]))

    run_candidate_stability(make_config(tmp_path))

    first_call = segmentation_calls[0]
    assert first_call.perturbation_id == "cand-a__baseline"
    assert first_call.feature_space_stack_path == tmp_path / "features.tif"
    assert first_call.perturbation_candidates_json_path == tmp_path / "perturbation_candidates.json"
    assert not hasattr(first_call, "spatialr_px")
    assert not hasattr(first_call, "minsize_px")
    assert not hasattr(first_call, "ranger")


def test_07_hoover_uses_existing_helper_and_compares_each_perturbation_to_own_baseline(tmp_path: Path, monkeypatch) -> None:
    segmentation_calls: list[object] = []
    hoover_calls: list[object] = []
    monkeypatch.setattr(stability, "run_one_scale_segmentation_smoke", fake_segmentation_factory(segmentation_calls))
    monkeypatch.setattr(stability, "run_hoover_compare", fake_hoover_factory(hoover_calls))

    run_candidate_stability(make_config(tmp_path))

    assert [call.comparison_id for call in hoover_calls] == [
        "cand-a__cand-a__perturb_001",
        "cand-a__cand-a__perturb_002",
        "cand-b__cand-b__perturb_002",
    ]
    assert all("cand-a__baseline" in str(call.baseline_labels_path) for call in hoover_calls[:2])
    assert "cand-b__baseline" in str(hoover_calls[2].baseline_labels_path)
    assert all("cand-b__baseline" not in str(call.baseline_labels_path) for call in hoover_calls[:2])


def test_08_outputs_are_deterministic_non_colliding_and_summary_files_written(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(stability, "run_one_scale_segmentation_smoke", fake_segmentation_factory([]))
    monkeypatch.setattr(stability, "run_hoover_compare", fake_hoover_factory([]))

    report = run_candidate_stability(make_config(tmp_path))

    assert Path(report["scale_stability_csv_path"]).exists()
    assert Path(report["scale_stability_json_path"]).exists()
    assert (tmp_path / "out" / "level1b" / "stability" / "cand-a" / "candidate_stability_report.json").exists()
    assert (tmp_path / "out" / "level1b" / "stability" / "cand-b" / "candidate_stability_report.json").exists()
    assert "baseline" in report["candidate_summaries"][0]["baseline_merged_labels_path"]


def test_09_failed_perturbation_segmentation_is_reported_and_counted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        stability,
        "run_one_scale_segmentation_smoke",
        fake_segmentation_factory([], fail_ids={"cand-a__perturb_001"}),
    )
    monkeypatch.setattr(stability, "run_hoover_compare", fake_hoover_factory([]))

    report = run_candidate_stability(make_config(tmp_path))
    cand_a = next(item for item in report["candidate_summaries"] if item["source_candidate_id"] == "cand-a")

    assert cand_a["candidate_status"] == "partial"
    assert cand_a["successful_perturbation_count"] == 1
    assert cand_a["failed_perturbation_count"] == 1


def test_10_baseline_failure_marks_group_failed_and_skips_comparisons(tmp_path: Path, monkeypatch) -> None:
    hoover_calls: list[object] = []
    monkeypatch.setattr(
        stability,
        "run_one_scale_segmentation_smoke",
        fake_segmentation_factory([], fail_ids={"cand-a__baseline"}),
    )
    monkeypatch.setattr(stability, "run_hoover_compare", fake_hoover_factory(hoover_calls))

    report = run_candidate_stability(make_config(tmp_path))
    cand_a = next(item for item in report["candidate_summaries"] if item["source_candidate_id"] == "cand-a")

    assert cand_a["candidate_status"] == "failed"
    assert cand_a["failed_perturbation_count"] == 2
    assert all("cand-a" not in call.comparison_id for call in hoover_calls)


def test_11_hoover_numeric_metrics_are_aggregated_only_when_present(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(stability, "run_one_scale_segmentation_smoke", fake_segmentation_factory([]))
    monkeypatch.setattr(
        stability,
        "run_hoover_compare",
        fake_hoover_factory([], empty_for={"cand-a__cand-a__perturb_002", "cand-b__cand-b__perturb_002"}),
    )

    report = run_candidate_stability(make_config(tmp_path))
    cand_a = next(item for item in report["candidate_summaries"] if item["source_candidate_id"] == "cand-a")
    cand_b = next(item for item in report["candidate_summaries"] if item["source_candidate_id"] == "cand-b")

    assert cand_a["hoover_numeric_metric_keys"] == ["correct_detection_score", "over_segmentation_score"]
    assert cand_a["hoover_correct_detection_score_mean"] == 0.5
    assert "hoover_correct_detection_score_mean" not in cand_b
    assert cand_b["hoover_numeric_metric_keys"] == []


def test_12_validation_rejects_bad_inputs_and_output_collision(tmp_path: Path) -> None:
    bad_rows = [dict(rows()[2], spatialr_px=0)]
    config = make_config(tmp_path, bad_rows, feature_space_stack_path=touch(tmp_path / "features.txt"))

    report = run_candidate_stability(config)

    assert report["groups_failed"] == 1
    assert any("feature_space_stack_path suffix" in reason for reason in report["failure_reasons"])

    good_config = make_config(tmp_path / "collision")
    layout = stability.build_level1b_candidate_stability_layout(good_config.output_dir)
    touch(layout["scale_stability_csv_path"])
    collision_report = run_candidate_stability(Level1BCandidateStabilityConfig(**{**good_config.__dict__, "overwrite": False}))
    assert any("overwrite is false" in reason for reason in collision_report["failure_reasons"])


def test_13_step9_does_not_build_otb_commands_or_emit_blocked_outputs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(stability, "run_one_scale_segmentation_smoke", fake_segmentation_factory([]))
    monkeypatch.setattr(stability, "run_hoover_compare", fake_hoover_factory([]))

    report = run_candidate_stability(make_config(tmp_path))
    source = (REPO_ROOT / "metashape_qc_engine" / "level1b" / "candidate_stability.py").read_text(encoding="utf-8")
    test_source = (REPO_ROOT / "tests" / "test_level1b_candidate_stability.py").read_text(encoding="utf-8")
    combined = source + "\n" + test_source
    blocked = [
        "selected_" + "scale_id",
        "final_" + "labels",
        "final_" + "segments",
        "g" + "pkg",
        "shape" + "file",
        "LSMS" + "Vectorization",
        "side" + "car",
        "C" + "LI",
        "run" + "ner",
    ]

    assert "MeanShiftSmoothing" not in source
    assert "LSMSSegmentation" not in source
    assert "SmallRegionsMerging" not in source
    assert "HooverCompareSegmentation" not in source
    assert [term for term in blocked if term in combined] == []
    assert "selected_" + "scale_id" not in json.dumps(report)
    assert "final_" + "labels" not in json.dumps(report)
    assert "vector" in json.dumps(report)


def test_14_dry_run_builds_planned_segmentation_without_calling_helpers(tmp_path: Path, monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise AssertionError("helper should not be called during Step 9 dry run")

    monkeypatch.setattr(stability, "run_one_scale_segmentation_smoke", fail)
    monkeypatch.setattr(stability, "run_hoover_compare", fail)

    report = run_candidate_stability(make_config(tmp_path, dry_run=True))

    assert report["segmentation_runs_attempted"] == 5
    assert report["hoover_comparisons_attempted"] == 0
