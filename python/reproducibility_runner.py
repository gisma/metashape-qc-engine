#!/usr/bin/env python3
# Copyright (c) 2026 Chris Reudenbach, Lars Opgenoorth, Christian Mestre Runge
"""
Run reproducibility experiments for the automate-metashape workflow.

The runner can operate in two modes:

1. Simple replicate mode:
   one base YAML -> N independent replicate builds

2. Variant mode:
   one base YAML + CSV variant table -> variants x N independent replicate builds

The runner does not change the photogrammetric workflow itself.
It generates temporary YAML files, runs the platform-specific Metashape launcher,
and writes a manifest for later orthomosaic stability analysis.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml


SKIP = object()

MANIFEST_COLUMNS = [
    "experiment_id",
    "variant_id",
    "replicate",
    "status",
    "return_code",
    "config_file",
    "project_dir",
    "output_dir",
    "project_file",
    "ortho_file",
    "launcher_log",
    "elapsed_sec",
]

MANIFEST_STATUSES = {"ok", "ok_no_ortho", "failed"}


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def parse_variant_value(value: str) -> Any:
    value = value.strip()

    if value == "":
        return SKIP

    if value.lower() in {"null", "none", "na"}:
        return SKIP

    if value.lower() == "true":
        return True

    if value.lower() == "false":
        return False

    try:
        parsed = yaml.safe_load(value)
    except Exception:
        return value

    return parsed


def set_nested(cfg: dict[str, Any], dotted_key: str, value: Any) -> None:
    keys = dotted_key.split(".")
    cur = cfg

    for key in keys[:-1]:
        if key not in cur or not isinstance(cur[key], dict):
            cur[key] = {}
        cur = cur[key]

    cur[keys[-1]] = value


def sanitize_id(value: str) -> str:
    value = value.strip()
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    value = value.strip("_")
    if not value:
        raise RuntimeError("Empty variant_id after sanitizing.")
    return value


def read_variants(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return [{"variant_id": "default", "overrides": {}}]

    variants: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)

        if "variant_id" not in (reader.fieldnames or []):
            raise RuntimeError("Variant CSV must contain a 'variant_id' column.")

        for row in reader:
            variant_id = sanitize_id(row["variant_id"])
            overrides: dict[str, Any] = {}

            for key, raw_value in row.items():
                if key == "variant_id":
                    continue

                if raw_value is None:
                    continue

                value = parse_variant_value(raw_value)
                if value is SKIP:
                    continue

                overrides[key] = value

            variants.append(
                {
                    "variant_id": variant_id,
                    "overrides": overrides,
                }
            )

    if not variants:
        raise RuntimeError(f"No variants found in: {path}")

    return variants


def apply_overrides(cfg: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(cfg)

    for dotted_key, value in overrides.items():
        set_nested(out, dotted_key, value)

    return out


PREPARED_CONTROL_FILES = {"config.yml", "variants.csv"}


def is_run_dir_only_prepared_controls(path: Path) -> bool:
    if not path.exists():
        return True
    if not path.is_dir():
        return False
    entries = list(path.iterdir())
    if not entries:
        return True
    return all(entry.is_file() and entry.name in PREPARED_CONTROL_FILES for entry in entries)


def ensure_experiment_dir(path: Path, overwrite: bool) -> None:
    if path.exists() and any(path.iterdir()) and not overwrite:
        if is_run_dir_only_prepared_controls(path):
            print(
                f"Run directory contains only prepared control files; continuing without --overwrite: {path}",
                file=sys.stderr,
            )
        else:
            raise RuntimeError(
                "Run directory contains analysis artifacts or unrecognized files.\n"
                f"Conflicting path: {path}\n"
                "Execution stopped to avoid mixing this run with existing files.\n"
                "Prepared-control-only directories containing config.yml and/or variants.csv are accepted without --overwrite.\n"
                "Analysis artifacts such as manifest.csv, replicate directories, Metashape project files, "
                "orthomosaic outputs, stability/evaluation outputs, selected_product.json, "
                "generic_ortho_resolution.* reports, or analyzer/evaluation output directories require a new "
                "run directory or explicit --overwrite.\n"
                "Safe options:\n"
                "  1. Choose a new --run-dir.\n"
                "  2. Use resume-analysis for an interrupted run.\n"
                "  3. Use --overwrite only if intentionally reusing or replacing an existing run directory."
            )

    path.mkdir(parents=True, exist_ok=True)


def format_existing_manifest_error(manifest_file: Path) -> str:
    return (
        "Run manifest already exists.\n"
        f"Conflicting path: {manifest_file}\n"
        "Execution stopped to avoid overwriting or appending to an existing run manifest.\n"
        "Safe options:\n"
        "  1. Choose a new --run-dir.\n"
        "  2. Use resume-analysis for an interrupted run.\n"
        "  3. Use --overwrite only if intentionally reusing or replacing an existing run directory."
    )


def shell_join(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def analysis_command(
    command_name: str,
    base_config: Path,
    variants_file: Path | None,
    experiment_dir: Path,
    reps: int,
    metashape_dir: str | None,
) -> list[str]:
    command = [
        "metashape-qc",
        command_name,
        str(base_config),
        "--reps",
        str(reps),
        "--run-dir",
        str(experiment_dir),
    ]
    if variants_file is not None:
        command.extend(["--variants", str(variants_file)])
    if metashape_dir:
        command.extend(["--metashape-dir", metashape_dir])
    return command


def evaluate_command(experiment_dir: Path) -> list[str]:
    return ["metashape-qc", "evaluate", str(experiment_dir)]


def has_remaining_failures(
    variants: list[dict[str, Any]],
    reps: int,
    latest_rows: dict[tuple[str, str], dict[str, str]],
) -> bool:
    for variant in variants:
        variant_id = variant["variant_id"]
        for i in range(1, reps + 1):
            row = latest_rows.get((variant_id, f"rep_{i:03d}"))
            if row is None or row.get("status") == "failed":
                return True
    return False


def print_next_commands(
    *,
    resume: bool,
    failed_count: int,
    remaining_failures: bool,
    base_config: Path,
    variants_file: Path | None,
    experiment_dir: Path,
    reps: int,
    metashape_dir: str | None,
) -> None:
    resume_cmd = analysis_command(
        "resume-analysis",
        base_config,
        variants_file,
        experiment_dir,
        reps,
        metashape_dir,
    )
    evaluate_cmd = evaluate_command(experiment_dir)

    print("Next commands:")
    if resume:
        print(f"  {shell_join(evaluate_cmd)}")
        if failed_count or remaining_failures:
            print(f"  {shell_join(resume_cmd)}")
    elif failed_count:
        print(f"  {shell_join(resume_cmd)}")
        print(f"  After successful or partial runs: {shell_join(evaluate_cmd)}")
    else:
        print(f"  {shell_join(evaluate_cmd)}")


def print_generic_field_screening_next_step() -> None:
    print("Next step:")
    print(
        "  Use recommended_sampling_m_per_px as the technical sampling reference for follow-up product analysis."
    )
    print("  Optional: run product analysis from the GUI if a full analysis is needed.")


def validate_manifest_row(row: dict[str, str]) -> None:
    missing = [col for col in MANIFEST_COLUMNS if col not in row]
    if missing:
        raise RuntimeError(
            "Manifest row is missing required columns: "
            + ", ".join(missing)
        )
    if row["status"] not in MANIFEST_STATUSES:
        raise RuntimeError(f"Invalid manifest status: {row['status']}")


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [{col: row.get(col, "") for col in MANIFEST_COLUMNS} for row in reader]

    for row in rows:
        validate_manifest_row(row)

    return rows


def append_manifest_row(path: Path, row: dict[str, str]) -> None:
    validate_manifest_row(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not path.exists() or path.stat().st_size == 0

    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS)
        if needs_header:
            writer.writeheader()
        writer.writerow(row)


def manifest_key(row: dict[str, str]) -> tuple[str, str]:
    return row["variant_id"], row["replicate"]


def latest_manifest_rows(
    rows: list[dict[str, str]],
) -> tuple[dict[tuple[str, str], dict[str, str]], set[tuple[str, str]]]:
    latest: dict[tuple[str, str], dict[str, str]] = {}
    seen: set[tuple[str, str]] = set()
    duplicates: set[tuple[str, str]] = set()

    for row in rows:
        key = manifest_key(row)
        if key in seen:
            duplicates.add(key)
        seen.add(key)
        latest[key] = row

    return latest, duplicates


def is_resumable_success(row: dict[str, str] | None) -> bool:
    if row is None or row["status"] not in {"ok", "ok_no_ortho"}:
        return False

    required = [
        "config_file",
        "project_dir",
        "output_dir",
        "project_file",
        "launcher_log",
    ]
    return all(row.get(col, "").strip() for col in required)


def find_latest(pattern_dir: Path, pattern: str) -> str:
    files = sorted(
        pattern_dir.glob(pattern),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )
    return str(files[0]) if files else ""


def count_input_images(cfg: dict[str, Any]) -> str:
    photo_paths = cfg.get("photo_path")
    if isinstance(photo_paths, str):
        photo_paths = [photo_paths]
    if not isinstance(photo_paths, list):
        return "unknown"

    total = 0
    found_any_path = False
    for raw_path in photo_paths:
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        photo_path = Path(raw_path).expanduser()
        if not photo_path.is_dir():
            continue
        found_any_path = True
        for path in photo_path.rglob("*"):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix in {".jpg", ".jpeg", ".tif", ".tiff"} and path.name != "dem_usgs.tif":
                total += 1

    if not found_any_path:
        return "unknown"
    return str(total)


def read_ortho_pixel_size_m_per_px(ortho_file: str) -> float | None:
    if not ortho_file:
        return None
    try:
        from osgeo import gdal
    except ImportError:
        return None

    gdal.DontUseExceptions()
    dataset = gdal.Open(ortho_file)
    if dataset is None:
        return None

    gt = dataset.GetGeoTransform()
    if gt is None:
        dataset = None
        return None

    xres = abs(gt[1])
    yres = abs(gt[5])
    dataset = None
    return (xres + yres) / 2


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        for row in rows:
            validate_manifest_row(row)
            writer.writerow(row)


def generic_ortho_resolution_report(row: dict[str, str]) -> dict[str, Any] | None:
    ortho_file = row["ortho_file"]
    pixel_size_mean = read_ortho_pixel_size_m_per_px(ortho_file)
    if pixel_size_mean is None:
        return None

    from osgeo import gdal

    gdal.DontUseExceptions()
    dataset = gdal.Open(ortho_file)
    if dataset is None:
        return None

    gt = dataset.GetGeoTransform()
    if gt is None:
        dataset = None
        return None

    xres = abs(gt[1])
    yres = abs(gt[5])
    report = {
        "ortho_file": ortho_file,
        "xres": xres,
        "yres": yres,
        "pixel_size_mean": pixel_size_mean,
        "xsize": dataset.RasterXSize,
        "ysize": dataset.RasterYSize,
        "recommended_numeric_orthoRes": pixel_size_mean,
    }
    dataset = None
    return report


def write_generic_ortho_resolution_reports(experiment_dir: Path) -> dict[str, Any] | None:
    manifest_file = experiment_dir / "manifest.csv"
    rows = read_manifest(manifest_file)
    usable_rows = [
        row
        for row in rows
        if row["status"] == "ok"
        and row["ortho_file"].strip()
        and Path(row["ortho_file"]).is_file()
    ]

    if len(usable_rows) != 1:
        raise RuntimeError(
            "Expected exactly one successful manifest row with an existing ortho_file "
            f"for --generic-ortho-resolution; found {len(usable_rows)}."
        )

    report = generic_ortho_resolution_report(usable_rows[0])
    if report is None:
        print(
            "Generic ortho resolution report unavailable: could not read produced GeoTIFF pixel size.",
            file=sys.stderr,
        )
        return None

    with (experiment_dir / "generic_ortho_resolution.json").open(
        "w", encoding="utf-8"
    ) as f:
        json.dump(report, f, indent=2)
        f.write("\n")

    with (experiment_dir / "generic_ortho_resolution.tsv").open(
        "w", encoding="utf-8", newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=list(report.keys()), delimiter="\t")
        writer.writeheader()
        writer.writerow(report)

    with (experiment_dir / "generic_ortho_resolution.md").open(
        "w", encoding="utf-8"
    ) as f:
        f.write("- buildOrthomosaic.orthoRes was forced to 0 for this probe run.\n")
        f.write(
            "- The reported resolution was read from the exported GeoTIFF GeoTransform.\n"
        )
        f.write(
            "- recommended_numeric_orthoRes is the value to use manually in later normal product preparation.\n"
        )
    return report


def field_screening_interpretation(
    status: str,
    orthomosaic: str,
    sampling: str,
) -> str:
    if status == "SUCCESS" and orthomosaic == "CREATED":
        if sampling != "unavailable":
            return (
                "Flight is processable; use ~%s m/px as technical sampling reference."
                % sampling
            )
        return "Flight is processable; technical sampling could not be read."
    if status == "FAILED":
        return "Flight is not processable enough for this first-pass orthomosaic check."
    return "Flight needs review before it is used for follow-up analysis."


def format_field_screening_block(summary: dict[str, str]) -> str:
    keys = [
        "status",
        "images",
        "aligned_cameras",
        "alignment",
        "orthomosaic",
        "technical_sampling_m_per_px",
        "recommended_sampling_m_per_px",
        "interpretation",
        "ortho_path",
        "run_dir",
    ]
    lines = ["FIELD SCREENING RESULT"]
    lines.extend("%s: %s" % (key, summary[key]) for key in keys)
    lines.append("END FIELD SCREENING RESULT")
    return "\n".join(lines)


def write_field_screening_summary(
    *,
    experiment_dir: Path,
    base_cfg: dict[str, Any],
    row: dict[str, str] | None,
    failed_count: int,
) -> dict[str, str]:
    ortho_file = row.get("ortho_file", "") if row else ""
    return_code_ok = bool(row and row.get("return_code") == "0")
    ortho_exists = bool(ortho_file and Path(ortho_file).is_file())

    if ortho_exists and return_code_ok:
        status = "SUCCESS"
        orthomosaic = "CREATED"
    elif not ortho_exists:
        status = "FAILED"
        orthomosaic = "MISSING"
    elif failed_count:
        status = "CRITICAL"
        orthomosaic = "CREATED"
    else:
        status = "CRITICAL"
        orthomosaic = "CREATED"

    pixel_size = read_ortho_pixel_size_m_per_px(ortho_file) if ortho_exists else None
    if pixel_size is None:
        sampling = "unavailable"
    else:
        sampling = format(pixel_size, ".12g")

    if orthomosaic == "CREATED":
        alignment = "OK"
    elif status == "FAILED":
        alignment = "UNKNOWN"
    else:
        alignment = "CRITICAL"

    summary = {
        "status": status,
        "images": count_input_images(base_cfg),
        "aligned_cameras": "unknown",
        "alignment": alignment,
        "orthomosaic": orthomosaic,
        "technical_sampling_m_per_px": sampling,
        "recommended_sampling_m_per_px": sampling,
        "interpretation": field_screening_interpretation(status, orthomosaic, sampling),
        "ortho_path": ortho_file if ortho_exists else "unavailable",
        "run_dir": str(experiment_dir),
    }

    block = format_field_screening_block(summary)
    print(block, flush=True)
    with (experiment_dir / "field_screening_summary.txt").open(
        "w", encoding="utf-8"
    ) as f:
        f.write(block)
        f.write("\n")
    with (experiment_dir / "field_screening_summary.json").open(
        "w", encoding="utf-8"
    ) as f:
        json.dump(summary, f, indent=2)
        f.write("\n")
    return summary


def make_replicate_config(
    base_cfg: dict[str, Any],
    variant_id: str,
    base_run_name: str,
    experiment_dir: Path,
    replicate_index: int,
    run_label: str | None = None,
) -> tuple[dict[str, Any], Path, Path, Path]:
    rep = f"rep_{replicate_index:03d}"
    run_label = run_label or rep

    variant_dir = experiment_dir / "variants" / variant_id
    run_dir = variant_dir / "runs" / run_label
    project_dir = run_dir / "psx"
    output_dir = run_dir / "output"
    config_dir = variant_dir / "configs"

    cfg = copy.deepcopy(base_cfg)

    # Reproducibility runs must be independent builds.
    # They must not continue a previously generated PSX file.
    cfg["load_project"] = ""

    cfg["run_name"] = f"{base_run_name}_{variant_id}_{run_label}"
    cfg["project_path"] = str(project_dir) + "/"
    cfg["output_path"] = str(output_dir) + "/"

    rep_config = config_dir / f"{run_label}.yml"

    return cfg, rep_config, project_dir, output_dir


def choose_run_label(
    experiment_dir: Path,
    variant_id: str,
    rep: str,
    prior_rows: list[dict[str, str]],
    resume: bool,
) -> str:
    default_run_dir = experiment_dir / "variants" / variant_id / "runs" / rep
    default_config = experiment_dir / "variants" / variant_id / "configs" / f"{rep}.yml"

    if not resume:
        return rep
    if not prior_rows and not default_run_dir.exists() and not default_config.exists():
        return rep

    return f"{rep}_attempt_{len(prior_rows) + 1:03d}"


def metashape_wrapper_command(repo_root: Path, config_file: Path) -> list[str]:
    if os.name != "nt":
        return [
            str(repo_root / "scripts" / "run_metashape_workflow.sh"),
            str(config_file),
        ]

    powershell = (
        shutil.which("pwsh")
        or shutil.which("powershell.exe")
        or shutil.which("powershell")
    )
    if powershell is None:
        raise RuntimeError("PowerShell is required for the Windows Metashape launcher.")
    return [
        powershell,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(repo_root / "scripts" / "run_metashape_workflow.ps1"),
        str(config_file),
    ]


def run_replicate(
    repo_root: Path,
    config_file: Path,
    launcher_log: Path,
    metashape_dir: str | None,
) -> int:
    env = os.environ.copy()

    if metashape_dir:
        env["METASHAPE_DIR"] = metashape_dir

    cmd = metashape_wrapper_command(repo_root, config_file)

    launcher_log.parent.mkdir(parents=True, exist_ok=True)

    with launcher_log.open("w", encoding="utf-8") as log:
        proc = subprocess.run(
            cmd,
            cwd=str(repo_root),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )

    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run repeated automate-metashape builds for reproducibility analysis."
    )
    parser.add_argument(
        "base_config",
        type=Path,
        help="Base YAML configuration used as template for all replicates.",
    )
    parser.add_argument(
        "--reps",
        type=int,
        required=True,
        help="Number of replicate runs per variant.",
    )
    parser.add_argument(
        "--experiment-dir",
        type=Path,
        required=True,
        help="Directory where replicate configs, projects, outputs and manifest are written.",
    )
    parser.add_argument(
        "--variants",
        type=Path,
        default=None,
        help="Optional CSV table with variant_id and dotted YAML override columns.",
    )
    parser.add_argument(
        "--metashape-dir",
        type=str,
        default=None,
        help="Optional Metashape installation directory. Passed as METASHAPE_DIR.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow writing into an existing non-empty experiment directory.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an existing experiment by skipping successful variant/replicate runs.",
    )
    parser.add_argument(
        "--generic-ortho-resolution",
        action="store_true",
        help="Run one no-variants probe with buildOrthomosaic.orthoRes forced to 0.",
    )

    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    base_config = args.base_config.resolve()
    experiment_dir = args.experiment_dir.resolve()
    variants_file = args.variants.resolve() if args.variants else None

    if args.generic_ortho_resolution and variants_file is not None:
        raise RuntimeError("--generic-ortho-resolution cannot be used with --variants.")
    if args.generic_ortho_resolution and args.reps != 1:
        raise RuntimeError("--generic-ortho-resolution requires --reps 1.")
    if args.reps < 2 and not args.generic_ortho_resolution:
        raise RuntimeError("Use at least --reps 2 for a reproducibility experiment.")

    manifest_file = experiment_dir / "manifest.csv"
    if manifest_file.exists() and not args.resume:
        raise RuntimeError(format_existing_manifest_error(manifest_file))

    ensure_experiment_dir(experiment_dir, overwrite=args.overwrite or args.resume)

    base_cfg = read_yaml(base_config)

    base_run_name = base_cfg.get("run_name") or base_config.stem
    if base_run_name == "from_config_filename":
        base_run_name = base_config.stem

    variants = read_variants(variants_file)

    existing_rows = read_manifest(manifest_file) if manifest_file.exists() else []
    latest_rows, duplicate_keys = latest_manifest_rows(existing_rows)
    rows_by_key: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in existing_rows:
        rows_by_key.setdefault(manifest_key(row), []).append(row)

    if duplicate_keys:
        duplicate_list = ", ".join(
            f"{variant_id}/{rep}" for variant_id, rep in sorted(duplicate_keys)
        )
        print(
            f"Duplicate manifest rows found; latest rows will be used for resume decisions: {duplicate_list}",
            file=sys.stderr,
        )

    ok_count = 0
    ok_no_ortho_count = 0
    failed_count = 0
    skipped_count = 0

    for variant in variants:
        variant_id = variant["variant_id"]
        overrides = variant["overrides"]

        print(f"Variant: {variant_id}", flush=True)

        variant_cfg = apply_overrides(base_cfg, overrides)

        for i in range(1, args.reps + 1):
            rep = f"rep_{i:03d}"
            key = (variant_id, rep)
            if args.resume and is_resumable_success(latest_rows.get(key)):
                skipped_count += 1
                print(f"  Skipping {rep}/{args.reps:03d} (already successful)", flush=True)
                continue

            prior_rows = rows_by_key.get(key, [])
            run_label = choose_run_label(
                experiment_dir=experiment_dir,
                variant_id=variant_id,
                rep=rep,
                prior_rows=prior_rows,
                resume=args.resume,
            )

            print(f"  Running {rep}/{args.reps:03d}", flush=True)

            cfg, rep_config, project_dir, output_dir = make_replicate_config(
                base_cfg=variant_cfg,
                variant_id=variant_id,
                base_run_name=base_run_name,
                experiment_dir=experiment_dir,
                replicate_index=i,
                run_label=run_label,
            )
            if args.generic_ortho_resolution:
                cfg.setdefault("buildOrthomosaic", {})["orthoRes"] = 0

            project_dir.mkdir(parents=True, exist_ok=True)
            output_dir.mkdir(parents=True, exist_ok=True)

            launcher_log = (
                experiment_dir
                / "variants"
                / variant_id
                / "runs"
                / run_label
                / "launcher.log"
            )

            write_yaml(rep_config, cfg)

            t0 = time.time()
            return_code = run_replicate(
                repo_root=repo_root,
                config_file=rep_config,
                launcher_log=launcher_log,
                metashape_dir=args.metashape_dir,
            )
            elapsed = round(time.time() - t0, 1)

            project_file = find_latest(project_dir, "*.psx")
            ortho_file = find_latest(output_dir, "*ortho*.tif")

            if return_code == 0 and ortho_file:
                status = "ok"
            elif return_code == 0 and not ortho_file:
                status = "ok_no_ortho"
            else:
                status = "failed"

            row = {
                "experiment_id": experiment_dir.name,
                "variant_id": variant_id,
                "replicate": rep,
                "status": status,
                "return_code": str(return_code),
                "config_file": str(rep_config),
                "project_dir": str(project_dir),
                "output_dir": str(output_dir),
                "project_file": project_file,
                "ortho_file": ortho_file,
                "launcher_log": str(launcher_log),
                "elapsed_sec": str(elapsed),
            }
            append_manifest_row(manifest_file, row)
            latest_rows[key] = row
            rows_by_key.setdefault(key, []).append(row)

            if status == "ok":
                ok_count += 1
            elif status == "ok_no_ortho":
                ok_no_ortho_count += 1
            else:
                failed_count += 1

            if return_code != 0:
                print(f"{variant_id}/{rep} failed. See: {launcher_log}", file=sys.stderr)

            if not ortho_file:
                print(
                    f"{variant_id}/{rep} finished but no ortho TIFF was found in {output_dir}",
                    file=sys.stderr,
                )

    print(f"Manifest written to: {manifest_file}")
    print(
        "Summary: "
        f"ok={ok_count}, "
        f"ok_no_ortho={ok_no_ortho_count}, "
        f"failed={failed_count}, "
        f"skipped={skipped_count}"
    )
    if args.generic_ortho_resolution:
        row = latest_rows.get(("default", "rep_001"))
        if row and row.get("status") == "ok":
            write_generic_ortho_resolution_reports(experiment_dir)
        write_field_screening_summary(
            experiment_dir=experiment_dir,
            base_cfg=base_cfg,
            row=row,
            failed_count=failed_count,
        )
        print_generic_field_screening_next_step()
    else:
        print_next_commands(
            resume=args.resume,
            failed_count=failed_count,
            remaining_failures=has_remaining_failures(
                variants=variants,
                reps=args.reps,
                latest_rows=latest_rows,
            ),
            base_config=base_config,
            variants_file=variants_file,
            experiment_dir=experiment_dir,
            reps=args.reps,
            metashape_dir=args.metashape_dir,
        )

    if failed_count:
        return 1

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)
