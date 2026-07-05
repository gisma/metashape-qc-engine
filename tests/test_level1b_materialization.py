import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from metashape_qc_engine import level1b_materialization as materialization
from metashape_qc_engine.level1b_materialization import (
    _selected_label_raster_path,
    run_level1b_step10_aggregate_finalist_evidence,
    run_level1b_step10_collect_finalist_evidence,
    run_level1b_step10_compute_exactextractr_segment_stats_and_quality_info,
    run_level1b_step10_make_finalist_figures,
    run_level1b_step10_materialize_selected_segments,
)


def test_selected_label_raster_uses_explicit_versioned_path() -> None:
    row = {
        "run_contract_version": 2,
        "merged_labels_path": "/canonical/run/merged_labels.tif",
        "masked_segmentation_stack_path": "/response/masked_segmentation_stack.tif",
    }

    assert _selected_label_raster_path(row) == Path(
        "/canonical/run/merged_labels.tif"
    )


def test_selected_label_raster_keeps_explicit_legacy_contract() -> None:
    row = {
        "masked_segmentation_stack_path": (
            "/legacy/run/masked_segmentation_stack.tif"
        )
    }

    assert _selected_label_raster_path(row) == Path(
        "/legacy/run/merged_labels.tif"
    )



def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _seed_step9_evidence(
    output_dir: Path,
    *,
    selected_candidate_id: str = "midpoint-id",
) -> dict[str, Path]:
    step9a_dir = output_dir / "level1b" / "candidate_response_surface"
    step9b_dir = output_dir / "level1b" / "local_transition_refinement"
    midpoint_dir = (
        step9b_dir
        / "midpoint_response_surface_eval"
        / "level1b"
        / "candidate_response_surface"
    )
    paths = {
        "handoff": step9b_dir / "step9b_midpoint_gain_share_handoff.json",
        "step9a_groups": step9a_dir / "candidate_group_response_summary.json",
        "step9a_runs": step9a_dir / "run_population_summary.json",
        "midpoint_groups": midpoint_dir / "candidate_group_response_summary.json",
        "midpoint_runs": midpoint_dir / "run_population_summary.json",
    }
    _write_json(
        paths["handoff"],
        {
            "no2_candidate_scale_group_id": "lower-id",
            "midpoint_candidate_id": "midpoint-id",
            "no1_candidate_scale_group_id": "upper-id",
            "top_pair_lower_scale_candidate_group_id": "lower-id",
            "top_pair_upper_scale_candidate_group_id": "upper-id",
            "handoff_candidate_id": selected_candidate_id,
        },
    )
    _write_json(
        paths["step9a_groups"],
        [
            {
                "candidate_scale_group_id": "lower-id",
                "medoid_run_id": "lower-baseline",
                "stability_score_raw": 0.1,
                "stability_score": 0.1,
            },
            {
                "candidate_scale_group_id": "upper-id",
                "medoid_run_id": "upper-baseline",
                "stability_score_raw": 0.8,
                "stability_score": 0.8,
            },
        ],
    )
    _write_json(
        paths["midpoint_groups"],
        [
            {
                "candidate_scale_group_id": "midpoint-id",
                "medoid_run_id": "midpoint-baseline",
                "stability_score_raw": 0.7,
                "stability_score": 0.7,
            }
        ],
    )

    source_dir = output_dir / "source-products"
    source_dir.mkdir(parents=True, exist_ok=True)
    run_rows = {}
    for role, candidate_id in (
        ("lower", "lower-id"),
        ("upper", "upper-id"),
        ("midpoint", "midpoint-id"),
    ):
        merged_labels = source_dir / f"{role}_merged_labels.tif"
        masked_stack = source_dir / f"{role}_masked_stack.tif"
        valid_mask = source_dir / f"{role}_valid_mask.tif"
        run_rows[role] = [
            {
                "run_id": f"{role}-baseline",
                "candidate_scale_group_id": candidate_id,
                "original_row_metadata": {"is_baseline": True},
                "ensemble_representative": True,
                "run_contract_version": 2,
                "merged_labels_path": str(merged_labels),
                "masked_segmentation_stack_path": str(masked_stack),
                "valid_mask_path": str(valid_mask),
                "label_invalid_support_value": 0,
                "segment_count": 10,
                "mean_area_m2": 2.0,
                "spatialr_px": 4,
            },
            {
                "run_id": f"{role}-perturbation",
                "candidate_scale_group_id": candidate_id,
                "original_row_metadata": {"is_baseline": False},
                "ensemble_representative": False,
                "run_contract_version": 2,
                "merged_labels_path": str(merged_labels),
                "masked_segmentation_stack_path": str(masked_stack),
                "valid_mask_path": str(valid_mask),
                "label_invalid_support_value": 0,
                "segment_count": 12,
                "mean_area_m2": 3.0,
                "spatialr_px": 5,
            },
        ]
    _write_json(paths["step9a_runs"], [*run_rows["lower"], *run_rows["upper"]])
    _write_json(paths["midpoint_runs"], run_rows["midpoint"])
    return paths


def _write_selected_source_labels(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.array([[0, 1], [2, 2]], dtype="uint32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype=data.dtype,
        transform=from_origin(0, 2, 1, 1),
    ) as dataset:
        dataset.write(data, 1)


def test_step10_canonical_evidence_preserves_upper_selected_display_order(
    tmp_path: Path,
) -> None:
    _seed_step9_evidence(tmp_path, selected_candidate_id="upper-id")

    result = run_level1b_step10_collect_finalist_evidence(tmp_path)
    evidence = json.loads(
        Path(result["finalist_evidence_json"]).read_text(encoding="utf-8")
    )

    assert evidence["display_order"] == [
        "upper_boundary",
        "midpoint",
        "lower_boundary",
    ]
    assert evidence["selected_candidate_id"] == "upper-id"
    assert evidence["selected_role"] == "upper_boundary"
    assert evidence["selected_representative_run_id"] == "upper-baseline"
    assert [
        row["step10_finalist_role"] for row in evidence["finalist_group_rows"]
    ] == evidence["display_order"]
    assert [
        row["step10_display_rank"] for row in evidence["finalist_group_rows"]
    ] == [1, 2, 3]


def test_step10_roles_follow_scale_order_when_no1_is_lower(
    tmp_path: Path,
) -> None:
    paths = _seed_step9_evidence(tmp_path, selected_candidate_id="lower-id")
    handoff = json.loads(paths["handoff"].read_text(encoding="utf-8"))
    handoff.update(
        {
            "no1_candidate_scale_group_id": "lower-id",
            "no2_candidate_scale_group_id": "upper-id",
            "top_pair_lower_scale_candidate_group_id": "lower-id",
            "top_pair_upper_scale_candidate_group_id": "upper-id",
        }
    )
    _write_json(paths["handoff"], handoff)

    result = run_level1b_step10_collect_finalist_evidence(tmp_path)
    evidence = json.loads(
        Path(result["finalist_evidence_json"]).read_text(encoding="utf-8")
    )

    assert evidence["selected_candidate_id"] == "lower-id"
    assert evidence["selected_role"] == "lower_boundary"
    assert evidence["display_order"] == [
        "lower_boundary",
        "midpoint",
        "upper_boundary",
    ]
    selected_row = evidence["finalist_group_rows"][0]
    assert selected_row["step10_selected_candidate"] is True
    assert selected_row["step10_lower_boundary_documentation_only"] is False


def test_step10_parts_share_canonical_evidence_without_step9_reread(
    tmp_path: Path,
    monkeypatch,
) -> None:
    step9_paths = _seed_step9_evidence(tmp_path)
    collect_result = run_level1b_step10_collect_finalist_evidence(tmp_path)
    evidence_path = Path(collect_result["finalist_evidence_json"])
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    decision_dir = evidence_path.parent

    assert evidence["display_order"] == [
        "midpoint",
        "upper_boundary",
        "lower_boundary",
    ]
    assert evidence["selected_candidate_id"] == "midpoint-id"
    assert evidence["selected_role"] == "midpoint"
    assert evidence["selected_representative_run_id"] == "midpoint-baseline"
    assert json.loads(
        (decision_dir / "finalist_group_summary.json").read_text(encoding="utf-8")
    ) == evidence["finalist_group_rows"]
    assert json.loads(
        (decision_dir / "finalist_perturbation_runs.json").read_text(
            encoding="utf-8"
        )
    ) == evidence["finalist_run_rows"]

    for path in step9_paths.values():
        path.write_text("not valid JSON", encoding="utf-8")
    for name in ("finalist_group_summary.json", "finalist_perturbation_runs.json"):
        (decision_dir / name).write_text("not valid JSON", encoding="utf-8")

    aggregate_result = run_level1b_step10_aggregate_finalist_evidence(tmp_path)
    aggregated_evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert aggregated_evidence["status"] == (
        "step10_part2_finalist_evidence_aggregated"
    )
    assert [
        row["step10_finalist_role"]
        for row in aggregated_evidence["group_aggregation_rows"]
    ] == aggregated_evidence["display_order"]
    assert json.loads(
        Path(aggregate_result["finalist_group_aggregation_json"]).read_text(
            encoding="utf-8"
        )
    ) == aggregated_evidence["group_aggregation_rows"]
    assert json.loads(
        Path(
            aggregate_result["finalist_numeric_distribution_summary_json"]
        ).read_text(encoding="utf-8")
    ) == aggregated_evidence["numeric_distribution_rows"]

    figure_result = run_level1b_step10_make_finalist_figures(tmp_path)
    assert figure_result["figure_count"] == 6
    figure_manifest = json.loads(
        Path(figure_result["manifest_json"]).read_text(encoding="utf-8")
    )
    assert figure_manifest["input_files_used"] == [str(evidence_path)]
    assert figure_manifest["selected_candidate_id"] == "midpoint-id"

    selected_row = materialization._selected_representative_run(aggregated_evidence)
    source_labels = Path(selected_row["merged_labels_path"])
    _write_selected_source_labels(source_labels)
    materialize_result = run_level1b_step10_materialize_selected_segments(
        tmp_path
    )
    selected_labels = Path(materialize_result["selected_labels_tif"])
    assert selected_labels.read_bytes() == source_labels.read_bytes()
    assert Path(materialize_result["selected_segments_gpkg"]).exists()
    materialize_manifest = json.loads(
        Path(materialize_result["manifest_json"]).read_text(encoding="utf-8")
    )
    assert materialize_manifest["source_run_id"] == "midpoint-baseline"
    assert materialize_manifest["selected_candidate_id"] == "midpoint-id"

    calls = []

    def fake_subprocess_run(command, check):
        calls.append((command, check))
        stats_csv = Path(command[5])
        summary_json = Path(command[6])
        stats_csv.parent.mkdir(parents=True, exist_ok=True)
        stats_csv.write_text("segment_id,band_001_mean\n1,2.5\n", encoding="utf-8")
        summary_json.write_text(
            json.dumps(
                {
                    "status": "step10_part5_exactextractr_segment_stats_ready",
                    "segment_count": 2,
                    "band_count": 1,
                    "stats_column_count": 1,
                    "stats_columns": ["band_001_mean"],
                    "numeric_column_summary": {
                        "band_001_mean": {
                            "n_non_na": 2,
                            "mean": 2.5,
                            "median": 2.5,
                            "min": 2.0,
                            "max": 3.0,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(materialization.subprocess, "run", fake_subprocess_run)
    quality_result = (
        run_level1b_step10_compute_exactextractr_segment_stats_and_quality_info(
            tmp_path
        )
    )
    assert len(calls) == 1
    command, check = calls[0]
    assert check is True
    assert command[3] == str(
        Path(selected_row["masked_segmentation_stack_path"])
    )
    assert command[4] == str(Path(selected_row["valid_mask_path"]))
    quality = json.loads(
        Path(quality_result["ortho_segmentation_quality_info_json"]).read_text(
            encoding="utf-8"
        )
    )
    assert quality["selected_representative_id"] == "midpoint-baseline"
    assert quality["selected_group_aggregation_row"] == next(
        row
        for row in aggregated_evidence["group_aggregation_rows"]
        if row["step10_selected_candidate"] is True
    )
    assert quality["source_files"]["finalist_evidence_json"] == str(
        evidence_path
    )
    assert quality["segment_stats_summary"]["numeric_column_summary"] == {
        "band_001_mean": {
            "n_non_na": 2,
            "mean": 2.5,
            "median": 2.5,
            "min": 2.0,
            "max": 3.0,
        }
    }
