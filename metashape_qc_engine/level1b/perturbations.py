from dataclasses import dataclass
import csv
import json
import math
from pathlib import Path
import random

from metashape_qc_engine.level1b.step_manifest import write_step_manifest


PERTURBATION_RULE = "saga_spatial_feature_local_grid"
REQUIRED_CANDIDATE_FIELDS = ("candidate_id", "scale_id", "spatialr_px", "minsize_px", "ranger")
OPTIONAL_PASSTHROUGH_FIELDS = ("radius_m", "area_m2", "ranger_id", "ranger_source", "assignment_rule")
ROW_FIELDS = (
    "perturbation_id",
    "source_candidate_id",
    "scale_id",
    "spatialr_px",
    "minsize_px",
    "ranger",
    "deltas",
    "is_baseline",
    "perturbation_rule",
    *OPTIONAL_PASSTHROUGH_FIELDS,
)
JSON_FIELDS = (
    "candidate_id",
    "scale_candidates_with_ranger_json_path",
    "perturbation_rule",
    "K",
    "seed",
    "minsize_floor_frac",
    "input_candidate_count",
    "output_row_count",
    "baseline_row_count",
    "perturbation_row_count",
    "candidates",
    "no_global_parameter_matrix_created",
    "no_cross_parameter_combinations_created",
    "no_segmentation_performed",
    "no_otb_used",
    "no_raster_read",
)
CHECK_KEYS = (
    "candidate_id_non_empty",
    "output_dir_valid",
    "scale_candidates_with_ranger_json_path_present",
    "scale_candidates_with_ranger_json_path_exists",
    "scale_candidates_with_ranger_json_path_suffix_json",
    "K_positive_integer",
    "ds_non_negative_integer",
    "minsize_floor_frac_valid",
    "dr_positive_when_explicit",
    "dm_positive_when_explicit",
    "output_csv_path_available",
    "output_json_path_available",
)


@dataclass
class Level1BPerturbationConfig:
    candidate_id: str
    output_dir: str | Path
    scale_candidates_with_ranger_json_path: str | Path | None
    dr: float | None = None
    ds: int = 1
    dm: int | None = None
    K: int = 8
    minsize_floor_frac: float = 0.8
    seed: int = 1
    output_csv_filename: str = "perturbation_candidates.csv"
    output_json_filename: str = "perturbation_candidates.json"
    overwrite: bool = False


def build_level1b_perturbation_layout(output_dir) -> dict[str, Path]:
    perturbation_dir = Path(output_dir) / "level1b" / "perturbations"
    perturbation_dir.mkdir(parents=True, exist_ok=True)
    return {"perturbation_dir": perturbation_dir}


def validate_perturbation_config(config, layout) -> tuple[dict[str, bool], list[str]]:
    checks = {key: True for key in CHECK_KEYS}
    failure_reasons: list[str] = []
    json_path = Path(config.scale_candidates_with_ranger_json_path) if config.scale_candidates_with_ranger_json_path else None
    csv_path = layout["perturbation_dir"] / config.output_csv_filename
    output_json_path = layout["perturbation_dir"] / config.output_json_filename

    if not str(config.candidate_id).strip():
        checks["candidate_id_non_empty"] = False
        failure_reasons.append("candidate_id is empty")
    if not Path(config.output_dir).is_dir():
        checks["output_dir_valid"] = False
        failure_reasons.append("output_dir is invalid")
    if json_path is None:
        checks["scale_candidates_with_ranger_json_path_present"] = False
        checks["scale_candidates_with_ranger_json_path_exists"] = False
        checks["scale_candidates_with_ranger_json_path_suffix_json"] = False
        failure_reasons.append("scale_candidates_with_ranger_json_path is missing")
    else:
        if not json_path.exists():
            checks["scale_candidates_with_ranger_json_path_exists"] = False
            failure_reasons.append("scale_candidates_with_ranger_json_path does not exist")
        if json_path.suffix.lower() != ".json":
            checks["scale_candidates_with_ranger_json_path_suffix_json"] = False
            failure_reasons.append("scale_candidates_with_ranger_json_path suffix must be .json")
    if not _is_positive_int(config.K):
        checks["K_positive_integer"] = False
        failure_reasons.append("K must be a positive integer")
    if not _is_non_negative_int(config.ds):
        checks["ds_non_negative_integer"] = False
        failure_reasons.append("ds must be a non-negative integer")
    if (
        not _is_finite_number(config.minsize_floor_frac)
        or float(config.minsize_floor_frac) <= 0
        or float(config.minsize_floor_frac) > 1
    ):
        checks["minsize_floor_frac_valid"] = False
        failure_reasons.append("minsize_floor_frac must be numeric and > 0 and <= 1")
    if config.dr is not None and (not _is_finite_number(config.dr) or float(config.dr) <= 0):
        checks["dr_positive_when_explicit"] = False
        failure_reasons.append("dr must be positive when explicit")
    if config.dm is not None and (not _is_finite_number(config.dm) or float(config.dm) <= 0):
        checks["dm_positive_when_explicit"] = False
        failure_reasons.append("dm must be positive when explicit")
    if csv_path.exists() and not config.overwrite:
        checks["output_csv_path_available"] = False
        failure_reasons.append("perturbation_candidates.csv already exists and overwrite is false")
    if output_json_path.exists() and not config.overwrite:
        checks["output_json_path_available"] = False
        failure_reasons.append("perturbation_candidates.json already exists and overwrite is false")

    return checks, failure_reasons


def read_scale_candidates_with_ranger(json_path) -> list[dict[str, object]]:
    with Path(json_path).open(encoding="utf-8") as file_obj:
        payload = json.load(file_obj)

    if "candidates" not in payload:
        raise ValueError("candidates key is missing")
    if not payload["candidates"]:
        raise ValueError("candidates is empty")

    complete_candidates: list[dict[str, object]] = []
    for candidate in payload["candidates"]:
        for field in REQUIRED_CANDIDATE_FIELDS:
            if field not in candidate:
                raise ValueError(f"candidate field {field} is missing")

        spatialr_px = _positive_int_field(candidate["spatialr_px"], "spatialr_px")
        minsize_px = _positive_int_field(candidate["minsize_px"], "minsize_px")
        ranger = _positive_float_field(candidate["ranger"], "ranger")

        complete_candidate = {
            "candidate_id": candidate["candidate_id"],
            "scale_id": candidate["scale_id"],
            "spatialr_px": spatialr_px,
            "minsize_px": minsize_px,
            "ranger": ranger,
        }
        for field in OPTIONAL_PASSTHROUGH_FIELDS:
            if field in candidate:
                complete_candidate[field] = candidate[field]
        complete_candidates.append(complete_candidate)

    return complete_candidates


def build_perturbation_candidates(config, complete_candidates) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []

    for complete_candidate in complete_candidates:
        source_candidate_id = str(complete_candidate["candidate_id"])
        baseline = {
            "spatialr_px": int(complete_candidate["spatialr_px"]),
            "minsize_px": int(complete_candidate["minsize_px"]),
            "ranger": float(complete_candidate["ranger"]),
        }
        passthrough = {field: complete_candidate[field] for field in OPTIONAL_PASSTHROUGH_FIELDS if field in complete_candidate}
        candidates.append(
            _candidate_row(
                perturbation_id=f"{source_candidate_id}__baseline",
                source_candidate_id=source_candidate_id,
                scale_id=complete_candidate["scale_id"],
                spatialr_px=baseline["spatialr_px"],
                minsize_px=baseline["minsize_px"],
                ranger=baseline["ranger"],
                deltas=_deltas(baseline["spatialr_px"], baseline["minsize_px"], baseline["ranger"], baseline),
                is_baseline=True,
                passthrough=passthrough,
            )
        )

        dr = float(config.dr) if config.dr is not None else max(0.005, 0.10 * baseline["ranger"])
        ds = int(config.ds)
        if baseline["spatialr_px"] <= 3:
            ds = 0

        cand_spatialr = _unique(max(1, baseline["spatialr_px"] + delta) for delta in (-ds, 0, ds))
        cand_ranger = _unique(max(1e-6, baseline["ranger"] + delta) for delta in (-dr, 0.0, dr))
        local_rows: list[tuple[int, int, float]] = []
        seen: set[tuple[int, int, float]] = set()

        # SAGA Seeded Region Growing has no minimum-size merge parameter.
        # Keep minsize_px as scale provenance, but never vary it independently:
        # minsize-only rows would execute identical segmentations and inflate
        # stability evidence with duplicate results.
        for spatialr_px in cand_spatialr:
            for ranger in cand_ranger:
                minsize_px = baseline["minsize_px"]
                if _same_parameters(spatialr_px, minsize_px, ranger, baseline):
                    continue
                key = (spatialr_px, minsize_px, ranger)
                if key in seen:
                    continue
                seen.add(key)
                local_rows.append(key)

        if len(local_rows) > int(config.K):
            local_rows = random.Random(config.seed).sample(local_rows, int(config.K))

        for index, (spatialr_px, minsize_px, ranger) in enumerate(local_rows, start=1):
            candidates.append(
                _candidate_row(
                    perturbation_id=f"{source_candidate_id}__perturb_{index:03d}",
                    source_candidate_id=source_candidate_id,
                    scale_id=complete_candidate["scale_id"],
                    spatialr_px=spatialr_px,
                    minsize_px=minsize_px,
                    ranger=ranger,
                    deltas=_deltas(spatialr_px, minsize_px, ranger, baseline),
                    is_baseline=False,
                    passthrough=passthrough,
                )
            )

    return candidates


def write_perturbation_candidates_csv(candidates, csv_path) -> None:
    with Path(csv_path).open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=ROW_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for candidate in candidates:
            row = {field: candidate.get(field, "") for field in ROW_FIELDS}
            row["deltas"] = json.dumps(row["deltas"], sort_keys=True, separators=(",", ":"))
            writer.writerow(row)


def write_perturbation_candidates_json(config, candidates, json_path) -> None:
    payload = _json_payload(config, candidates)
    with Path(json_path).open("w", encoding="utf-8") as file_obj:
        json.dump({key: payload[key] for key in JSON_FIELDS}, file_obj, indent=2)


def run_local_perturbation_step(config) -> dict[str, object]:
    try:
        layout = build_level1b_perturbation_layout(config.output_dir)
    except OSError as exc:
        layout = {"perturbation_dir": Path(config.output_dir) / "level1b" / "perturbations"}
        checks = {key: True for key in CHECK_KEYS}
        checks["output_dir_valid"] = False
        failure_reasons = [f"output_dir is invalid: {exc}"]
        return _run_report(config, layout, checks, failure_reasons, [], [], [])

    csv_path = layout["perturbation_dir"] / config.output_csv_filename
    json_path = layout["perturbation_dir"] / config.output_json_filename
    checks, failure_reasons = validate_perturbation_config(config, layout)
    complete_candidates: list[dict[str, object]] = []
    candidates: list[dict[str, object]] = []
    files_written: list[str] = []

    if not failure_reasons:
        try:
            complete_candidates = read_scale_candidates_with_ranger(config.scale_candidates_with_ranger_json_path)
            candidates = build_perturbation_candidates(config, complete_candidates)
            write_perturbation_candidates_csv(candidates, csv_path)
            write_perturbation_candidates_json(config, candidates, json_path)
            files_written = [str(csv_path), str(json_path)]
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            failure_reasons.append(str(exc))

    return _run_report(config, layout, checks, failure_reasons, complete_candidates, candidates, files_written)


def _run_report(config, layout, checks, failure_reasons, complete_candidates, candidates, files_written) -> dict[str, object]:
    csv_path = layout["perturbation_dir"] / config.output_csv_filename
    json_path = layout["perturbation_dir"] / config.output_json_filename
    baseline_count = sum(1 for candidate in candidates if candidate["is_baseline"])
    perturbation_count = len(candidates) - baseline_count
    report = {
        "candidate_id": str(config.candidate_id).strip(),
        "output_dir": str(Path(config.output_dir)),
        "perturbation_dir": str(layout["perturbation_dir"]),
        "scale_candidates_with_ranger_json_path": (
            str(Path(config.scale_candidates_with_ranger_json_path)) if config.scale_candidates_with_ranger_json_path else ""
        ),
        "output_csv_path": str(csv_path),
        "output_json_path": str(json_path),
        "perturbation_rule": PERTURBATION_RULE,
        "K": config.K,
        "seed": config.seed,
        "minsize_floor_frac": config.minsize_floor_frac,
        "checks": checks,
        "status": "failed" if failure_reasons else "ok",
        "failure_reasons": failure_reasons,
        "input_candidate_count": len(complete_candidates),
        "source_candidate_count": len(complete_candidates),
        "output_row_count": len(candidates),
        "baseline_row_count": baseline_count,
        "perturbation_row_count": perturbation_count,
        "perturbation_count": perturbation_count,
        "candidates": candidates,
        "files_written": files_written,
        "no_global_parameter_matrix_created": True,
        "no_cross_parameter_combinations_created": True,
        "no_segmentation_performed": True,
        "no_otb_used": True,
        "no_raster_read": True,
    }
    if Path(config.output_dir).is_dir():
        manifest_inputs = {}
        if config.scale_candidates_with_ranger_json_path is not None:
            manifest_inputs["scale_candidates_with_ranger_json"] = (
                config.scale_candidates_with_ranger_json_path
            )
        write_step_manifest(
            config.output_dir,
            step="perturbations",
            status=report["status"],
            inputs=manifest_inputs,
            artifacts={
                "perturbation_candidates_csv": csv_path,
                "perturbation_candidates_json": json_path,
            },
            candidate_id=str(config.candidate_id).strip(),
        )
    return report


def _json_payload(config, candidates) -> dict[str, object]:
    baseline_count = sum(1 for candidate in candidates if candidate["is_baseline"])
    return {
        "candidate_id": str(config.candidate_id).strip(),
        "scale_candidates_with_ranger_json_path": str(Path(config.scale_candidates_with_ranger_json_path)),
        "perturbation_rule": PERTURBATION_RULE,
        "K": config.K,
        "seed": config.seed,
        "minsize_floor_frac": float(config.minsize_floor_frac),
        "input_candidate_count": baseline_count,
        "output_row_count": len(candidates),
        "baseline_row_count": baseline_count,
        "perturbation_row_count": len(candidates) - baseline_count,
        "candidates": candidates,
        "no_global_parameter_matrix_created": True,
        "no_cross_parameter_combinations_created": True,
        "no_segmentation_performed": True,
        "no_otb_used": True,
        "no_raster_read": True,
    }


def _candidate_row(
    perturbation_id,
    source_candidate_id,
    scale_id,
    spatialr_px,
    minsize_px,
    ranger,
    deltas,
    is_baseline,
    passthrough,
):
    row = {
        "perturbation_id": perturbation_id,
        "source_candidate_id": source_candidate_id,
        "scale_id": scale_id,
        "spatialr_px": int(spatialr_px),
        "minsize_px": int(minsize_px),
        "ranger": float(ranger),
        "deltas": deltas,
        "is_baseline": is_baseline,
        "perturbation_rule": PERTURBATION_RULE,
    }
    row.update(passthrough)
    return row


def _deltas(spatialr_px, minsize_px, ranger, baseline) -> dict[str, float | int]:
    minsize_px_delta = int(minsize_px) - baseline["minsize_px"]
    ranger_delta = float(ranger) - baseline["ranger"]
    return {
        "spatialr_px_delta": int(spatialr_px) - baseline["spatialr_px"],
        "minsize_px_delta": minsize_px_delta,
        "ranger_delta": ranger_delta,
        "minsize_delta_fraction": minsize_px_delta / baseline["minsize_px"],
        "ranger_delta_fraction": ranger_delta / baseline["ranger"],
    }


def _same_parameters(spatialr_px, minsize_px, ranger, baseline) -> bool:
    return (
        int(spatialr_px) == baseline["spatialr_px"]
        and int(minsize_px) == baseline["minsize_px"]
        and float(ranger) == baseline["ranger"]
    )


def _unique(values) -> list:
    unique_values = []
    seen = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            unique_values.append(value)
    return unique_values


def _is_positive_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_non_negative_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _positive_int_field(value, field_name) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be finite and > 0")
    try:
        converted = int(value)
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be finite and > 0") from exc
    if not math.isfinite(numeric) or converted <= 0:
        raise ValueError(f"{field_name} must be finite and > 0")
    return converted


def _positive_float_field(value, field_name) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be finite and > 0")
    try:
        converted = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field_name} must be finite and > 0") from exc
    if not math.isfinite(converted) or converted <= 0:
        raise ValueError(f"{field_name} must be finite and > 0")
    return converted
