from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
from collections.abc import Sequence
import sys
from typing import Any
import yaml

from metashape_qc_engine.level1b.candidate_response_surface import (
    Level1BCandidateResponseSurfaceConfig,
    _pixel_size_m,
    run_candidate_response_surface_step,
    run_step9b_midpoint_response_surface_and_handoff_from_prepare,
    run_step9b_prepare_from_existing_step9a,
)
from metashape_qc_engine.level1b.channels import (
    Level1BChannelConfig,
    run_channel_construction_step,
)
from metashape_qc_engine.level1b.candidate_prescreening import (
    Level1BCandidatePrescreeningConfig,
    run_candidate_prescreening_step,
)
from metashape_qc_engine.level1b.centroid_seed_stabilization import (
    run_multiscale_centroid_seed_stabilization,
)
from metashape_qc_engine.level1b.materialization import (
    run_level1b_step10_aggregate_finalist_evidence,
    run_level1b_step10_collect_finalist_evidence,
    run_level1b_step10_compute_exactextractr_segment_stats_and_quality_info,
    run_level1b_step10_make_finalist_figures,
    run_level1b_step10_materialize_selected_segments,
)
from metashape_qc_engine.level1b.perturbations import Level1BPerturbationConfig
from metashape_qc_engine.level1b.preflight import (
    Level1BPreflightConfig,
    run_preflight,
)
from metashape_qc_engine.level1b.scaling import (
    Level1BScalingConfig,
    run_scaling_step,
)
from metashape_qc_engine.level1b.valid_mask import (
    Level1BValidMaskConfig,
    run_valid_mask_step,
)
from metashape_qc_engine.level1b.step_manifest import (
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

    config_path = Path(__file__).resolve().parents[2] / "config" / "level1b_default.yaml"
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
            input_type="rgb",
            valid_mask_path=valid_mask,
            pixel_size_m=pixel_size_m,
            rgb_band_indices=tuple(channels_cfg["rgb_band_indices"]),
            dglcm_pc1_small_radius_m=channels_cfg[
                "dglcm_pc1_small_radius_m"
            ],
            dglcm_pc1_large_radius_m=channels_cfg[
                "dglcm_pc1_large_radius_m"
            ],
            pc1_clip_quantiles=tuple(channels_cfg["pc1_clip_quantiles"]),
            pc1_output_min=float(channels_cfg["pc1_output_min"]),
            pc1_output_max=float(channels_cfg["pc1_output_max"]),
            glcm_nbbin=channels_cfg["glcm_nbbin"],
            glcm_directions=tuple(
                tuple(direction) for direction in channels_cfg["glcm_directions"]
            ),
            ratio_eps=channels_cfg["ratio_eps"],
            background_value=channels_cfg["background_value"],
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
    proxy_band_count = int(channels_result["band_count"])
    step_results["channels"] = _compact_step_result(output_dir, channels_manifest)

    scaling_result = run_scaling_step(
        Level1BScalingConfig(
            candidate_id=candidate_id,
            feature_stack_path=proxy_stack,
            valid_mask_path=valid_mask,
            output_dir=output_dir,
            band_count=proxy_band_count,
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

    prescreen_cfg = cfg["candidate_pre_screening"]
    prescreen_result = run_candidate_prescreening_step(
        Level1BCandidatePrescreeningConfig(
            candidate_id=candidate_id,
            output_dir=output_dir,
            feature_space_stack_path=scaled_feature_stack,
            valid_mask_path=valid_mask,
            pixel_size_m=pixel_size_m,
            band_count=proxy_band_count,
            radius_min_m=prescreen_cfg["radius_min_m"],
            radius_max_m=prescreen_cfg["radius_max_m"],
            lag_count=prescreen_cfg["lag_count"],
            lag_spacing=prescreen_cfg["lag_spacing"],
            directions=tuple(
                tuple(value) for value in prescreen_cfg["directions"]
            ),
            pair_sample_n_per_direction=prescreen_cfg[
                "pair_sample_n_per_direction"
            ],
            min_valid_pairs_per_direction=prescreen_cfg[
                "min_valid_pairs_per_direction"
            ],
            sill_tail_fraction=prescreen_cfg["sill_tail_fraction"],
            sill_fraction_targets=tuple(
                prescreen_cfg["sill_fraction_targets"]
            ),
            stable_crossing_window=prescreen_cfg["stable_crossing_window"],
            plateau_rel_tol=prescreen_cfg["plateau_rel_tol"],
            anisotropy_ratio_threshold=prescreen_cfg[
                "anisotropy_ratio_threshold"
            ],
            candidate_budget=prescreen_cfg["candidate_budget"],
            seed_phase_offsets=tuple(
                tuple(float(value) for value in phase)
                for phase in prescreen_cfg["seed_phase_offsets"]
            ),
            ranger_level_policy=prescreen_cfg["ranger_level_policy"],
            sample_n=prescreen_cfg["sample_n"],
            knn_k_policy=prescreen_cfg["knn_k_policy"],
            knn_k_candidates=tuple(prescreen_cfg["knn_k_candidates"]),
            hsm_stability_rel_tol=prescreen_cfg["hsm_stability_rel_tol"],
            hsm_plateau_window=prescreen_cfg["hsm_plateau_window"],
            max_distance_sample_n=prescreen_cfg["max_distance_sample_n"],
            seed=prescreen_cfg["seed"],
            overwrite=overwrite,
        )
    )
    _raise_on_failed_status("candidate_pre_screening", prescreen_result)
    prescreen_manifest = _consume_step_manifest(
        output_dir, "candidate_pre_screening", prescreen_result
    )
    prescreen_artifacts = _manifest_artifacts(
        "candidate_pre_screening",
        prescreen_manifest,
        ("candidate_population_json", "variogram_diagnostics_json"),
    )
    candidate_population = prescreen_artifacts["candidate_population_json"]
    variogram_diagnostics = prescreen_artifacts["variogram_diagnostics_json"]
    step_results["candidate_pre_screening"] = _compact_step_result(
        output_dir, prescreen_manifest
    )

    # Step-9b reuses the existing local midpoint-family generator. Its source
    # table path is provenance only in that call; Step-9a consumes the complete
    # pre-screened population directly.
    perturbation_config = Level1BPerturbationConfig(
        candidate_id=candidate_id,
        output_dir=output_dir,
        scale_candidates_with_ranger_json_path=candidate_population,
        overwrite=overwrite,
    )

    candidate_response_surface_config = Level1BCandidateResponseSurfaceConfig(
        candidate_id=candidate_id,
        output_dir=output_dir,
        perturbation_candidates_json_path=candidate_population,
        valid_mask_path=valid_mask,
        segmentation_stack_path=scaled_feature_stack,
        segmentation_stack_source="scaled_proxy_stack",
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

    stabilization_cfg = cfg["centroid_seed_stabilization"]
    stabilization_result = run_multiscale_centroid_seed_stabilization(
        output_dir,
        minimum_run_support=stabilization_cfg["minimum_run_support"],
        minimum_phase_support=stabilization_cfg["minimum_phase_support"],
        minimum_ranger_support=stabilization_cfg["minimum_ranger_support"],
    )
    _raise_on_failed_status("centroid_seed_stabilization", stabilization_result)
    stabilization_manifest = _consume_step_manifest(
        output_dir, "centroid_seed_stabilization", stabilization_result
    )
    _manifest_artifacts(
        "centroid_seed_stabilization",
        stabilization_manifest,
        (
            "stabilization_report_json",
            "stabilized_seed_grid",
            "stabilized_seed_csv",
            "stabilized_labels_tif",
        ),
    )
    step_results["centroid_seed_stabilization"] = _compact_step_result(
        output_dir, stabilization_manifest
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
            "candidate_population": str(candidate_population),
            "variogram_diagnostics": str(variogram_diagnostics),
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


def shell_join(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _is_windows() -> bool:
    return os.name == "nt"


def print_next_commands(
    status: str,
    run_root: Path,
    input_ortho: Path,
    *,
    stream: Any = sys.stdout,
) -> None:
    run_root = Path(run_root).resolve()
    input_ortho = Path(input_ortho).resolve()
    report_path = run_root / CHAIN_REPORT_FILENAME
    log_path = run_root / "level1b_chain.log"
    manifests_dir = run_root / "level1b" / "manifests"

    print("Next commands:", file=stream)
    print(f"  {shell_join(['jq', '.', str(report_path)])}", file=stream)
    print(f"  {shell_join(['tail', '-n', '80', str(log_path)])}", file=stream)

    if status == "level1b_dumb_chain_failed":
        print(f"  {shell_join(['ls', '-la', str(manifests_dir)])}", file=stream)
        return

    wrapper_name = (
        "run_level1b_dumb_with_user_header.ps1"
        if _is_windows()
        else "run_level1b_dumb_with_user_header.sh"
    )
    wrapper_path = Path(__file__).resolve().parent.parent / wrapper_name
    if wrapper_path.exists():
        if _is_windows():
            ps_quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            rerun_command = "; ".join(
                [
                    f"$env:ORTHO={ps_quote(input_ortho)}",
                    f"$env:RUN_ROOT={ps_quote(run_root)}",
                    "$env:OVERWRITE='1'",
                    "powershell -ExecutionPolicy Bypass -File "
                    + ps_quote(wrapper_path),
                ]
            )
        else:
            rerun_command = " ".join(
                [
                    f"ORTHO={shlex.quote(str(input_ortho))}",
                    f"RUN_ROOT={shlex.quote(str(run_root))}",
                    "OVERWRITE=1",
                    shell_join(["bash", str(wrapper_path)]),
                ]
            )
        print(f"  {rerun_command}", file=stream)
    else:
        print(
            "  # UNRESOLVED: wrapper script not found next to "
            "dumb_runner.py",
            file=stream,
        )
        direct_rerun_command = shell_join(
            [
                "python3",
                "-m",
                "metashape_qc_engine.level1b.dumb_runner",
                "--rgb-ortho",
                str(input_ortho),
                "--out-dir",
                str(run_root),
                "--overwrite",
            ]
        )
        print(f"  {direct_rerun_command}", file=stream)

    if status == "step9b_non_adjacent_choice_required":
        alternatives_path = (
            run_root
            / "level1b"
            / "local_transition_refinement"
            / "step9b_supported_scale_alternatives.json"
        )
        print(f"  {shell_join(['jq', '.', str(alternatives_path)])}", file=stream)
        return

    if status == "level1b_dumb_chain_complete":
        print(f"  REPORT={shlex.quote(str(report_path))}", file=stream)
        print(
            "  MATERIALIZE_MANIFEST=$(jq -r "
            "'.step_results.step10_materialize.manifest' \"$REPORT\")",
            file=stream,
        )
        print(
            "  jq -r '.artifacts.selected_labels_tif,\n"
            "       .artifacts.selected_segments_gpkg,\n"
            "       .artifacts.selected_segments_manifest_json' "
            "\"$MATERIALIZE_MANIFEST\"",
            file=stream,
        )
        print(
            "  QUALITY_MANIFEST=$(jq -r "
            "'.step_results.step10_quality.manifest' \"$REPORT\")",
            file=stream,
        )
        print(
            "  jq -r '.artifacts.selected_segment_exactextractr_stats_csv,\n"
            "       .artifacts.selected_segment_exactextractr_summary_json,\n"
            "       .artifacts.ortho_segmentation_quality_info_json' "
            "\"$QUALITY_MANIFEST\"",
            file=stream,
        )
        print(
            "  FIGURE_STEP_MANIFEST=$(jq -r "
            "'.step_results.step10_figures.manifest' \"$REPORT\")",
            file=stream,
        )
        print(
            "  FIGURE_MANIFEST=$(jq -r '.artifacts.figure_manifest_json' "
            "\"$FIGURE_STEP_MANIFEST\")",
            file=stream,
        )
        print('  jq . "$FIGURE_MANIFEST"', file=stream)


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
    print_next_commands(
        str(report["status"]),
        args.out_dir,
        args.rgb_ortho,
        stream=stream,
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
