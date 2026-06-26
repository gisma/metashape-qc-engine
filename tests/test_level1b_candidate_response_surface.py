import json
from pathlib import Path
import sys

import numpy as np
import rasterio
from rasterio.transform import from_origin


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from metashape_qc_engine import level1b_candidate_response_surface as rs
from metashape_qc_engine.level1b_candidate_response_surface import (
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
    }
    base.update(extra)
    return base


def test_01_groups_step8_rows_into_candidate_scale_groups() -> None:
    groups = group_rows_by_candidate_scale(rows())

    assert [group["candidate_scale_group_id"] for group in groups] == ["scale-a", "scale-b"]
    assert [row["perturbation_id"] for row in groups[0]["rows"]] == ["a1", "a2"]


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
        [{"candidate_scale_group_id": "scale-a", "candidate_outcome": "stable_representative_candidate", "stability_score": 0.9, "response_center_q": 1.0, "response_spread_q": 0.2, "central_area_share_mean": 0.8}],
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
    labels = write_raster(tmp_path / "labels.tif", np.array([[1, 1], [2, 2]], dtype=np.uint32))
    candidate_path = tmp_path / "candidates.json"
    candidate_path.write_text(json.dumps({"candidates": [{"perturbation_id": "run-a", "source_candidate_id": "cand-a", "scale_id": "scale-a", "radius_m": 1.0, "spatialr_px": 1, "minsize_px": 1, "ranger": 0.1}]}), encoding="utf-8")

    monkeypatch.setattr(
        rs,
        "run_one_scale_segmentation_smoke",
        lambda config: {"status": "ok", "failure_reasons": [], "output_artifacts": {"merged_labels": str(labels)}},
    )
    report = run_candidate_response_surface_step(
        cfg(tmp_path, perturbation_candidates_json_path=candidate_path, feature_space_stack_path=feature)
    )

    for path in report["required_outputs"].values():
        assert Path(path).exists()
