from __future__ import annotations

import json
from pathlib import Path

import pytest

from metashape_qc_engine import level1b_dumb_runner as runner
from metashape_qc_engine.level1b_candidate_response_surface import (
    Level1BCandidateResponseSurfaceConfig,
)
from metashape_qc_engine.level1b_perturbations import Level1BPerturbationConfig
from metashape_qc_engine.level1b_scale_distribution import (
    Level1BScaleDistributionConfig,
)
from metashape_qc_engine.level1b_step_manifest import write_step_manifest


def _write(path: Path, value: object | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".json":
        path.write_text(json.dumps({} if value is None else value), encoding="utf-8")
    else:
        path.write_bytes(b"test")


def _install_stubs(
    monkeypatch: pytest.MonkeyPatch,
    output_dir: Path,
    *,
    branch: str = "adjacent",
    omit_step: str | None = None,
) -> tuple[list[str], dict[str, object]]:
    calls: list[str] = []
    captured: dict[str, object] = {}
    level1b = output_dir / "level1b"
    monkeypatch.setattr(runner, "_pixel_size_m", lambda path: 0.25)

    def manifest(step, status, artifacts):
        write_step_manifest(
            output_dir,
            step=step,
            status=status,
            inputs={},
            artifacts=artifacts,
            candidate_id="test-candidate",
        )

    def preflight(config):
        calls.append("preflight")
        captured["preflight"] = config
        report = level1b / "reports" / "preflight.json"
        _write(report, {"status": "ok"})
        manifest("preflight", "ok", {"preflight_report": report})
        return {"status": "ok"}

    def valid_mask(config):
        calls.append("valid_mask")
        captured["valid_mask"] = config
        if omit_step != "valid_mask":
            _write(level1b / "mask" / "valid_mask.tif")
        report = level1b / "mask" / "valid_mask_report.json"
        _write(report)
        manifest(
            "valid_mask",
            "ok",
            {
                "valid_mask": level1b / "mask" / "valid_mask.tif",
                "report": report,
            },
        )
        return {"status": "ok"}

    def channels(config):
        calls.append("channels")
        captured["channels"] = config
        _write(level1b / "channels" / "proxy_stack.tif")
        _write(level1b / "channels" / "channel_report.json")
        manifest(
            "channels",
            "ok",
            {
                "proxy_stack": level1b / "channels" / "proxy_stack.tif",
                "report": level1b / "channels" / "channel_report.json",
            },
        )
        return {"status": "ok"}

    def scaling(config):
        calls.append("scaling")
        captured["scaling"] = config
        _write(level1b / "scaling" / "scaled_feature_stack.tif")
        _write(level1b / "scaling" / "scaling_report.json")
        manifest(
            "scaling",
            "ok",
            {
                "scaled_feature_stack": level1b
                / "scaling"
                / "scaled_feature_stack.tif",
                "report": level1b / "scaling" / "scaling_report.json",
            },
        )
        return {"status": "ok"}

    def scale_distribution(config):
        calls.append("scale_distribution")
        captured["scale_distribution"] = config
        _write(level1b / "scales" / "scale_candidates.json", {"candidates": [{}]})
        manifest(
            "scale_distribution",
            "ok",
            {
                "scale_candidates_json": level1b
                / "scales"
                / "scale_candidates.json"
            },
        )
        return {"status": "ok"}

    def feature_range(config):
        calls.append("feature_range")
        captured["feature_range"] = config
        _write(
            level1b / "ranger" / "scale_candidates_with_ranger.json",
            {"candidates": [{}]},
        )
        manifest(
            "feature_range",
            "ok",
            {
                "scale_candidates_with_ranger_json": level1b
                / "ranger"
                / "scale_candidates_with_ranger.json"
            },
        )
        return {"status": "ok"}

    def perturbations(config):
        calls.append("perturbations")
        captured["perturbations"] = config
        _write(
            level1b / "perturbations" / "perturbation_candidates.json",
            {"candidates": [{}]},
        )
        manifest(
            "perturbations",
            "ok",
            {
                "perturbation_candidates_json": level1b
                / "perturbations"
                / "perturbation_candidates.json"
            },
        )
        return {"status": "ok"}

    def step9a(config):
        calls.append("step9a")
        captured["step9a"] = config
        surface = level1b / "candidate_response_surface"
        _write(surface / "run_population_summary.json", [])
        _write(surface / "candidate_group_response_summary.json", [])
        _write(surface / "candidate_response_surface_report.json")
        manifest(
            "candidate_response_surface",
            "ok",
            {
                "run_population_json": surface / "run_population_summary.json",
                "group_json": surface / "candidate_group_response_summary.json",
                "report": surface / "candidate_response_surface_report.json",
            },
        )
        return {"status": "ok", "large_embedded_report": "must-not-be-copied"}

    def step9b_prepare(*, run_root, candidate_id, perturbation_config):
        calls.append("step9b_prepare")
        captured["step9b_prepare"] = {
            "run_root": run_root,
            "candidate_id": candidate_id,
            "perturbation_config": perturbation_config,
        }
        status = {
            "adjacent": "step9b_midpoint_probe_ready",
            "non_adjacent": "step9b_user_choice_required_bimodal_or_multimodal",
            "blocked": "step9b_blocked_cannot_determine_scale_continuity",
        }[branch]
        prepared = level1b / "step9b_prepare_inputs"
        local = level1b / "local_transition_refinement"
        ranked_view = prepared / "ranked_candidate_scales_view.json"
        domain_manifest = prepared / "step9b_prepare_manifest.json"
        prepare_artifacts = {
            "step9b_prepare_manifest_json": domain_manifest,
            "ranked_candidate_scales_view_json": ranked_view,
            "step9b_interval_preflight_json": local
            / "step9b_interval_preflight.json",
        }
        branch_artifacts = {
            "step9b_interval_preflight_json": str(
                local / "step9b_interval_preflight.json"
            )
        }
        _write(local / "step9b_interval_preflight.json", {"step9b_status": status})
        if branch == "adjacent":
            _write(local / "step9b_midpoint_probe_candidate.json")
            _write(local / "step9b_midpoint_perturbation_candidates.json", [])
            prepare_artifacts.update(
                {
                    "midpoint_probe_candidate_json": local
                    / "step9b_midpoint_probe_candidate.json",
                    "midpoint_perturbation_candidates_json": local
                    / "step9b_midpoint_perturbation_candidates.json",
                }
            )
            branch_artifacts.update(
                {
                    "midpoint_probe_candidate_json": str(
                        local / "step9b_midpoint_probe_candidate.json"
                    ),
                    "midpoint_perturbation_candidates_json": str(
                        local / "step9b_midpoint_perturbation_candidates.json"
                    ),
                }
            )
        elif branch == "non_adjacent":
            _write(local / "step9b_supported_scale_alternatives.json", [])
            prepare_artifacts["supported_scale_alternatives_json"] = (
                local / "step9b_supported_scale_alternatives.json"
            )
            branch_artifacts["supported_scale_alternatives_json"] = str(
                local / "step9b_supported_scale_alternatives.json"
            )
        if omit_step != "step9b_prepare":
            _write(ranked_view, [])
            _write(
                domain_manifest,
                {
                    "schema": "level1b_step9b_prepare_manifest",
                    "schema_version": 1,
                    "status": status,
                    "source_step9a_directory": str(
                        level1b / "candidate_response_surface"
                    ),
                    "source_artifacts": {},
                    "ranked_candidate_scales_json": str(ranked_view),
                    "gate_metadata": {},
                    "produced_branch_artifacts": branch_artifacts,
                },
            )
            manifest("step9b_prepare", status, prepare_artifacts)
        return {
            "status": None,
            "step9b_prepare_manifest_json": str(domain_manifest),
            "ranked_candidate_scales_view_json": str(ranked_view),
            "step9b_result": {"step9b_status": status},
        }

    def midpoint_handoff(
        *,
        run_root,
        candidate_id,
        candidate_response_surface_config,
        step9b_prepare_manifest_path,
    ):
        calls.append("step9b_midpoint_handoff")
        captured["step9b_midpoint_handoff"] = {
            "run_root": run_root,
            "candidate_id": candidate_id,
            "candidate_response_surface_config": candidate_response_surface_config,
            "step9b_prepare_manifest_path": step9b_prepare_manifest_path,
        }
        local = level1b / "local_transition_refinement"
        nested = (
            local
            / "midpoint_response_surface_eval"
            / "level1b"
            / "candidate_response_surface"
        )
        _write(nested / "run_population_summary.json", [])
        _write(nested / "candidate_group_response_summary.json", [])
        _write(
            local / "step9b_midpoint_gain_share_handoff.json",
            {
                "no1_candidate_scale_group_id": "no1",
                "no2_candidate_scale_group_id": "no2",
                "midpoint_candidate_id": "local_midpoint",
                "handoff_candidate_id": "local_midpoint",
            },
        )
        _write(nested / "candidate_response_surface_report.json")
        _write(nested / "ranked_candidate_scales.json", [])
        manifest(
            "step9b_midpoint_handoff",
            "step9b_midpoint_response_surface_and_handoff_ready",
            {
                "midpoint_run_population_summary_json": nested
                / "run_population_summary.json",
                "midpoint_candidate_group_response_summary_json": nested
                / "candidate_group_response_summary.json",
                "midpoint_ranked_candidate_scales_json": nested
                / "ranked_candidate_scales.json",
                "midpoint_candidate_response_surface_report_json": nested
                / "candidate_response_surface_report.json",
                "step9b_midpoint_gain_share_handoff_json": local
                / "step9b_midpoint_gain_share_handoff.json",
            },
        )
        return {"status": "step9b_midpoint_response_surface_and_handoff_ready"}

    def collect(path):
        calls.append("step10_collect")
        assert Path(path) == output_dir
        evidence = level1b / "step10_materialization" / "decision_evidence"
        _write(evidence / "finalist_evidence.json", {})
        manifest(
            "step10_collect",
            "step10_part1_finalist_evidence_collected",
            {
                "finalist_evidence_json": evidence / "finalist_evidence.json",
            },
        )
        return {"status": "step10_part1_finalist_evidence_collected"}

    def aggregate(path):
        calls.append("step10_aggregate")
        assert Path(path) == output_dir
        evidence = level1b / "step10_materialization" / "decision_evidence"
        _write(evidence / "finalist_evidence.json", {})
        manifest(
            "step10_aggregate",
            "step10_part2_finalist_evidence_aggregated",
            {
                "finalist_evidence_json": evidence / "finalist_evidence.json",
            },
        )
        return {"status": "step10_part2_finalist_evidence_aggregated"}

    def figures(path):
        calls.append("step10_figures")
        assert Path(path) == output_dir
        figure_manifest = (
            level1b
            / "step10_materialization"
            / "figures"
            / "step10_figure_manifest.json"
        )
        _write(figure_manifest)
        manifest(
            "step10_figures",
            "step10_part3_figures_created",
            {"figure_manifest_json": figure_manifest},
        )
        return {"status": "step10_part3_figures_created"}

    def materialize(path):
        calls.append("step10_materialize")
        assert Path(path) == output_dir
        final = level1b / "step10_materialization" / "final_segments"
        _write(final / "selected_segments_manifest.json")
        _write(final / "selected_segments.gpkg")
        _write(final / "selected_labels.tif")
        manifest(
            "step10_materialize",
            "step10_part4_selected_segments_materialized",
            {
                "selected_segments_manifest_json": final
                / "selected_segments_manifest.json",
                "selected_segments_gpkg": final / "selected_segments.gpkg",
                "selected_labels_tif": final / "selected_labels.tif",
            },
        )
        return {"status": "step10_part4_selected_segments_materialized"}

    def quality(path):
        calls.append("step10_quality")
        assert Path(path) == output_dir
        step10 = level1b / "step10_materialization"
        _write(
            step10 / "segment_stats" / "selected_segment_exactextractr_stats.csv"
        )
        _write(
            step10 / "segment_stats" / "selected_segment_exactextractr_summary.json"
        )
        _write(step10 / "quality" / "ortho_segmentation_quality_info.json")
        manifest(
            "step10_quality",
            "step10_part5_exactextractr_segment_stats_and_quality_info_ready",
            {
                "selected_segment_exactextractr_stats_csv": step10
                / "segment_stats"
                / "selected_segment_exactextractr_stats.csv",
                "selected_segment_exactextractr_summary_json": step10
                / "segment_stats"
                / "selected_segment_exactextractr_summary.json",
                "ortho_segmentation_quality_info_json": step10
                / "quality"
                / "ortho_segmentation_quality_info.json",
            },
        )
        return {
            "status": "step10_part5_exactextractr_segment_stats_and_quality_info_ready"
        }

    monkeypatch.setattr(runner, "run_preflight", preflight)
    monkeypatch.setattr(runner, "run_valid_mask_step", valid_mask)
    monkeypatch.setattr(runner, "run_channel_construction_step", channels)
    monkeypatch.setattr(runner, "run_scaling_step", scaling)
    monkeypatch.setattr(runner, "run_scale_distribution_step", scale_distribution)
    monkeypatch.setattr(runner, "run_feature_range_assignment_step", feature_range)
    monkeypatch.setattr(runner, "run_local_perturbation_step", perturbations)
    monkeypatch.setattr(runner, "run_candidate_response_surface_step", step9a)
    monkeypatch.setattr(
        runner, "run_step9b_prepare_from_existing_step9a", step9b_prepare
    )
    monkeypatch.setattr(
        runner,
        "run_step9b_midpoint_response_surface_and_handoff_from_prepare",
        midpoint_handoff,
    )
    monkeypatch.setattr(
        runner, "run_level1b_step10_collect_finalist_evidence", collect
    )
    monkeypatch.setattr(
        runner, "run_level1b_step10_aggregate_finalist_evidence", aggregate
    )
    monkeypatch.setattr(runner, "run_level1b_step10_make_finalist_figures", figures)
    monkeypatch.setattr(
        runner, "run_level1b_step10_materialize_selected_segments", materialize
    )
    monkeypatch.setattr(
        runner,
        "run_level1b_step10_compute_exactextractr_segment_stats_and_quality_info",
        quality,
    )
    return calls, captured


def test_candidate_id_is_deterministic_and_human_readable() -> None:
    first = runner._candidate_id(Path("/tmp/My Ortho.tif"))
    second = runner._candidate_id(Path("/tmp/My Ortho.tif"))
    assert first == second
    assert first == "My_Ortho__structure_scales"


def test_adjacent_chain_uses_real_primary_structure_scale_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "run"
    calls, captured = _install_stubs(monkeypatch, output_dir, branch="adjacent")

    result = runner.run_level1b_dumb_chain(Path("/tmp/ortho.tif"), output_dir)

    assert calls == [
        "preflight",
        "valid_mask",
        "channels",
        "scaling",
        "scale_distribution",
        "feature_range",
        "perturbations",
        "step9a",
        "step9b_prepare",
        "step9b_midpoint_handoff",
        "step10_collect",
        "step10_aggregate",
        "step10_figures",
        "step10_materialize",
        "step10_quality",
    ]
    scale_config = captured["scale_distribution"]
    assert isinstance(scale_config, Level1BScaleDistributionConfig)
    assert scale_config.scale_mode == "structure_derived_scale_distribution"
    assert scale_config.metric_radius_m is None
    assert scale_config.proxy_stack_path == (
        output_dir / "level1b" / "channels" / "proxy_stack.tif"
    )
    assert scale_config.channel_report_path == (
        output_dir / "level1b" / "channels" / "channel_report.json"
    )

    step9a_config = captured["step9a"]
    assert isinstance(step9a_config, Level1BCandidateResponseSurfaceConfig)
    assert step9a_config.perturbation_candidates_json_path == (
        output_dir / "level1b" / "perturbations" / "perturbation_candidates.json"
    )
    prepare = captured["step9b_prepare"]
    assert prepare["run_root"] == output_dir
    assert prepare["candidate_id"] == result["candidate_id"]
    assert isinstance(prepare["perturbation_config"], Level1BPerturbationConfig)
    connector = captured["step9b_midpoint_handoff"]
    assert connector["candidate_response_surface_config"] is step9a_config
    assert connector["step9b_prepare_manifest_path"] == (
        output_dir
        / "level1b"
        / "step9b_prepare_inputs"
        / "step9b_prepare_manifest.json"
    )
    assert result["artifacts"]["step9b_prepare_manifest"] == str(
        connector["step9b_prepare_manifest_path"]
    )
    assert result["artifacts"]["step10_evidence"] == str(
        output_dir
        / "level1b"
        / "step10_materialization"
        / "decision_evidence"
        / "finalist_evidence.json"
    )
    assert result["status"] == "level1b_dumb_chain_complete"
    assert result["step_results"]["step9a"] == {
        "status": "ok",
        "manifest": str(
            output_dir
            / "level1b"
            / "manifests"
            / "candidate_response_surface.json"
        ),
    }
    assert all(
        set(step_result) == {"status", "manifest"}
        for step_result in result["step_results"].values()
    )


def test_runner_consumes_exact_manifest_artifact_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "run"
    calls, captured = _install_stubs(monkeypatch, output_dir, branch="adjacent")
    manifest_mask = output_dir / "level1b" / "manifest_owned" / "mask.tif"
    legacy_mask = output_dir / "level1b" / "mask" / "valid_mask.tif"

    def valid_mask(config):
        calls.append("valid_mask")
        captured["valid_mask"] = config
        _write(manifest_mask)
        _write(legacy_mask)
        report = output_dir / "level1b" / "mask" / "valid_mask_report.json"
        _write(report)
        write_step_manifest(
            output_dir,
            step="valid_mask",
            status="ok",
            inputs={},
            artifacts={"valid_mask": manifest_mask, "report": report},
            candidate_id="test-candidate",
        )
        return {"status": "ok"}

    monkeypatch.setattr(runner, "run_valid_mask_step", valid_mask)

    runner.run_level1b_dumb_chain(Path("/tmp/ortho.tif"), output_dir)

    assert captured["channels"].valid_mask_path == manifest_mask


def test_non_adjacent_artifact_branch_stops_before_midpoint_and_step10(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "run"
    calls, _ = _install_stubs(monkeypatch, output_dir, branch="non_adjacent")

    result = runner.run_level1b_dumb_chain(Path("/tmp/ortho.tif"), output_dir)

    assert result["status"] == "step9b_non_adjacent_choice_required"
    assert result["branch"] == "non_adjacent"
    assert result["supported_scale_alternatives_json"].endswith(
        "step9b_supported_scale_alternatives.json"
    )
    assert "step9b_midpoint_handoff" not in calls
    assert not any(call.startswith("step10_") for call in calls)


def test_missing_step9b_branch_artifacts_fail_fast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "run"
    _install_stubs(monkeypatch, output_dir, branch="blocked")

    with pytest.raises(RuntimeError, match="step9b_branch"):
        runner.run_level1b_dumb_chain(Path("/tmp/ortho.tif"), output_dir)


def test_missing_artifact_fails_with_step_and_exact_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "run"
    _install_stubs(monkeypatch, output_dir, omit_step="valid_mask")
    expected = output_dir / "level1b" / "mask" / "valid_mask.tif"

    with pytest.raises(RuntimeError) as exc_info:
        runner.run_level1b_dumb_chain(Path("/tmp/ortho.tif"), output_dir)

    assert "valid_mask" in str(exc_info.value)
    assert str(expected) in str(exc_info.value)


def test_existing_output_is_refused_before_metadata_or_processing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "run"
    (output_dir / "level1b").mkdir(parents=True)
    monkeypatch.setattr(
        runner,
        "_pixel_size_m",
        lambda path: pytest.fail("pixel metadata must not be read"),
    )
    monkeypatch.setattr(
        runner,
        "run_preflight",
        lambda config: pytest.fail("preflight must not run"),
    )

    with pytest.raises(RuntimeError, match="output directory already exists"):
        runner.run_level1b_dumb_chain(Path("/tmp/ortho.tif"), output_dir)


def test_manual_prepare_directory_is_not_a_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "run"
    manual = output_dir / "level1b" / "manual_step9b_inputs"
    _write(manual / "run_population_summary.json", [])
    _write(manual / "ranked_candidate_scales.json", [])
    _write(manual / "candidate_response_surface_report.json")
    _install_stubs(monkeypatch, output_dir, omit_step="step9b_prepare")

    with pytest.raises(RuntimeError) as exc_info:
        runner.run_level1b_dumb_chain(
            Path("/tmp/ortho.tif"), output_dir, overwrite=True
        )

    assert "manifests/step9b_prepare.json" in str(exc_info.value)
    assert str(manual) not in str(exc_info.value)


def test_cli_writes_one_compact_report_without_dumping_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "run"
    chain_result = {
        "status": "level1b_dumb_chain_complete",
        "candidate_id": "candidate",
        "output_dir": str(output_dir),
        "branch": "adjacent_midpoint",
        "artifacts": {"step10_quality": "/quality.json"},
        "step_results": {
            "preflight": {
                "status": "ok",
                "manifest": "/manifests/preflight.json",
            }
        },
    }
    monkeypatch.setattr(
        runner,
        "run_level1b_dumb_chain",
        lambda **kwargs: chain_result,
    )

    exit_code = runner.main(
        ["--rgb-ortho", "/tmp/ortho.tif", "--out-dir", str(output_dir)]
    )

    report_path = (
        output_dir / "level1b_dumb_chain_report.json"
    )
    assert exit_code == 0
    assert json.loads(report_path.read_text(encoding="utf-8")) == chain_result
    captured = capsys.readouterr()
    assert captured.out.strip() == (
        f"level1b_dumb_chain_complete report={report_path}"
    )
    assert captured.err == ""
    assert "step_results" not in captured.out


def test_cli_writes_same_report_path_for_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "run"

    def fail(**kwargs):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(runner, "run_level1b_dumb_chain", fail)

    exit_code = runner.main(
        ["--rgb-ortho", "/tmp/ortho.tif", "--out-dir", str(output_dir)]
    )

    report_path = (
        output_dir / "level1b_dumb_chain_report.json"
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert not (output_dir / "level1b").exists()
    assert exit_code == 1
    assert report == {
        "status": "level1b_dumb_chain_failed",
        "output_dir": str(output_dir),
        "error_type": "RuntimeError",
        "error": "synthetic failure",
    }
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == (
        f"level1b_dumb_chain_failed report={report_path}"
    )
