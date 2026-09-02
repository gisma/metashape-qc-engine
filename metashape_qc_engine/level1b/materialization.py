from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import shutil
import statistics
import subprocess

from metashape_qc_engine.level1b.step_manifest import step_manifest_path, write_step_manifest


STEP10_FINALIST_EVIDENCE_FILENAME = "finalist_evidence.json"
STEP10_FINALIST_EVIDENCE_SCHEMA = "level1b_step10_finalist_evidence"
DEFAULT_STEP10_SUBDIR = "step10_materialization"


def _step10_root_dir(
    output_dir: str | Path,
    *,
    step10_subdir: str = DEFAULT_STEP10_SUBDIR,
) -> Path:
    return Path(output_dir) / "level1b" / Path(step10_subdir)


def _step10_decision_evidence_dir(
    output_dir: str | Path,
    *,
    step10_subdir: str = DEFAULT_STEP10_SUBDIR,
) -> Path:
    return _step10_root_dir(output_dir, step10_subdir=step10_subdir) / "decision_evidence"


def _step10_finalist_evidence_path(
    output_dir: str | Path,
    *,
    step10_subdir: str = DEFAULT_STEP10_SUBDIR,
) -> Path:
    return (
        _step10_decision_evidence_dir(output_dir, step10_subdir=step10_subdir)
        / STEP10_FINALIST_EVIDENCE_FILENAME
    )


def _step10_manifest_step_name(step: str, step10_subdir: str) -> str:
    if step10_subdir == DEFAULT_STEP10_SUBDIR:
        return step
    suffix = "".join(
        character if character.isalnum() else "_"
        for character in step10_subdir
    ).strip("_")
    return f"{step}__{suffix}"


def _read_step10_finalist_evidence(
    output_dir: str | Path,
    *,
    step10_subdir: str = DEFAULT_STEP10_SUBDIR,
) -> dict:
    evidence = json.loads(
        _step10_finalist_evidence_path(
            output_dir, step10_subdir=step10_subdir
        ).read_text(encoding="utf-8")
    )
    if evidence["schema"] != STEP10_FINALIST_EVIDENCE_SCHEMA:
        raise ValueError("Invalid Step-10 finalist evidence schema")
    return evidence


def _write_step10_finalist_evidence(path: Path, evidence: dict) -> None:
    path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")


def _selected_representative_run(evidence: dict) -> dict:
    [selected_row] = [
        row
        for row in evidence["finalist_run_rows"]
        if row["run_id"] == evidence["selected_representative_run_id"]
        and row["step10_selected_candidate"] is True
        and row.get("ensemble_representative") is True
    ]
    return selected_row


def _selected_label_raster_path(selected_row: dict) -> Path:
    run_contract_version = selected_row.get("run_contract_version")
    if run_contract_version is None or int(run_contract_version) == 1:
        return (
            Path(selected_row["masked_segmentation_stack_path"]).parent
            / "merged_labels.tif"
        )
    return Path(selected_row["merged_labels_path"])


def run_level1b_step10_collect_finalist_evidence(
    output_dir: str | Path,
    *,
    step10_subdir: str = DEFAULT_STEP10_SUBDIR,
    selected_candidate_id: str | None = None,
    selected_role: str | None = None,
    supported_alternatives_json: str | Path | None = None,
) -> dict:
    output_root = Path(output_dir)
    step9a_dir = output_root / "level1b" / "candidate_response_surface"
    step9b_dir = output_root / "level1b" / "local_transition_refinement"
    midpoint_response_surface_dir = (
        step9b_dir
        / "midpoint_response_surface_eval"
        / "level1b"
        / "candidate_response_surface"
    )
    decision_evidence_dir = _step10_decision_evidence_dir(
        output_root, step10_subdir=step10_subdir
    )
    decision_evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_json_path = _step10_finalist_evidence_path(
        output_root, step10_subdir=step10_subdir
    )

    step9a_group_summary_json = (
        step9a_dir / "candidate_group_response_summary.json"
    )
    step9a_run_population_json = step9a_dir / "run_population_summary.json"
    step9a_group_summary = json.loads(
        step9a_group_summary_json.read_text(encoding="utf-8")
    )
    step9a_run_population = json.loads(
        step9a_run_population_json.read_text(encoding="utf-8")
    )

    branch_mode = selected_candidate_id is not None
    source_artifacts: dict[str, str] = {
        "step9a_candidate_group_response_summary_json": str(
            step9a_group_summary_json
        ),
        "step9a_run_population_summary_json": str(
            step9a_run_population_json
        ),
    }
    if branch_mode:
        if selected_role is None:
            raise ValueError(
                "selected_role is required when selected_candidate_id is provided"
            )
        selected_candidate_id = str(selected_candidate_id)
        selected_role = str(selected_role)
        finalist_ids = {selected_role: selected_candidate_id}
        ordered_roles = [selected_role]
        display_rank_by_role = {selected_role: 1}
        if supported_alternatives_json is not None:
            source_artifacts["supported_scale_alternatives_json"] = str(
                supported_alternatives_json
            )

        def annotate(row: dict, role: str, source_table: str) -> dict:
            annotated = dict(row)
            annotated.update(
                {
                    "step10_display_rank": display_rank_by_role[role],
                    "step10_finalist_role": role,
                    "step10_selected_candidate": True,
                    "step10_selected_role": selected_role,
                    "step10_source_table": source_table,
                    "step10_lower_boundary_documentation_only": False,
                }
            )
            return annotated

        selected_group_row = next(
            row
            for row in step9a_group_summary
            if row["candidate_scale_group_id"] == selected_candidate_id
        )
        group_rows_by_role = {
            selected_role: annotate(
                selected_group_row,
                selected_role,
                "step9a_candidate_group_response_summary",
            )
        }
        group_rows = [group_rows_by_role[selected_role]]
        run_rows_by_role = {
            selected_role: [
                annotate(
                    row,
                    selected_role,
                    "step9a_run_population_summary",
                )
                for row in step9a_run_population
                if row["candidate_scale_group_id"] == selected_candidate_id
            ]
        }
        run_rows = run_rows_by_role[selected_role]
    else:
        handoff_json = step9b_dir / "step9b_midpoint_gain_share_handoff.json"
        midpoint_group_summary_json = (
            midpoint_response_surface_dir / "candidate_group_response_summary.json"
        )
        midpoint_run_population_json = (
            midpoint_response_surface_dir / "run_population_summary.json"
        )

        handoff = json.loads(handoff_json.read_text(encoding="utf-8"))
        midpoint_group_summary = json.loads(
            midpoint_group_summary_json.read_text(encoding="utf-8")
        )
        midpoint_run_population = json.loads(
            midpoint_run_population_json.read_text(encoding="utf-8")
        )
        source_artifacts.update(
            {
                "step9b_handoff_json": str(handoff_json),
                "midpoint_candidate_group_response_summary_json": str(
                    midpoint_group_summary_json
                ),
                "midpoint_run_population_summary_json": str(
                    midpoint_run_population_json
                ),
            }
        )

        finalist_ids = {
            "lower_boundary": handoff["top_pair_lower_scale_candidate_group_id"],
            "midpoint": handoff["midpoint_candidate_id"],
            "upper_boundary": handoff["top_pair_upper_scale_candidate_group_id"],
        }
        selected_candidate_id = str(handoff["handoff_candidate_id"])
        selected_role = next(
            role
            for role, candidate_id in finalist_ids.items()
            if candidate_id == selected_candidate_id
        )
        no1_role = next(
            role
            for role, candidate_id in finalist_ids.items()
            if candidate_id == handoff["no1_candidate_scale_group_id"]
        )
        no2_role = next(
            role
            for role, candidate_id in finalist_ids.items()
            if candidate_id == handoff["no2_candidate_scale_group_id"]
        )
        ordered_roles = (
            ["midpoint", no1_role, no2_role]
            if selected_role == "midpoint"
            else [selected_role, "midpoint", no2_role]
        )
        display_rank_by_role = {
            role: index for index, role in enumerate(ordered_roles, start=1)
        }

        def annotate(row: dict, role: str, source_table: str) -> dict:
            annotated = dict(row)
            annotated.update(
                {
                    "step10_display_rank": display_rank_by_role[role],
                    "step10_finalist_role": role,
                    "step10_selected_candidate": row["candidate_scale_group_id"]
                    == selected_candidate_id,
                    "step10_selected_role": selected_role,
                    "step10_source_table": source_table,
                    "step10_lower_boundary_documentation_only": (
                        role == "lower_boundary"
                        and row["candidate_scale_group_id"] != selected_candidate_id
                    ),
                }
            )
            return annotated

        lower_group_row = next(
            row
            for row in step9a_group_summary
            if row["candidate_scale_group_id"] == finalist_ids["lower_boundary"]
        )
        upper_group_row = next(
            row
            for row in step9a_group_summary
            if row["candidate_scale_group_id"] == finalist_ids["upper_boundary"]
        )
        midpoint_group_row = next(
            row
            for row in midpoint_group_summary
            if row["candidate_scale_group_id"] == finalist_ids["midpoint"]
        )
        group_rows_by_role = {
            "lower_boundary": annotate(
                lower_group_row,
                "lower_boundary",
                "step9a_candidate_group_response_summary",
            ),
            "upper_boundary": annotate(
                upper_group_row,
                "upper_boundary",
                "step9a_candidate_group_response_summary",
            ),
            "midpoint": annotate(
                midpoint_group_row,
                "midpoint",
                "midpoint_candidate_group_response_summary",
            ),
        }
        group_rows = [group_rows_by_role[role] for role in ordered_roles]

        run_rows_by_role = {
            "lower_boundary": [
                annotate(
                    row,
                    "lower_boundary",
                    "step9a_run_population_summary",
                )
                for row in step9a_run_population
                if row["candidate_scale_group_id"]
                == finalist_ids["lower_boundary"]
            ],
            "upper_boundary": [
                annotate(
                    row,
                    "upper_boundary",
                    "step9a_run_population_summary",
                )
                for row in step9a_run_population
                if row["candidate_scale_group_id"]
                == finalist_ids["upper_boundary"]
            ],
            "midpoint": [
                annotate(
                    row,
                    "midpoint",
                    "midpoint_run_population_summary",
                )
                for row in midpoint_run_population
                if row["candidate_scale_group_id"] == finalist_ids["midpoint"]
            ],
        }
        run_rows = [
            row for role in ordered_roles for row in run_rows_by_role[role]
        ]

    selected_group_row = group_rows_by_role[selected_role]
    selected_representative_run_id = str(selected_group_row["medoid_run_id"])
    [selected_representative_row] = [
        row
        for row in run_rows
        if row["step10_selected_candidate"] is True
        and str(row["run_id"]) == selected_representative_run_id
        and row.get("ensemble_representative") is True
    ]
    evidence = {
        "schema": STEP10_FINALIST_EVIDENCE_SCHEMA,
        "schema_version": 2,
        "status": "step10_part1_finalist_evidence_collected",
        "source_artifacts": source_artifacts,
        "finalist_candidate_ids": finalist_ids,
        "display_order": ordered_roles,
        "selected_candidate_id": selected_candidate_id,
        "selected_role": selected_role,
        "selected_representative_run_id": selected_representative_row["run_id"],
        "finalist_group_rows": group_rows,
        "finalist_run_rows": run_rows,
        "group_aggregation_rows": [],
        "numeric_distribution_rows": [],
    }
    _write_step10_finalist_evidence(evidence_json_path, evidence)

    group_json_path = decision_evidence_dir / "finalist_group_summary.json"
    group_csv_path = decision_evidence_dir / "finalist_group_summary.csv"
    runs_json_path = decision_evidence_dir / "finalist_perturbation_runs.json"
    runs_csv_path = decision_evidence_dir / "finalist_perturbation_runs.csv"

    annotation_fields = [
        "step10_display_rank",
        "step10_finalist_role",
        "step10_selected_candidate",
        "step10_selected_role",
        "step10_source_table",
        "step10_lower_boundary_documentation_only",
    ]

    def write_json(path: Path, rows: list[dict]) -> None:
        path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    def write_csv(path: Path, rows: list[dict]) -> None:
        source_fields = sorted(
            {key for row in rows for key in row if key not in annotation_fields}
        )
        fieldnames = [*annotation_fields, *source_fields]
        with path.open("w", newline="", encoding="utf-8") as file_obj:
            writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        key: json.dumps(value, sort_keys=True)
                        if isinstance(value, (dict, list, tuple))
                        else value
                        for key, value in row.items()
                    }
                )

    write_json(group_json_path, group_rows)
    write_csv(group_csv_path, group_rows)
    write_json(runs_json_path, run_rows)
    write_csv(runs_csv_path, run_rows)

    step_name = _step10_manifest_step_name("step10_collect", step10_subdir)
    manifest_path = write_step_manifest(
        output_dir,
        step=step_name,
        status="step10_part1_finalist_evidence_collected",
        inputs=source_artifacts,
        artifacts={
            "finalist_evidence_json": evidence_json_path,
            "finalist_group_summary_json": group_json_path,
            "finalist_group_summary_csv": group_csv_path,
            "finalist_perturbation_runs_json": runs_json_path,
            "finalist_perturbation_runs_csv": runs_csv_path,
        },
        candidate_id=selected_candidate_id,
    )

    return {
        "status": "step10_part1_finalist_evidence_collected",
        "output_dir": str(output_dir),
        "decision_evidence_dir": str(decision_evidence_dir),
        "selected_candidate_id": selected_candidate_id,
        "selected_role": selected_role,
        "selected_representative_run_id": selected_representative_row["run_id"],
        "finalist_evidence_json": str(evidence_json_path),
        "finalist_group_summary_json": str(group_json_path),
        "finalist_group_summary_csv": str(group_csv_path),
        "finalist_perturbation_runs_json": str(runs_json_path),
        "finalist_perturbation_runs_csv": str(runs_csv_path),
        "group_row_count": len(group_rows),
        "perturbation_run_row_count": len(run_rows),
        "manifest_json": str(manifest_path),
        "step_manifest_json": str(manifest_path),
    }


def run_level1b_step10_aggregate_finalist_evidence(
    output_dir: str | Path,
    *,
    step10_subdir: str = DEFAULT_STEP10_SUBDIR,
) -> dict:
    decision_evidence_dir = _step10_decision_evidence_dir(
        output_dir, step10_subdir=step10_subdir
    )
    evidence_json_path = _step10_finalist_evidence_path(
        output_dir, step10_subdir=step10_subdir
    )
    evidence = _read_step10_finalist_evidence(
        output_dir, step10_subdir=step10_subdir
    )
    group_rows = evidence["finalist_group_rows"]
    perturbation_run_rows = evidence["finalist_run_rows"]

    runs_by_role = {
        group_row["step10_finalist_role"]: [
            row
            for row in perturbation_run_rows
            if row["step10_finalist_role"] == group_row["step10_finalist_role"]
        ]
        for group_row in group_rows
    }

    def is_numeric(value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def percentile(values: list[int | float], probability: float) -> float:
        ordered = sorted(values)
        position = (len(ordered) - 1) * probability
        lower_index = math.floor(position)
        upper_index = math.ceil(position)
        if lower_index == upper_index:
            return float(ordered[lower_index])
        fraction = position - lower_index
        return float(
            ordered[lower_index]
            + (ordered[upper_index] - ordered[lower_index]) * fraction
        )

    numeric_distribution_rows = []
    group_aggregation_rows = []
    selected_decision_fields = [
        "stability_score_raw",
        "stability_score",
        "candidate_score",
        "segment_count",
        "segment_density_per_ha",
        "valid_area_ha",
        "source_candidate_radius_m",
        "radius_m",
        "spatialr_px",
        "minsize_px",
        "ranger",
    ]

    for group_row in group_rows:
        role = group_row["step10_finalist_role"]
        role_run_rows = runs_by_role[role]
        numeric_fields = sorted(
            {
                key
                for row in role_run_rows
                for key, value in row.items()
                if is_numeric(value)
            }
        )

        group_aggregation = {
            "step10_finalist_role": role,
            "candidate_scale_group_id": group_row["candidate_scale_group_id"],
            "step10_selected_candidate": group_row["step10_selected_candidate"],
            "step10_selected_role": group_row["step10_selected_role"],
            "step10_source_table": group_row["step10_source_table"],
            "step10_lower_boundary_documentation_only": group_row[
                "step10_lower_boundary_documentation_only"
            ],
            "perturbation_run_count": len(role_run_rows),
            "numeric_field_count": len(numeric_fields),
        }
        if "step10_display_rank" in group_row:
            group_aggregation = {
                "step10_display_rank": group_row["step10_display_rank"],
                **group_aggregation,
            }
        group_aggregation.update(
            {
                field: group_row[field]
                for field in selected_decision_fields
                if field in group_row
            }
        )
        group_aggregation_rows.append(group_aggregation)

        for numeric_field in numeric_fields:
            values = [
                row[numeric_field]
                for row in role_run_rows
                if numeric_field in row and is_numeric(row[numeric_field])
            ]
            distribution_row = {
                "step10_finalist_role": role,
                "candidate_scale_group_id": group_row["candidate_scale_group_id"],
                "step10_selected_candidate": group_row["step10_selected_candidate"],
                "step10_selected_role": group_row["step10_selected_role"],
                "step10_lower_boundary_documentation_only": group_row[
                    "step10_lower_boundary_documentation_only"
                ],
                "numeric_field": numeric_field,
                "n": len(values),
                "mean": statistics.fmean(values),
                "median": statistics.median(values),
                "min": min(values),
                "max": max(values),
                "p05": percentile(values, 0.05),
                "p95": percentile(values, 0.95),
                "std": statistics.pstdev(values) if len(values) > 1 else 0.0,
            }
            if "step10_display_rank" in group_row:
                distribution_row = {
                    "step10_display_rank": group_row["step10_display_rank"],
                    **distribution_row,
                }
            numeric_distribution_rows.append(distribution_row)

    group_json_path = decision_evidence_dir / "finalist_group_aggregation.json"
    group_csv_path = decision_evidence_dir / "finalist_group_aggregation.csv"
    distribution_json_path = (
        decision_evidence_dir / "finalist_numeric_distribution_summary.json"
    )
    distribution_csv_path = (
        decision_evidence_dir / "finalist_numeric_distribution_summary.csv"
    )

    evidence["status"] = "step10_part2_finalist_evidence_aggregated"
    evidence["group_aggregation_rows"] = group_aggregation_rows
    evidence["numeric_distribution_rows"] = numeric_distribution_rows
    _write_step10_finalist_evidence(evidence_json_path, evidence)

    group_json_path.write_text(
        json.dumps(group_aggregation_rows, indent=2), encoding="utf-8"
    )
    distribution_json_path.write_text(
        json.dumps(numeric_distribution_rows, indent=2), encoding="utf-8"
    )

    include_display_rank = all("step10_display_rank" in row for row in group_rows)
    group_base_fields = [
        "step10_finalist_role",
        "candidate_scale_group_id",
        "step10_selected_candidate",
        "step10_selected_role",
        "step10_source_table",
        "step10_lower_boundary_documentation_only",
        "perturbation_run_count",
        "numeric_field_count",
    ]
    if include_display_rank:
        group_base_fields.insert(0, "step10_display_rank")
    group_csv_fields = [
        *group_base_fields,
        *(
            field
            for field in selected_decision_fields
            if any(field in row for row in group_aggregation_rows)
        ),
    ]
    with group_csv_path.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=group_csv_fields)
        writer.writeheader()
        writer.writerows(group_aggregation_rows)

    distribution_csv_fields = [
        "step10_finalist_role",
        "candidate_scale_group_id",
        "step10_selected_candidate",
        "step10_selected_role",
        "step10_lower_boundary_documentation_only",
        "numeric_field",
        "n",
        "mean",
        "median",
        "min",
        "max",
        "p05",
        "p95",
        "std",
    ]
    if include_display_rank:
        distribution_csv_fields.insert(0, "step10_display_rank")
    with distribution_csv_path.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=distribution_csv_fields)
        writer.writeheader()
        writer.writerows(numeric_distribution_rows)

    selected_candidate_id = next(
        row["candidate_scale_group_id"]
        for row in group_rows
        if row["step10_selected_candidate"] is True
    )
    manifest_path = write_step_manifest(
        output_dir,
        step=_step10_manifest_step_name("step10_aggregate", step10_subdir),
        status="step10_part2_finalist_evidence_aggregated",
        inputs={
            "finalist_evidence_json": evidence_json_path,
        },
        artifacts={
            "finalist_evidence_json": evidence_json_path,
            "finalist_group_aggregation_json": group_json_path,
            "finalist_group_aggregation_csv": group_csv_path,
            "finalist_numeric_distribution_summary_json": distribution_json_path,
            "finalist_numeric_distribution_summary_csv": distribution_csv_path,
        },
        candidate_id=selected_candidate_id,
    )

    return {
        "status": "step10_part2_finalist_evidence_aggregated",
        "output_dir": str(output_dir),
        "decision_evidence_dir": str(decision_evidence_dir),
        "finalist_evidence_json": str(evidence_json_path),
        "finalist_group_aggregation_json": str(group_json_path),
        "finalist_group_aggregation_csv": str(group_csv_path),
        "finalist_numeric_distribution_summary_json": str(distribution_json_path),
        "finalist_numeric_distribution_summary_csv": str(distribution_csv_path),
        "group_aggregation_row_count": len(group_aggregation_rows),
        "numeric_distribution_row_count": len(numeric_distribution_rows),
        "manifest_json": str(manifest_path),
    }


def run_level1b_step10_make_finalist_figures(
    output_dir: str | Path,
    *,
    step10_subdir: str = DEFAULT_STEP10_SUBDIR,
) -> dict:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output_root = Path(output_dir)
    evidence_json_path = _step10_finalist_evidence_path(
        output_root, step10_subdir=step10_subdir
    )
    evidence = _read_step10_finalist_evidence(
        output_root, step10_subdir=step10_subdir
    )
    group_rows = evidence["finalist_group_rows"]
    perturbation_run_rows = evidence["finalist_run_rows"]
    group_aggregation_rows = evidence["group_aggregation_rows"]
    numeric_distribution_rows = evidence["numeric_distribution_rows"]

    display_roles = [row["step10_finalist_role"] for row in group_aggregation_rows]
    selected_row = next(
        row for row in group_aggregation_rows if row["step10_selected_candidate"] is True
    )
    selected_candidate_id = selected_row["candidate_scale_group_id"]
    selected_role = selected_row["step10_finalist_role"]
    aggregation_by_role = {
        row["step10_finalist_role"]: row for row in group_aggregation_rows
    }
    group_by_role = {row["step10_finalist_role"]: row for row in group_rows}

    def is_numeric(value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def role_label(role: str) -> str:
        label = role
        if role == selected_role:
            label += "\n[SELECTED]"
        if role == "lower_boundary":
            label += "\n[documentation only]"
        return label

    role_labels = [role_label(role) for role in display_roles]
    selected_title = f"Selected candidate: {selected_candidate_id}"

    figures_dir = _step10_root_dir(
        output_root, step10_subdir=step10_subdir
    ) / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    figure_paths = [
        figures_dir / "finalist_decision_scores.png",
        figures_dir / "finalist_stability_score_distribution.png",
        figures_dir / "finalist_segment_count_distribution.png",
        figures_dir / "finalist_area_distribution.png",
        figures_dir / "finalist_parameter_spread.png",
        figures_dir / "finalist_numeric_field_overview.png",
    ]

    def save_message_figure(path: Path, title: str) -> None:
        figure, axis = plt.subplots(figsize=(10, 4))
        axis.axis("off")
        axis.set_title(f"{title}\n{selected_title}")
        axis.text(
            0.5,
            0.5,
            "No matching existing numeric fields in Step-10 evidence table",
            ha="center",
            va="center",
            transform=axis.transAxes,
        )
        figure.tight_layout()
        figure.savefig(path, dpi=150)
        plt.close(figure)

    def first_existing_numeric(field: str) -> int | float | None:
        for rows in (group_rows, group_aggregation_rows):
            for row in rows:
                value = row.get(field)
                if is_numeric(value):
                    return value
        return None

    decision_values_by_role = {
        role: group_by_role[role].get("stability_score_raw")
        for role in display_roles
    }
    displayed_decision_values = [
        decision_values_by_role.get(role) for role in display_roles
    ]
    if any(value is not None for value in displayed_decision_values):
        figure, axis = plt.subplots(figsize=(10, 6))
        positions = list(range(len(display_roles)))
        plotted_positions = [
            position
            for position, value in zip(positions, displayed_decision_values)
            if value is not None
        ]
        plotted_values = [
            value for value in displayed_decision_values if value is not None
        ]
        colors = [
            "tab:orange" if display_roles[position] == selected_role else "tab:blue"
            for position in plotted_positions
        ]
        bars = axis.bar(plotted_positions, plotted_values, color=colors)
        for position, bar in zip(plotted_positions, bars):
            value = displayed_decision_values[position]
            annotation = f"{value:.6g}"
            if display_roles[position] == selected_role:
                annotation += "\nselected"
            axis.annotate(
                annotation,
                (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                ha="center",
                va="bottom",
            )
        midpoint_gain_share = first_existing_numeric("midpoint_gain_share")
        if midpoint_gain_share is not None:
            axis.text(
                0.02,
                0.98,
                f"midpoint_gain_share = {midpoint_gain_share:.6g}",
                transform=axis.transAxes,
                ha="left",
                va="top",
            )
        axis.set_xticks(positions, role_labels)
        axis.set_xlabel("Finalist role (existing display order)")
        axis.set_ylabel("Existing Step-9 decision value")
        axis.set_title(f"Finalist Step-9 Decision Values\n{selected_title}")
        figure.tight_layout()
        figure.savefig(figure_paths[0], dpi=150)
        plt.close(figure)
    else:
        save_message_figure(figure_paths[0], "Finalist Step-9 Decision Values")

    def write_run_distribution_figure(
        path: Path,
        title: str,
        field_names: list[str],
    ) -> None:
        if not field_names:
            save_message_figure(path, title)
            return
        figure, axes = plt.subplots(
            len(field_names),
            1,
            figsize=(11, max(5, 3.5 * len(field_names))),
            squeeze=False,
        )
        for axis, field_name in zip(axes[:, 0], field_names):
            available_positions = []
            available_values = []
            for position, role in enumerate(display_roles, start=1):
                values = [
                    row[field_name]
                    for row in perturbation_run_rows
                    if row["step10_finalist_role"] == role
                    and field_name in row
                    and is_numeric(row[field_name])
                ]
                if values:
                    available_positions.append(position)
                    available_values.append(values)
            axis.boxplot(
                available_values,
                positions=available_positions,
                widths=0.55,
                patch_artist=True,
                boxprops={"facecolor": "lightsteelblue"},
                medianprops={"color": "black"},
            )
            selected_position = display_roles.index(selected_role) + 1
            axis.axvspan(
                selected_position - 0.4,
                selected_position + 0.4,
                color="tab:orange",
                alpha=0.15,
                label="selected finalist",
            )
            axis.set_xticks(range(1, len(display_roles) + 1), role_labels)
            axis.set_xlim(0.5, len(display_roles) + 0.5)
            axis.set_xlabel("Finalist role (existing display order)")
            axis.set_ylabel(field_name)
            axis.set_title(field_name)
            axis.legend(loc="best")
        figure.suptitle(f"{title}\n{selected_title}")
        figure.tight_layout()
        figure.savefig(path, dpi=150)
        plt.close(figure)

    run_numeric_fields = sorted(
        {
            key
            for row in perturbation_run_rows
            for key, value in row.items()
            if is_numeric(value)
        }
    )
    stability_fields = [
        field
        for field in run_numeric_fields
        if any(token in field.lower() for token in ("score", "support", "stability"))
    ]
    segment_count_fields = [
        field
        for field in run_numeric_fields
        if any(token in field.lower() for token in ("segment_count", "n_segments"))
    ]
    area_fields = [
        field for field in run_numeric_fields if "area" in field.lower()
    ]
    parameter_fields = [
        field
        for field in (
            "spatialr_px",
            "minsize_px",
            "ranger",
            "radius_m",
            "source_candidate_radius_m",
        )
        if field in run_numeric_fields
    ]
    write_run_distribution_figure(
        figure_paths[1],
        "Finalist Stability and Support Score Distributions",
        stability_fields,
    )
    write_run_distribution_figure(
        figure_paths[2],
        "Finalist Segment Count Distributions",
        segment_count_fields,
    )
    write_run_distribution_figure(
        figure_paths[3],
        "Finalist Area Distributions",
        area_fields,
    )
    write_run_distribution_figure(
        figure_paths[4],
        "Finalist Parameter Spread",
        parameter_fields,
    )

    overview_fields = sorted(
        {
            row["numeric_field"]
            for row in numeric_distribution_rows
            if is_numeric(row.get("mean"))
        }
    )
    if overview_fields:
        figure, axis = plt.subplots(
            figsize=(max(10, 2.8 * len(display_roles)), max(5, 0.34 * len(overview_fields)))
        )
        axis.axis("off")
        cell_text = []
        for field in overview_fields:
            field_rows = {
                row["step10_finalist_role"]: row
                for row in numeric_distribution_rows
                if row["numeric_field"] == field
            }
            cell_text.append(
                [
                    f"{field_rows[role]['mean']:.6g}" if role in field_rows else "—"
                    for role in display_roles
                ]
            )
        table = axis.table(
            cellText=cell_text,
            rowLabels=overview_fields,
            colLabels=role_labels,
            cellLoc="center",
            loc="center",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(8)
        table.scale(1.0, 1.2)
        selected_column = display_roles.index(selected_role)
        for (row_index, column_index), cell in table.get_celld().items():
            if column_index == selected_column and row_index >= 0:
                cell.set_facecolor("moccasin")
            if (
                "lower_boundary" in display_roles
                and column_index == display_roles.index("lower_boundary")
                and row_index >= 0
            ):
                cell.set_edgecolor("gray")
        axis.set_title(
            "Aggregated Numeric Field Means by Finalist Role\n"
            f"{selected_title}\nLower boundary is documentation only",
            pad=20,
        )
        figure.tight_layout()
        figure.savefig(figure_paths[5], dpi=150, bbox_inches="tight")
        plt.close(figure)
    else:
        save_message_figure(
            figure_paths[5], "Aggregated Numeric Field Overview"
        )

    manifest_path = figures_dir / "step10_figure_manifest.json"
    manifest = {
        "status": "step10_part3_figures_created",
        "output_dir": str(output_dir),
        "figures_dir": str(figures_dir),
        "selected_candidate_id": selected_candidate_id,
        "selected_role": selected_role,
        "figure_paths": [str(path) for path in figure_paths],
        "input_files_used": [str(evidence_json_path)],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    step_manifest_json = write_step_manifest(
        output_dir,
        step=_step10_manifest_step_name("step10_figures", step10_subdir),
        status="step10_part3_figures_created",
        inputs={
            "finalist_evidence_json": evidence_json_path,
        },
        artifacts={
            "figure_manifest_json": manifest_path,
            **{path.stem: path for path in figure_paths},
        },
        candidate_id=selected_candidate_id,
    )

    return {
        "status": "step10_part3_figures_created",
        "output_dir": str(output_dir),
        "figures_dir": str(figures_dir),
        "selected_candidate_id": selected_candidate_id,
        "selected_role": selected_role,
        "figure_paths": [str(path) for path in figure_paths],
        "figure_count": len(figure_paths),
        "manifest_json": str(manifest_path),
    }


def run_level1b_step10_materialize_selected_segments(
    output_dir: str | Path,
    *,
    step10_subdir: str = DEFAULT_STEP10_SUBDIR,
) -> dict:
    from osgeo import gdal, ogr, osr

    output_root = Path(output_dir)
    evidence_json_path = _step10_finalist_evidence_path(
        output_root, step10_subdir=step10_subdir
    )
    evidence = _read_step10_finalist_evidence(
        output_root, step10_subdir=step10_subdir
    )
    selected_row = _selected_representative_run(evidence)
    stabilization_report_path = (
        _step10_root_dir(output_root, step10_subdir=step10_subdir)
        / "centroid_seed_stabilization"
        / "centroid_seed_stabilization_report.json"
    )
    stabilization_report = json.loads(
        stabilization_report_path.read_text(encoding="utf-8")
    )
    if stabilization_report["status"] != (
        "multiscale_centroid_seed_stabilization_ready"
    ):
        raise RuntimeError("centroid seed stabilization is not converged")
    source_label_raster = Path(stabilization_report["stabilized_labels_tif"])
    final_segments_dir = (
        _step10_root_dir(output_root, step10_subdir=step10_subdir)
        / "final_segments"
    )
    final_segments_dir.mkdir(parents=True, exist_ok=True)
    selected_labels_tif = final_segments_dir / "selected_labels.tif"
    selected_segments_gpkg = final_segments_dir / "selected_segments.gpkg"
    manifest_path = final_segments_dir / "selected_segments_manifest.json"

    shutil.copyfile(source_label_raster, selected_labels_tif)

    label_dataset = gdal.Open(str(selected_labels_tif), gdal.GA_ReadOnly)
    label_band = label_dataset.GetRasterBand(1)
    spatial_reference = None
    projection = label_dataset.GetProjection()
    if projection:
        spatial_reference = osr.SpatialReference()
        spatial_reference.ImportFromWkt(projection)

    geopackage_driver = ogr.GetDriverByName("GPKG")
    vector_dataset = geopackage_driver.CreateDataSource(str(selected_segments_gpkg))
    segment_layer = vector_dataset.CreateLayer(
        "selected_segments",
        srs=spatial_reference,
        geom_type=ogr.wkbPolygon,
    )
    segment_layer.CreateField(ogr.FieldDefn("segment_id", ogr.OFTInteger64))
    segment_layer.CreateField(ogr.FieldDefn("selected_candidate_id", ogr.OFTString))
    segment_layer.CreateField(ogr.FieldDefn("selected_source", ogr.OFTString))
    segment_layer.CreateField(ogr.FieldDefn("selected_representative_id", ogr.OFTString))
    segment_id_field_index = segment_layer.GetLayerDefn().GetFieldIndex("segment_id")
    gdal.Polygonize(
        label_band,
        None,
        segment_layer,
        segment_id_field_index,
        [],
    )

    invalid_support_value = selected_row.get("label_invalid_support_value")
    invalid_feature_ids = []
    for feature in segment_layer:
        if (
            "label_invalid_support_value" in selected_row
            and feature["segment_id"] == invalid_support_value
        ):
            invalid_feature_ids.append(feature.GetFID())
            continue
        feature["selected_candidate_id"] = selected_row["candidate_scale_group_id"]
        feature["selected_source"] = selected_row["step10_selected_role"]
        feature["selected_representative_id"] = selected_row["run_id"]
        segment_layer.SetFeature(feature)
    for feature_id in invalid_feature_ids:
        segment_layer.DeleteFeature(feature_id)
    segment_layer.SyncToDisk()
    vector_dataset.FlushCache()
    vector_dataset = None
    label_dataset = None

    manifest = {
        "status": "step10_part4_selected_segments_materialized",
        "output_dir": str(output_dir),
        "final_segments_dir": str(final_segments_dir),
        "source_run_id": selected_row["run_id"],
        "source_candidate_scale_group_id": selected_row[
            "candidate_scale_group_id"
        ],
        "source_label_raster": str(source_label_raster),
        "centroid_seed_stabilization_report_json": str(
            stabilization_report_path
        ),
        "centroid_seed_stabilization_source_run_id": selected_row["run_id"],
        "selected_labels_tif": str(selected_labels_tif),
        "selected_segments_gpkg": str(selected_segments_gpkg),
        "selected_candidate_id": selected_row["candidate_scale_group_id"],
        "selected_source": selected_row["step10_selected_role"],
        "selected_representative_id": selected_row["run_id"],
    }
    if "label_invalid_support_value" in selected_row:
        manifest["label_invalid_support_value"] = invalid_support_value
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    step_manifest_json = write_step_manifest(
        output_dir,
        step=_step10_manifest_step_name("step10_materialize", step10_subdir),
        status="step10_part4_selected_segments_materialized",
        inputs={
            "finalist_evidence_json": evidence_json_path,
            "centroid_seed_stabilization_report_json": stabilization_report_path,
            "source_label_raster": source_label_raster,
        },
        artifacts={
            "selected_labels_tif": selected_labels_tif,
            "selected_segments_gpkg": selected_segments_gpkg,
            "selected_segments_manifest_json": manifest_path,
        },
        candidate_id=selected_row["candidate_scale_group_id"],
    )

    return {
        "status": "step10_part4_selected_segments_materialized",
        "output_dir": str(output_dir),
        "final_segments_dir": str(final_segments_dir),
        "source_run_id": selected_row["run_id"],
        "source_candidate_scale_group_id": selected_row[
            "candidate_scale_group_id"
        ],
        "source_label_raster": str(source_label_raster),
        "centroid_seed_stabilization_report_json": str(
            stabilization_report_path
        ),
        "centroid_seed_stabilization_source_run_id": selected_row["run_id"],
        "selected_labels_tif": str(selected_labels_tif),
        "selected_segments_gpkg": str(selected_segments_gpkg),
        "manifest_json": str(manifest_path),
        "step_manifest_json": str(step_manifest_json),
        "selected_candidate_id": selected_row["candidate_scale_group_id"],
        "selected_source": selected_row["step10_selected_role"],
        "selected_representative_id": selected_row["run_id"],
    }


def run_level1b_step10_compute_exactextractr_segment_stats_and_quality_info(
    output_dir: str | Path,
    *,
    step10_subdir: str = DEFAULT_STEP10_SUBDIR,
) -> dict:
    output_root = Path(output_dir)
    step10_dir = _step10_root_dir(output_root, step10_subdir=step10_subdir)
    final_segments_dir = step10_dir / "final_segments"
    selected_labels_tif = final_segments_dir / "selected_labels.tif"
    selected_segments_gpkg = final_segments_dir / "selected_segments.gpkg"
    selected_segments_manifest_json = (
        final_segments_dir / "selected_segments_manifest.json"
    )
    evidence_json_path = _step10_finalist_evidence_path(
        output_root, step10_subdir=step10_subdir
    )

    json.loads(selected_segments_manifest_json.read_text(encoding="utf-8"))
    evidence = _read_step10_finalist_evidence(
        output_root, step10_subdir=step10_subdir
    )
    selected_row = _selected_representative_run(evidence)
    [selected_group_aggregation_row] = [
        row
        for row in evidence["group_aggregation_rows"]
        if row["step10_selected_candidate"] is True
    ]
    selected_candidate_id = selected_row["candidate_scale_group_id"]
    selected_source = selected_row["step10_selected_role"]
    selected_representative_id = selected_row["run_id"]
    value_raster = Path(selected_row["masked_segmentation_stack_path"])
    valid_mask_path = Path(selected_row["valid_mask_path"])

    segment_stats_dir = step10_dir / "segment_stats"
    quality_dir = step10_dir / "quality"
    segment_stats_dir.mkdir(parents=True, exist_ok=True)
    quality_dir.mkdir(parents=True, exist_ok=True)
    stats_csv = segment_stats_dir / "selected_segment_exactextractr_stats.csv"
    summary_json = (
        segment_stats_dir / "selected_segment_exactextractr_summary.json"
    )
    quality_info_json = quality_dir / "ortho_segmentation_quality_info.json"
    r_script = (
        Path(__file__).resolve().parents[2]
        / "R"
        / "level1b_step10_exactextractr_segment_stats.R"
    )

    subprocess.run(
        [
            "Rscript",
            str(r_script),
            str(selected_segments_gpkg),
            str(value_raster),
            str(valid_mask_path),
            str(stats_csv),
            str(summary_json),
            selected_candidate_id,
            selected_source,
            selected_representative_id,
        ],
        check=True,
    )
    segment_stats_summary = json.loads(summary_json.read_text(encoding="utf-8"))

    selected_run_field_names = [
        "run_id",
        "candidate_scale_group_id",
        "segment_count",
        "segment_density_per_ha",
        "total_labelled_area_m2",
        "mean_area_m2",
        "median_area_m2",
        "q10_area_m2",
        "q25_area_m2",
        "q50_area_m2",
        "q75_area_m2",
        "q90_area_m2",
        "q95_area_m2",
        "central_area_share",
        "upper_tail_area_share",
        "lower_tail_area_share",
        "in_scale_area_share",
        "large_area_share",
        "oversize_area_share",
    ]
    quality_info = {
        "status": "step10_part5_quality_info_ready",
        "quality_signal_status": "evidence_ready",
        "quality_signal_scope": "ortho_segmentation_run",
        "quality_signal_reason": (
            "Step-10 evidence, selected segment products, and exactextractr "
            "segment statistics are available; no thresholded quality class "
            "is assigned."
        ),
        "selected_candidate_id": selected_candidate_id,
        "selected_source": selected_source,
        "selected_representative_id": selected_representative_id,
        "source_files": {
            "selected_labels_tif": str(selected_labels_tif),
            "selected_segments_gpkg": str(selected_segments_gpkg),
            "selected_segments_manifest_json": str(
                selected_segments_manifest_json
            ),
            "finalist_evidence_json": str(evidence_json_path),
            "selected_segment_exactextractr_stats_csv": str(stats_csv),
            "selected_segment_exactextractr_summary_json": str(summary_json),
        },
        "value_raster_used": str(value_raster),
        "valid_mask_path": str(valid_mask_path),
        "selected_run_fields": {
            field: selected_row[field]
            for field in selected_run_field_names
            if field in selected_row
        },
        "selected_group_aggregation_row": selected_group_aggregation_row,
        "segment_stats_summary": segment_stats_summary,
    }
    quality_info_json.write_text(
        json.dumps(quality_info, indent=2), encoding="utf-8"
    )

    manifest_path = write_step_manifest(
        output_dir,
        step=_step10_manifest_step_name("step10_quality", step10_subdir),
        status="step10_part5_exactextractr_segment_stats_and_quality_info_ready",
        inputs={
            "selected_labels_tif": selected_labels_tif,
            "selected_segments_gpkg": selected_segments_gpkg,
            "selected_segments_manifest_json": selected_segments_manifest_json,
            "finalist_evidence_json": evidence_json_path,
        },
        artifacts={
            "selected_segment_exactextractr_stats_csv": stats_csv,
            "selected_segment_exactextractr_summary_json": summary_json,
            "ortho_segmentation_quality_info_json": quality_info_json,
        },
        candidate_id=selected_candidate_id,
    )

    return {
        "status": (
            "step10_part5_exactextractr_segment_stats_and_quality_info_ready"
        ),
        "output_dir": str(output_dir),
        "segment_stats_dir": str(segment_stats_dir),
        "quality_dir": str(quality_dir),
        "selected_segment_exactextractr_stats_csv": str(stats_csv),
        "selected_segment_exactextractr_summary_json": str(summary_json),
        "ortho_segmentation_quality_info_json": str(quality_info_json),
        "selected_candidate_id": selected_candidate_id,
        "selected_source": selected_source,
        "selected_representative_id": selected_representative_id,
        "value_raster_used": str(value_raster),
        "valid_mask_path": str(valid_mask_path),
        "manifest_json": str(manifest_path),
    }
