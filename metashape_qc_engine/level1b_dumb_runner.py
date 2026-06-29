from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from collections.abc import Sequence
import sys
from typing import Any

from metashape_qc_engine.level1b_candidate_response_surface import (
    Level1BCandidateResponseSurfaceConfig,
    _pixel_size_m,
    run_candidate_response_surface_step,
    run_step9b_midpoint_response_surface_and_handoff_from_prepare,
    run_step9b_prepare_from_existing_step9a,
)
from metashape_qc_engine.level1b_channels import (
    Level1BChannelConfig,
    run_channel_construction_step,
)
from metashape_qc_engine.level1b_feature_range import (
    Level1BFeatureRangeConfig,
    run_feature_range_assignment_step,
)
from metashape_qc_engine.level1b_materialization import (
    run_level1b_step10_aggregate_finalist_evidence,
    run_level1b_step10_collect_finalist_evidence,
    run_level1b_step10_compute_exactextractr_segment_stats_and_quality_info,
    run_level1b_step10_make_finalist_figures,
    run_level1b_step10_materialize_selected_segments,
)
from metashape_qc_engine.level1b_perturbations import (
    Level1BPerturbationConfig,
    run_local_perturbation_step,
)
from metashape_qc_engine.level1b_preflight import (
    Level1BPreflightConfig,
    run_preflight,
)
from metashape_qc_engine.level1b_scale_distribution import (
    Level1BScaleDistributionConfig,
    run_scale_distribution_step,
)
from metashape_qc_engine.level1b_scaling import (
    Level1BScalingConfig,
    run_scaling_step,
)
from metashape_qc_engine.level1b_valid_mask import (
    Level1BValidMaskConfig,
    run_valid_mask_step,
)


FEATURE_BAND_COUNT = 5


def _candidate_id(rgb_ortho: Path) -> str:
    opaque_source = str(Path(rgb_ortho).absolute()).encode("utf-8")
    return "level1b_" + hashlib.sha256(opaque_source).hexdigest()[:16]


def _raise_on_failed_status(step_name: str, result: object) -> None:
    if isinstance(result, dict) and result.get("status") == "failed":
        raise RuntimeError(f"{step_name}: processing function returned status=failed")


def _require_artifacts(step_name: str, paths: Sequence[Path]) -> None:
    for path in paths:
        if not path.exists():
            raise RuntimeError(f"{step_name}: expected artifact missing: {path}")


def run_level1b_dumb_chain(
    rgb_ortho: Path,
    output_dir: Path,
    *,
    overwrite: bool = False,
) -> dict:
    rgb_ortho = Path(rgb_ortho)
    output_dir = Path(output_dir)
    candidate_id = _candidate_id(rgb_ortho)
    level1b_dir = output_dir / "level1b"
    if level1b_dir.exists() and not overwrite:
        raise RuntimeError(
            f"level1b_dumb_chain: output directory already exists: {level1b_dir}"
        )

    valid_mask = level1b_dir / "mask" / "valid_mask.tif"
    proxy_stack = level1b_dir / "channels" / "proxy_stack.tif"
    channel_report = level1b_dir / "channels" / "channel_report.json"
    scaled_feature_stack = level1b_dir / "scaling" / "scaled_feature_stack.tif"
    scale_candidates = level1b_dir / "scales" / "scale_candidates.json"
    scale_candidates_with_ranger = (
        level1b_dir / "ranger" / "scale_candidates_with_ranger.json"
    )
    perturbation_candidates = (
        level1b_dir / "perturbations" / "perturbation_candidates.json"
    )
    step9a_dir = level1b_dir / "candidate_response_surface"
    step9a_run_population = step9a_dir / "run_population_summary.json"
    step9a_group_summary = step9a_dir / "candidate_group_response_summary.json"
    step9a_report = step9a_dir / "candidate_response_surface_report.json"
    step9b_prepare_dir = level1b_dir / "step9b_prepare_inputs"
    step9b_prepare_artifacts = (
        step9b_prepare_dir / "run_population_summary.json",
        step9b_prepare_dir / "ranked_candidate_scales.json",
        step9b_prepare_dir / "candidate_response_surface_report.json",
        step9b_prepare_dir / "step9b_prepare_result.json",
    )
    local_transition_dir = level1b_dir / "local_transition_refinement"
    midpoint_probe = local_transition_dir / "step9b_midpoint_probe_candidate.json"
    midpoint_perturbations = (
        local_transition_dir / "step9b_midpoint_perturbation_candidates.json"
    )
    supported_alternatives = (
        local_transition_dir / "step9b_supported_scale_alternatives.json"
    )

    step_results: dict[str, Any] = {}

    preflight_result = run_preflight(
        Level1BPreflightConfig(
            candidate_id=candidate_id,
            input_path=rgb_ortho,
            output_dir=output_dir,
        )
    )
    _raise_on_failed_status("preflight", preflight_result)
    step_results["preflight"] = preflight_result

    valid_mask_result = run_valid_mask_step(
        Level1BValidMaskConfig(
            candidate_id=candidate_id,
            input_path=rgb_ortho,
            output_dir=output_dir,
            overwrite=overwrite,
        )
    )
    _raise_on_failed_status("valid_mask", valid_mask_result)
    _require_artifacts("valid_mask", (valid_mask,))
    step_results["valid_mask"] = valid_mask_result

    pixel_size_m = _pixel_size_m(rgb_ortho)
    channels_result = run_channel_construction_step(
        Level1BChannelConfig(
            candidate_id=candidate_id,
            input_path=rgb_ortho,
            output_dir=output_dir,
            input_type="rgb",
            valid_mask_path=valid_mask,
            pixel_size_m=pixel_size_m,
            overwrite=overwrite,
        )
    )
    _raise_on_failed_status("channels", channels_result)
    _require_artifacts("channels", (proxy_stack, channel_report))
    step_results["channels"] = channels_result

    scaling_result = run_scaling_step(
        Level1BScalingConfig(
            candidate_id=candidate_id,
            feature_stack_path=proxy_stack,
            valid_mask_path=valid_mask,
            output_dir=output_dir,
            band_count=FEATURE_BAND_COUNT,
            overwrite=overwrite,
        )
    )
    _raise_on_failed_status("scaling", scaling_result)
    _require_artifacts("scaling", (scaled_feature_stack,))
    step_results["scaling"] = scaling_result

    scale_distribution_result = run_scale_distribution_step(
        Level1BScaleDistributionConfig(
            candidate_id=candidate_id,
            output_dir=output_dir,
            pixel_size_m=pixel_size_m,
            scale_mode="structure_derived_scale_distribution",
            proxy_stack_path=proxy_stack,
            valid_mask_path=valid_mask,
            channel_report_path=channel_report,
            proxy_structure_mode="texture_preferred",
            sampling_regime="auto",
            infer_structure_support_from_proxy=True,
            infer_texture_support_from_proxy=True,
            upper_radius_factor=2.5,
            overwrite=overwrite,
        )
    )
    _raise_on_failed_status("scale_distribution", scale_distribution_result)
    _require_artifacts("scale_distribution", (scale_candidates,))
    step_results["scale_distribution"] = scale_distribution_result

    feature_range_result = run_feature_range_assignment_step(
        Level1BFeatureRangeConfig(
            candidate_id=candidate_id,
            output_dir=output_dir,
            feature_space_stack_path=scaled_feature_stack,
            valid_mask_path=valid_mask,
            scale_candidates_json_path=scale_candidates,
            feature_space_source="scaled",
            band_count=FEATURE_BAND_COUNT,
            overwrite=overwrite,
        )
    )
    _raise_on_failed_status("feature_range", feature_range_result)
    _require_artifacts("feature_range", (scale_candidates_with_ranger,))
    step_results["feature_range"] = feature_range_result

    perturbation_config = Level1BPerturbationConfig(
        candidate_id=candidate_id,
        output_dir=output_dir,
        scale_candidates_with_ranger_json_path=scale_candidates_with_ranger,
        overwrite=overwrite,
    )
    perturbation_result = run_local_perturbation_step(perturbation_config)
    _raise_on_failed_status("perturbations", perturbation_result)
    _require_artifacts("perturbations", (perturbation_candidates,))
    step_results["perturbations"] = perturbation_result

    candidate_response_surface_config = Level1BCandidateResponseSurfaceConfig(
        candidate_id=candidate_id,
        output_dir=output_dir,
        perturbation_candidates_json_path=perturbation_candidates,
        valid_mask_path=valid_mask,
        segmentation_stack_path=scaled_feature_stack,
        segmentation_stack_source="scaled_proxy_stack",
        overwrite=overwrite,
    )
    step9a_result = run_candidate_response_surface_step(
        candidate_response_surface_config
    )
    _raise_on_failed_status("step9a", step9a_result)
    _require_artifacts(
        "step9a",
        (step9a_run_population, step9a_group_summary, step9a_report),
    )
    step_results["step9a"] = step9a_result

    step9b_prepare_result = run_step9b_prepare_from_existing_step9a(
        run_root=output_dir,
        candidate_id=candidate_id,
        perturbation_config=perturbation_config,
    )
    _raise_on_failed_status("step9b_prepare", step9b_prepare_result)
    _require_artifacts("step9b_prepare", step9b_prepare_artifacts)
    step_results["step9b_prepare"] = step9b_prepare_result

    prepare_result = json.loads(
        step9b_prepare_artifacts[-1].read_text(encoding="utf-8")
    )
    prepare_status = prepare_result.get("step9b_status")
    if prepare_status == "step9b_user_choice_required_bimodal_or_multimodal":
        _require_artifacts("step9b_non_adjacent", (supported_alternatives,))
        return {
            "status": "step9b_non_adjacent_choice_required",
            "candidate_id": candidate_id,
            "output_dir": str(output_dir),
            "branch": "non_adjacent",
            "supported_scale_alternatives_json": str(supported_alternatives),
            "step_results": step_results,
        }
    if prepare_status != "step9b_midpoint_probe_ready":
        raise RuntimeError(
            "step9b_prepare: expected step9b_midpoint_probe_ready or "
            "step9b_user_choice_required_bimodal_or_multimodal, "
            f"got {prepare_status!r}"
        )
    _require_artifacts(
        "step9b_midpoint_probe", (midpoint_probe, midpoint_perturbations)
    )

    step9b_midpoint_handoff_result = (
        run_step9b_midpoint_response_surface_and_handoff_from_prepare(
            run_root=output_dir,
            candidate_id=candidate_id,
            candidate_response_surface_config=candidate_response_surface_config,
        )
    )
    _raise_on_failed_status(
        "step9b_midpoint_handoff", step9b_midpoint_handoff_result
    )
    midpoint_response_surface_dir = (
        local_transition_dir
        / "midpoint_response_surface_eval"
        / "level1b"
        / "candidate_response_surface"
    )
    midpoint_run_population = (
        midpoint_response_surface_dir / "run_population_summary.json"
    )
    midpoint_group_summary = (
        midpoint_response_surface_dir / "candidate_group_response_summary.json"
    )
    handoff = local_transition_dir / "step9b_midpoint_gain_share_handoff.json"
    _require_artifacts(
        "step9b_midpoint_handoff",
        (midpoint_run_population, midpoint_group_summary, handoff),
    )
    step_results["step9b_midpoint_handoff"] = step9b_midpoint_handoff_result

    step10_root = level1b_dir / "step10_materialization"
    decision_evidence_dir = step10_root / "decision_evidence"
    finalist_group_summary = decision_evidence_dir / "finalist_group_summary.json"
    finalist_perturbation_runs = (
        decision_evidence_dir / "finalist_perturbation_runs.json"
    )
    step10_collect_result = run_level1b_step10_collect_finalist_evidence(
        output_dir
    )
    _raise_on_failed_status("step10_collect", step10_collect_result)
    _require_artifacts(
        "step10_collect", (finalist_group_summary, finalist_perturbation_runs)
    )
    step_results["step10_collect"] = step10_collect_result

    finalist_group_aggregation = (
        decision_evidence_dir / "finalist_group_aggregation.json"
    )
    finalist_numeric_distribution = (
        decision_evidence_dir / "finalist_numeric_distribution_summary.json"
    )
    step10_aggregate_result = run_level1b_step10_aggregate_finalist_evidence(
        output_dir
    )
    _raise_on_failed_status("step10_aggregate", step10_aggregate_result)
    _require_artifacts(
        "step10_aggregate",
        (finalist_group_aggregation, finalist_numeric_distribution),
    )
    step_results["step10_aggregate"] = step10_aggregate_result

    figure_manifest = step10_root / "figures" / "step10_figure_manifest.json"
    step10_figures_result = run_level1b_step10_make_finalist_figures(output_dir)
    _raise_on_failed_status("step10_figures", step10_figures_result)
    _require_artifacts("step10_figures", (figure_manifest,))
    step_results["step10_figures"] = step10_figures_result

    final_segments_dir = step10_root / "final_segments"
    selected_segments_manifest = (
        final_segments_dir / "selected_segments_manifest.json"
    )
    selected_segments = final_segments_dir / "selected_segments.gpkg"
    selected_labels = final_segments_dir / "selected_labels.tif"
    step10_materialize_result = run_level1b_step10_materialize_selected_segments(
        output_dir
    )
    _raise_on_failed_status("step10_materialize", step10_materialize_result)
    _require_artifacts(
        "step10_materialize",
        (selected_segments_manifest, selected_segments, selected_labels),
    )
    step_results["step10_materialize"] = step10_materialize_result

    segment_stats_dir = step10_root / "segment_stats"
    segment_stats_csv = (
        segment_stats_dir / "selected_segment_exactextractr_stats.csv"
    )
    segment_stats_summary = (
        segment_stats_dir / "selected_segment_exactextractr_summary.json"
    )
    step10_quality = step10_root / "quality" / "ortho_segmentation_quality_info.json"
    step10_quality_result = (
        run_level1b_step10_compute_exactextractr_segment_stats_and_quality_info(
            output_dir
        )
    )
    _raise_on_failed_status("step10_quality", step10_quality_result)
    _require_artifacts(
        "step10_quality",
        (segment_stats_csv, segment_stats_summary, step10_quality),
    )
    step_results["step10_quality"] = step10_quality_result

    return {
        "status": "level1b_dumb_chain_complete",
        "candidate_id": candidate_id,
        "output_dir": str(output_dir),
        "branch": "adjacent_midpoint",
        "artifacts": {
            "valid_mask": str(valid_mask),
            "proxy_stack": str(proxy_stack),
            "scaled_feature_stack": str(scaled_feature_stack),
            "scale_candidates": str(scale_candidates),
            "scale_candidates_with_ranger": str(scale_candidates_with_ranger),
            "perturbation_candidates": str(perturbation_candidates),
            "step9a_report": str(step9a_report),
            "step9b_prepare_result": str(step9b_prepare_artifacts[-1]),
            "handoff": str(handoff),
            "step10_quality": str(step10_quality),
        },
        "step_results": step_results,
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rgb-ortho", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = run_level1b_dumb_chain(
            rgb_ortho=args.rgb_ortho,
            output_dir=args.out_dir,
            overwrite=args.overwrite,
        )
        report_path = (
            args.out_dir / "level1b" / "level1b_dumb_chain_report.json"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(result, indent=2, default=str), encoding="utf-8"
        )
        print(json.dumps(result, indent=2, default=str))
        if result["status"] == "step9b_non_adjacent_choice_required":
            return 2
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI converts processing failures to exit 1.
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
