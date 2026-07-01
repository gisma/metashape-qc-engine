from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from collections.abc import Sequence
import sys
from typing import Any
import yaml

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
from metashape_qc_engine.level1b_step_manifest import (
    manifest_artifact,
    read_step_manifest,
    step_manifest_path,
)


CHAIN_REPORT_FILENAME = "level1b_dumb_chain_report.json"


def _filename_token(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(value))


def _candidate_id(rgb_ortho: Path) -> str:
    sanitized_ortho_stem = _filename_token(Path(rgb_ortho).stem)
    return sanitized_ortho_stem + "__structure_scales"


def _raise_on_failed_status(step_name: str, result: object) -> None:
    if isinstance(result, dict) and result.get("status") == "failed":
        raise RuntimeError(f"{step_name}: processing function returned status=failed")


def _require_artifacts(step_name: str, paths: Sequence[Path]) -> None:
    for path in paths:
        if not path.exists():
            raise RuntimeError(f"{step_name}: expected artifact missing: {path}")


def _consume_step_manifest(
    output_dir: Path,
    step: str,
    result: object,
) -> dict[str, object]:
    path = step_manifest_path(output_dir, step)
    if not path.exists():
        raise RuntimeError(f"{step}: expected manifest missing: {path}")
    manifest = read_step_manifest(output_dir, step)
    result_status = result.get("status") if isinstance(result, dict) else None
    if result_status is not None and result_status != manifest["status"]:
        raise RuntimeError(
            f"{step}: result status {result_status!r} does not match manifest "
            f"status {manifest['status']!r}"
        )
    return manifest


def _manifest_artifacts(
    step_name: str,
    manifest: dict[str, object],
    keys: Sequence[str],
) -> dict[str, Path]:
    paths = {key: manifest_artifact(manifest, key) for key in keys}
    _require_artifacts(step_name, tuple(paths.values()))
    return paths


def _compact_step_result(
    output_dir: Path,
    manifest: dict[str, object],
) -> dict[str, object]:
    return {
        "status": manifest["status"],
        "manifest": str(
            step_manifest_path(output_dir, str(manifest["step"]))
        ),
    }


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

    level1b_dir.mkdir(parents=True, exist_ok=True)

    config_path = Path(__file__).resolve().parent / "config" / "level1b_default.yaml"
    with config_path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)["level1b"]

    resolved_config_path = level1b_dir / "resolved_level1b_config.yaml"
    with resolved_config_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump({"level1b": cfg}, f, default_flow_style=False)

    step_results: dict[str, Any] = {}

    preflight_result = run_preflight(
        Level1BPreflightConfig(
            candidate_id=candidate_id,
            input_path=rgb_ortho,
            output_dir=output_dir,
        )
    )
    _raise_on_failed_status("preflight", preflight_result)
    preflight_manifest = _consume_step_manifest(
        output_dir, "preflight", preflight_result
    )
    _manifest_artifacts(
        "preflight", preflight_manifest, ("preflight_report",)
    )
    step_results["preflight"] = _compact_step_result(output_dir, preflight_manifest)

    valid_mask_result = run_valid_mask_step(
        Level1BValidMaskConfig(
            candidate_id=candidate_id,
            input_path=rgb_ortho,
            output_dir=output_dir,
            overwrite=overwrite,
        )
    )
    _raise_on_failed_status("valid_mask", valid_mask_result)
    valid_mask_manifest = _consume_step_manifest(
        output_dir, "valid_mask", valid_mask_result
    )
    valid_mask_artifacts = _manifest_artifacts(
        "valid_mask", valid_mask_manifest, ("valid_mask", "report")
    )
    valid_mask = valid_mask_artifacts["valid_mask"]
    step_results["valid_mask"] = _compact_step_result(output_dir, valid_mask_manifest)

    pixel_size_m = _pixel_size_m(rgb_ortho)
    channels_cfg = cfg["channels"]
    channels_result = run_channel_construction_step(
        Level1BChannelConfig(
            candidate_id=candidate_id,
            input_path=rgb_ortho,
            output_dir=output_dir,
            input_type=channels_cfg["input_type"],
            valid_mask_path=valid_mask,
            pixel_size_m=pixel_size_m,
            rgb_band_indices=tuple(channels_cfg["rgb_band_indices"]),
            tex_100m_radius_m=channels_cfg["tex_100m_radius_m"],
            tex_200m_radius_m=channels_cfg["tex_200m_radius_m"],
            report_filename=channels_cfg["report_filename"],
            overwrite=overwrite,
        )
    )
    _raise_on_failed_status("channels", channels_result)
    channels_manifest = _consume_step_manifest(output_dir, "channels", channels_result)
    channels_artifacts = _manifest_artifacts(
        "channels", channels_manifest, ("proxy_stack", "report")
    )
    proxy_stack = channels_artifacts["proxy_stack"]
    channel_report = channels_artifacts["report"]
    step_results["channels"] = _compact_step_result(output_dir, channels_manifest)

    scaling_result = run_scaling_step(
        Level1BScalingConfig(
            candidate_id=candidate_id,
            feature_stack_path=proxy_stack,
            valid_mask_path=valid_mask,
            output_dir=output_dir,
            band_count=cfg["feature_band_count"],
            overwrite=overwrite,
        )
    )
    _raise_on_failed_status("scaling", scaling_result)
    scaling_manifest = _consume_step_manifest(output_dir, "scaling", scaling_result)
    scaling_artifacts = _manifest_artifacts(
        "scaling", scaling_manifest, ("scaled_feature_stack", "report")
    )
    scaled_feature_stack = scaling_artifacts["scaled_feature_stack"]
    step_results["scaling"] = _compact_step_result(output_dir, scaling_manifest)

    scale_distribution_result = run_scale_distribution_step(
        Level1BScaleDistributionConfig(
            candidate_id=candidate_id,
            output_dir=output_dir,
            pixel_size_m=pixel_size_m,
            scale_mode=cfg["scale_distribution"]["scale_mode"],
            proxy_stack_path=proxy_stack,
            valid_mask_path=valid_mask,
            channel_report_path=channel_report,
            proxy_structure_mode=cfg["scale_distribution"]["proxy_structure_mode"],
            sampling_regime=cfg["scale_distribution"]["sampling_regime"],
            infer_structure_support_from_proxy=cfg["scale_distribution"]["infer_structure_support_from_proxy"],
            infer_texture_support_from_proxy=cfg["scale_distribution"]["infer_texture_support_from_proxy"],
            upper_radius_factor=cfg["scale_distribution"]["upper_radius_factor"],
            overwrite=overwrite,
        )
    )
    _raise_on_failed_status("scale_distribution", scale_distribution_result)
    scale_distribution_manifest = _consume_step_manifest(
        output_dir, "scale_distribution", scale_distribution_result
    )
    scale_distribution_artifacts = _manifest_artifacts(
        "scale_distribution",
        scale_distribution_manifest,
        ("scale_candidates_json",),
    )
    scale_candidates = scale_distribution_artifacts["scale_candidates_json"]
    step_results["scale_distribution"] = _compact_step_result(
        output_dir, scale_distribution_manifest
    )

    feature_range_cfg = cfg["feature_range"]
    feature_range_result = run_feature_range_assignment_step(
        Level1BFeatureRangeConfig(
            candidate_id=candidate_id,
            output_dir=output_dir,
            feature_space_stack_path=scaled_feature_stack,
            valid_mask_path=valid_mask,
            scale_candidates_json_path=scale_candidates,
            feature_space_source=feature_range_cfg["feature_space_source"],
            band_count=cfg["feature_band_count"],
            sample_n=feature_range_cfg["sample_n"],
            knn_k=feature_range_cfg["knn_k"],
            quantile_probs=tuple(feature_range_cfg["quantile_probs"]),
            max_distance_sample_n=feature_range_cfg["max_distance_sample_n"],
            overwrite=overwrite,
        )
    )
    _raise_on_failed_status("feature_range", feature_range_result)
    feature_range_manifest = _consume_step_manifest(
        output_dir, "feature_range", feature_range_result
    )
    feature_range_artifacts = _manifest_artifacts(
        "feature_range",
        feature_range_manifest,
        ("scale_candidates_with_ranger_json",),
    )
    scale_candidates_with_ranger = feature_range_artifacts[
        "scale_candidates_with_ranger_json"
    ]
    step_results["feature_range"] = _compact_step_result(output_dir, feature_range_manifest)

    perturbation_config = Level1BPerturbationConfig(
        candidate_id=candidate_id,
        output_dir=output_dir,
        scale_candidates_with_ranger_json_path=scale_candidates_with_ranger,
        overwrite=overwrite,
    )
    perturbation_result = run_local_perturbation_step(perturbation_config)
    _raise_on_failed_status("perturbations", perturbation_result)
    perturbations_manifest = _consume_step_manifest(
        output_dir, "perturbations", perturbation_result
    )
    perturbation_artifacts = _manifest_artifacts(
        "perturbations",
        perturbations_manifest,
        ("perturbation_candidates_json",),
    )
    perturbation_candidates = perturbation_artifacts[
        "perturbation_candidates_json"
    ]
    step_results["perturbations"] = _compact_step_result(output_dir, perturbations_manifest)

    candidate_response_surface_config = Level1BCandidateResponseSurfaceConfig(
        candidate_id=candidate_id,
        output_dir=output_dir,
        perturbation_candidates_json_path=perturbation_candidates,
        valid_mask_path=valid_mask,
        segmentation_stack_path=scaled_feature_stack,
        segmentation_stack_source=cfg["candidate_response_surface"]["segmentation_stack_source"],
        overwrite=overwrite,
    )
    step9a_result = run_candidate_response_surface_step(
        candidate_response_surface_config
    )
    step9a_status = (
        step9a_result.get("status") if isinstance(step9a_result, dict) else None
    )
    if step9a_status != "ok":
        raise RuntimeError(
            "step9a: incomplete response surface with status "
            f"{step9a_status!r}; Step-9b and Step-10 were not run"
        )
    step9a_manifest = _consume_step_manifest(
        output_dir, "candidate_response_surface", step9a_result
    )
    step9a_artifacts = _manifest_artifacts(
        "step9a",
        step9a_manifest,
        ("run_population_json", "group_json", "report"),
    )
    step9a_run_population = step9a_artifacts["run_population_json"]
    step9a_group_summary = step9a_artifacts["group_json"]
    step9a_report = step9a_artifacts["report"]
    step_results["step9a"] = _compact_step_result(output_dir, step9a_manifest)

    step9b_prepare_result = run_step9b_prepare_from_existing_step9a(
        run_root=output_dir,
        candidate_id=candidate_id,
        perturbation_config=perturbation_config,
    )
    _raise_on_failed_status("step9b_prepare", step9b_prepare_result)
    step9b_prepare_manifest = _consume_step_manifest(
        output_dir, "step9b_prepare", step9b_prepare_result
    )
    step9b_prepare_artifacts = _manifest_artifacts(
        "step9b_prepare",
        step9b_prepare_manifest,
        (
            "step9b_prepare_manifest_json",
            "ranked_candidate_scales_view_json",
            "step9b_interval_preflight_json",
        ),
    )
    step_results["step9b_prepare"] = _compact_step_result(output_dir, step9b_prepare_manifest)

    if (
        step9b_prepare_manifest["status"]
        == "step9b_user_choice_required_bimodal_or_multimodal"
    ):
        supported_alternatives = _manifest_artifacts(
            "step9b_prepare",
            step9b_prepare_manifest,
            ("supported_scale_alternatives_json",),
        )["supported_scale_alternatives_json"]
        return {
            "status": "step9b_non_adjacent_choice_required",
            "candidate_id": candidate_id,
            "output_dir": str(output_dir),
            "branch": "non_adjacent",
            "supported_scale_alternatives_json": str(supported_alternatives),
            "step_results": step_results,
        }
    if step9b_prepare_manifest["status"] != "step9b_midpoint_probe_ready":
        raise RuntimeError(
            "step9b_branch: unsupported Step-9b Prepare manifest status: "
            f"{step9b_prepare_manifest['status']!r}"
        )
    _manifest_artifacts(
        "step9b_prepare",
        step9b_prepare_manifest,
        ("midpoint_probe_candidate_json", "midpoint_perturbation_candidates_json"),
    )

    step9b_midpoint_handoff_result = (
        run_step9b_midpoint_response_surface_and_handoff_from_prepare(
            run_root=output_dir,
            candidate_id=candidate_id,
            candidate_response_surface_config=candidate_response_surface_config,
            step9b_prepare_manifest_path=step9b_prepare_artifacts[
                "step9b_prepare_manifest_json"
            ],
        )
    )
    _raise_on_failed_status(
        "step9b_midpoint_handoff", step9b_midpoint_handoff_result
    )
    step9b_midpoint_manifest = _consume_step_manifest(
        output_dir,
        "step9b_midpoint_handoff",
        step9b_midpoint_handoff_result,
    )
    midpoint_artifacts = _manifest_artifacts(
        "step9b_midpoint_handoff",
        step9b_midpoint_manifest,
        (
            "midpoint_run_population_summary_json",
            "midpoint_candidate_group_response_summary_json",
            "step9b_midpoint_gain_share_handoff_json",
        ),
    )
    midpoint_run_population = midpoint_artifacts[
        "midpoint_run_population_summary_json"
    ]
    midpoint_group_summary = midpoint_artifacts[
        "midpoint_candidate_group_response_summary_json"
    ]
    handoff = midpoint_artifacts["step9b_midpoint_gain_share_handoff_json"]
    step_results["step9b_midpoint_handoff"] = _compact_step_result(
        output_dir, step9b_midpoint_manifest
    )

    step10_collect_result = run_level1b_step10_collect_finalist_evidence(
        output_dir
    )
    _raise_on_failed_status("step10_collect", step10_collect_result)
    step10_collect_manifest = _consume_step_manifest(
        output_dir, "step10_collect", step10_collect_result
    )
    step10_collect_artifacts = _manifest_artifacts(
        "step10_collect",
        step10_collect_manifest,
        ("finalist_evidence_json",),
    )
    step10_evidence = step10_collect_artifacts["finalist_evidence_json"]
    step_results["step10_collect"] = _compact_step_result(
        output_dir, step10_collect_manifest
    )

    step10_aggregate_result = run_level1b_step10_aggregate_finalist_evidence(
        output_dir
    )
    _raise_on_failed_status("step10_aggregate", step10_aggregate_result)
    step10_aggregate_manifest = _consume_step_manifest(
        output_dir, "step10_aggregate", step10_aggregate_result
    )
    _manifest_artifacts(
        "step10_aggregate",
        step10_aggregate_manifest,
        ("finalist_evidence_json",),
    )
    step_results["step10_aggregate"] = _compact_step_result(
        output_dir, step10_aggregate_manifest
    )

    step10_figures_result = run_level1b_step10_make_finalist_figures(output_dir)
    _raise_on_failed_status("step10_figures", step10_figures_result)
    step10_figures_manifest = _consume_step_manifest(
        output_dir, "step10_figures", step10_figures_result
    )
    _manifest_artifacts(
        "step10_figures", step10_figures_manifest, ("figure_manifest_json",)
    )
    step_results["step10_figures"] = _compact_step_result(
        output_dir, step10_figures_manifest
    )

    step10_materialize_result = run_level1b_step10_materialize_selected_segments(
        output_dir
    )
    _raise_on_failed_status("step10_materialize", step10_materialize_result)
    step10_materialize_manifest = _consume_step_manifest(
        output_dir, "step10_materialize", step10_materialize_result
    )
    materialize_artifacts = _manifest_artifacts(
        "step10_materialize",
        step10_materialize_manifest,
        (
            "selected_segments_manifest_json",
            "selected_segments_gpkg",
            "selected_labels_tif",
        ),
    )
    selected_segments_manifest = materialize_artifacts[
        "selected_segments_manifest_json"
    ]
    selected_segments = materialize_artifacts["selected_segments_gpkg"]
    selected_labels = materialize_artifacts["selected_labels_tif"]
    step_results["step10_materialize"] = _compact_step_result(
        output_dir, step10_materialize_manifest
    )

    step10_quality_result = (
        run_level1b_step10_compute_exactextractr_segment_stats_and_quality_info(
            output_dir
        )
    )
    _raise_on_failed_status("step10_quality", step10_quality_result)
    step10_quality_manifest = _consume_step_manifest(
        output_dir, "step10_quality", step10_quality_result
    )
    quality_artifacts = _manifest_artifacts(
        "step10_quality",
        step10_quality_manifest,
        (
            "selected_segment_exactextractr_stats_csv",
            "selected_segment_exactextractr_summary_json",
            "ortho_segmentation_quality_info_json",
        ),
    )
    step10_quality = quality_artifacts["ortho_segmentation_quality_info_json"]
    step_results["step10_quality"] = _compact_step_result(
        output_dir, step10_quality_manifest
    )

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
            "step9b_prepare_manifest": str(
                step9b_prepare_artifacts["step9b_prepare_manifest_json"]
            ),
            "handoff": str(handoff),
            "step10_evidence": str(step10_evidence),
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


def _write_chain_report(output_dir: Path, report: dict[str, object]) -> Path:
    report_path = output_dir / CHAIN_REPORT_FILENAME
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, default=str),
        encoding="utf-8",
    )
    return report_path


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        report = run_level1b_dumb_chain(
            rgb_ortho=args.rgb_ortho,
            output_dir=args.out_dir,
            overwrite=args.overwrite,
        )
        exit_code = (
            2
            if report["status"] == "step9b_non_adjacent_choice_required"
            else 0
        )
    except Exception as exc:  # noqa: BLE001 - CLI converts processing failures to exit 1.
        report = {
            "status": "level1b_dumb_chain_failed",
            "output_dir": str(args.out_dir),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        exit_code = 1

    report_path = _write_chain_report(args.out_dir, report)
    stream = sys.stderr if exit_code == 1 else sys.stdout
    print(
        f"{report['status']} report={report_path}",
        file=stream,
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
