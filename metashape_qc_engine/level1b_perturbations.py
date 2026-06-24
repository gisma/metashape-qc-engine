from dataclasses import dataclass
import csv
import json
from pathlib import Path


PERTURBATION_RULE = "baseline_plus_local_one_at_a_time_axis_perturbations"
ROW_FIELDS = (
    "perturbation_id",
    "scale_id",
    "spatialr_px",
    "minsize_px",
    "ranger",
    "deltas",
    "is_baseline",
)
JSON_FIELDS = (
    "candidate_id",
    "scale_candidates_with_ranger_json_path",
    "perturbation_rule",
    "spatialr_delta_px",
    "minsize_delta_fraction",
    "ranger_delta_fraction",
    "source_candidate_count",
    "perturbation_count",
    "candidates",
)
CHECK_KEYS = (
    "candidate_id_non_empty",
    "scale_candidates_with_ranger_json_path_exists",
    "scale_candidates_with_ranger_json_path_suffix_json",
    "spatialr_delta_px_positive_integer",
    "minsize_delta_fraction_valid",
    "ranger_delta_fraction_valid",
    "output_csv_path_available",
    "output_json_path_available",
)


@dataclass
class Level1BPerturbationConfig:
    candidate_id: str
    output_dir: str | Path
    scale_candidates_with_ranger_json_path: str | Path
    spatialr_delta_px: int = 1
    minsize_delta_fraction: float = 0.10
    ranger_delta_fraction: float = 0.10
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
    json_path = Path(config.scale_candidates_with_ranger_json_path)
    csv_path = layout["perturbation_dir"] / config.output_csv_filename
    output_json_path = layout["perturbation_dir"] / config.output_json_filename

    if not str(config.candidate_id).strip():
        checks["candidate_id_non_empty"] = False
        failure_reasons.append("candidate_id is empty")
    if not json_path.exists():
        checks["scale_candidates_with_ranger_json_path_exists"] = False
        failure_reasons.append("scale_candidates_with_ranger_json_path does not exist")
    if json_path.suffix.lower() != ".json":
        checks["scale_candidates_with_ranger_json_path_suffix_json"] = False
        failure_reasons.append("scale_candidates_with_ranger_json_path suffix must be .json")
    if (
        not isinstance(config.spatialr_delta_px, int)
        or isinstance(config.spatialr_delta_px, bool)
        or config.spatialr_delta_px <= 0
    ):
        checks["spatialr_delta_px_positive_integer"] = False
        failure_reasons.append("spatialr_delta_px must be a positive integer")
    if (
        not isinstance(config.minsize_delta_fraction, (int, float))
        or isinstance(config.minsize_delta_fraction, bool)
        or not 0 < config.minsize_delta_fraction < 1
    ):
        checks["minsize_delta_fraction_valid"] = False
        failure_reasons.append("minsize_delta_fraction must be numeric and > 0 and < 1")
    if (
        not isinstance(config.ranger_delta_fraction, (int, float))
        or isinstance(config.ranger_delta_fraction, bool)
        or not 0 < config.ranger_delta_fraction < 1
    ):
        checks["ranger_delta_fraction_valid"] = False
        failure_reasons.append("ranger_delta_fraction must be numeric and > 0 and < 1")
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
        for field in ("candidate_id", "scale_id", "spatialr_px", "minsize_px", "ranger"):
            if field not in candidate:
                raise ValueError(f"candidate field {field} is missing")

        try:
            spatialr_px = int(candidate["spatialr_px"])
        except (TypeError, ValueError) as exc:
            raise ValueError("spatialr_px must be convertible to int and >= 1") from exc
        if spatialr_px < 1:
            raise ValueError("spatialr_px must be convertible to int and >= 1")

        try:
            minsize_px = int(candidate["minsize_px"])
        except (TypeError, ValueError) as exc:
            raise ValueError("minsize_px must be convertible to int and >= 1") from exc
        if minsize_px < 1:
            raise ValueError("minsize_px must be convertible to int and >= 1")

        try:
            ranger = float(candidate["ranger"])
        except (TypeError, ValueError) as exc:
            raise ValueError("ranger must be convertible to float and > 0") from exc
        if ranger <= 0:
            raise ValueError("ranger must be convertible to float and > 0")

        complete_candidates.append(
            {
                "candidate_id": candidate["candidate_id"],
                "scale_id": candidate["scale_id"],
                "spatialr_px": spatialr_px,
                "minsize_px": minsize_px,
                "ranger": ranger,
            }
        )

    return complete_candidates


def _deltas(axis, direction, spatialr_px, minsize_px, ranger, baseline) -> dict[str, object]:
    return {
        "axis": axis,
        "direction": direction,
        "spatialr_px_delta": spatialr_px - baseline["spatialr_px"],
        "minsize_px_delta": minsize_px - baseline["minsize_px"],
        "ranger_delta": ranger - baseline["ranger"],
    }


def _candidate_row(source_candidate_id, index, scale_id, spatialr_px, minsize_px, ranger, deltas, is_baseline):
    return {
        "perturbation_id": f"{source_candidate_id}__perturb_{index:03d}",
        "scale_id": scale_id,
        "spatialr_px": spatialr_px,
        "minsize_px": minsize_px,
        "ranger": ranger,
        "deltas": deltas,
        "is_baseline": is_baseline,
    }


def build_perturbation_candidates(config, complete_candidates) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []

    for complete_candidate in complete_candidates:
        source_candidate_id = complete_candidate["candidate_id"]
        scale_id = complete_candidate["scale_id"]
        baseline = {
            "spatialr_px": int(complete_candidate["spatialr_px"]),
            "minsize_px": int(complete_candidate["minsize_px"]),
            "ranger": float(complete_candidate["ranger"]),
        }
        retained_index = 0
        baseline_deltas = {
            "axis": "baseline",
            "direction": "baseline",
            "spatialr_px_delta": 0,
            "minsize_px_delta": 0,
            "ranger_delta": 0.0,
        }
        candidates.append(
            _candidate_row(
                source_candidate_id,
                retained_index,
                scale_id,
                baseline["spatialr_px"],
                baseline["minsize_px"],
                baseline["ranger"],
                baseline_deltas,
                True,
            )
        )

        attempts = (
            (
                "spatialr_px",
                "minus",
                max(1, baseline["spatialr_px"] - config.spatialr_delta_px),
                baseline["minsize_px"],
                baseline["ranger"],
            ),
            (
                "spatialr_px",
                "plus",
                baseline["spatialr_px"] + config.spatialr_delta_px,
                baseline["minsize_px"],
                baseline["ranger"],
            ),
            (
                "minsize_px",
                "minus",
                baseline["spatialr_px"],
                max(1, round(baseline["minsize_px"] * (1 - float(config.minsize_delta_fraction)))),
                baseline["ranger"],
            ),
            (
                "minsize_px",
                "plus",
                baseline["spatialr_px"],
                max(1, round(baseline["minsize_px"] * (1 + float(config.minsize_delta_fraction)))),
                baseline["ranger"],
            ),
            (
                "ranger",
                "minus",
                baseline["spatialr_px"],
                baseline["minsize_px"],
                baseline["ranger"] * (1 - float(config.ranger_delta_fraction)),
            ),
            (
                "ranger",
                "plus",
                baseline["spatialr_px"],
                baseline["minsize_px"],
                baseline["ranger"] * (1 + float(config.ranger_delta_fraction)),
            ),
        )

        for axis, direction, spatialr_px, minsize_px, ranger in attempts:
            if (
                spatialr_px == baseline["spatialr_px"]
                and minsize_px == baseline["minsize_px"]
                and ranger == baseline["ranger"]
            ):
                continue
            deltas = _deltas(axis, direction, spatialr_px, minsize_px, ranger, baseline)
            non_zero_delta_count = sum(
                value != 0 for value in (deltas["spatialr_px_delta"], deltas["minsize_px_delta"], deltas["ranger_delta"])
            )
            if non_zero_delta_count != 1:
                raise ValueError("non-baseline perturbation must change exactly one axis")
            retained_index += 1
            candidates.append(
                _candidate_row(source_candidate_id, retained_index, scale_id, spatialr_px, minsize_px, ranger, deltas, False)
            )

    return candidates


def write_perturbation_candidates_csv(candidates, csv_path) -> None:
    with Path(csv_path).open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=ROW_FIELDS)
        writer.writeheader()
        for candidate in candidates:
            row = {field: candidate[field] for field in ROW_FIELDS}
            row["deltas"] = json.dumps(row["deltas"], sort_keys=True, separators=(",", ":"))
            writer.writerow(row)


def write_perturbation_candidates_json(config, candidates, json_path) -> None:
    payload = {
        "candidate_id": str(config.candidate_id).strip(),
        "scale_candidates_with_ranger_json_path": str(Path(config.scale_candidates_with_ranger_json_path)),
        "perturbation_rule": PERTURBATION_RULE,
        "spatialr_delta_px": config.spatialr_delta_px,
        "minsize_delta_fraction": float(config.minsize_delta_fraction),
        "ranger_delta_fraction": float(config.ranger_delta_fraction),
        "source_candidate_count": sum(1 for candidate in candidates if candidate["is_baseline"]),
        "perturbation_count": len(candidates),
        "candidates": candidates,
    }
    with Path(json_path).open("w", encoding="utf-8") as file_obj:
        json.dump({key: payload[key] for key in JSON_FIELDS}, file_obj, indent=2)


def run_local_perturbation_step(config) -> dict[str, object]:
    layout = build_level1b_perturbation_layout(config.output_dir)
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
            status = "ok"
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            failure_reasons.append(str(exc))
            status = "failed"
    else:
        status = "failed"

    return {
        "candidate_id": str(config.candidate_id).strip(),
        "output_dir": str(Path(config.output_dir)),
        "perturbation_dir": str(layout["perturbation_dir"]),
        "scale_candidates_with_ranger_json_path": str(Path(config.scale_candidates_with_ranger_json_path)),
        "output_csv_path": str(csv_path),
        "output_json_path": str(json_path),
        "spatialr_delta_px": config.spatialr_delta_px,
        "minsize_delta_fraction": config.minsize_delta_fraction,
        "ranger_delta_fraction": config.ranger_delta_fraction,
        "checks": checks,
        "status": status,
        "failure_reasons": failure_reasons,
        "source_candidate_count": len(complete_candidates),
        "perturbation_count": len(candidates),
        "candidates": candidates,
        "files_written": files_written,
        "no_global_parameter_matrix_created": True,
        "no_cross_parameter_combinations_created": True,
        "no_segmentation_performed": True,
        "no_otb_used": True,
        "no_raster_read": True,
    }
