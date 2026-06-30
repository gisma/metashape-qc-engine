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

    def preflight(config):
        calls.append("preflight")
        captured["preflight"] = config
        _write(level1b / "reports" / "preflight.json", {"status": "ok"})
        return {"status": "ok"}

    def valid_mask(config):
        calls.append("valid_mask")
        captured["valid_mask"] = config
        if omit_step != "valid_mask":
            _write(level1b / "mask" / "valid_mask.tif")
        return {"status": "ok"}

    def channels(config):
        calls.append("channels")
        captured["channels"] = config
        _write(level1b / "channels" / "proxy_stack.tif")
        _write(level1b / "channels" / "channel_report.json")
        return {"status": "ok"}

    def scaling(config):
        calls.append("scaling")
        captured["scaling"] = config
        _write(level1b / "scaling" / "scaled_feature_stack.tif")
        return {"status": "ok"}

    def scale_distribution(config):
        calls.append("scale_distribution")
        captured["scale_distribution"] = config
        _write(level1b / "scales" / "scale_candidates.json", {"candidates": [{}]})
        return {"status": "ok"}

    def feature_range(config):
        calls.append("feature_range")
        captured["feature_range"] = config
        _write(
            level1b / "ranger" / "scale_candidates_with_ranger.json",
            {"candidates": [{}]},
        )
        return {"status": "ok"}

    def perturbations(config):
        calls.append("perturbations")
        captured["perturbations"] = config
        _write(
            level1b / "perturbations" / "perturbation_candidates.json",
            {"candidates": [{}]},
        )
        return {"status": "ok"}

    def step9a(config):
        calls.append("step9a")
        captured["step9a"] = config
        surface = level1b / "candidate_response_surface"
        _write(surface / "run_population_summary.json", [])
        _write(surface / "candidate_group_response_summary.json", [])
        _write(surface / "candidate_response_surface_report.json")
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
        if omit_step != "step9b_prepare":
            _write(prepared / "run_population_summary.json", [])
            _write(prepared / "ranked_candidate_scales.json", [])
            _write(prepared / "candidate_response_surface_report.json")
            _write(prepared / "step9b_prepare_result.json", {"step9b_status": status})

        local = level1b / "local_transition_refinement"
        if branch == "adjacent":
            _write(local / "step9b_midpoint_probe_candidate.json")
            _write(local / "step9b_midpoint_perturbation_candidates.json", [])
        elif branch == "non_adjacent":
            _write(local / "step9b_supported_scale_alternatives.json", [])
        return {"status": None, "step9b_result": {"step9b_status": status}}

    def midpoint_handoff(
        *, run_root, candidate_id, candidate_response_surface_config
    ):
        calls.append("step9b_midpoint_handoff")
        captured["step9b_midpoint_handoff"] = {
            "run_root": run_root,
            "candidate_id": candidate_id,
            "candidate_response_surface_config": candidate_response_surface_config,
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
        return {"status": "step9b_midpoint_response_surface_and_handoff_ready"}

    def collect(path):
        calls.append("step10_collect")
        assert Path(path) == output_dir
        evidence = level1b / "step10_materialization" / "decision_evidence"
        _write(evidence / "finalist_group_summary.json", [])
        _write(evidence / "finalist_perturbation_runs.json", [])
        return {"status": "step10_part1_finalist_evidence_collected"}

    def aggregate(path):
        calls.append("step10_aggregate")
        assert Path(path) == output_dir
        evidence = level1b / "step10_materialization" / "decision_evidence"
        _write(evidence / "finalist_group_aggregation.json", [])
        _write(evidence / "finalist_numeric_distribution_summary.json", [])
        return {"status": "step10_part2_finalist_evidence_aggregated"}

    def figures(path):
        calls.append("step10_figures")
        assert Path(path) == output_dir
        _write(
            level1b
            / "step10_materialization"
            / "figures"
            / "step10_figure_manifest.json"
        )
        return {"status": "step10_part3_figures_created"}

    def materialize(path):
        calls.append("step10_materialize")
        assert Path(path) == output_dir
        final = level1b / "step10_materialization" / "final_segments"
        _write(final / "selected_segments_manifest.json")
        _write(final / "selected_segments.gpkg")
        _write(final / "selected_labels.tif")
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
    assert result["status"] == "level1b_dumb_chain_complete"
    assert result["step_results"]["step9a"] == {
        "status": "ok",
        "artifacts": {
            "run_population": str(
                output_dir
                / "level1b"
                / "candidate_response_surface"
                / "run_population_summary.json"
            ),
            "candidate_group_summary": str(
                output_dir
                / "level1b"
                / "candidate_response_surface"
                / "candidate_group_response_summary.json"
            ),
            "report": str(
                output_dir
                / "level1b"
                / "candidate_response_surface"
                / "candidate_response_surface_report.json"
            ),
        },
    }
    assert all(
        set(step_result).issubset({"status", "step9b_status", "artifacts"})
        for step_result in result["step_results"].values()
    )


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

    assert "step9b_prepare_inputs" in str(exc_info.value)
    assert str(manual) not in str(exc_info.value)
