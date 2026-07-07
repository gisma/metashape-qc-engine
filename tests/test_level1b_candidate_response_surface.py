import csv
import inspect
import json
from pathlib import Path
import sys

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from metashape_qc_engine.level1b import candidate_response_surface as rs
from metashape_qc_engine.level1b.candidate_response_surface import (
    Level1BCandidateResponseSurfaceConfig,
    aggregate_analysis_matrix,
    analyze_full_candidate_space,
    area_weighted_q_histogram,
    assign_scale_relative_size_classes,
    compute_candidate_group_response_summary,
    compute_class_summaries,
    compute_normal_response_diagnostics,
    compute_run_population_summary,
    count_segment_sizes,
    equivalent_radii,
    group_rows_by_candidate_scale,
    ordinal_cumulative_distribution_distance,
    run_candidate_response_surface_step,
    select_medoid_run,
)


@pytest.fixture(autouse=True)
def _stub_canonical_masked_stack(monkeypatch: pytest.MonkeyPatch):
    def prepare(
        segmentation_stack_path,
        valid_mask_path,
        output_path,
        *,
        segmentation_nodata_value=0.0,
        overwrite=False,
    ):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"canonical-masked-stack")
        report = {
            "status": "ok",
            "preparation_status": "computed",
            "segmentation_stack_path": str(segmentation_stack_path),
            "valid_mask_path": str(valid_mask_path),
            "segmentation_nodata_value": float(segmentation_nodata_value),
            "masked_segmentation_stack_path": str(output_path),
        }
        output_path.with_name("masked_segmentation_stack_report.json").write_text(
            json.dumps(report), encoding="utf-8"
        )
        return report

    monkeypatch.setattr(rs, "prepare_canonical_masked_segmentation_stack", prepare)


def cfg(tmp_path: Path | None = None, **overrides) -> Level1BCandidateResponseSurfaceConfig:
    root = tmp_path or Path("/tmp")
    values = {
        "candidate_id": "candidate",
        "output_dir": root / "out",
        "perturbation_candidates_json_path": root / "candidates.json",
        "feature_space_stack_path": root / "features.tif",
        "overwrite": True,
    }
    values.update(overrides)
    return Level1BCandidateResponseSurfaceConfig(**values)


def rows() -> list[dict[str, object]]:
    return [
        {"perturbation_id": "b2", "source_candidate_id": "cand-b", "scale_id": "scale-b", "radius_m": 2.0, "spatialr_px": 2, "minsize_px": 4, "ranger": 0.2},
        {"perturbation_id": "a2", "source_candidate_id": "cand-a", "scale_id": "scale-a", "radius_m": 2.0, "spatialr_px": 2, "minsize_px": 4, "ranger": 0.2},
        {"perturbation_id": "a1", "source_candidate_id": "cand-a", "scale_id": "scale-a", "radius_m": 2.0, "spatialr_px": 2, "minsize_px": 4, "ranger": 0.2},
    ]


def write_raster(path: Path, data: np.ndarray, pixel_size: float = 1.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=data.dtype,
        transform=from_origin(0, 0, pixel_size, pixel_size),
    ) as dst:
        dst.write(data, 1)
    return path


def summary(run_id: str, dist: list[float], hist: list[float] | None = None, **extra) -> dict[str, object]:
    hist = hist or dist + [0.0, 0.0]
    base = {
        "run_id": run_id,
        "candidate_scale_group_id": "scale-a",
        "size_class_area_distribution": dist,
        "q_histogram_area_distribution": hist,
        "area_weighted_q_q10": 0.8,
        "area_weighted_q_q50": 1.0,
        "area_weighted_q_median": 1.0,
        "area_weighted_q_q75": 1.1,
        "area_weighted_q_q90": 1.2,
        "area_weighted_q_q95": 1.3,
        "micro_area_share": dist[0],
        "small_area_share": dist[1],
        "in_scale_area_share": dist[2],
        "large_area_share": dist[3],
        "oversize_area_share": dist[4],
        "lower_tail_area_share": dist[0] + dist[1],
        "central_area_share": dist[2],
        "upper_tail_area_share": dist[3] + dist[4],
        "scale_match_support": 1.0,
    }
    base.update(extra)
    return base


def test_01_groups_step8_rows_into_candidate_scale_groups() -> None:
    groups = group_rows_by_candidate_scale(rows())

    assert [group["candidate_scale_group_id"] for group in groups] == ["scale-a", "scale-b"]
    assert [row["perturbation_id"] for row in groups[0]["rows"]] == ["a1", "a2"]


def test_step8_reader_accepts_direct_candidate_list(tmp_path: Path) -> None:
    candidate_rows = rows()
    path = tmp_path / "midpoint_perturbation_candidates.json"
    path.write_text(json.dumps(candidate_rows), encoding="utf-8")

    assert rs.read_step8_local_parameter_combinations(path) == candidate_rows


def test_step9_input_validation_failure_reports_failed_status(tmp_path: Path) -> None:
    path = tmp_path / "empty_candidates.json"
    path.write_text("[]", encoding="utf-8")

    report = run_candidate_response_surface_step(
        cfg(tmp_path, perturbation_candidates_json_path=path)
    )

    assert report["status"] == "failed"
    assert report["number_of_failed_runs"] == 1
    assert report["failed_runs"][0]["status"] == "failed"
    assert "empty or missing" in report["failed_runs"][0]["reason"]


def test_02_counts_segments_without_dense_label_assumption() -> None:
    labels = np.array([[0, 5, 5], [1000, 1000, 0]], dtype=np.int32)
    counts = count_segment_sizes(labels, 2.0)

    assert counts["max_label"] == 1000
    assert counts["unique_label_count"] == 2
    assert counts["label_count_strategy"] == "sparse_unique"
    assert dict(zip(counts["labels"].tolist(), counts["area_px"].tolist())) == {5: 2, 1000: 2}


def test_03_equivalent_radius_formula() -> None:
    radii = equivalent_radii(np.array([np.pi, 4.0 * np.pi]))

    assert np.allclose(radii, np.array([1.0, 2.0]))


def test_04_q_uses_source_candidate_radius() -> None:
    labels = np.array([[1, 1, 1, 1]], dtype=np.int32)
    run = compute_run_population_summary("run-a", "scale-a", {"radius_m": 2.0}, labels, 1.0, cfg())

    assert np.isclose(run["area_weighted_q_median"], (2.0 / np.sqrt(np.pi)) / 2.0)


def test_continuous_scale_match_is_reciprocal_and_area_weighted() -> None:
    support = rs.area_weighted_scale_match_support(
        np.asarray([1.0, 0.5, 2.0]),
        np.asarray([2.0, 1.0, 1.0]),
    )

    assert support == pytest.approx(0.75)


def test_robust_lower_support_penalizes_perturbation_uncertainty() -> None:
    support = rs.robust_lower_support([0.7, 0.8, 0.9])

    assert support["median"] == pytest.approx(0.8)
    assert support["mad"] == pytest.approx(0.1)
    assert support["support"] == pytest.approx(0.8 - 1.4826 * 0.1)


def test_scale_relative_boundary_support_uses_candidate_radius() -> None:
    valid = np.ones((7, 7), dtype=bool)
    left = np.zeros((7, 7), dtype=bool)
    right = np.zeros((7, 7), dtype=bool)
    left[:, 2] = True
    right[:, 3] = True

    small = rs._scale_relative_boundary_sums(
        left, right, valid, 0, 7, 2.0
    )
    large = rs._scale_relative_boundary_sums(
        left, right, valid, 0, 7, 4.0
    )
    small_support = (small[2] + small[3]) / (small[0] + small[1])
    large_support = (large[2] + large[3]) / (large[0] + large[1])

    assert small_support == pytest.approx(0.5)
    assert large_support == pytest.approx(0.75)


def test_05_assigns_diagnostic_size_classes() -> None:
    classes = assign_scale_relative_size_classes(np.array([0.1, 0.3, 1.0, 3.0, 5.0]), cfg())

    assert classes.tolist() == ["micro", "small", "in_scale", "large", "oversize"]


def test_06_area_weighted_class_shares() -> None:
    classes = np.array(["micro", "in_scale", "oversize"], dtype=object)
    out = compute_class_summaries(classes, np.array([1.0, 2.0, 1.0]), np.array([1.0, 2.0, 3.0]))

    assert out["micro"]["area_share"] == 0.25
    assert out["in_scale"]["area_share"] == 0.5
    assert out["oversize"]["area_share"] == 0.25


def test_07_lower_central_upper_tail_shares() -> None:
    classes = np.array(["micro", "small", "in_scale", "large", "oversize"], dtype=object)
    out = compute_class_summaries(classes, np.ones(5), np.ones(5))

    assert out["lower_tail_area_share"] == 0.4
    assert out["central_area_share"] == 0.2
    assert out["upper_tail_area_share"] == 0.4


def test_08_normal_response_diagnostics_centered_distribution() -> None:
    diagnostics = compute_normal_response_diagnostics([summary("r1", [0.05, 0.1, 0.75, 0.05, 0.05])], cfg())

    assert diagnostics["centered"]
    assert not diagnostics["missing_central_mass_flag"]


def test_09_detects_lower_tail_only_response() -> None:
    diagnostics = compute_normal_response_diagnostics([summary("r1", [0.6, 0.3, 0.1, 0.0, 0.0])], cfg())

    assert diagnostics["lower_tail_dominated"]
    assert diagnostics["one_sided_lower_tail_flag"]


def test_10_detects_upper_tail_only_response() -> None:
    diagnostics = compute_normal_response_diagnostics([summary("r1", [0.0, 0.0, 0.1, 0.3, 0.6])], cfg())

    assert diagnostics["upper_tail_dominated"]
    assert diagnostics["one_sided_upper_tail_flag"]


def test_11_detects_distributional_flutter() -> None:
    group = compute_candidate_group_response_summary(
        "scale-a",
        [summary("r1", [0.9, 0.1, 0.0, 0.0, 0.0]), summary("r2", [0.0, 0.0, 0.0, 0.1, 0.9])],
        [],
        cfg(max_distribution_flutter=0.5),
    )

    assert group["distribution_flutter_flag"]
    assert group["flurry_like"]


def test_12_ordinal_cumulative_distribution_distance() -> None:
    distance = ordinal_cumulative_distribution_distance([1, 0, 0, 0, 0], [0, 0, 1, 0, 0])

    assert distance == 2.0


def test_13_medoid_selection_from_summary_distances() -> None:
    medoid = select_medoid_run(
        [
            summary("left", [0.8, 0.2, 0.0, 0.0, 0.0]),
            summary("middle", [0.0, 0.2, 0.8, 0.0, 0.0]),
            summary("right", [0.0, 0.0, 0.0, 0.2, 0.8]),
        ]
    )

    assert medoid["medoid_run_id"] == "middle"


def test_14_analysis_matrix_aggregation() -> None:
    labels = np.array([[1, 1, 2, 2], [1, 1, 2, 2], [3, 3, 4, 4], [3, 3, 4, 4]], dtype=np.int32)
    label_classes = {1: "micro", 2: "in_scale", 3: "large", 4: "oversize"}
    matrix = aggregate_analysis_matrix(labels, label_classes, 1.0, 2.0, "run-a", "scale-a")

    assert len(matrix["cell_records"]) == 4
    assert matrix["cell_records"][0]["dominant_size_class"] == "micro"


def test_15_spatial_dominance_summaries() -> None:
    labels = np.array([[1, 1, 2, 2], [1, 1, 2, 2]], dtype=np.int32)
    matrix = aggregate_analysis_matrix(labels, {1: "micro", 2: "in_scale"}, 1.0, 2.0, "run-a", "scale-a")

    assert matrix["summary"]["analysis_cell_count"] == 2
    assert matrix["summary"]["dominant_lower_tail_cell_share"] == 0.5
    assert matrix["summary"]["dominant_central_cell_share"] == 0.5


def test_16_full_candidate_space_distribution_summary() -> None:
    space = analyze_full_candidate_space(
        [{"candidate_scale_group_id": "scale-a", "candidate_outcome": "ensemble_support_evaluable", "stability_score": 0.9, "response_center_q": 1.0, "response_spread_q": 0.2, "central_area_share_mean": 0.8}],
        [{"source_candidate_radius_m": 2.0}],
    )

    assert space["all_run_count"] == 1
    assert space["all_candidate_group_count"] == 1
    assert space["stable_mode_count"] == 1


def test_17_active_step9_does_not_call_hoover_by_default(tmp_path: Path, monkeypatch) -> None:
    feature = write_raster(tmp_path / "features.tif", np.ones((2, 2), dtype=np.uint8))
    labels = write_raster(tmp_path / "labels.tif", np.array([[1, 1], [2, 2]], dtype=np.uint32))
    candidate_path = tmp_path / "candidates.json"
    candidate_path.write_text(json.dumps({"candidates": [{"perturbation_id": "run-a", "source_candidate_id": "cand-a", "scale_id": "scale-a", "radius_m": 1.0, "spatialr_px": 1, "minsize_px": 1, "ranger": 0.1}]}), encoding="utf-8")

    def fake_segmentation(config):
        return {"status": "ok", "failure_reasons": [], "output_artifacts": {"merged_labels": str(labels)}}

    monkeypatch.setattr(rs, "run_one_scale_segmentation_smoke", fake_segmentation)
    report = run_candidate_response_surface_step(
        cfg(tmp_path, perturbation_candidates_json_path=candidate_path, feature_space_stack_path=feature)
    )

    assert report["active_step9_does_not_run_full_hoover_by_default"]
    assert report["hoover_audit_run"] is False


def test_18_legacy_hoover_archive_remains_importable() -> None:
    import metashape_qc_engine.legacy.level1b_candidate_stability_hoover_archive as archive

    assert hasattr(archive, "run_candidate_stability")


def test_19_required_outputs_are_written(tmp_path: Path, monkeypatch) -> None:
    feature = write_raster(tmp_path / "features.tif", np.ones((2, 2), dtype=np.uint8))
    mask = write_raster(tmp_path / "mask.tif", np.ones((2, 2), dtype=np.uint8))
    labels = write_raster(tmp_path / "labels.tif", np.array([[1, 1], [2, 2]], dtype=np.uint32))
    candidate_path = tmp_path / "candidates.json"
    candidate_path.write_text(json.dumps({"candidates": [{"perturbation_id": "run-a", "source_candidate_id": "cand-a", "scale_id": "scale-a", "radius_m": 1.0, "spatialr_px": 1, "minsize_px": 1, "ranger": 0.1}]}), encoding="utf-8")

    monkeypatch.setattr(
        rs,
        "run_one_scale_segmentation_smoke",
        lambda config: {"status": "ok", "failure_reasons": [], "output_artifacts": {"merged_labels": str(labels)}},
    )
    report = run_candidate_response_surface_step(
        cfg(tmp_path, perturbation_candidates_json_path=candidate_path, feature_space_stack_path=feature, valid_mask_path=mask)
    )

    for path in report["required_outputs"].values():
        assert Path(path).exists()
    output_dir = rs.response_surface_output_dir(tmp_path / "out")
    assert not (output_dir / "candidate_response_surface_summary.json").exists()
    assert not (output_dir / "candidate_response_surface_summary.csv").exists()
    assert set(report["perturbation_statuses"][0]) == {
        "run_id",
        "candidate_scale_group_id",
        "status",
        "report_path",
        "retention_shadow_audit_path",
        "retention_shadow_audit_status",
        "retention_cleanup_result_path",
        "retention_cleanup_status",
    }
    assert report["perturbation_statuses"][0]["report_path"].endswith(
        "one_scale_segmentation_report.json"
    )
    for stem in ("candidate_group_response_summary", "ranked_candidate_scales"):
        summaries = json.loads((output_dir / f"{stem}.json").read_text(encoding="utf-8"))
        assert "stability_score_raw" in summaries[0]
        assert "scale_coordinate_name" in summaries[0]
        assert "scale_coordinate_value" in summaries[0]
        assert "scale_ladder_rank" in summaries[0]
        with (output_dir / f"{stem}.csv").open(newline="", encoding="utf-8") as file_obj:
            header = next(csv.DictReader(file_obj))
            assert "stability_score_raw" in header
            assert "scale_coordinate_name" in header
            assert "scale_coordinate_value" in header
            assert "scale_ladder_rank" in header
    assert report["top_pair_scale_continuity_status"] == "cannot_determine_missing_top_pair"
    assert report["top_pair_is_scale_adjacent"] is False
    assert report["top_pair_rank1_boundary_side"] == "cannot_determine"
    assert report["top_pair_rank1_upper_extrapolation_not_tested"] is False
    assert report["top_pair_boundary_constrained"] is False


def _one_run_candidates(path: Path) -> Path:
    path.write_text(json.dumps({"candidates": [{"perturbation_id": "run-a", "source_candidate_id": "cand-a", "scale_id": "scale-a", "radius_m": 1.0, "spatialr_px": 1, "minsize_px": 1, "ranger": 0.1}]}), encoding="utf-8")
    return path


def _gate_run_rows(pairs: list[tuple[str, float]], field_name: str = "source_candidate_radius_m") -> list[dict[str, object]]:
    return [{"candidate_scale_group_id": group_id, field_name: coordinate} for group_id, coordinate in pairs]


def _gate_rank_rows(entries: list[tuple[str, float, float]]) -> list[dict[str, object]]:
    return [
        {"candidate_scale_group_id": group_id, "stability_score_raw": raw, "stability_score": clamped}
        for group_id, raw, clamped in entries
    ]


def _step9b_adjacent_gate(**overrides) -> dict[str, object]:
    gate = {
        "top_pair_scale_continuity_status": "adjacent_top_pair_confirmed",
        "top_pair_is_scale_adjacent": True,
        "top_pair_rank1_candidate_scale_group_id": "r999px001",
        "top_pair_rank2_candidate_scale_group_id": "r001px999",
        "top_pair_lower_scale_candidate_group_id": "r999px001",
        "top_pair_upper_scale_candidate_group_id": "r001px999",
        "top_pair_scale_coordinate_name": "source_candidate_radius_m",
        "top_pair_lower_scale_coordinate_value": 1.0,
        "top_pair_upper_scale_coordinate_value": 2.0,
        "top_pair_intervening_candidate_scale_group_ids": [],
        "top_pair_rank1_at_scale_boundary": False,
        "top_pair_rank1_boundary_side": "none",
        "top_pair_rank1_upper_extrapolation_not_tested": False,
        "top_pair_boundary_constrained": False,
    }
    gate.update(overrides)
    return gate


def _step9b_ranked_support_rows() -> list[dict[str, object]]:
    return [
        {"candidate_scale_group_id": "r999px001", "stability_score_raw": 1.0, "stability_score": 1.0},
        {"candidate_scale_group_id": "r001px999", "stability_score_raw": 0.0, "stability_score": 0.0},
    ]


def _step9b_boundary_run_rows() -> list[dict[str, object]]:
    return [
        {
            "run_id": "lower-central-opaque",
            "candidate_scale_group_id": "r999px001",
            "source_candidate_id": "source-lower-900",
            "source_candidate_radius_m": 1.0,
            "spatialr_px": 4,
            "minsize_px": 10,
            "ranger": 0.2,
            "original_row_metadata": json.dumps({"is_baseline": True}),
        },
        {
            "run_id": "lower-variation-opaque",
            "candidate_scale_group_id": "r999px001",
            "source_candidate_id": "source-lower-900",
            "source_candidate_radius_m": 1.0,
            "spatialr_px": 99,
            "minsize_px": 99,
            "ranger": 9.9,
            "original_row_metadata": json.dumps({"is_baseline": False}),
        },
        {
            "run_id": "upper-central-opaque",
            "candidate_scale_group_id": "r001px999",
            "source_candidate_id": "source-upper-100",
            "source_candidate_radius_m": 3.0,
            "spatialr_px": 5,
            "minsize_px": 11,
            "ranger": 0.4,
            "original_row_metadata": {"is_baseline": True},
        },
        {
            "run_id": "upper-variation-opaque",
            "candidate_scale_group_id": "r001px999",
            "source_candidate_id": "source-upper-100",
            "source_candidate_radius_m": 3.0,
            "spatialr_px": 1,
            "minsize_px": 1,
            "ranger": 0.01,
            "original_row_metadata": {"is_baseline": False},
        },
    ]


def _step9b_perturbation_config(tmp_path: Path) -> rs.Level1BPerturbationConfig:
    return rs.Level1BPerturbationConfig(
        candidate_id="step9b",
        output_dir=tmp_path,
        scale_candidates_with_ranger_json_path=None,
        K=2,
    )


def test_20_proxy_stack_is_default_and_mask_is_forwarded(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "out"
    proxy = write_raster(output / "level1b" / "channels" / "proxy_stack.tif", np.ones((2, 2), dtype=np.uint8))
    mask = write_raster(output / "level1b" / "mask" / "valid_mask.tif", np.ones((2, 2), dtype=np.uint8))
    labels = write_raster(tmp_path / "labels.tif", np.array([[1, 1], [2, 2]], dtype=np.uint32))
    candidates = _one_run_candidates(tmp_path / "candidates.json")
    captured = []

    def fake(config):
        captured.append(config)
        return {"status": "ok", "failure_reasons": [], "output_artifacts": {"merged_labels": str(labels)}}

    monkeypatch.setattr(rs, "run_one_scale_segmentation_smoke", fake)
    report = run_candidate_response_surface_step(
        Level1BCandidateResponseSurfaceConfig(
            "candidate", output, candidates, debug_command_output=True
        )
    )

    assert captured[0].segmentation_stack_path == proxy
    assert captured[0].segmentation_stack_source == "proxy_stack"
    assert captured[0].valid_mask_path == mask
    assert captured[0].masked_segmentation_stack_path == (
        output
        / "level1b"
        / "candidate_response_surface"
        / "masked_segmentation_stack.tif"
    )
    assert captured[0].masked_segmentation_stack_scope == (
        "response_surface_canonical"
    )
    assert captured[0].run_contract_version == 6
    assert captured[0].debug_command_output is True
    assert report["segmentation_stack_path"] == str(proxy)
    assert report["segmentation_stack_source"] == "proxy_stack"
    assert report["canonical_masked_segmentation_stack_path"] == str(
        captured[0].masked_segmentation_stack_path
    )


def test_21_pca_is_used_only_when_explicitly_configured(tmp_path: Path) -> None:
    default_cfg = Level1BCandidateResponseSurfaceConfig("candidate", tmp_path / "out", tmp_path / "candidates.json")
    assert rs.resolve_segmentation_stack(default_cfg)[0].name == "proxy_stack.tif"

    pca = tmp_path / "pca_feature_stack.tif"
    explicit_cfg = Level1BCandidateResponseSurfaceConfig(
        "candidate", tmp_path / "out", tmp_path / "candidates.json", segmentation_stack_path=pca, segmentation_stack_source="pca_explicit"
    )
    assert rs.resolve_segmentation_stack(explicit_cfg) == (pca, "pca_explicit")


def test_22_invalid_support_is_zero_and_excluded_from_run_statistics(tmp_path: Path, monkeypatch) -> None:
    feature = write_raster(tmp_path / "features.tif", np.ones((2, 2), dtype=np.uint8))
    mask = write_raster(tmp_path / "mask.tif", np.array([[1, 1], [0, 0]], dtype=np.uint8))
    labels = write_raster(tmp_path / "labels.tif", np.array([[1, 1], [99, 99]], dtype=np.uint32))
    candidates = _one_run_candidates(tmp_path / "candidates.json")
    monkeypatch.setattr(rs, "run_one_scale_segmentation_smoke", lambda config: {"status": "ok", "failure_reasons": [], "output_artifacts": {"merged_labels": str(labels)}})

    run_candidate_response_surface_step(cfg(tmp_path, perturbation_candidates_json_path=candidates, feature_space_stack_path=feature, valid_mask_path=mask))
    paths = rs._run_artifact_paths(rs.response_surface_output_dir(tmp_path / "out"), "scale-a", "run-a")
    summary_json = json.loads(paths["summary_json"].read_text(encoding="utf-8"))
    segment_rows = list(__import__("csv").DictReader(paths["segments_csv"].open(encoding="utf-8")))

    assert summary_json["n_segments"] == 1
    assert summary_json["total_labelled_area_m2"] == 2.0
    assert {row["label"] for row in segment_rows} == {"1"}
    assert summary_json["invalid_support_excluded_from_q_statistics"] is True
    assert summary_json["pre_lsms_mask_applied"] is False
    assert summary_json["pre_segmentation_mask_applied"] is True
    assert summary_json["post_mask_applied"] is True
    assert summary_json["label_invalid_support_value"] == 0
    assert summary_json["segmentation_stack_path"] == str(feature)
    assert summary_json["segmentation_stack_source"] == "explicit_feature_space_stack_compat"
    assert summary_json["valid_mask_path"] == str(mask)
    assert summary_json["masked_segmentation_stack_path"] == str(
        tmp_path
        / "out"
        / "level1b"
        / "candidate_response_surface"
        / "masked_segmentation_stack.tif"
    )
    assert summary_json["masked_segmentation_stack_scope"] == (
        "response_surface_canonical"
    )
    assert summary_json["run_contract_version"] == 6
    assert summary_json["merged_labels_path"].endswith("merged_labels.tif")
    assert {"scale_id", "candidate_id", "perturbation_id", "radius_m", "spatialr_px", "minsize_px", "ranger", "n_segments", "q_p10", "q_p25", "q_median", "q_p75", "q_p90"}.issubset(summary_json)
    assert {f"{size}_frac_{weight}" for size in rs.SIZE_CLASSES for weight in ("n", "area")}.issubset(summary_json)
    assert {"area_m2", "req_m", "q", "q_class"}.issubset(segment_rows[0])


def test_23_per_run_statistics_survive_a_later_run_failure(tmp_path: Path, monkeypatch) -> None:
    feature = write_raster(tmp_path / "features.tif", np.ones((2, 2), dtype=np.uint8))
    mask = write_raster(tmp_path / "mask.tif", np.ones((2, 2), dtype=np.uint8))
    labels = write_raster(tmp_path / "labels.tif", np.array([[1, 1], [2, 2]], dtype=np.uint32))
    candidates = tmp_path / "candidates.json"
    candidates.write_text(json.dumps({"candidates": [
        {"perturbation_id": "run-a", "source_candidate_id": "cand-a", "scale_id": "scale-a", "radius_m": 1.0, "spatialr_px": 1, "minsize_px": 1, "ranger": 0.1},
        {"perturbation_id": "run-b", "source_candidate_id": "cand-a", "scale_id": "scale-a", "radius_m": 1.0, "spatialr_px": 1, "minsize_px": 1, "ranger": 0.2},
    ]}), encoding="utf-8")
    calls = []

    def fake(config):
        calls.append(config.perturbation_id)
        if config.perturbation_id == "run-b":
            raise RuntimeError("stop after first run")
        return {"status": "ok", "failure_reasons": [], "output_artifacts": {"merged_labels": str(labels)}}

    monkeypatch.setattr(rs, "run_one_scale_segmentation_smoke", fake)
    run_candidate_response_surface_step(cfg(tmp_path, perturbation_candidates_json_path=candidates, feature_space_stack_path=feature, valid_mask_path=mask))
    paths = rs._run_artifact_paths(rs.response_surface_output_dir(tmp_path / "out"), "scale-a", "run-a")

    assert calls == ["run-a", "run-b"]
    assert paths["segments_csv"].exists() and paths["summary_json"].exists() and paths["summary_csv"].exists()
    audit_path = paths["labels"].parent / rs.SHADOW_RETENTION_AUDIT_FILENAME
    assert audit_path.exists()
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["deletion_performed"] is False
    assert audit["deleted_paths"] == []


def test_retention_cleanup_runs_only_after_analysis_matrix_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feature = write_raster(
        tmp_path / "features.tif", np.ones((2, 2), dtype=np.uint8)
    )
    mask = write_raster(tmp_path / "mask.tif", np.ones((2, 2), dtype=np.uint8))
    labels = write_raster(
        tmp_path / "labels.tif", np.array([[1, 1], [2, 2]], dtype=np.uint32)
    )
    candidates = _one_run_candidates(tmp_path / "candidates.json")
    monkeypatch.setattr(
        rs,
        "run_one_scale_segmentation_smoke",
        lambda config: {
            "status": "ok",
            "failure_reasons": [],
            "output_artifacts": {"merged_labels": str(labels)},
        },
    )
    events: list[str] = []
    real_matrix = rs.aggregate_analysis_matrix_from_raster

    def matrix(*args, **kwargs):
        result = real_matrix(*args, **kwargs)
        events.append("analysis_matrix_complete")
        return result

    def shadow(*args, **kwargs):
        events.append("shadow_audit")
        return {"status": "shadow_retention_audit_ready"}

    def cleanup(*args, **kwargs):
        events.append("cleanup")
        return {"status": "retention_cleanup_complete"}

    monkeypatch.setattr(rs, "aggregate_analysis_matrix_from_raster", matrix)
    monkeypatch.setattr(rs, "_write_shadow_retention_audit", shadow)
    monkeypatch.setattr(rs, "_apply_shadow_retention_cleanup", cleanup)

    run_candidate_response_surface_step(
        cfg(
            tmp_path,
            perturbation_candidates_json_path=candidates,
            feature_space_stack_path=feature,
            valid_mask_path=mask,
        )
    )

    assert events == ["analysis_matrix_complete", "shadow_audit", "cleanup"]


def test_retention_cleanup_is_not_called_after_analysis_matrix_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feature = write_raster(
        tmp_path / "features.tif", np.ones((2, 2), dtype=np.uint8)
    )
    mask = write_raster(tmp_path / "mask.tif", np.ones((2, 2), dtype=np.uint8))
    labels = write_raster(
        tmp_path / "labels.tif", np.array([[1, 1], [2, 2]], dtype=np.uint32)
    )
    candidates = _one_run_candidates(tmp_path / "candidates.json")
    monkeypatch.setattr(
        rs,
        "run_one_scale_segmentation_smoke",
        lambda config: {
            "status": "ok",
            "failure_reasons": [],
            "output_artifacts": {"merged_labels": str(labels)},
        },
    )
    monkeypatch.setattr(
        rs,
        "aggregate_analysis_matrix_from_raster",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("synthetic matrix failure")
        ),
    )
    monkeypatch.setattr(
        rs,
        "_write_shadow_retention_audit",
        lambda *args, **kwargs: pytest.fail("shadow audit must not run"),
    )
    monkeypatch.setattr(
        rs,
        "_apply_shadow_retention_cleanup",
        lambda *args, **kwargs: pytest.fail("cleanup must not run"),
    )

    report = run_candidate_response_surface_step(
        cfg(
            tmp_path,
            perturbation_candidates_json_path=candidates,
            feature_space_stack_path=feature,
            valid_mask_path=mask,
        )
    )

    assert report["number_of_failed_runs"] == 1
    assert "synthetic matrix failure" in report["failed_runs"][0]["reason"]


def test_29_resume_recomputes_intermediate_only_state(tmp_path: Path, monkeypatch) -> None:
    feature = write_raster(tmp_path / "features.tif", np.ones((2, 2), dtype=np.uint8))
    mask = write_raster(tmp_path / "mask.tif", np.ones((2, 2), dtype=np.uint8))
    candidates = _one_run_candidates(tmp_path / "candidates.json")
    config = cfg(tmp_path, perturbation_candidates_json_path=candidates, feature_space_stack_path=feature, valid_mask_path=mask, overwrite=False)
    paths = rs._run_artifact_paths(rs.response_surface_output_dir(config.output_dir), "scale-a", "run-a")
    paths["labels"].parent.mkdir(parents=True, exist_ok=True)
    (paths["labels"].parent / "lsms_labels.tif").write_bytes(b"partial")
    computed_labels = write_raster(tmp_path / "computed_labels.tif", np.array([[1, 1], [2, 2]], dtype=np.uint32))
    calls = []

    def fake(segmentation_config):
        calls.append(segmentation_config)
        return {"status": "ok", "failure_reasons": [], "output_artifacts": {"merged_labels": str(computed_labels)}}

    monkeypatch.setattr(rs, "run_one_scale_segmentation_smoke", fake)
    report = run_candidate_response_surface_step(config)

    assert len(calls) == 1 and calls[0].overwrite is True
    assert report["perturbation_statuses"][0]["status"] == "recomputed_incomplete"


def test_resume_accepts_existing_full_report_without_reading_label_raster(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feature = write_raster(
        tmp_path / "features.tif", np.ones((2, 2), dtype=np.uint8)
    )
    mask = write_raster(tmp_path / "mask.tif", np.ones((2, 2), dtype=np.uint8))
    candidates = _one_run_candidates(tmp_path / "candidates.json")
    config = cfg(
        tmp_path,
        perturbation_candidates_json_path=candidates,
        feature_space_stack_path=feature,
        valid_mask_path=mask,
        overwrite=False,
    )
    out_dir = rs.response_surface_output_dir(config.output_dir)
    paths = rs._run_artifact_paths(out_dir, "scale-a", "run-a")
    paths["labels"].parent.mkdir(parents=True, exist_ok=True)
    paths["labels"].write_bytes(b"existing-label-product")
    row = json.loads(candidates.read_text(encoding="utf-8"))["candidates"][0]
    canonical_expected = rs._expected_run_metadata(
        config, paths, "scale-a", row, "run-a"
    )
    legacy_expected = {
        key: value
        for key, value in canonical_expected.items()
        if key
        not in {
            "masked_segmentation_stack_scope",
            "run_contract_version",
            "merged_labels_path",
        }
    }
    legacy_masked_stack = paths["labels"].parent / "masked_segmentation_stack.tif"
    legacy_masked_stack.write_bytes(b"legacy-masked-stack")
    legacy_expected["masked_segmentation_stack_path"] = str(
        legacy_masked_stack
    )
    old_full_report = {
        **legacy_expected,
        "status": "ok",
        "output_artifacts": {"merged_labels": str(paths["labels"])},
        "command_results": [
            {
                "command": ["otbcli_Test"],
                "returncode": 0,
                "stdout": "legacy successful stdout",
                "stderr": "legacy successful stderr",
            }
        ],
    }
    paths["report"].write_text(json.dumps(old_full_report), encoding="utf-8")
    summary_row = {
        **legacy_expected,
        "run_id": "run-a",
        "candidate_scale_group_id": "scale-a",
        "n_segments": 1,
    }
    rs._write_json(paths["summary_json"], summary_row)
    rs._write_csv(paths["summary_csv"], [summary_row])
    rs._write_csv(
        paths["segments_csv"],
        [
            {
                "scale_id": "scale-a",
                "candidate_id": "cand-a",
                "perturbation_id": "run-a",
                "area_m2": 1.0,
                "req_m": 1.0,
                "q": 1.0,
                "q_class": "in_scale",
            }
        ],
    )

    assert (
        rs._is_complete_legacy_run(
            paths, canonical_expected, "scale-a"
        )
        is True
    )
    monkeypatch.setattr(
        rs,
        "run_one_scale_segmentation_smoke",
        lambda config: pytest.fail("legacy complete run must be reused"),
    )
    reused = rs._run_or_reuse_segmentation(
        config, out_dir, "scale-a", row, "run-a"
    )
    assert reused["step9_run_status"] == "reused"


def test_shadow_retention_audit_proposes_only_resume_safe_transients(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = _one_run_candidates(tmp_path / "candidates.json")
    config = cfg(tmp_path, perturbation_candidates_json_path=candidates)
    out_dir = rs.response_surface_output_dir(config.output_dir)
    paths = rs._run_artifact_paths(out_dir, "scale-a", "run-a")
    paths["labels"].parent.mkdir(parents=True, exist_ok=True)
    paths["labels"].write_bytes(b"labels")
    row = json.loads(candidates.read_text(encoding="utf-8"))["candidates"][0]
    expected = rs._expected_run_metadata(
        config, paths, "scale-a", row, "run-a"
    )
    report = {
        **expected,
        "status": "ok",
        "output_artifacts": {"merged_labels": str(paths["labels"])},
    }
    paths["report"].write_text(json.dumps(report), encoding="utf-8")
    summary_row = {
        **expected,
        "run_id": "run-a",
        "candidate_scale_group_id": "scale-a",
        "n_segments": 1,
    }
    rs._write_json(paths["summary_json"], summary_row)
    rs._write_csv(paths["summary_csv"], [summary_row])
    rs._write_csv(
        paths["segments_csv"],
        [
            {
                "scale_id": "scale-a",
                "candidate_id": "cand-a",
                "perturbation_id": "run-a",
                "area_m2": 1.0,
                "req_m": 1.0,
                "q": 1.0,
                "q_class": "in_scale",
            }
        ],
    )
    for artifact_key in rs.SHADOW_TRANSIENT_ARTIFACT_KEYS:
        (paths["labels"].parent / rs.OUTPUT_ARTIFACT_FILENAMES[artifact_key]).write_bytes(
            artifact_key.encode("utf-8")
        )
    canonical_masked_stack = Path(expected["masked_segmentation_stack_path"])
    canonical_masked_stack.parent.mkdir(parents=True, exist_ok=True)
    canonical_masked_stack.write_bytes(b"masked_segmentation_stack")

    audit = rs._write_shadow_retention_audit(
        out_dir, config, "scale-a", row, "run-a"
    )

    assert audit["status"] == "shadow_retention_audit_ready"
    assert audit["mode"] == "shadow_only_no_deletion"
    assert audit["deletion_performed"] is False
    assert audit["deleted_paths"] == []
    assert audit["checks"] == {
        "final_label_exists_and_non_empty": True,
        "run_summary_exists_and_non_empty": True,
        "run_report_exists_and_non_empty": True,
        "run_report_status_successful": True,
        "resume_complete_without_proposed_transients": True,
        "proposed_transients_unreferenced_by_step9b_or_step10": True,
    }
    assert [item["artifact_key"] for item in audit["would_delete"]] == list(
        rs.SHADOW_TRANSIENT_ARTIFACT_KEYS
    )
    assert all(item["would_delete"] for item in audit["artifact_inventory"])
    assert not any(
        item["resume_contract_required"]
        or item["referenced_by_step9b_or_step10"]
        for item in audit["artifact_inventory"]
    )
    retained = {
        item["artifact_key"]: item for item in audit["retained_artifacts"]
    }
    assert retained["masked_segmentation_stack"]["reason"] == (
        "required_by_step10_exactextractr_segment_stats"
    )
    assert "masked_segmentation_stack" not in {
        item["artifact_key"] for item in audit["would_delete"]
    }
    assert (
        paths["labels"].parent / rs.SHADOW_RETENTION_AUDIT_FILENAME
    ).exists()

    report_before_cleanup = paths["report"].read_bytes()
    cleanup = rs._apply_shadow_retention_cleanup(
        out_dir, config, "scale-a", row, "run-a", "computed"
    )
    assert cleanup["status"] == "retention_cleanup_complete"
    assert cleanup["execution_report_preserved_unchanged"] is True
    assert cleanup["scientific_run_status_unchanged"] is True
    assert cleanup["bytes_reclaimed"] == sum(
        len(artifact_key.encode("utf-8"))
        for artifact_key in rs.SHADOW_TRANSIENT_ARTIFACT_KEYS
    )
    assert paths["report"].read_bytes() == report_before_cleanup
    assert all(not Path(item["path"]).exists() for item in audit["would_delete"])
    assert retained["masked_segmentation_stack"]["path"] not in cleanup[
        "deleted_paths"
    ]
    assert rs._is_complete_run(paths, expected, "scale-a") is True
    cleanup_result_path = (
        paths["labels"].parent / rs.RETENTION_CLEANUP_RESULT_FILENAME
    )
    cleanup_result_before_resume = cleanup_result_path.read_bytes()

    repeated = rs._apply_shadow_retention_cleanup(
        out_dir, config, "scale-a", row, "run-a", "computed"
    )
    assert repeated["status"] == "retention_cleanup_complete"
    assert repeated["bytes_reclaimed"] == cleanup["bytes_reclaimed"]
    assert {
        item["status"] for item in repeated["artifact_results"]
    } == {"deleted"}
    assert cleanup_result_path.read_bytes() == cleanup_result_before_resume

    for artifact_key in rs.SHADOW_TRANSIENT_ARTIFACT_KEYS:
        (paths["labels"].parent / rs.OUTPUT_ARTIFACT_FILENAMES[artifact_key]).write_bytes(
            b"reused"
        )
    reused = rs._apply_shadow_retention_cleanup(
        out_dir, config, "scale-a", row, "run-a", "reused"
    )
    assert reused["status"] == (
        "retention_cleanup_skipped_reused_or_unclassified_run"
    )
    assert reused["cleanup_result_file_preserved"] is True
    assert reused["prior_cleanup_status"] == "retention_cleanup_complete"
    assert cleanup_result_path.read_bytes() == cleanup_result_before_resume
    assert all(
        (paths["labels"].parent / rs.OUTPUT_ARTIFACT_FILENAMES[key]).exists()
        for key in rs.SHADOW_TRANSIENT_ARTIFACT_KEYS
    )

    failed_path = (
        paths["labels"].parent
        / rs.OUTPUT_ARTIFACT_FILENAMES["meanshift_position"]
    )
    real_unlink = Path.unlink

    def fail_one_unlink(path: Path, *args, **kwargs):
        if path == failed_path:
            raise PermissionError("synthetic cleanup denial")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_one_unlink)
    partial = rs._apply_shadow_retention_cleanup(
        out_dir, config, "scale-a", row, "run-a", "computed"
    )
    assert partial["status"] == "retention_cleanup_partial"
    assert failed_path.exists()
    assert any(
        item["status"] == "delete_failed"
        and item["artifact_key"] == "meanshift_position"
        for item in partial["artifact_results"]
    )
    assert rs._is_complete_run(paths, expected, "scale-a") is True


def test_shadow_retention_audit_never_proposes_deletion_for_incomplete_run(
    tmp_path: Path,
) -> None:
    candidates = _one_run_candidates(tmp_path / "candidates.json")
    config = cfg(tmp_path, perturbation_candidates_json_path=candidates)
    out_dir = rs.response_surface_output_dir(config.output_dir)
    paths = rs._run_artifact_paths(out_dir, "scale-a", "run-a")
    paths["labels"].parent.mkdir(parents=True, exist_ok=True)
    transient = (
        paths["labels"].parent
        / rs.OUTPUT_ARTIFACT_FILENAMES["meanshift_smoothed"]
    )
    transient.write_bytes(b"interrupted")
    row = json.loads(candidates.read_text(encoding="utf-8"))["candidates"][0]

    audit = rs._write_shadow_retention_audit(
        out_dir, config, "scale-a", row, "run-a"
    )

    assert audit["status"] == "shadow_retention_audit_not_ready"
    assert audit["would_delete"] == []
    assert audit["deletion_performed"] is False
    cleanup = rs._apply_shadow_retention_cleanup(
        out_dir, config, "scale-a", row, "run-a", "computed"
    )
    assert cleanup["status"] == "retention_cleanup_skipped_shadow_not_ready"
    assert transient.read_bytes() == b"interrupted"


def test_shadow_transients_are_not_read_by_step9b_or_step10() -> None:
    from metashape_qc_engine.level1b import materialization as level1b_materialization

    consumer_source = "\n".join(
        [
            inspect.getsource(rs.validate_step9b_local_transition_refinement),
            inspect.getsource(rs.run_step9b_local_transition_refinement_preflight),
            inspect.getsource(rs.run_step9b_midpoint_support_probe),
            inspect.getsource(rs.run_step9b_prepare_from_existing_step9a),
            inspect.getsource(
                rs.run_step9b_midpoint_response_surface_and_handoff_from_prepare
            ),
            inspect.getsource(level1b_materialization),
        ]
    )

    assert all(
        rs.OUTPUT_ARTIFACT_FILENAMES[artifact_key] not in consumer_source
        for artifact_key in rs.SHADOW_TRANSIENT_ARTIFACT_KEYS
    )
    assert "masked_segmentation_stack_path" in consumer_source


def test_32_current_support_score_is_bounded_and_legacy_flags_do_not_rank() -> None:
    group = compute_candidate_group_response_summary(
        "scale-a",
        [
            summary(
                "run-a",
                [0.9, 0.1, 0.0, 0.0, 0.0],
                area_weighted_q_q10=0.0,
                area_weighted_q_q90=100.0,
                scale_match_support=0.4,
            )
        ],
        [],
        cfg(),
    )

    assert group["stability_score_raw"] == pytest.approx(0.4)
    assert group["stability_score"] == pytest.approx(0.4)
    assert group["legacy_response_stability_score_raw"] < 0.0
    assert rs.stability_score(
        {
            "stability_score_raw": 1.5,
        }
    ) == 1.0

    current_support = {
        "scale_match_support_raw": 0.7,
        "edge_loaded_flag": True,
        "scale_jump_flag": True,
        "distribution_flutter_flag": True,
        "spatial_scale_jump_flag": True,
    }
    assert rs.stability_score_raw(current_support) == pytest.approx(0.7)


def test_33_zero_score_candidates_rank_by_raw_score_before_id(tmp_path: Path, monkeypatch) -> None:
    feature = write_raster(tmp_path / "features.tif", np.ones((2, 2), dtype=np.uint8))
    mask = write_raster(tmp_path / "mask.tif", np.ones((2, 2), dtype=np.uint8))
    labels = write_raster(tmp_path / "labels.tif", np.array([[1, 1], [2, 2]], dtype=np.uint32))
    candidates = tmp_path / "candidates.json"
    candidates.write_text(json.dumps({"candidates": [
        {"perturbation_id": "run-alpha", "source_candidate_id": "candidate-alpha", "scale_id": "alpha", "radius_m": 1.0, "spatialr_px": 1, "minsize_px": 1, "ranger": 0.1},
        {"perturbation_id": "run-zulu", "source_candidate_id": "candidate-zulu", "scale_id": "zulu", "radius_m": 1.0, "spatialr_px": 1, "minsize_px": 1, "ranger": 0.1},
    ]}), encoding="utf-8")
    raw_scores = iter([-2.0, -1.0])

    monkeypatch.setattr(rs, "run_one_scale_segmentation_smoke", lambda config: {"status": "ok", "failure_reasons": [], "output_artifacts": {"merged_labels": str(labels)}})
    monkeypatch.setattr(rs, "finalize_boundary_ensemble_scores", lambda *_args: None)
    monkeypatch.setattr(
        rs,
        "compute_candidate_group_response_summary",
        lambda group_id, run_summaries, matrix_summaries, config: {
            "candidate_scale_group_id": group_id,
            "stability_score_raw": next(raw_scores),
            "stability_score": 0.0,
            "candidate_outcome": "scale_jump_detected",
            "medoid_run_id": "",
        },
    )

    run_candidate_response_surface_step(
        cfg(tmp_path, perturbation_candidates_json_path=candidates, feature_space_stack_path=feature, valid_mask_path=mask)
    )
    ranked = json.loads(
        (rs.response_surface_output_dir(tmp_path / "out") / "ranked_candidate_scales.json").read_text(encoding="utf-8")
    )

    assert [item["candidate_scale_group_id"] for item in ranked] == ["zulu", "alpha"]


def test_34_true_ranking_uses_clamped_score_before_candidate_id(tmp_path: Path, monkeypatch) -> None:
    feature = write_raster(tmp_path / "features.tif", np.ones((2, 2), dtype=np.uint8))
    mask = write_raster(tmp_path / "mask.tif", np.ones((2, 2), dtype=np.uint8))
    labels = write_raster(tmp_path / "labels.tif", np.array([[1, 1], [2, 2]], dtype=np.uint32))
    candidates = tmp_path / "candidates.json"
    candidates.write_text(json.dumps({"candidates": [
        {"perturbation_id": "run-alpha", "source_candidate_id": "candidate-alpha", "scale_id": "alpha", "radius_m": 1.0, "spatialr_px": 1, "minsize_px": 1, "ranger": 0.1},
        {"perturbation_id": "run-zulu", "source_candidate_id": "candidate-zulu", "scale_id": "zulu", "radius_m": 1.0, "spatialr_px": 1, "minsize_px": 1, "ranger": 0.1},
    ]}), encoding="utf-8")
    clamped_scores = iter([0.1, 0.9])

    monkeypatch.setattr(rs, "run_one_scale_segmentation_smoke", lambda config: {"status": "ok", "failure_reasons": [], "output_artifacts": {"merged_labels": str(labels)}})
    monkeypatch.setattr(rs, "finalize_boundary_ensemble_scores", lambda *_args: None)
    monkeypatch.setattr(
        rs,
        "compute_candidate_group_response_summary",
        lambda group_id, run_summaries, matrix_summaries, config: {
            "candidate_scale_group_id": group_id,
            "stability_score_raw": 0.0,
            "stability_score": next(clamped_scores),
            "candidate_outcome": "scale_jump_detected",
            "medoid_run_id": "",
        },
    )

    run_candidate_response_surface_step(
        cfg(tmp_path, perturbation_candidates_json_path=candidates, feature_space_stack_path=feature, valid_mask_path=mask)
    )
    ranked = json.loads(
        (rs.response_surface_output_dir(tmp_path / "out") / "ranked_candidate_scales.json").read_text(encoding="utf-8")
    )

    assert [item["candidate_scale_group_id"] for item in ranked] == ["zulu", "alpha"]


def test_35_scale_continuity_confirms_adjacent_top_pair_and_opaque_ids_are_inert() -> None:
    run_rows = _gate_run_rows(
        [
            ("candidate-100", 1.0),
            ("candidate-020", 2.0),
            ("candidate-300", 3.0),
            ("candidate-040", 4.0),
        ]
    )
    ranked_rows = _gate_rank_rows(
        [
            ("candidate-300", 0.9, 0.9),
            ("candidate-020", 0.8, 0.8),
            ("candidate-100", 0.7, 0.7),
            ("candidate-040", 0.6, 0.6),
        ]
    )

    gate = rs.compute_top_pair_scale_continuity_and_boundary_gate(run_rows, ranked_rows)

    assert gate["top_pair_scale_continuity_status"] == "adjacent_top_pair_confirmed"
    assert gate["top_pair_is_scale_adjacent"] is True
    assert gate["top_pair_rank1_candidate_scale_group_id"] == "candidate-300"
    assert gate["top_pair_rank2_candidate_scale_group_id"] == "candidate-020"
    assert gate["top_pair_lower_scale_candidate_group_id"] == "candidate-020"
    assert gate["top_pair_upper_scale_candidate_group_id"] == "candidate-300"
    assert gate["top_pair_intervening_candidate_scale_group_ids"] == []
    assert gate["top_pair_rank1_at_scale_boundary"] is False
    assert gate["top_pair_rank1_boundary_side"] == "none"
    assert gate["top_pair_rank1_upper_extrapolation_not_tested"] is False
    assert gate["top_pair_boundary_constrained"] is False
    assert gate["selected_scale_coordinate_name"] == "source_candidate_radius_m"
    assert [item["candidate_scale_group_id"] for item in gate["scale_ladder"]] == [
        "candidate-100",
        "candidate-020",
        "candidate-300",
        "candidate-040",
    ]


def test_36_scale_continuity_reports_non_adjacent_top_pair_and_intervening_ids() -> None:
    run_rows = _gate_run_rows([("alpha", 1.0), ("beta", 2.0), ("gamma", 3.0), ("delta", 4.0)])
    ranked_rows = _gate_rank_rows(
        [
            ("gamma", 0.9, 0.9),
            ("alpha", 0.8, 0.8),
            ("beta", 0.7, 0.7),
            ("delta", 0.6, 0.6),
        ]
    )

    gate = rs.compute_top_pair_scale_continuity_and_boundary_gate(run_rows, ranked_rows)

    assert gate["top_pair_scale_continuity_status"] == "non_adjacent_top_pair_possible_bimodal_or_multimodal"
    assert gate["top_pair_is_scale_adjacent"] is False
    assert gate["top_pair_rank1_candidate_scale_group_id"] == "gamma"
    assert gate["top_pair_rank2_candidate_scale_group_id"] == "alpha"
    assert gate["top_pair_lower_scale_candidate_group_id"] == "alpha"
    assert gate["top_pair_upper_scale_candidate_group_id"] == "gamma"
    assert gate["top_pair_intervening_candidate_scale_group_ids"] == ["beta"]


def test_37_scale_continuity_reports_missing_explicit_coordinate() -> None:
    run_rows = [{"candidate_scale_group_id": "alpha"}, {"candidate_scale_group_id": "beta"}]
    ranked_rows = _gate_rank_rows([("beta", 0.9, 0.9), ("alpha", 0.8, 0.8)])

    gate = rs.compute_top_pair_scale_continuity_and_boundary_gate(run_rows, ranked_rows)

    assert gate["top_pair_scale_continuity_status"] == "cannot_determine_no_explicit_scale_coordinate"
    assert gate["top_pair_is_scale_adjacent"] is False
    assert gate["top_pair_rank1_boundary_side"] == "cannot_determine"
    assert gate["top_pair_rank1_at_scale_boundary"] is False
    assert gate["top_pair_boundary_constrained"] is False
    assert gate["selected_scale_coordinate_name"] is None


def test_38_duplicate_explicit_scale_coordinates_do_not_form_a_valid_scale_ladder() -> None:
    run_rows = _gate_run_rows([("alpha", 1.0), ("omega", 1.0), ("beta", 2.0)])
    ranked_rows = _gate_rank_rows([("beta", 0.9, 0.9), ("omega", 0.8, 0.8), ("alpha", 0.7, 0.7)])

    gate = rs.compute_top_pair_scale_continuity_and_boundary_gate(run_rows, ranked_rows)

    assert gate["top_pair_scale_continuity_status"] == "cannot_determine_no_explicit_scale_coordinate"
    assert gate["top_pair_is_scale_adjacent"] is False
    assert gate["selected_scale_coordinate_name"] is None
    assert gate["scale_ladder"] == []


def test_39_rank1_upper_boundary_is_reported_without_extending_the_ladder() -> None:
    run_rows = _gate_run_rows([("alpha", 1.0), ("beta", 2.0), ("gamma", 3.0)])
    ranked_rows = _gate_rank_rows([("gamma", 0.9, 0.9), ("beta", 0.8, 0.8), ("alpha", 0.7, 0.7)])

    gate = rs.compute_top_pair_scale_continuity_and_boundary_gate(run_rows, ranked_rows)

    assert gate["top_pair_scale_continuity_status"] == "adjacent_top_pair_confirmed"
    assert gate["top_pair_is_scale_adjacent"] is True
    assert gate["top_pair_rank1_at_scale_boundary"] is True
    assert gate["top_pair_rank1_boundary_side"] == "upper"
    assert gate["top_pair_rank1_upper_extrapolation_not_tested"] is True
    assert gate["top_pair_boundary_constrained"] is True
    assert gate["top_pair_lower_scale_candidate_group_id"] == "beta"
    assert gate["top_pair_upper_scale_candidate_group_id"] == "gamma"


def test_boundary_ensemble_support_separates_seed_and_ranger_agreement(
    tmp_path: Path,
) -> None:
    mask = write_raster(
        tmp_path / "mask.tif",
        np.ones((6, 8), dtype=np.uint8),
    )
    split_three = np.ones((6, 8), dtype=np.uint32)
    split_three[:, 3:] = 2
    same_partition_new_labels = np.full((6, 8), 10, dtype=np.uint32)
    same_partition_new_labels[:, 3:] = 20
    split_six = np.ones((6, 8), dtype=np.uint32)
    split_six[:, 6:] = 2
    label_paths = [
        write_raster(tmp_path / "phase_00_mode.tif", split_three),
        write_raster(tmp_path / "phase_01_mode.tif", same_partition_new_labels),
        write_raster(tmp_path / "phase_00_upper.tif", split_six),
    ]
    runs = [
        {
            "run_id": "a-phase00-mode",
            "merged_labels_path": str(label_paths[0]),
            "seed_realization_id": "phase_00",
            "run_ranger": 0.2,
            "run_spatial_radius_m": 1.0,
            "spatialr_px": 2,
            "original_row_metadata": {"ranger_position": "mode"},
        },
        {
            "run_id": "b-phase01-mode",
            "merged_labels_path": str(label_paths[1]),
            "seed_realization_id": "phase_01",
            "run_ranger": 0.2,
            "run_spatial_radius_m": 1.0,
            "spatialr_px": 2,
            "original_row_metadata": {"ranger_position": "mode"},
        },
        {
            "run_id": "c-phase00-upper",
            "merged_labels_path": str(label_paths[2]),
            "seed_realization_id": "phase_00",
            "run_ranger": 0.3,
            "run_spatial_radius_m": 1.0,
            "spatialr_px": 2,
            "original_row_metadata": {"ranger_position": "main_interval_upper"},
        },
    ]

    summary = rs.compute_boundary_ensemble_support(
        tmp_path / "response_surface",
        "scale_001",
        runs,
        mask,
        block_rows=2,
    )

    assert Path(summary["boundary_support_raster"]).is_file()
    assert summary["seed_realization_count"] == 2
    assert summary["ranger_position_count"] == 2
    assert summary["seed_realization_boundary_agreement"] == pytest.approx(1.0)
    assert summary["ranger_boundary_agreement"] < 1.0
    assert summary["boundary_medoid_run_id"] in {
        "a-phase00-mode",
        "b-phase01-mode",
    }
    assert {row["pair_class"] for row in summary["pairwise_boundary_agreements"]} == {
        "seed_realization",
        "ranger",
        "factorial_cross",
    }


def test_final_support_is_geometric_mean_of_four_empirical_components(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summaries = []
    runs = []
    for index, group_id in enumerate(("scale-a", "scale-b"), start=1):
        run_id = f"run-{index}"
        summaries.append(
            {
                "candidate_scale_group_id": group_id,
                "run_count": 1,
                "seed_realization_count": 4,
                "ranger_position_count": 3,
                "boundary_support_raster": str(tmp_path / f"{group_id}.tif"),
                "boundary_agreement_metric": "scale_relative_linear_distance_support",
                "pairwise_boundary_agreements": [],
                "ensemble_boundary_agreement": 0.85,
                "boundary_medoid_mean_agreement": 0.85,
                "boundary_medoid_run_id": run_id,
                "medoid_run_id": run_id,
                "boundary_support_summary_json": str(
                    tmp_path / f"{group_id}.json"
                ),
                "seed_realization_boundary_agreement": 0.9,
                "ranger_boundary_agreement": 0.8,
                "local_radius_boundary_agreement": 1.0,
                "seed_realization_boundary_support_robust": 0.9,
                "ranger_boundary_support_robust": 0.8,
                "local_radius_boundary_support_count": 0,
                "local_radius_boundary_support_median": None,
                "local_radius_boundary_support_mad": None,
                "local_radius_boundary_support_robust": None,
                "scale_match_support_raw": 0.7,
            }
        )
        runs.append(
            {
                "run_id": run_id,
                "candidate_scale_group_id": group_id,
                "source_candidate_radius_m": float(index),
                "spatialr_px": index * 2,
                "merged_labels_path": str(tmp_path / f"{run_id}.tif"),
            }
        )

    monkeypatch.setattr(
        rs,
        "_boundary_agreement_between_labels",
        lambda *_args, **_kwargs: 0.8,
    )
    rs.finalize_boundary_ensemble_scores(
        summaries,
        runs,
        tmp_path / "mask.tif",
    )

    expected = (0.9 * 0.8 * 0.8 * 0.7) ** 0.25
    for candidate in summaries:
        assert candidate["ensemble_support_evaluable"] is True
        assert candidate["ensemble_support_raw_v2"] == pytest.approx(expected)
        assert candidate["stability_score_raw"] == pytest.approx(expected)
        assert candidate["candidate_outcome"] == "ensemble_support_evaluable"


def test_40_step9b_non_adjacent_top_pair_requires_user_choice() -> None:
    gate = _step9b_adjacent_gate(
        top_pair_scale_continuity_status="non_adjacent_top_pair_possible_bimodal_or_multimodal",
        top_pair_is_scale_adjacent=False,
        top_pair_intervening_candidate_scale_group_ids=["middle"],
    )

    result = rs.validate_step9b_local_transition_refinement(gate, [1.0, 1.5, 2.0], "/step9a")

    assert result["step9b_status"] == "step9b_user_choice_required_bimodal_or_multimodal"
    assert result["user_choice_required"] is True
    assert result["supported_alternative_count"] == 2
    assert result["supported_alternative_candidate_scale_group_ids"] == ["r999px001", "r001px999"]
    assert result["local_coordinate_plan"] == []
    assert result["local_candidate_count"] == 0


def test_41_step9b_blocks_cannot_determine_scale_continuity() -> None:
    for status in (
        "cannot_determine_no_explicit_scale_coordinate",
        "cannot_determine_scale_order_disagreement",
        "cannot_determine_missing_top_pair",
    ):
        gate = _step9b_adjacent_gate(top_pair_scale_continuity_status=status, top_pair_is_scale_adjacent=False)

        result = rs.validate_step9b_local_transition_refinement(gate, [1.0, 1.5, 2.0], "/step9a")

        assert result["step9b_status"] == "step9b_blocked_cannot_determine_scale_continuity"
        assert result["local_coordinate_plan"] == []


def test_42_step9b_blocks_missing_top_pair_metadata() -> None:
    for field in (
        "top_pair_rank1_candidate_scale_group_id",
        "top_pair_rank2_candidate_scale_group_id",
        "top_pair_lower_scale_candidate_group_id",
        "top_pair_upper_scale_candidate_group_id",
        "top_pair_scale_coordinate_name",
    ):
        gate = _step9b_adjacent_gate()
        del gate[field]

        result = rs.validate_step9b_local_transition_refinement(gate, [1.0, 1.5, 2.0], "/step9a")

        assert result["step9b_status"] == "step9b_blocked_missing_top_pair_metadata"
        assert result["local_coordinate_plan"] == []


def test_43_step9b_blocks_invalid_interval_bounds() -> None:
    for lower, upper in ((2.0, 1.0), (1.0, 1.0), ("invalid", 2.0)):
        gate = _step9b_adjacent_gate(
            top_pair_lower_scale_coordinate_value=lower,
            top_pair_upper_scale_coordinate_value=upper,
        )

        result = rs.validate_step9b_local_transition_refinement(gate, [1.0, 1.5, 2.0], "/step9a")

        assert result["step9b_status"] == "step9b_blocked_invalid_interval_bounds"
        assert result["local_coordinate_plan"] == []


def test_44_step9b_blocks_missing_explicit_local_scale_coordinates() -> None:
    for local_values in (None, []):
        result = rs.validate_step9b_local_transition_refinement(_step9b_adjacent_gate(), local_values, "/step9a")

        assert result["step9b_status"] == "step9b_blocked_missing_explicit_local_scale_coordinates"
        assert result["local_coordinate_plan"] == []


def test_45_step9b_blocks_coordinates_outside_confirmed_interval() -> None:
    below = rs.validate_step9b_local_transition_refinement(_step9b_adjacent_gate(), [0.9, 1.0, 2.0], "/step9a")
    above = rs.validate_step9b_local_transition_refinement(_step9b_adjacent_gate(), [1.0, 2.0, 2.1], "/step9a")

    assert below["step9b_status"] == "step9b_blocked_local_coordinate_outside_interval"
    assert above["step9b_status"] == "step9b_blocked_local_coordinate_outside_interval"
    assert below["step9b_no_extrapolation_beyond_interval"] is False
    assert above["step9b_no_extrapolation_beyond_interval"] is False


def test_46_step9b_blocks_duplicate_local_coordinates() -> None:
    result = rs.validate_step9b_local_transition_refinement(
        _step9b_adjacent_gate(),
        [1.0, 1.5, 1.5, 2.0],
        "/step9a",
    )

    assert result["step9b_status"] == "step9b_blocked_local_coordinate_duplicate"
    assert result["local_coordinate_plan"] == []


def test_47_step9b_blocks_non_strict_local_coordinate_ordering() -> None:
    result = rs.validate_step9b_local_transition_refinement(
        _step9b_adjacent_gate(),
        [1.0, 1.75, 1.5, 2.0],
        "/step9a",
    )

    assert result["step9b_status"] == "step9b_blocked_local_coordinate_not_strictly_ordered"
    assert result["local_coordinate_plan"] == []


def test_48_step9b_accepts_ordered_explicit_coordinates_and_keeps_ids_opaque() -> None:
    gate = _step9b_adjacent_gate(
        top_pair_rank1_candidate_scale_group_id="scale-00000099",
        top_pair_rank2_candidate_scale_group_id="scale-99999900",
        top_pair_lower_scale_candidate_group_id="scale-00000099",
        top_pair_upper_scale_candidate_group_id="scale-99999900",
    )

    result = rs.validate_step9b_local_transition_refinement(gate, [1.0, 1.25, 1.75, 2.0], "/step9a")

    assert result["step9b_status"] == "step9b_ready_adjacent_interval"
    assert result["local_scale_coordinate_values"] == [1.0, 1.25, 1.75, 2.0]
    assert result["local_scale_coordinate_count"] == 4
    assert result["step9b_no_extrapolation_beyond_interval"] is True
    assert [row["step9b_local_candidate_id"] for row in result["local_coordinate_plan"]] == [
        "local_000",
        "local_001",
        "local_002",
        "local_003",
    ]
    assert [row["scale_coordinate_value"] for row in result["local_coordinate_plan"]] == [1.0, 1.25, 1.75, 2.0]
    assert result["local_coordinate_plan"][0]["source_step9a_lower_candidate_scale_group_id"] == "scale-00000099"
    assert result["local_coordinate_plan"][-1]["source_step9a_upper_candidate_scale_group_id"] == "scale-99999900"


def test_49_step9b_propagates_upper_boundary_and_blocks_unavailable_parameter_construction(tmp_path: Path) -> None:
    gate = _step9b_adjacent_gate(
        top_pair_rank1_at_scale_boundary=True,
        top_pair_rank1_boundary_side="upper",
        top_pair_rank1_upper_extrapolation_not_tested=True,
        top_pair_boundary_constrained=True,
    )

    result = rs.run_step9b_local_transition_refinement_preflight(
        tmp_path / "out",
        "/step9a/candidate_response_surface",
        gate,
        [1.0, 1.5, 2.0],
    )

    step9b_dir = rs.local_transition_refinement_output_dir(tmp_path / "out")
    assert result["step9b_status"] == "step9b_blocked_parameter_construction_unavailable"
    assert result["top_pair_rank1_boundary_side"] == "upper"
    assert result["top_pair_rank1_upper_extrapolation_not_tested"] is True
    assert result["top_pair_boundary_constrained"] is True
    assert result["step9b_no_extrapolation_beyond_interval"] is True
    assert max(row["scale_coordinate_value"] for row in result["local_coordinate_plan"]) == 2.0
    assert result["local_candidate_count"] == 0
    assert all(
        not {"radius_m", "spatialr_px", "minsize_px", "ranger"}.intersection(row)
        for row in result["local_coordinate_plan"]
    )
    assert (step9b_dir / "step9b_interval_preflight.json").exists()
    assert not (step9b_dir / "step9b_local_candidate_table.csv").exists()
    assert not (step9b_dir / "step9b_local_response_surface.csv").exists()
    assert not (step9b_dir / "step9b_local_response_surface.json").exists()


def test_50_step9b_requires_both_confirmed_interval_endpoints() -> None:
    result = rs.validate_step9b_local_transition_refinement(
        _step9b_adjacent_gate(),
        [1.25, 1.5, 2.0],
        "/step9a",
    )

    assert result["step9b_status"] == "step9b_blocked_missing_explicit_local_scale_coordinates"
    assert result["local_coordinate_plan"] == []


def test_51_step9b_non_adjacent_forwards_two_supported_alternatives_without_midpoint(tmp_path: Path) -> None:
    gate = _step9b_adjacent_gate(
        top_pair_scale_continuity_status="non_adjacent_top_pair_possible_bimodal_or_multimodal",
        top_pair_is_scale_adjacent=False,
        top_pair_intervening_candidate_scale_group_ids=["unselected-middle"],
    )

    result = rs.run_step9b_midpoint_support_probe(
        tmp_path / "out",
        "/step9a",
        gate,
        _step9b_ranked_support_rows(),
        _step9b_boundary_run_rows(),
        None,
    )

    step9b_dir = rs.local_transition_refinement_output_dir(tmp_path / "out")
    assert result["step9b_status"] == "step9b_user_choice_required_bimodal_or_multimodal"
    assert result["user_choice_required"] is True
    assert result["supported_alternative_count"] == 2
    assert [row["candidate_scale_group_id"] for row in result["supported_alternatives"]] == [
        "r999px001",
        "r001px999",
    ]
    assert result["midpoint_candidate_count"] == 0
    assert (step9b_dir / "step9b_supported_scale_alternatives.csv").exists()
    assert (step9b_dir / "step9b_supported_scale_alternatives.json").exists()
    assert not (step9b_dir / "step9b_midpoint_probe_candidate.csv").exists()
    assert not (step9b_dir / "step9b_midpoint_perturbation_candidates.csv").exists()


def test_52_step9b_adjacent_midpoint_uses_central_rows_and_existing_perturbation_helper(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: list[dict[str, object]] = []

    def fake_builder(config, complete_candidates):
        assert isinstance(config, rs.Level1BPerturbationConfig)
        captured.extend(complete_candidates)
        midpoint = complete_candidates[0]
        return [
            {
                "perturbation_id": "local_midpoint__baseline",
                "source_candidate_id": midpoint["candidate_id"],
                "scale_id": midpoint["scale_id"],
                "spatialr_px": midpoint["spatialr_px"],
                "minsize_px": midpoint["minsize_px"],
                "ranger": midpoint["ranger"],
                "deltas": {},
                "is_baseline": True,
            },
            {
                "perturbation_id": "local_midpoint__variation",
                "source_candidate_id": midpoint["candidate_id"],
                "scale_id": midpoint["scale_id"],
                "spatialr_px": midpoint["spatialr_px"] + 1,
                "minsize_px": midpoint["minsize_px"],
                "ranger": midpoint["ranger"],
                "deltas": {"spatialr_px_delta": 1},
                "is_baseline": False,
            },
        ]

    monkeypatch.setattr(rs, "build_perturbation_candidates", fake_builder)
    result = rs.run_step9b_midpoint_support_probe(
        tmp_path / "out",
        "/step9a",
        _step9b_adjacent_gate(),
        _step9b_ranked_support_rows(),
        _step9b_boundary_run_rows(),
        _step9b_perturbation_config(tmp_path),
    )

    assert result["step9b_status"] == "step9b_midpoint_probe_ready"
    assert result["midpoint_candidate_count"] == 1
    assert len(captured) == 1
    midpoint = captured[0]
    assert midpoint["candidate_id"] == "local_midpoint"
    assert midpoint["scale_id"] == "local_midpoint"
    assert midpoint["scale_coordinate_value"] == 1.5
    assert midpoint["source_candidate_radius_m"] == 2.0
    assert midpoint["spatialr_px"] == 5
    assert midpoint["minsize_px"] == 11
    assert midpoint["ranger"] == pytest.approx(0.3)
    assert midpoint["source_lower_candidate_scale_group_id"] == "r999px001"
    assert midpoint["source_upper_candidate_scale_group_id"] == "r001px999"
    assert midpoint["source_lower_candidate_id"] == "source-lower-900"
    assert midpoint["source_upper_candidate_id"] == "source-upper-100"
    assert midpoint["requires_step9b_execution"] is True
    assert midpoint["source_step9a_metrics_reused"] is False
    assert all(anchor["requires_step9b_execution"] is False for anchor in result["anchor_references"])
    assert all(anchor["source_step9a_metrics_reused"] is True for anchor in result["anchor_references"])
    assert all("pair_key" not in row for row in result["anchor_references"])
    step9b_dir = rs.local_transition_refinement_output_dir(tmp_path / "out")
    perturbations = json.loads((step9b_dir / "step9b_midpoint_perturbation_candidates.json").read_text(encoding="utf-8"))
    assert len(perturbations) == 2
    assert all(row["candidate_scale_group_id"] == "local_midpoint" for row in perturbations)
    assert all(row["scale_coordinate_value"] == 1.5 for row in perturbations)
    assert all(row["source_candidate_radius_m"] == 2.0 for row in perturbations)
    assert not (step9b_dir / "step9b_midpoint_gain_share_handoff.json").exists()


def test_step9b_midpoint_expands_the_same_seed_phase_ensemble(
    tmp_path: Path,
    monkeypatch,
) -> None:
    phases = (
        ("phase_00", 0.0, 0.0),
        ("phase_01", 0.5, 0.0),
        ("phase_02", 0.0, 0.5),
        ("phase_03", 0.5, 0.5),
    )
    boundary_rows = []
    templates = {
        "r999px001": ("source-lower-900", 1.0, 4, 10, 0.2),
        "r001px999": ("source-upper-100", 3.0, 5, 11, 0.4),
    }
    for group_id, (source_id, radius, spatialr, minsize, ranger) in templates.items():
        for phase_id, phase_u, phase_v in phases:
            boundary_rows.append(
                {
                    "run_id": f"{group_id}-{phase_id}",
                    "candidate_scale_group_id": group_id,
                    "source_candidate_id": source_id,
                    "source_candidate_radius_m": radius,
                    "spatialr_px": spatialr,
                    "minsize_px": minsize,
                    "ranger": ranger,
                    "seed_realization_id": phase_id,
                    "seed_phase_u": phase_u,
                    "seed_phase_v": phase_v,
                    "original_row_metadata": {
                        "is_baseline": phase_id == "phase_00",
                        "seed_realization_id": phase_id,
                        "seed_phase_u": phase_u,
                        "seed_phase_v": phase_v,
                    },
                }
            )

    monkeypatch.setattr(
        rs,
        "build_perturbation_candidates",
        lambda _config, complete_candidates: [
            {
                "perturbation_id": "local_midpoint__baseline",
                "source_candidate_id": complete_candidates[0]["candidate_id"],
                "scale_id": complete_candidates[0]["scale_id"],
                "spatialr_px": complete_candidates[0]["spatialr_px"],
                "minsize_px": complete_candidates[0]["minsize_px"],
                "ranger": complete_candidates[0]["ranger"],
                "deltas": {},
                "is_baseline": True,
            },
            {
                "perturbation_id": "local_midpoint__spatial_plus",
                "source_candidate_id": complete_candidates[0]["candidate_id"],
                "scale_id": complete_candidates[0]["scale_id"],
                "spatialr_px": complete_candidates[0]["spatialr_px"] + 1,
                "minsize_px": complete_candidates[0]["minsize_px"],
                "ranger": complete_candidates[0]["ranger"],
                "deltas": {"spatialr_px_delta": 1},
                "is_baseline": False,
            },
        ],
    )

    result = rs.run_step9b_midpoint_support_probe(
        tmp_path / "out",
        "/step9a",
        _step9b_adjacent_gate(),
        _step9b_ranked_support_rows(),
        boundary_rows,
        _step9b_perturbation_config(tmp_path),
    )
    perturbations = json.loads(
        (
            rs.local_transition_refinement_output_dir(tmp_path / "out")
            / "step9b_midpoint_perturbation_candidates.json"
        ).read_text(encoding="utf-8")
    )

    assert result["step9b_status"] == "step9b_midpoint_probe_ready"
    assert result["midpoint_perturbation_candidate_count"] == 8
    assert len(perturbations) == 8
    assert {row["seed_realization_id"] for row in perturbations} == {
        phase[0] for phase in phases
    }
    assert sum(bool(row["is_baseline"]) for row in perturbations) == 1
    assert all(row["candidate_scale_group_id"] == "local_midpoint" for row in perturbations)


def test_53_step9b_midpoint_requires_explicit_boundary_metadata(tmp_path: Path) -> None:
    for field in (
        "top_pair_lower_scale_candidate_group_id",
        "top_pair_upper_scale_candidate_group_id",
        "top_pair_scale_coordinate_name",
        "top_pair_lower_scale_coordinate_value",
        "top_pair_upper_scale_coordinate_value",
    ):
        gate = _step9b_adjacent_gate()
        del gate[field]

        result = rs.run_step9b_midpoint_support_probe(
            tmp_path / field,
            "/step9a",
            gate,
            _step9b_ranked_support_rows(),
            _step9b_boundary_run_rows(),
            _step9b_perturbation_config(tmp_path),
        )

        assert result["step9b_status"] == "step9b_blocked_missing_top_pair_or_boundary_metadata"
        assert result["midpoint_candidate_count"] == 0


def test_54_step9b_midpoint_blocks_invalid_bounds_and_cannot_determine_continuity(tmp_path: Path) -> None:
    for lower, upper in ((2.0, 1.0), (1.0, 1.0), (1.0, float("inf"))):
        gate = _step9b_adjacent_gate(
            top_pair_lower_scale_coordinate_value=lower,
            top_pair_upper_scale_coordinate_value=upper,
        )
        result = rs.run_step9b_midpoint_support_probe(
            tmp_path / "bounds",
            "/step9a",
            gate,
            _step9b_ranked_support_rows(),
            _step9b_boundary_run_rows(),
            _step9b_perturbation_config(tmp_path),
        )
        assert result["step9b_status"] == "step9b_blocked_invalid_interval_bounds"

    cannot_gate = _step9b_adjacent_gate(
        top_pair_scale_continuity_status="cannot_determine_scale_order_disagreement",
        top_pair_is_scale_adjacent=False,
    )
    cannot = rs.run_step9b_midpoint_support_probe(
        tmp_path / "cannot",
        "/step9a",
        cannot_gate,
        _step9b_ranked_support_rows(),
        _step9b_boundary_run_rows(),
        _step9b_perturbation_config(tmp_path),
    )
    assert cannot["step9b_status"] == "step9b_blocked_cannot_determine_scale_continuity"


def test_55_step9b_midpoint_requires_one_nonconflicting_central_row_per_boundary(tmp_path: Path) -> None:
    conflicting_rows = _step9b_boundary_run_rows()
    conflicting_rows[0]["is_baseline"] = False
    conflict = rs.run_step9b_midpoint_support_probe(
        tmp_path / "conflict",
        "/step9a",
        _step9b_adjacent_gate(),
        _step9b_ranked_support_rows(),
        conflicting_rows,
        _step9b_perturbation_config(tmp_path),
    )
    assert conflict["step9b_status"] == "step9b_blocked_conflicting_baseline_metadata"

    missing_rows = [
        row
        for row in _step9b_boundary_run_rows()
        if not (
            row["candidate_scale_group_id"] == "r999px001"
            and json.loads(row["original_row_metadata"])["is_baseline"] is True
        )
    ]
    missing = rs.run_step9b_midpoint_support_probe(
        tmp_path / "missing",
        "/step9a",
        _step9b_adjacent_gate(),
        _step9b_ranked_support_rows(),
        missing_rows,
        _step9b_perturbation_config(tmp_path),
    )
    assert missing["step9b_status"] == "step9b_blocked_missing_central_boundary_rows"


def test_56_step9b_gain_share_uses_strict_half_threshold() -> None:
    above = rs.compute_step9b_gain_share_handoff("no1", "no2", "local_midpoint", 1.0, 0.0, 0.5001)
    equal = rs.compute_step9b_gain_share_handoff("no1", "no2", "local_midpoint", 1.0, 0.0, 0.5)
    below = rs.compute_step9b_gain_share_handoff("no1", "no2", "local_midpoint", 1.0, 0.0, 0.4999)

    assert above["midpoint_gain_share"] == pytest.approx(0.5001)
    assert above["handoff_candidate_id"] == "local_midpoint"
    assert above["status"] == "step9b_midpoint_gain_share_handoff"
    assert equal["midpoint_gain_share"] == 0.5
    assert equal["handoff_candidate_id"] == "no1"
    assert equal["status"] == "step9b_no1_retained_gain_share"
    assert below["handoff_candidate_id"] == "no1"
    assert below["status"] == "step9b_no1_retained_gain_share"
    assert above["gain_share_threshold"] == 0.5
    assert above["gain_share_comparator"] == ">"


def test_57_step9b_gain_share_retains_no1_for_invalid_reference_or_midpoint_support() -> None:
    invalid_gain = rs.compute_step9b_gain_share_handoff("no1", "no2", "local_midpoint", 0.0, 0.0, 0.5)
    missing_midpoint = rs.compute_step9b_gain_share_handoff("no1", "no2", "local_midpoint", 1.0, 0.0, None)
    nonfinite_midpoint = rs.compute_step9b_gain_share_handoff("no1", "no2", "local_midpoint", 1.0, 0.0, float("nan"))

    assert invalid_gain["status"] == "step9b_no1_retained_invalid_reference_gain"
    assert invalid_gain["handoff_candidate_id"] == "no1" and invalid_gain["warning"] is True
    assert missing_midpoint["status"] == "step9b_no1_retained_midpoint_uninterpretable"
    assert missing_midpoint["handoff_candidate_id"] == "no1" and missing_midpoint["warning"] is True
    assert nonfinite_midpoint["status"] == "step9b_no1_retained_midpoint_uninterpretable"
    assert nonfinite_midpoint["warning"] is True


def test_58_step9b_stubbed_midpoint_support_writes_gain_share_handoff(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        rs,
        "build_perturbation_candidates",
        lambda config, candidates: [
            {
                "perturbation_id": "local_midpoint__baseline",
                "source_candidate_id": "local_midpoint",
                "scale_id": "local_midpoint",
                "spatialr_px": candidates[0]["spatialr_px"],
                "minsize_px": candidates[0]["minsize_px"],
                "ranger": candidates[0]["ranger"],
                "is_baseline": True,
            }
        ],
    )
    result = rs.run_step9b_midpoint_support_probe(
        tmp_path / "out",
        "/step9a",
        _step9b_adjacent_gate(),
        _step9b_ranked_support_rows(),
        _step9b_boundary_run_rows(),
        _step9b_perturbation_config(tmp_path),
        midpoint_family_support_raw=0.75,
    )

    step9b_dir = rs.local_transition_refinement_output_dir(tmp_path / "out")
    assert result["step9b_status"] == "step9b_midpoint_gain_share_handoff"
    handoff = json.loads((step9b_dir / "step9b_midpoint_gain_share_handoff.json").read_text(encoding="utf-8"))
    assert handoff["midpoint_gain_share"] == 0.75
    assert handoff["handoff_candidate_id"] == "local_midpoint"
    forbidden = ("optim", "search", "best-scale", "final-selection", "distribution_break", "inconclusive")
    user_facing = " ".join(
        str(value).lower()
        for value in (result["step9b_status"], result["step9b_status_reason"], handoff["status"], handoff["handoff_reason"])
    )
    assert not any(term in user_facing for term in forbidden)


def _write_step9b_prepare_domain_manifest(
    path: Path,
    *,
    ranked_path: Path,
    midpoint_probe_path: Path,
    midpoint_perturbations_path: Path,
    status: str = "step9b_midpoint_probe_ready",
    lower_candidate_id: str = "opaque-no2",
    upper_candidate_id: str = "opaque-no1",
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": "level1b_step9b_prepare_manifest",
                "schema_version": 1,
                "status": status,
                "candidate_id": "opaque-candidate",
                "source_step9a_directory": str(
                    path.parents[1] / "candidate_response_surface"
                ),
                "source_artifacts": {},
                "ranked_candidate_scales_json": str(ranked_path),
                "gate_metadata": {
                    "top_pair_lower_scale_candidate_group_id": lower_candidate_id,
                    "top_pair_upper_scale_candidate_group_id": upper_candidate_id,
                },
                "produced_branch_artifacts": {
                    "midpoint_probe_candidate_json": str(midpoint_probe_path),
                    "midpoint_perturbation_candidates_json": str(
                        midpoint_perturbations_path
                    ),
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_step9b_prepare_from_existing_step9a_writes_manifest_and_ranked_view(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_root = tmp_path / "run"
    step9a_dir = run_root / "level1b" / "candidate_response_surface"
    step9a_dir.mkdir(parents=True)
    run_population_rows = [
        {"run_id": "run-1", "candidate_scale_group_id": "candidate-b"}
    ]
    candidate_group_rows = [
        {"candidate_scale_group_id": "candidate-b", "test_raw": 2.0, "test_clamped": 0.0},
        {"candidate_scale_group_id": "candidate-a", "test_raw": 1.0, "test_clamped": 1.0},
        {"candidate_scale_group_id": "zulu", "test_raw": 0.0, "test_clamped": 0.8},
        {"candidate_scale_group_id": "alpha", "test_raw": 0.0, "test_clamped": 0.8},
        {"candidate_scale_group_id": "candidate-c", "test_raw": 0.0, "test_clamped": 0.2},
    ]
    source_report = {"status": "step9a-complete"}
    (step9a_dir / "run_population_summary.json").write_text(
        json.dumps(run_population_rows), encoding="utf-8"
    )
    (step9a_dir / "candidate_group_response_summary.json").write_text(
        json.dumps(candidate_group_rows), encoding="utf-8"
    )
    (step9a_dir / "candidate_response_surface_report.json").write_text(
        json.dumps(source_report), encoding="utf-8"
    )

    monkeypatch.setattr(rs, "stability_score_raw", lambda row: row["test_raw"])
    monkeypatch.setattr(rs, "stability_score", lambda row: row["test_clamped"])
    captured: dict[str, object] = {}

    def fake_gate(run_rows, ranked_rows):
        captured["gate_run_rows"] = run_rows
        captured["gate_ranked_rows"] = ranked_rows
        return {"top_pair_scale_continuity_status": "adjacent_top_pair_confirmed"}

    def fake_probe(**kwargs):
        captured["probe"] = kwargs
        step9b_dir = (
            Path(kwargs["output_dir"])
            / "level1b"
            / "local_transition_refinement"
        )
        step9b_dir.mkdir(parents=True)
        for filename, payload in (
            ("step9b_interval_preflight.json", {}),
            ("step9b_midpoint_probe_candidate.csv", "x\n"),
            ("step9b_midpoint_probe_candidate.json", {}),
            ("step9b_midpoint_perturbation_candidates.csv", "x\n"),
            ("step9b_midpoint_perturbation_candidates.json", []),
        ):
            path = step9b_dir / filename
            if path.suffix == ".json":
                path.write_text(json.dumps(payload), encoding="utf-8")
            else:
                path.write_text(payload, encoding="utf-8")
        return {"step9b_status": "step9b_midpoint_probe_ready"}

    monkeypatch.setattr(
        rs, "compute_top_pair_scale_continuity_and_boundary_gate", fake_gate
    )
    monkeypatch.setattr(rs, "run_step9b_midpoint_support_probe", fake_probe)
    perturbation_config = _step9b_perturbation_config(tmp_path)

    result = rs.run_step9b_prepare_from_existing_step9a(
        run_root,
        "opaque-candidate-id",
        perturbation_config,
    )

    prepare_dir = run_root / "level1b" / "step9b_prepare_inputs"
    assert sorted(path.name for path in prepare_dir.iterdir()) == [
        "ranked_candidate_scales_view.json",
        "step9b_prepare_manifest.json",
    ]
    ranked_path = prepare_dir / "ranked_candidate_scales_view.json"
    ranked = json.loads(ranked_path.read_text(encoding="utf-8"))
    assert [row["candidate_scale_group_id"] for row in ranked] == [
        "candidate-b",
        "candidate-a",
        "alpha",
        "zulu",
        "candidate-c",
    ]
    manifest_path = prepare_dir / "step9b_prepare_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == "level1b_step9b_prepare_manifest"
    assert manifest["schema_version"] == 1
    assert manifest["status"] == "step9b_midpoint_probe_ready"
    assert manifest["source_step9a_directory"] == str(step9a_dir)
    assert manifest["source_artifacts"] == {
        "run_population_summary_json": str(step9a_dir / "run_population_summary.json"),
        "candidate_group_response_summary_json": str(
            step9a_dir / "candidate_group_response_summary.json"
        ),
        "candidate_response_surface_report_json": str(
            step9a_dir / "candidate_response_surface_report.json"
        ),
    }
    assert manifest["ranked_candidate_scales_json"] == str(ranked_path)
    assert manifest["gate_metadata"] == {
        "top_pair_scale_continuity_status": "adjacent_top_pair_confirmed"
    }
    assert set(manifest["produced_branch_artifacts"]) == {
        "step9b_interval_preflight_json",
        "midpoint_probe_candidate_csv",
        "midpoint_probe_candidate_json",
        "midpoint_perturbation_candidates_csv",
        "midpoint_perturbation_candidates_json",
    }
    probe = captured["probe"]
    assert probe["output_dir"] == run_root
    assert probe["source_step9a_directory"] == step9a_dir
    assert probe["step9a_gate_metadata"] == {
        "status": "step9a-complete",
        "candidate_id": "opaque-candidate-id",
        "source_candidate_response_surface_report": str(
            step9a_dir / "candidate_response_surface_report.json"
        ),
        "top_pair_scale_continuity_status": "adjacent_top_pair_confirmed",
    }
    assert probe["ranked_candidate_rows"] == ranked
    assert probe["run_population_rows"] == run_population_rows
    assert probe["perturbation_config"] is perturbation_config
    assert probe["midpoint_family_support_raw"] is None
    assert set(result) == {
        "status",
        "run_root",
        "candidate_id",
        "step9a_dir",
        "step9b_prepare_inputs_dir",
        "local_transition_refinement_dir",
        "step9b_prepare_manifest_json",
        "ranked_candidate_scales_view_json",
        "step9b_result",
    }
    assert result["status"] is None
    assert result["step9b_prepare_manifest_json"] == str(manifest_path)
    assert result["ranked_candidate_scales_view_json"] == str(ranked_path)


def test_step9b_prepare_manifest_records_non_adjacent_branch_without_source_copies(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_root = tmp_path / "run"
    step9a_dir = run_root / "level1b" / "candidate_response_surface"
    step9a_dir.mkdir(parents=True)
    (step9a_dir / "run_population_summary.json").write_text("[]", encoding="utf-8")
    (step9a_dir / "candidate_group_response_summary.json").write_text(
        json.dumps(
            [
                {"candidate_scale_group_id": "one"},
                {"candidate_scale_group_id": "two"},
            ]
        ),
        encoding="utf-8",
    )
    (step9a_dir / "candidate_response_surface_report.json").write_text(
        "{}", encoding="utf-8"
    )
    monkeypatch.setattr(rs, "stability_score_raw", lambda row: 0.0)
    monkeypatch.setattr(rs, "stability_score", lambda row: 0.0)
    monkeypatch.setattr(
        rs,
        "compute_top_pair_scale_continuity_and_boundary_gate",
        lambda run_rows, ranked_rows: {
            "top_pair_scale_continuity_status": (
                "non_adjacent_top_pair_possible_bimodal_or_multimodal"
            )
        },
    )

    def fake_probe(**kwargs):
        step9b_dir = (
            Path(kwargs["output_dir"])
            / "level1b"
            / "local_transition_refinement"
        )
        step9b_dir.mkdir(parents=True)
        (step9b_dir / "step9b_interval_preflight.json").write_text(
            "{}", encoding="utf-8"
        )
        (step9b_dir / "step9b_supported_scale_alternatives.csv").write_text(
            "rank\n", encoding="utf-8"
        )
        (step9b_dir / "step9b_supported_scale_alternatives.json").write_text(
            "[]", encoding="utf-8"
        )
        return {
            "step9b_status": (
                "step9b_user_choice_required_bimodal_or_multimodal"
            )
        }

    monkeypatch.setattr(rs, "run_step9b_midpoint_support_probe", fake_probe)
    result = rs.run_step9b_prepare_from_existing_step9a(
        run_root,
        "opaque",
        _step9b_perturbation_config(tmp_path),
    )
    prepare_dir = run_root / "level1b" / "step9b_prepare_inputs"
    manifest = json.loads(
        (prepare_dir / "step9b_prepare_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == (
        "step9b_user_choice_required_bimodal_or_multimodal"
    )
    assert set(manifest["produced_branch_artifacts"]) == {
        "step9b_interval_preflight_json",
        "supported_scale_alternatives_csv",
        "supported_scale_alternatives_json",
    }
    assert result["status"] is None
    assert not (prepare_dir / "run_population_summary.json").exists()
    assert not (prepare_dir / "candidate_response_surface_report.json").exists()
    assert not (prepare_dir / "step9b_prepare_result.json").exists()


def test_step9b_prepare_from_existing_step9a_does_not_search_for_missing_inputs(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "run"
    alternate_dir = run_root / "alternate"
    alternate_dir.mkdir(parents=True)
    for filename, payload in (
        ("run_population_summary.json", []),
        ("candidate_group_response_summary.json", []),
        ("candidate_response_surface_report.json", {}),
    ):
        (alternate_dir / filename).write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        rs.run_step9b_prepare_from_existing_step9a(
            run_root,
            "opaque-candidate-id",
            _step9b_perturbation_config(tmp_path),
        )


def test_midpoint_response_surface_and_handoff_from_prepare_runs_nested_surface_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_root = tmp_path / "run"
    prepare_dir = run_root / "level1b" / "step9b_prepare_inputs"
    step9b_dir = run_root / "level1b" / "local_transition_refinement"
    prepare_dir.mkdir(parents=True)
    step9b_dir.mkdir(parents=True)
    ranked_path = prepare_dir / "ranked-candidates-at-explicit-path.json"
    midpoint_probe_path = step9b_dir / "probe-at-explicit-path.json"
    midpoint_perturbations_path = step9b_dir / "family-at-explicit-path.json"
    ranked_rows = [
        {"candidate_scale_group_id": "opaque-no1", "stability_score_raw": 1.0},
        {"candidate_scale_group_id": "opaque-no2", "stability_score_raw": 0.0},
    ]
    ranked_path.write_text(json.dumps(ranked_rows), encoding="utf-8")
    midpoint_probe_path.write_text(
        json.dumps({"candidate_scale_group_id": "opaque-midpoint"}),
        encoding="utf-8",
    )
    midpoint_perturbations_path.write_text(
        json.dumps([{"candidate_scale_group_id": "opaque-midpoint"}]),
        encoding="utf-8",
    )
    manifest_path = _write_step9b_prepare_domain_manifest(
        prepare_dir / "step9b_prepare_manifest.json",
        ranked_path=ranked_path,
        midpoint_probe_path=midpoint_probe_path,
        midpoint_perturbations_path=midpoint_perturbations_path,
    )

    original_config = Level1BCandidateResponseSurfaceConfig(
        candidate_id="original-candidate",
        output_dir=tmp_path / "original-output",
        perturbation_candidates_json_path=tmp_path / "original-candidates.json",
        feature_space_stack_path=tmp_path / "features.tif",
        valid_mask_path=tmp_path / "mask.tif",
        segmentation_stack_path=tmp_path / "segmentation-stack.tif",
        segmentation_stack_source="explicit-test-stack",
        otb_bin_dir="/otb/bin",
        ram_mb=1234,
        overwrite=True,
        dry_run=True,
    )
    original_values = vars(original_config).copy()
    calls = []

    def fake_run_candidate_response_surface_step(config):
        calls.append(config)
        nested_dir = rs.response_surface_output_dir(config.output_dir)
        nested_dir.mkdir(parents=True)
        (nested_dir / "candidate_group_response_summary.json").write_text(
            json.dumps(
                [
                    {
                        "candidate_scale_group_id": "opaque-midpoint",
                        "stability_score_raw": 0.75,
                    }
                ]
            ),
            encoding="utf-8",
        )
        (nested_dir / "run_population_summary.json").write_text(
            json.dumps(
                [{"candidate_scale_group_id": "opaque-midpoint", "run_id": "run-1"}]
            ),
            encoding="utf-8",
        )
        return {"status": "ok"}

    monkeypatch.setattr(
        rs,
        "run_candidate_response_surface_step",
        fake_run_candidate_response_surface_step,
    )

    result = rs.run_step9b_midpoint_response_surface_and_handoff_from_prepare(
        run_root,
        "requested-candidate",
        original_config,
        manifest_path,
    )

    assert len(calls) == 1
    nested_config = calls[0]
    expected_output_dir = step9b_dir / "midpoint_response_surface_eval"
    assert nested_config.output_dir == expected_output_dir
    assert nested_config.perturbation_candidates_json_path == midpoint_perturbations_path
    assert nested_config.candidate_id == "requested-candidate"
    for field, value in original_values.items():
        if field not in {"output_dir", "perturbation_candidates_json_path", "candidate_id"}:
            assert getattr(nested_config, field) == value
    assert vars(original_config) == original_values

    nested_summary_dir = rs.response_surface_output_dir(expected_output_dir)
    assert result["step9b_prepare_manifest_json"] == str(manifest_path)
    assert result["midpoint_candidate_group_summary_json"] == str(
        nested_summary_dir / "candidate_group_response_summary.json"
    )
    assert result["midpoint_run_population_json"] == str(
        nested_summary_dir / "run_population_summary.json"
    )
    handoff = result["handoff"]
    assert handoff["no1_candidate_scale_group_id"] == "opaque-no1"
    assert handoff["no2_candidate_scale_group_id"] == "opaque-no2"
    assert handoff["midpoint_candidate_id"] == "opaque-midpoint"
    assert handoff["S1"] == 1.0
    assert handoff["S2"] == 0.0
    assert handoff["SM"] == 0.75
    assert handoff["handoff_candidate_id"] == "opaque-midpoint"
    assert handoff["top_pair_lower_scale_candidate_group_id"] == "opaque-no2"
    assert handoff["top_pair_upper_scale_candidate_group_id"] == "opaque-no1"
    handoff_path = step9b_dir / "step9b_midpoint_gain_share_handoff.json"
    assert json.loads(handoff_path.read_text(encoding="utf-8")) == handoff
    assert result["step9b_midpoint_gain_share_handoff_json"] == str(handoff_path)


def test_select_step9_handoff_candidate_uses_numeric_boundary_metadata() -> None:
    handoff = {
        "handoff_candidate_id": "opaque-no1",
        "midpoint_candidate_id": "opaque-midpoint",
        "no1_candidate_scale_group_id": "opaque-no1",
        "top_pair_lower_scale_candidate_group_id": "opaque-no1",
        "top_pair_upper_scale_candidate_group_id": "opaque-no2",
    }

    selected = rs.select_step9_handoff_candidate(handoff)

    assert selected["selected_candidate_id"] == "opaque-no1"
    assert selected["selected_source"] == "lower_bound"


def test_midpoint_response_surface_and_handoff_from_prepare_rejects_unmatched_multiple_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_root = tmp_path / "run"
    prepare_dir = run_root / "level1b" / "step9b_prepare_inputs"
    step9b_dir = run_root / "level1b" / "local_transition_refinement"
    prepare_dir.mkdir(parents=True)
    step9b_dir.mkdir(parents=True)
    ranked_path = prepare_dir / "ranked.json"
    midpoint_probe_path = step9b_dir / "probe.json"
    midpoint_perturbations_path = step9b_dir / "perturbations.json"
    ranked_path.write_text(
        json.dumps(
            [
                {"candidate_scale_group_id": "no1", "stability_score_raw": 1.0},
                {"candidate_scale_group_id": "no2", "stability_score_raw": 0.0},
            ]
        ),
        encoding="utf-8",
    )
    midpoint_probe_path.write_text(
        json.dumps({"candidate_scale_group_id": "expected-midpoint"}),
        encoding="utf-8",
    )
    midpoint_perturbations_path.write_text("[]", encoding="utf-8")
    manifest_path = _write_step9b_prepare_domain_manifest(
        prepare_dir / "manifest.json",
        ranked_path=ranked_path,
        midpoint_probe_path=midpoint_probe_path,
        midpoint_perturbations_path=midpoint_perturbations_path,
    )

    def fake_run_candidate_response_surface_step(config):
        nested_dir = rs.response_surface_output_dir(config.output_dir)
        nested_dir.mkdir(parents=True)
        (nested_dir / "candidate_group_response_summary.json").write_text(
            json.dumps(
                [
                    {"candidate_scale_group_id": "other-a", "stability_score_raw": 0.7},
                    {"candidate_scale_group_id": "other-b", "stability_score_raw": 0.6},
                ]
            ),
            encoding="utf-8",
        )
        (nested_dir / "run_population_summary.json").write_text(
            "[]", encoding="utf-8"
        )
        return {"status": "ok"}

    monkeypatch.setattr(
        rs,
        "run_candidate_response_surface_step",
        fake_run_candidate_response_surface_step,
    )
    config = Level1BCandidateResponseSurfaceConfig(
        candidate_id="original",
        output_dir=tmp_path / "original-output",
        perturbation_candidates_json_path=tmp_path / "original-candidates.json",
    )

    with pytest.raises(ValueError, match="exactly one row matching"):
        rs.run_step9b_midpoint_response_surface_and_handoff_from_prepare(
            run_root,
            "requested-candidate",
            config,
            manifest_path,
        )


def test_midpoint_connector_stops_on_failed_nested_response_surface(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_root = tmp_path / "run"
    prepare_dir = run_root / "level1b" / "step9b_prepare_inputs"
    step9b_dir = run_root / "level1b" / "local_transition_refinement"
    prepare_dir.mkdir(parents=True)
    step9b_dir.mkdir(parents=True)
    ranked_path = prepare_dir / "ranked.json"
    midpoint_probe_path = step9b_dir / "probe.json"
    midpoint_perturbations_path = step9b_dir / "perturbations.json"
    ranked_path.write_text(
        json.dumps(
            [
                {"candidate_scale_group_id": "no1", "stability_score_raw": 1.0},
                {"candidate_scale_group_id": "no2", "stability_score_raw": 0.0},
            ]
        ),
        encoding="utf-8",
    )
    midpoint_probe_path.write_text(
        json.dumps({"candidate_scale_group_id": "midpoint"}), encoding="utf-8"
    )
    midpoint_perturbations_path.write_text(
        json.dumps([{"candidate_scale_group_id": "midpoint"}]), encoding="utf-8"
    )
    manifest_path = _write_step9b_prepare_domain_manifest(
        prepare_dir / "manifest.json",
        ranked_path=ranked_path,
        midpoint_probe_path=midpoint_probe_path,
        midpoint_perturbations_path=midpoint_perturbations_path,
    )
    monkeypatch.setattr(
        rs,
        "run_candidate_response_surface_step",
        lambda config: {"status": "failed"},
    )
    config = Level1BCandidateResponseSurfaceConfig(
        candidate_id="candidate",
        output_dir=tmp_path / "unused",
        perturbation_candidates_json_path=tmp_path / "unused.json",
    )

    with pytest.raises(
        RuntimeError, match="Midpoint response surface failed with status 'failed'"
    ):
        rs.run_step9b_midpoint_response_surface_and_handoff_from_prepare(
            run_root,
            "candidate",
            config,
            manifest_path,
        )


def test_completed_step9a_removes_only_seed_scaffold_rasters(tmp_path: Path) -> None:
    out_dir = tmp_path / "candidate_response_surface"
    scaffold = out_dir / "seed_scaffolds" / "scale_001" / "phase_00"
    scaffold.mkdir(parents=True)
    expected_bytes = 0
    for suffix in rs.SEED_SCAFFOLD_RASTER_SUFFIXES:
        path = scaffold / f"seeds{suffix}"
        payload = suffix.encode("utf-8")
        path.write_bytes(payload)
        expected_bytes += len(payload)
    report_json = scaffold / "controlled_seed_report.json"
    report_json.write_text('{"status":"ok"}', encoding="utf-8")
    unrelated = scaffold / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")

    cleanup = rs._cleanup_completed_seed_scaffold_rasters(
        out_dir,
        {
            "status": "ok",
            "number_of_planned_runs": 4,
            "number_of_omitted_runs_due_to_explicit_safety_limits": 0,
            "number_of_successful_runs": 4,
            "number_of_failed_runs": 0,
        },
        dry_run=False,
    )

    assert cleanup["status"] == "complete"
    assert cleanup["deleted_file_count"] == len(rs.SEED_SCAFFOLD_RASTER_SUFFIXES)
    assert cleanup["bytes_reclaimed"] == expected_bytes
    assert report_json.is_file()
    assert unrelated.is_file()
    assert not any(
        path.suffix in rs.SEED_SCAFFOLD_RASTER_SUFFIXES
        for path in scaffold.iterdir()
    )


def test_incomplete_step9a_preserves_seed_scaffold_rasters(tmp_path: Path) -> None:
    out_dir = tmp_path / "candidate_response_surface"
    scaffold = out_dir / "seed_scaffolds" / "scale_001" / "phase_00"
    scaffold.mkdir(parents=True)
    seed_grid = scaffold / "seeds.sdat"
    seed_grid.write_bytes(b"seed-grid")

    cleanup = rs._cleanup_completed_seed_scaffold_rasters(
        out_dir,
        {
            "status": "partial",
            "number_of_planned_runs": 4,
            "number_of_omitted_runs_due_to_explicit_safety_limits": 0,
            "number_of_successful_runs": 3,
            "number_of_failed_runs": 1,
        },
        dry_run=False,
    )

    assert cleanup["status"] == "skipped"
    assert cleanup["reason"] == "step9a_not_complete_success"
    assert seed_grid.is_file()
