#!/usr/bin/env python3
"""
Run reproducibility experiments for the automate-metashape workflow.

This runner does not change the photogrammetric workflow itself.
It creates N independent workflow configurations from one base YAML file,
runs each replicate through scripts/run_metashape_workflow.sh, and writes
a manifest listing project files, output folders, logs and exported orthos.

Main purpose:
  Generate repeated, formally identical Metashape builds for later
  raster-based orthomosaic stability analysis.
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def ensure_clean_dir(path: Path, overwrite: bool) -> None:
    if path.exists() and any(path.iterdir()) and not overwrite:
        raise RuntimeError(
            f"Directory already exists and is not empty: {path}\n"
            f"Use --overwrite only when you intentionally want to reuse this experiment folder."
        )
    path.mkdir(parents=True, exist_ok=True)


def find_latest(pattern_dir: Path, pattern: str) -> str:
    files = sorted(
        pattern_dir.glob(pattern),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )
    return str(files[0]) if files else ""


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "experiment_id",
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

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def make_replicate_config(
    base_cfg: dict[str, Any],
    base_run_name: str,
    experiment_dir: Path,
    replicate_index: int,
) -> tuple[dict[str, Any], Path, Path]:
    rep = f"rep_{replicate_index:03d}"

    run_dir = experiment_dir / "runs" / rep
    project_dir = run_dir / "psx"
    output_dir = run_dir / "output"

    cfg = dict(base_cfg)

    # Reproducibility runs must be independent builds.
    # They must not continue a previously generated PSX file.
    cfg["load_project"] = ""

    cfg["run_name"] = f"{base_run_name}_{rep}"
    cfg["project_path"] = str(project_dir) + "/"
    cfg["output_path"] = str(output_dir) + "/"

    return cfg, project_dir, output_dir


def run_replicate(
    repo_root: Path,
    config_file: Path,
    launcher_log: Path,
    metashape_dir: str | None,
) -> int:
    env = os.environ.copy()

    if metashape_dir:
        env["METASHAPE_DIR"] = metashape_dir

    cmd = [
        str(repo_root / "scripts" / "run_metashape_workflow.sh"),
        str(config_file),
    ]

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
        help="Number of replicate runs.",
    )
    parser.add_argument(
        "--experiment-dir",
        type=Path,
        required=True,
        help="Directory where replicate configs, projects, outputs and manifest are written.",
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

    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    base_config = args.base_config.resolve()
    experiment_dir = args.experiment_dir.resolve()

    if args.reps < 2:
        raise RuntimeError("Use at least --reps 2 for a reproducibility experiment.")

    ensure_clean_dir(experiment_dir, overwrite=args.overwrite)

    base_cfg = read_yaml(base_config)

    base_run_name = base_cfg.get("run_name") or base_config.stem
    if base_run_name == "from_config_filename":
        base_run_name = base_config.stem

    configs_dir = experiment_dir / "configs"
    manifest_file = experiment_dir / "manifest.csv"

    rows: list[dict[str, str]] = []

    for i in range(1, args.reps + 1):
        rep = f"rep_{i:03d}"
        print(f"Running {rep}/{args.reps:03d}", flush=True)

        cfg, project_dir, output_dir = make_replicate_config(
            base_cfg=base_cfg,
            base_run_name=base_run_name,
            experiment_dir=experiment_dir,
            replicate_index=i,
        )

        project_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        rep_config = configs_dir / f"{rep}.yml"
        launcher_log = experiment_dir / "runs" / rep / "launcher.log"

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

        rows.append(
            {
                "experiment_id": experiment_dir.name,
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
        )

        write_manifest(manifest_file, rows)

        if return_code != 0:
            print(f"{rep} failed. See: {launcher_log}", file=sys.stderr)
            return return_code

        if not ortho_file:
            print(f"{rep} finished but no ortho TIFF was found in {output_dir}", file=sys.stderr)

    print(f"Manifest written to: {manifest_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
