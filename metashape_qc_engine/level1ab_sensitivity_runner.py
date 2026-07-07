"""Run a compact, YAML-defined Level-1A/Level-1B sensitivity study.

The module contains no scientific selection rule.  It materializes an explicit
run table, calls the existing workflows, and collects their existing numeric
outputs into one table.
"""

from __future__ import annotations

import argparse
import copy
import csv
import itertools
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any, Sequence

import yaml

from metashape_qc_engine.level1a.prepare_product_experiment import (
    read_preset,
    render_variant_id,
)


STAGES = ("plan", "level1a", "level1b", "collect", "all")
TOP_LEVEL_KEYS = {"schema_version", "study", "level1a", "level1b"}
STUDY_KEYS = {"id", "output_root", "overwrite"}
LEVEL1A_KEYS = {
    "image_dir",
    "product_id",
    "project_crs",
    "preset",
    "replicates",
    "metashape_dir",
    "factors",
}
LEVEL1B_KEYS = {
    "base_config",
    "wrapper",
    "otb_root",
    "profiles",
    "sources",
}
SOURCE_KEYS = {"selected_product", "level1a_variants"}
SOURCE_SPEC_KEYS = {"profile_ids", "variant_ids"}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def shell_join(command: Sequence[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in command)


def _require_keys(value: dict[str, Any], required: set[str], label: str) -> None:
    missing = sorted(required - set(value))
    if missing:
        raise ValueError(f"{label} is missing required keys: {', '.join(missing)}")


def _reject_unknown(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{label} contains unknown keys: {', '.join(unknown)}")


def _repo_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (repo_root() / path).resolve()


def load_study_config(path: Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise ValueError("Sensitivity study YAML must decode to an object.")
    _reject_unknown(raw, TOP_LEVEL_KEYS, "study YAML")
    _require_keys(raw, TOP_LEVEL_KEYS, "study YAML")
    if raw["schema_version"] != 1:
        raise ValueError("schema_version must be 1.")

    for name in ("study", "level1a", "level1b"):
        if not isinstance(raw[name], dict):
            raise ValueError(f"{name} must be an object.")
    _reject_unknown(raw["study"], STUDY_KEYS, "study")
    _require_keys(raw["study"], STUDY_KEYS, "study")
    _reject_unknown(raw["level1a"], LEVEL1A_KEYS, "level1a")
    _require_keys(raw["level1a"], LEVEL1A_KEYS, "level1a")
    _reject_unknown(raw["level1b"], LEVEL1B_KEYS, "level1b")
    _require_keys(raw["level1b"], LEVEL1B_KEYS, "level1b")

    if not isinstance(raw["study"]["overwrite"], bool):
        raise ValueError("study.overwrite must be true or false.")
    if int(raw["level1a"]["replicates"]) < 2:
        raise ValueError("level1a.replicates must be at least 2.")
    if not isinstance(raw["level1a"]["factors"], dict):
        raise ValueError("level1a.factors must be an object.")
    for key, values in raw["level1a"]["factors"].items():
        if not isinstance(values, list) or not values:
            raise ValueError(f"level1a factor {key!r} must be a non-empty list.")

    sources = raw["level1b"]["sources"]
    if not isinstance(sources, dict):
        raise ValueError("level1b.sources must be an object.")
    _reject_unknown(sources, SOURCE_KEYS, "level1b.sources")
    _require_keys(sources, SOURCE_KEYS, "level1b.sources")
    for name, spec in sources.items():
        if not isinstance(spec, dict):
            raise ValueError(f"level1b.sources.{name} must be an object.")
        _reject_unknown(spec, SOURCE_SPEC_KEYS, f"level1b.sources.{name}")
        if "profile_ids" not in spec or not isinstance(spec["profile_ids"], list):
            raise ValueError(f"level1b.sources.{name}.profile_ids must be a list.")
        if name == "level1a_variants" and not isinstance(
            spec.get("variant_ids"), list
        ):
            raise ValueError("level1b.sources.level1a_variants.variant_ids must be a list.")

    profile_ids: set[str] = set()
    profiles = raw["level1b"]["profiles"]
    if not isinstance(profiles, list) or not profiles:
        raise ValueError("level1b.profiles must be a non-empty list.")
    for profile in profiles:
        if not isinstance(profile, dict) or set(profile) != {"id", "overrides"}:
            raise ValueError("Each Level-1B profile requires exactly id and overrides.")
        profile_id = str(profile["id"])
        if not profile_id or profile_id in profile_ids:
            raise ValueError(f"Invalid or duplicate Level-1B profile id: {profile_id!r}")
        if not isinstance(profile["overrides"], dict):
            raise ValueError(f"Profile {profile_id!r} overrides must be an object.")
        profile_ids.add(profile_id)
    referenced = {
        str(profile_id)
        for spec in sources.values()
        for profile_id in spec["profile_ids"]
    }
    missing_profiles = sorted(referenced - profile_ids)
    if missing_profiles:
        raise ValueError(
            "Level-1B sources reference unknown profiles: "
            + ", ".join(missing_profiles)
        )
    return raw


def study_root(config: dict[str, Any]) -> Path:
    return Path(config["study"]["output_root"]).expanduser().resolve()


def level1a_paths(config: dict[str, Any]) -> tuple[Path, Path, Path]:
    l1a = config["level1a"]
    output_root = study_root(config) / "level1a"
    preset = read_preset(_repo_path(l1a["preset"]))
    experiment_dir = Path(
        preset["experiment_dir_template"].format(
            output_root=str(output_root),
            product_id=l1a["product_id"],
            reps=int(l1a["replicates"]),
        )
    ).expanduser().resolve()
    return output_root, experiment_dir, _repo_path(l1a["preset"])


def effective_level1a_factors(config: dict[str, Any]) -> dict[str, list[Any]]:
    preset = read_preset(_repo_path(config["level1a"]["preset"]))
    factors = copy.deepcopy(preset["factors"])
    factors.update(copy.deepcopy(config["level1a"]["factors"]))
    factors["project_crs"] = [config["level1a"]["project_crs"]]
    return factors


def planned_level1a_variant_ids(config: dict[str, Any]) -> list[str]:
    preset = read_preset(_repo_path(config["level1a"]["preset"]))
    template_csv = _repo_path(preset["template_variants_csv"])
    with template_csv.open("r", encoding="utf-8", newline="") as handle:
        header = csv.DictReader(handle).fieldnames or []
    factors = effective_level1a_factors(config)
    names = [name for name in factors if name in header]
    ids = []
    for combination in itertools.product(*(factors[name] for name in names)):
        values = dict(zip(names, combination))
        ids.append(render_variant_id(preset["variant_id_template"], values))
    return ids


def _compatible_override(old: Any, new: Any) -> bool:
    if isinstance(old, bool):
        return isinstance(new, bool)
    if isinstance(old, (int, float)) and not isinstance(old, bool):
        return isinstance(new, (int, float)) and not isinstance(new, bool)
    return isinstance(new, type(old))


def apply_profile_overrides(
    base: dict[str, Any], overrides: dict[str, Any]
) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for dotted_key, new_value in overrides.items():
        parts = str(dotted_key).split(".")
        if not parts or any(not part for part in parts):
            raise ValueError(f"Invalid Level-1B override path: {dotted_key!r}")
        node: Any = result
        for part in parts[:-1]:
            if not isinstance(node, dict) or part not in node:
                raise ValueError(f"Unknown Level-1B override path: {dotted_key}")
            node = node[part]
        leaf = parts[-1]
        if not isinstance(node, dict) or leaf not in node:
            raise ValueError(f"Unknown Level-1B override path: {dotted_key}")
        if not _compatible_override(node[leaf], new_value):
            raise ValueError(
                f"Type mismatch for Level-1B override {dotted_key}: "
                f"expected {type(node[leaf]).__name__}, got {type(new_value).__name__}"
            )
        node[leaf] = copy.deepcopy(new_value)
    return result


def materialize_level1b_profiles(config: dict[str, Any]) -> dict[str, Path]:
    base_path = _repo_path(config["level1b"]["base_config"])
    with base_path.open("r", encoding="utf-8") as handle:
        base = yaml.safe_load(handle)
    if not isinstance(base, dict) or not isinstance(base.get("level1b"), dict):
        raise ValueError(f"Invalid Level-1B base config: {base_path}")

    config_dir = study_root(config) / "level1b" / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for profile in config["level1b"]["profiles"]:
        profile_id = str(profile["id"])
        resolved = apply_profile_overrides(base["level1b"], profile["overrides"])
        path = config_dir / f"{profile_id}.yaml"
        with path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(
                {"level1b": resolved},
                handle,
                sort_keys=False,
                default_flow_style=False,
            )
        paths[profile_id] = path
    return paths


def planned_rows(config: dict[str, Any]) -> list[dict[str, str]]:
    root = study_root(config)
    _, experiment_dir, _ = level1a_paths(config)
    variants = planned_level1a_variant_ids(config)
    rows: list[dict[str, str]] = []
    for variant_id in variants:
        for replicate in range(1, int(config["level1a"]["replicates"]) + 1):
            rows.append(
                {
                    "workflow": "level1a",
                    "run_id": f"{variant_id}__rep_{replicate:03d}",
                    "source_kind": "raw_images",
                    "source_id": str(config["level1a"]["product_id"]),
                    "profile_id": variant_id,
                    "replicate": str(replicate),
                    "output_dir": str(experiment_dir),
                }
            )

    profile_paths = materialize_level1b_profiles(config)
    sources = config["level1b"]["sources"]
    for profile_id in sources["selected_product"]["profile_ids"]:
        run_id = f"selected_product__{profile_id}"
        rows.append(
            {
                "workflow": "level1b",
                "run_id": run_id,
                "source_kind": "selected_product",
                "source_id": "selected_product",
                "profile_id": str(profile_id),
                "replicate": "",
                "output_dir": str(root / "level1b" / "runs" / run_id),
                "config_path": str(profile_paths[str(profile_id)]),
            }
        )
    planned_variants = set(variants)
    requested_variants = {
        str(value) for value in sources["level1a_variants"]["variant_ids"]
    }
    unknown_variants = sorted(requested_variants - planned_variants)
    if unknown_variants:
        raise ValueError(
            "Level-1B propagation references unknown Level-1A variants: "
            + ", ".join(unknown_variants)
        )
    for variant_id in sources["level1a_variants"]["variant_ids"]:
        for profile_id in sources["level1a_variants"]["profile_ids"]:
            run_id = f"variant_{variant_id}__{profile_id}"
            rows.append(
                {
                    "workflow": "level1b",
                    "run_id": run_id,
                    "source_kind": "level1a_variant",
                    "source_id": str(variant_id),
                    "profile_id": str(profile_id),
                    "replicate": "",
                    "output_dir": str(root / "level1b" / "runs" / run_id),
                    "config_path": str(profile_paths[str(profile_id)]),
                }
            )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({str(key) for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_plan(config: dict[str, Any]) -> Path:
    path = study_root(config) / "study_design.csv"
    _write_csv(path, planned_rows(config))
    return path


def _factor_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def run_command(command: list[str], *, env: dict[str, str] | None = None) -> int:
    print(shell_join(command), flush=True)
    result = subprocess.run(command, env=env, check=False)
    return int(result.returncode)


def run_level1a(config: dict[str, Any]) -> Path:
    l1a = config["level1a"]
    output_root, experiment_dir, preset_path = level1a_paths(config)
    prepare = [
        sys.executable,
        "-m",
        "metashape_qc_engine.cli",
        "prepare",
        "--image-dir",
        str(Path(l1a["image_dir"]).expanduser().resolve()),
        "--product-id",
        str(l1a["product_id"]),
        "--preset",
        str(preset_path),
        "--reps",
        str(l1a["replicates"]),
        "--output-root",
        str(output_root),
        "--factor",
        f"project_crs={l1a['project_crs']}",
    ]
    for name, values in l1a["factors"].items():
        prepare.extend(
            ["--factor", f"{name}={','.join(_factor_text(v) for v in values)}"]
        )
    if config["study"]["overwrite"]:
        prepare.append("--overwrite")
    if run_command(prepare) != 0:
        raise RuntimeError("Level-1A prepare failed.")

    run = [
        sys.executable,
        "-m",
        "metashape_qc_engine.cli",
        "run-analysis",
        str(experiment_dir / "config.yml"),
        "--variants",
        str(experiment_dir / "variants.csv"),
        "--reps",
        str(l1a["replicates"]),
        "--run-dir",
        str(experiment_dir),
    ]
    if l1a.get("metashape_dir"):
        run.extend(["--metashape-dir", str(_repo_path(l1a["metashape_dir"]))])
    if config["study"]["overwrite"]:
        run.append("--overwrite")
    if run_command(run) != 0:
        raise RuntimeError("Level-1A run-analysis failed.")

    evaluate = [
        sys.executable,
        "-m",
        "metashape_qc_engine.cli",
        "evaluate",
        str(experiment_dir),
    ]
    if run_command(evaluate) != 0:
        raise RuntimeError("Level-1A evaluate failed.")
    return experiment_dir


def level1b_sources(config: dict[str, Any]) -> list[dict[str, str]]:
    _, experiment_dir, _ = level1a_paths(config)
    selected_path = experiment_dir / "selected_product.json"
    with selected_path.open("r", encoding="utf-8") as handle:
        selected = json.load(handle)
    selected_ortho = Path(selected["product_modes"]["median_ortho"]["path"])

    sources = config["level1b"]["sources"]
    out: list[dict[str, str]] = []
    for profile_id in sources["selected_product"]["profile_ids"]:
        out.append(
            {
                "run_id": f"selected_product__{profile_id}",
                "source_kind": "selected_product",
                "source_id": str(selected["primary_variant_id"]),
                "profile_id": str(profile_id),
                "ortho": str(selected_ortho),
            }
        )
    for variant_id in sources["level1a_variants"]["variant_ids"]:
        ortho = (
            experiment_dir
            / "stability_union"
            / "variants"
            / str(variant_id)
            / "median_ortho.tif"
        )
        for profile_id in sources["level1a_variants"]["profile_ids"]:
            out.append(
                {
                    "run_id": f"variant_{variant_id}__{profile_id}",
                    "source_kind": "level1a_variant",
                    "source_id": str(variant_id),
                    "profile_id": str(profile_id),
                    "ortho": str(ortho),
                }
            )
    return out


def run_level1b(config: dict[str, Any]) -> list[dict[str, Any]]:
    profiles = materialize_level1b_profiles(config)
    wrapper = _repo_path(config["level1b"]["wrapper"])
    if not wrapper.is_file():
        raise FileNotFoundError(f"Level-1B wrapper is missing: {wrapper}")
    root = study_root(config)
    results = []
    for source in level1b_sources(config):
        ortho = Path(source["ortho"])
        if not ortho.is_file():
            raise FileNotFoundError(
                f"Level-1B source orthomosaic is missing: {ortho}"
            )
        run_root = root / "level1b" / "runs" / source["run_id"]
        env = os.environ.copy()
        env.update(
            {
                "ORTHO": str(ortho),
                "RUN_ROOT": str(run_root),
                "OVERWRITE": "1" if config["study"]["overwrite"] else "0",
                "LEVEL1B_CONFIG": str(profiles[source["profile_id"]]),
            }
        )
        if config["level1b"].get("otb_root"):
            env["OTB_ROOT"] = str(_repo_path(config["level1b"]["otb_root"]))
        command = ["bash", str(wrapper)]
        return_code = run_command(command, env=env)
        results.append({**source, "return_code": return_code, "run_root": str(run_root)})
    return results


def _read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _flatten_scalars(prefix: str, value: Any, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _flatten_scalars(f"{prefix}{key}.", child, out)
    elif value is None or isinstance(value, (str, int, float, bool)):
        out[prefix[:-1]] = value


def collect_results(config: dict[str, Any]) -> Path:
    _, experiment_dir, _ = level1a_paths(config)
    rows: list[dict[str, Any]] = []
    l1a_metrics = experiment_dir / "stability_union" / "summary_key_metrics.tsv"
    if l1a_metrics.is_file():
        for source in _read_tsv(l1a_metrics):
            rows.append({"workflow": "level1a", **source})

    for source in level1b_sources(config):
        run_root = study_root(config) / "level1b" / "runs" / source["run_id"]
        row: dict[str, Any] = {
            "workflow": "level1b",
            "run_id": source["run_id"],
            "source_kind": source["source_kind"],
            "source_id": source["source_id"],
            "profile_id": source["profile_id"],
            "ortho": source["ortho"],
        }
        report_path = run_root / "level1b_dumb_chain_report.json"
        if report_path.is_file():
            with report_path.open("r", encoding="utf-8") as handle:
                report = json.load(handle)
            row["status"] = report.get("status")
            row["branch"] = report.get("branch")
            row["candidate_id"] = report.get("candidate_id")
        else:
            row["status"] = "not_run"

        quality_path = (
            run_root
            / "level1b"
            / "step10_materialization"
            / "quality"
            / "ortho_segmentation_quality_info.json"
        )
        if quality_path.is_file():
            with quality_path.open("r", encoding="utf-8") as handle:
                quality = json.load(handle)
            for key in (
                "selected_candidate_id",
                "selected_source",
                "selected_representative_id",
            ):
                row[key] = quality.get(key)
            _flatten_scalars(
                "selected_run.", quality.get("selected_run_fields", {}), row
            )

        handoff_path = (
            run_root
            / "level1b"
            / "local_transition_refinement"
            / "step9b_midpoint_gain_share_handoff.json"
        )
        if handoff_path.is_file():
            with handoff_path.open("r", encoding="utf-8") as handle:
                handoff = json.load(handle)
            for key in ("S1", "S2", "SM", "midpoint_gain_share"):
                row[f"handoff.{key}"] = handoff.get(key)
        rows.append(row)

    output = study_root(config) / "study_results.csv"
    _write_csv(output, rows)
    report = {
        "status": "level1ab_sensitivity_results_collected",
        "study_id": config["study"]["id"],
        "study_design_csv": str(study_root(config) / "study_design.csv"),
        "study_results_csv": str(output),
        "row_count": len(rows),
        "level1a_row_count": sum(row["workflow"] == "level1a" for row in rows),
        "level1b_row_count": sum(row["workflow"] == "level1b" for row in rows),
    }
    (study_root(config) / "sensitivity_study_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return output


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the explicit Level-1A/Level-1B sensitivity study."
    )
    parser.add_argument("--study", required=True, type=Path)
    parser.add_argument("--stage", choices=STAGES, default="all")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_study_config(args.study)
    root = study_root(config)
    root.mkdir(parents=True, exist_ok=True)

    plan_path = write_plan(config)
    print(f"Study design: {plan_path}")
    if args.stage == "plan":
        return 0
    if args.stage in {"level1a", "all"}:
        print(f"Level-1A experiment: {run_level1a(config)}")
    if args.stage in {"level1b", "all"}:
        results = run_level1b(config)
        failures = [row for row in results if row["return_code"] not in {0, 2}]
        if failures:
            print(
                f"Level-1B completed with {len(failures)} failed runs; collecting all results.",
                file=sys.stderr,
            )
    if args.stage in {"collect", "all"}:
        print(f"Study results: {collect_results(config)}")
    return 1 if args.stage in {"level1b", "all"} and failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
