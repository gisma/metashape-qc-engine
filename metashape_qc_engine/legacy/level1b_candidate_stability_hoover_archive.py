"""Legacy/audit Hoover-based Level-1b Step 9 implementation.

This module preserves the former candidate-stability implementation for audit
and reproducibility. It is not the active Level-1b Step 9 path; the active
candidate-scale response surface analysis lives in
metashape_qc_engine.level1b_candidate_response_surface.
"""

from dataclasses import dataclass, fields
import csv
import json
import math
from pathlib import Path
import statistics

from metashape_qc_engine.level1b_hoover_compare import Level1BHooverCompareConfig, run_hoover_compare
from metashape_qc_engine.level1b_one_scale_segmentation import (
    Level1BOneScaleSegmentationConfig,
    run_one_scale_segmentation_smoke,
)


RASTER_SUFFIXES = {".tif", ".tiff", ".vrt", ".img", ".jp2"}
REQUIRED_ROW_FIELDS = (
    "perturbation_id",
    "source_candidate_id",
    "scale_id",
    "spatialr_px",
    "minsize_px",
    "ranger",
    "is_baseline",
)
BASELINE_SUMMARY_FIELDS = (
    "radius_m",
    "area_m2",
    "spatialr_px",
    "minsize_px",
    "ranger",
    "ranger_id",
    "ranger_source",
    "assignment_rule",
    "perturbation_rule",
)
PASSTHROUGH_FIELDS = (*BASELINE_SUMMARY_FIELDS, "deltas")
SUMMARY_BASE_FIELDS = (
    "source_candidate_id",
    "scale_id",
    "candidate_status",
    "baseline_perturbation_id",
    "perturbation_count",
    "successful_perturbation_count",
    "failed_perturbation_count",
    "baseline_merged_labels_path",
    "candidate_report_path",
)
NO_OUTPUT_FLAGS = {
    "no_final_scale_selection": True,
    "no_stable_region_analysis": True,
    "no_vector_output": True,
    "no_lsms_vectorization": True,
    "no_final_output": True,
}


@dataclass
class Level1BCandidateStabilityConfig:
    candidate_id: str
    output_dir: str | Path
    perturbation_candidates_json_path: str | Path
    feature_space_stack_path: str | Path
    otb_bin_dir: str | Path | None = None
    ram_mb: int = 4096
    overwrite: bool = False
    dry_run: bool = False


def build_level1b_candidate_stability_layout(output_dir) -> dict[str, Path]:
    stability_dir = Path(output_dir) / "level1b" / "stability"
    return {
        "stability_dir": stability_dir,
        "scale_stability_csv_path": stability_dir / "scale_stability.csv",
        "scale_stability_json_path": stability_dir / "scale_stability.json",
    }


def read_perturbation_candidates(json_path) -> list[dict[str, object]]:
    with Path(json_path).open(encoding="utf-8") as file_obj:
        payload = json.load(file_obj)
    if "candidates" not in payload:
        raise ValueError("candidates key is missing")
    if not payload["candidates"]:
        raise ValueError("candidates is empty")
    return list(payload["candidates"])


def validate_candidate_stability_config(config: Level1BCandidateStabilityConfig) -> tuple[list[dict[str, object]], list[str]]:
    failure_reasons: list[str] = []
    candidate_path = Path(config.perturbation_candidates_json_path) if config.perturbation_candidates_json_path else None
    feature_path = Path(config.feature_space_stack_path) if config.feature_space_stack_path else None
    output_dir = Path(config.output_dir) if config.output_dir else None

    if candidate_path is None:
        failure_reasons.append("perturbation_candidates_json_path is missing")
    else:
        if candidate_path.suffix.lower() != ".json":
            failure_reasons.append("perturbation_candidates_json_path suffix must be .json")
        if not candidate_path.exists():
            failure_reasons.append("perturbation_candidates_json_path does not exist")

    if feature_path is None:
        failure_reasons.append("feature_space_stack_path is missing")
    else:
        if feature_path.suffix.lower() not in RASTER_SUFFIXES:
            failure_reasons.append("feature_space_stack_path suffix must be raster-like")
        if not feature_path.exists():
            failure_reasons.append("feature_space_stack_path does not exist")

    if output_dir is None or not str(output_dir).strip():
        failure_reasons.append("output_dir is missing")
    if not _positive_int(config.ram_mb):
        failure_reasons.append("ram_mb must be a positive integer")

    candidates: list[dict[str, object]] = []
    if not failure_reasons and candidate_path is not None:
        try:
            candidates = read_perturbation_candidates(candidate_path)
            _validate_rows(candidates)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            failure_reasons.append(str(exc))

    if output_dir is not None and not config.overwrite:
        layout = build_level1b_candidate_stability_layout(output_dir)
        collisions = [
            str(path)
            for path in (layout["scale_stability_csv_path"], layout["scale_stability_json_path"])
            if path.exists()
        ]
        for row in candidates:
            candidate_report_path = layout["stability_dir"] / str(row["source_candidate_id"]) / "candidate_stability_report.json"
            if candidate_report_path.exists():
                collisions.append(str(candidate_report_path))
        if collisions:
            failure_reasons.append("output artifacts already exist and overwrite is false: " + ", ".join(collisions))

    return candidates, failure_reasons


def group_perturbation_candidates(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in rows:
        key = (str(row["source_candidate_id"]), str(row["scale_id"]))
        grouped.setdefault(key, []).append(row)

    groups: list[dict[str, object]] = []
    for key in sorted(grouped):
        rows_for_group = sorted(grouped[key], key=lambda item: str(item["perturbation_id"]))
        baselines = [row for row in rows_for_group if bool(row["is_baseline"])]
        if len(baselines) != 1:
            label = "without exactly one baseline row" if len(baselines) == 0 else "with multiple baseline rows"
            raise ValueError(f"group {key[0]} {key[1]} {label}")
        baseline = baselines[0]
        perturbations = [row for row in rows_for_group if row is not baseline]
        groups.append(
            {
                "source_candidate_id": key[0],
                "scale_id": key[1],
                "baseline": baseline,
                "perturbations": perturbations,
            }
        )
    return groups


def run_candidate_stability(config: Level1BCandidateStabilityConfig) -> dict[str, object]:
    layout = build_level1b_candidate_stability_layout(config.output_dir)
    rows, validation_reasons = validate_candidate_stability_config(config)
    if validation_reasons:
        return _top_report(config, layout, len(rows), 0, [], validation_reasons)

    try:
        groups = group_perturbation_candidates(rows)
    except ValueError as exc:
        return _top_report(config, layout, len(rows), 0, [], [str(exc)])

    if config.dry_run:
        summaries = [_dry_run_group_summary(config, layout, group) for group in groups]
        return _write_top_outputs(config, layout, rows, groups, summaries)

    layout["stability_dir"].mkdir(parents=True, exist_ok=True)
    summaries = [_run_group(config, layout, group) for group in groups]
    return _write_top_outputs(config, layout, rows, groups, summaries)


def _validate_rows(rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError("perturbation table is empty")
    seen_ids: set[str] = set()
    for row in rows:
        for field in REQUIRED_ROW_FIELDS:
            if field not in row:
                raise ValueError(f"row field {field} is missing")
        perturbation_id = str(row["perturbation_id"])
        if perturbation_id in seen_ids:
            raise ValueError("duplicate perturbation_id")
        seen_ids.add(perturbation_id)
        _positive_int_field(row["spatialr_px"], "spatialr_px")
        _positive_int_field(row["minsize_px"], "minsize_px")
        _positive_float_field(row["ranger"], "ranger")
    group_perturbation_candidates(rows)


def _run_group(config: Level1BCandidateStabilityConfig, layout: dict[str, Path], group: dict[str, object]) -> dict[str, object]:
    source_candidate_id = str(group["source_candidate_id"])
    scale_id = str(group["scale_id"])
    group_dir = layout["stability_dir"] / source_candidate_id
    baseline_row = dict(group["baseline"])
    perturbation_rows = [dict(row) for row in group["perturbations"]]
    segmentation_runs: list[dict[str, object]] = []
    hoover_runs: list[dict[str, object]] = []

    baseline_run = _run_segmentation(config, group_dir / "baseline", source_candidate_id, baseline_row)
    segmentation_runs.append(baseline_run)
    baseline_status = str(baseline_run["status"])
    baseline_labels = _merged_labels_path(baseline_run.get("report", {}))

    if baseline_status not in ("ok", "dry_run"):
        report = _candidate_report(
            group_dir,
            source_candidate_id,
            scale_id,
            baseline_row,
            perturbation_rows,
            segmentation_runs,
            hoover_runs,
            "failed",
        )
        return _summary_from_report(report, baseline_row)

    for row in perturbation_rows:
        perturbation_id = str(row["perturbation_id"])
        perturbation_run = _run_segmentation(config, group_dir / perturbation_id, source_candidate_id, row)
        segmentation_runs.append(perturbation_run)
        if perturbation_run["status"] not in ("ok", "dry_run"):
            continue
        perturbation_labels = _merged_labels_path(perturbation_run.get("report", {}))
        if not baseline_labels or not perturbation_labels:
            hoover_runs.append(
                {
                    "perturbation_id": perturbation_id,
                    "comparison_id": _comparison_id(source_candidate_id, perturbation_id),
                    "status": "failed",
                    "failure_reasons": ["merged_labels path missing from segmentation report"],
                    "report": {},
                }
            )
            continue
        hoover_runs.append(
            _run_hoover(config, group_dir / perturbation_id / "hoover", source_candidate_id, perturbation_id, baseline_labels, perturbation_labels)
        )

    candidate_status = "ok"
    if any(run["status"] not in ("ok", "dry_run") for run in segmentation_runs[1:]):
        candidate_status = "partial"
    if any(run["status"] not in ("ok", "dry_run") for run in hoover_runs):
        candidate_status = "partial"

    report = _candidate_report(
        group_dir,
        source_candidate_id,
        scale_id,
        baseline_row,
        perturbation_rows,
        segmentation_runs,
        hoover_runs,
        candidate_status,
    )
    return _summary_from_report(report, baseline_row)


def _run_segmentation(
    config: Level1BCandidateStabilityConfig,
    output_dir: Path,
    source_candidate_id: str,
    row: dict[str, object],
) -> dict[str, object]:
    perturbation_id = str(row["perturbation_id"])
    kwargs = {
        "candidate_id": source_candidate_id,
        "output_dir": output_dir,
        "feature_space_stack_path": config.feature_space_stack_path,
        "perturbation_candidates_json_path": config.perturbation_candidates_json_path,
        "perturbation_id": perturbation_id,
        "otb_bin_dir": config.otb_bin_dir,
        "ram_mb": config.ram_mb,
        "overwrite": config.overwrite,
        "dry_run": config.dry_run,
    }
    allowed = {field.name for field in fields(Level1BOneScaleSegmentationConfig)}
    segmentation_config = Level1BOneScaleSegmentationConfig(**{key: value for key, value in kwargs.items() if key in allowed})
    try:
        report = run_one_scale_segmentation_smoke(segmentation_config)
        status = str(report.get("status", "unknown"))
        failure_reasons = list(report.get("failure_reasons", []))
    except Exception as exc:  # noqa: BLE001 - orchestration reports helper failures per perturbation.
        report = {}
        status = "failed"
        failure_reasons = [str(exc)]
    return {
        "perturbation_id": perturbation_id,
        "is_baseline": bool(row["is_baseline"]),
        "status": status,
        "output_dir": str(output_dir),
        "report_path": _segmentation_report_path(report),
        "merged_labels_path": _merged_labels_path(report),
        "failure_reasons": failure_reasons,
        "config": _public_config(segmentation_config),
        "report": report,
    }


def _run_hoover(
    config: Level1BCandidateStabilityConfig,
    output_dir: Path,
    source_candidate_id: str,
    perturbation_id: str,
    baseline_labels_path: str,
    perturbation_labels_path: str,
) -> dict[str, object]:
    comparison_id = _comparison_id(source_candidate_id, perturbation_id)
    hoover_config = Level1BHooverCompareConfig(
        candidate_id=source_candidate_id,
        comparison_id=comparison_id,
        baseline_labels_path=baseline_labels_path,
        perturbation_labels_path=perturbation_labels_path,
        output_dir=output_dir,
        otb_bin_dir=config.otb_bin_dir,
        ram_mb=config.ram_mb,
        overwrite=config.overwrite,
        dry_run=config.dry_run,
    )
    try:
        report = run_hoover_compare(hoover_config)
        status = str(report.get("status", "unknown"))
        failure_reasons = list(report.get("failure_reasons", []))
    except Exception as exc:  # noqa: BLE001 - orchestration reports helper failures per perturbation.
        report = {}
        status = "failed"
        failure_reasons = [str(exc)]
    return {
        "perturbation_id": perturbation_id,
        "comparison_id": comparison_id,
        "status": status,
        "output_dir": str(output_dir),
        "report_path": _hoover_report_path(report),
        "raw_output_path": str(report.get("raw_output_path", "")) if report else "",
        "parsed_metrics": dict(report.get("parsed_metrics", {})) if report else {},
        "parser_status": str(report.get("parser_status", "not_run")) if report else "not_run",
        "failure_reasons": failure_reasons,
        "report": report,
    }


def _candidate_report(
    group_dir: Path,
    source_candidate_id: str,
    scale_id: str,
    baseline_row: dict[str, object],
    perturbation_rows: list[dict[str, object]],
    segmentation_runs: list[dict[str, object]],
    hoover_runs: list[dict[str, object]],
    candidate_status: str,
) -> dict[str, object]:
    group_dir.mkdir(parents=True, exist_ok=True)
    report_path = group_dir / "candidate_stability_report.json"
    report = {
        "source_candidate_id": source_candidate_id,
        "scale_id": scale_id,
        "candidate_status": candidate_status,
        "baseline_perturbation_id": str(baseline_row["perturbation_id"]),
        "perturbation_ids": [str(row["perturbation_id"]) for row in perturbation_rows],
        "segmentation_run_statuses": [
            {
                "perturbation_id": run["perturbation_id"],
                "is_baseline": run["is_baseline"],
                "status": run["status"],
                "report_path": run["report_path"],
                "merged_labels_path": run["merged_labels_path"],
                "failure_reasons": run["failure_reasons"],
            }
            for run in segmentation_runs
        ],
        "hoover_comparison_statuses": [
            {
                "perturbation_id": run["perturbation_id"],
                "comparison_id": run["comparison_id"],
                "status": run["status"],
                "report_path": run["report_path"],
                "raw_output_path": run["raw_output_path"],
                "parser_status": run["parser_status"],
                "parsed_metrics": run["parsed_metrics"],
                "failure_reasons": run["failure_reasons"],
            }
            for run in hoover_runs
        ],
        "candidate_report_path": str(report_path),
        **NO_OUTPUT_FLAGS,
    }
    with report_path.open("w", encoding="utf-8") as file_obj:
        json.dump(report, file_obj, indent=2)
    return json.loads(report_path.read_text(encoding="utf-8"))


def _summary_from_report(report: dict[str, object], baseline_row: dict[str, object]) -> dict[str, object]:
    segmentation_statuses = list(report["segmentation_run_statuses"])
    hoover_statuses = list(report["hoover_comparison_statuses"])
    perturbation_segmentation_statuses = [item for item in segmentation_statuses if not item["is_baseline"]]
    baseline_status = segmentation_statuses[0]["status"] if segmentation_statuses else "failed"
    if report["candidate_status"] == "dry_run":
        successful_perturbations = []
        failed_count = 0
    else:
        successful_perturbations = [
            item
            for item in perturbation_segmentation_statuses
            if item["status"] in ("ok", "dry_run")
            and any(h["perturbation_id"] == item["perturbation_id"] and h["status"] in ("ok", "dry_run") for h in hoover_statuses)
        ]
        if baseline_status not in ("ok", "dry_run"):
            failed_count = len(report["perturbation_ids"])
        else:
            failed_count = len(report["perturbation_ids"]) - len(successful_perturbations)
    successful_perturbation_count = len(successful_perturbations)
    baseline_merged = segmentation_statuses[0]["merged_labels_path"] if segmentation_statuses else ""
    parser_statuses = [str(item["parser_status"]) for item in hoover_statuses]
    numeric_metrics = _aggregate_hoover_metrics(hoover_statuses)
    summary = {
        "source_candidate_id": report["source_candidate_id"],
        "scale_id": report["scale_id"],
        "candidate_status": report["candidate_status"],
        "baseline_perturbation_id": report["baseline_perturbation_id"],
        "perturbation_count": len(report["perturbation_ids"]),
        "successful_perturbation_count": successful_perturbation_count,
        "failed_perturbation_count": failed_count,
        "baseline_merged_labels_path": baseline_merged,
        "candidate_report_path": report["candidate_report_path"],
        "hoover_report_paths": [item["report_path"] for item in hoover_statuses if item.get("report_path")],
        "hoover_raw_output_paths": [item["raw_output_path"] for item in hoover_statuses if item.get("raw_output_path")],
        "hoover_parser_statuses": parser_statuses,
        "hoover_numeric_metric_keys": numeric_metrics.pop("hoover_numeric_metric_keys"),
    }
    for field in BASELINE_SUMMARY_FIELDS:
        if field in baseline_row:
            summary[field] = baseline_row[field]
    summary.update(numeric_metrics)
    return summary


def _aggregate_hoover_metrics(hoover_statuses: list[dict[str, object]]) -> dict[str, object]:
    values_by_key: dict[str, list[float]] = {}
    for status in hoover_statuses:
        if status.get("status") not in ("ok", "dry_run"):
            continue
        for key, value in dict(status.get("parsed_metrics", {})).items():
            if _finite_number(value):
                values_by_key.setdefault(str(key), []).append(float(value))

    aggregate: dict[str, object] = {"hoover_numeric_metric_keys": sorted(values_by_key)}
    for key in sorted(values_by_key):
        values = values_by_key[key]
        aggregate[f"hoover_{key}_mean"] = statistics.fmean(values)
        aggregate[f"hoover_{key}_sd"] = statistics.stdev(values) if len(values) > 1 else 0.0
    return aggregate


def _write_top_outputs(
    config: Level1BCandidateStabilityConfig,
    layout: dict[str, Path],
    rows: list[dict[str, object]],
    groups: list[dict[str, object]],
    summaries: list[dict[str, object]],
) -> dict[str, object]:
    layout["stability_dir"].mkdir(parents=True, exist_ok=True)
    _write_scale_stability_csv(summaries, layout["scale_stability_csv_path"])
    top_report = _top_report(config, layout, len(rows), len(groups), summaries, [])
    with layout["scale_stability_json_path"].open("w", encoding="utf-8") as file_obj:
        json.dump(top_report, file_obj, indent=2)
    return json.loads(layout["scale_stability_json_path"].read_text(encoding="utf-8"))


def _write_scale_stability_csv(summaries: list[dict[str, object]], csv_path: Path) -> None:
    fieldnames = list(SUMMARY_BASE_FIELDS)
    extra_fields: list[str] = []
    for summary in summaries:
        for key in summary:
            if key not in fieldnames and key not in extra_fields:
                extra_fields.append(key)
    fieldnames.extend(extra_fields)
    with csv_path.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for summary in summaries:
            writer.writerow({key: _csv_value(summary.get(key, "")) for key in fieldnames})


def _top_report(
    config: Level1BCandidateStabilityConfig,
    layout: dict[str, Path],
    row_count: int,
    group_count: int,
    summaries: list[dict[str, object]],
    failure_reasons: list[str],
) -> dict[str, object]:
    completed_statuses = ("ok", "partial", "dry_run")
    groups_failed = sum(1 for item in summaries if item.get("candidate_status") not in completed_statuses)
    segmentation_attempted = sum(1 + int(item.get("perturbation_count", 0)) for item in summaries)
    segmentation_failed = sum(int(item.get("failed_perturbation_count", 0)) for item in summaries)
    if any(item.get("candidate_status") == "failed" for item in summaries):
        segmentation_failed += sum(1 for item in summaries if item.get("candidate_status") == "failed")
    hoover_attempted = sum(len(item.get("hoover_parser_statuses", [])) for item in summaries)
    hoover_succeeded = sum(
        max(0, int(item.get("successful_perturbation_count", 0)))
        for item in summaries
        if item.get("candidate_status") != "failed"
    )
    dry_run_only = bool(summaries) and all(item.get("candidate_status") == "dry_run" for item in summaries)
    report = {
        "candidate_id": str(config.candidate_id),
        "input_perturbation_row_count": row_count,
        "source_candidate_group_count": group_count,
        "groups_completed": sum(1 for item in summaries if item.get("candidate_status") in completed_statuses),
        "groups_failed": groups_failed if summaries else (1 if failure_reasons else 0),
        "segmentation_runs_attempted": segmentation_attempted,
        "segmentation_runs_succeeded": 0 if dry_run_only else max(0, segmentation_attempted - segmentation_failed),
        "segmentation_runs_failed": segmentation_failed,
        "hoover_comparisons_attempted": hoover_attempted,
        "hoover_comparisons_succeeded": hoover_succeeded,
        "hoover_comparisons_failed": max(0, hoover_attempted - hoover_succeeded),
        "scale_stability_csv_path": str(layout["scale_stability_csv_path"]),
        "scale_stability_json_path": str(layout["scale_stability_json_path"]),
        "candidate_summaries": summaries,
        "failure_reasons": failure_reasons,
        **NO_OUTPUT_FLAGS,
        "no_cli_integration": True,
        "no_" + "run" + "ner_created": True,
    }
    return report


def _dry_run_group_summary(
    config: Level1BCandidateStabilityConfig,
    layout: dict[str, Path],
    group: dict[str, object],
) -> dict[str, object]:
    source_candidate_id = str(group["source_candidate_id"])
    group_dir = layout["stability_dir"] / source_candidate_id
    baseline_row = dict(group["baseline"])
    perturbation_rows = [dict(row) for row in group["perturbations"]]
    segmentation_runs = [
        _planned_segmentation(config, group_dir / "baseline", source_candidate_id, baseline_row),
        *[
            _planned_segmentation(config, group_dir / str(row["perturbation_id"]), source_candidate_id, row)
            for row in perturbation_rows
        ],
    ]
    report = _candidate_report(
        group_dir,
        source_candidate_id,
        str(group["scale_id"]),
        baseline_row,
        perturbation_rows,
        segmentation_runs,
        [],
        "dry_run",
    )
    return _summary_from_report(report, baseline_row)


def _planned_segmentation(
    config: Level1BCandidateStabilityConfig,
    output_dir: Path,
    source_candidate_id: str,
    row: dict[str, object],
) -> dict[str, object]:
    kwargs = {
        "candidate_id": source_candidate_id,
        "output_dir": output_dir,
        "feature_space_stack_path": config.feature_space_stack_path,
        "perturbation_candidates_json_path": config.perturbation_candidates_json_path,
        "perturbation_id": str(row["perturbation_id"]),
        "otb_bin_dir": config.otb_bin_dir,
        "ram_mb": config.ram_mb,
        "overwrite": config.overwrite,
        "dry_run": config.dry_run,
    }
    allowed = {field.name for field in fields(Level1BOneScaleSegmentationConfig)}
    return {
        "perturbation_id": str(row["perturbation_id"]),
        "is_baseline": bool(row["is_baseline"]),
        "status": "dry_run",
        "output_dir": str(output_dir),
        "report_path": "",
        "merged_labels_path": "",
        "failure_reasons": [],
        "config": {key: str(value) for key, value in kwargs.items() if key in allowed},
        "report": {},
    }


def _merged_labels_path(report: object) -> str:
    if not isinstance(report, dict):
        return ""
    artifacts = report.get("output_artifacts", {})
    if isinstance(artifacts, dict) and artifacts.get("merged_labels"):
        return str(artifacts["merged_labels"])
    if report.get("merged_labels_path"):
        return str(report["merged_labels_path"])
    return ""


def _segmentation_report_path(report: object) -> str:
    if not isinstance(report, dict):
        return ""
    artifacts = report.get("output_artifacts", {})
    if isinstance(artifacts, dict) and artifacts.get("report"):
        return str(artifacts["report"])
    if report.get("report_path"):
        return str(report["report_path"])
    return ""


def _hoover_report_path(report: object) -> str:
    if not isinstance(report, dict):
        return ""
    if report.get("report_path"):
        return str(report["report_path"])
    if report.get("raw_output_path"):
        return str(Path(str(report["raw_output_path"])).with_name("hoover_report.json"))
    if report.get("stdout_path"):
        return str(Path(str(report["stdout_path"])).with_name("hoover_report.json"))
    return ""


def _comparison_id(source_candidate_id: str, perturbation_id: str) -> str:
    safe_source = "".join(char if char.isalnum() or char in "._-" else "_" for char in source_candidate_id)
    safe_perturbation = "".join(char if char.isalnum() or char in "._-" else "_" for char in perturbation_id)
    return f"{safe_source}__{safe_perturbation}"


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _positive_int_field(value: object, field_name: str) -> int:
    if not _finite_number(value):
        raise ValueError(f"{field_name} must be finite")
    try:
        integer = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be positive") from exc
    if integer <= 0 or float(value) != integer:
        raise ValueError(f"{field_name} must be positive")
    return integer


def _positive_float_field(value: object, field_name: str) -> float:
    if not _finite_number(value):
        raise ValueError(f"{field_name} must be finite")
    numeric = float(value)
    if numeric <= 0:
        raise ValueError(f"{field_name} must be positive")
    return numeric


def _finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _csv_value(value: object) -> object:
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value


def _public_config(config: object) -> dict[str, object]:
    result: dict[str, object] = {}
    for field in fields(config):
        value = getattr(config, field.name)
        result[field.name] = str(value) if isinstance(value, Path) else value
    return result
