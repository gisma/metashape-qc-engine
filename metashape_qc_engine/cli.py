"""Command-line wrappers for existing Metashape QC engine scripts."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    candidates = []

    package_path = Path(__file__).resolve()
    candidates.extend(package_path.parents)

    cwd = Path.cwd().resolve()
    candidates.append(cwd)
    candidates.extend(cwd.parents)

    for candidate in candidates:
        if (
            (candidate / "scripts" / "run_metashape_workflow.sh").is_file()
            and (candidate / "python" / "reproducibility_runner.py").is_file()
            and (candidate / "python" / "ortho_stability_analyzer.py").is_file()
            and (candidate / "python" / "evaluate_ortho_stability.py").is_file()
        ):
            return candidate

    raise RuntimeError(
        "Could not locate the metashape-qc-engine repository root. "
        "Run this command from the repository checkout or install in editable mode."
    )


def _print_command(cmd: list[str], env_overrides: dict[str, str] | None = None) -> None:
    prefix = []
    if env_overrides:
        prefix = [f"{key}={shlex.quote(value)}" for key, value in env_overrides.items()]
    print(" ".join(prefix + [shlex.quote(part) for part in cmd]), flush=True)


def _run(cmd: list[str], env_overrides: dict[str, str] | None = None) -> int:
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)

    _print_command(cmd, env_overrides)
    proc = subprocess.run(cmd, check=False, env=env)
    return proc.returncode


def _require_file(path: str, label: str) -> None:
    candidate = Path(path).expanduser()
    if not candidate.is_file():
        raise RuntimeError(f"{label} does not exist or is not a file: {path}")


def _require_dir(path: str, label: str) -> None:
    candidate = Path(path).expanduser()
    if not candidate.is_dir():
        raise RuntimeError(f"{label} does not exist or is not a directory: {path}")


def _same_path(left: str, right: str) -> bool:
    return Path(left).expanduser().resolve(strict=False) == Path(right).expanduser().resolve(
        strict=False
    )


def _select_run_dir(args: argparse.Namespace) -> str:
    run_dir = getattr(args, "run_dir", None)
    experiment_dir = getattr(args, "experiment_dir", None)

    if run_dir and experiment_dir:
        if not _same_path(run_dir, experiment_dir):
            raise RuntimeError(
                "--run-dir and --experiment-dir refer to different directories."
            )
        return run_dir
    if run_dir:
        return run_dir
    if experiment_dir:
        return experiment_dir
    raise RuntimeError("Provide --run-dir.")


def _run_workflow(args: argparse.Namespace) -> int:
    _require_file(args.config, "CONFIG")
    if args.metashape_dir:
        _require_dir(args.metashape_dir, "METASHAPE_DIR")

    root = _repo_root()
    cmd = [
        str(root / "scripts" / "run_metashape_workflow.sh"),
        args.config,
    ]
    env = {"METASHAPE_DIR": args.metashape_dir} if args.metashape_dir else None
    return _run(cmd, env)


def _run_prepare(args: argparse.Namespace) -> int:
    root = _repo_root()
    cmd = [
        sys.executable,
        str(root / "python" / "prepare_product_experiment.py"),
        "--image-dir",
        args.image_dir,
        "--product-id",
        args.product_id,
        "--preset",
        args.preset,
        "--reps",
        str(args.reps),
        "--output-root",
        args.output_root,
    ]

    if args.product_dir:
        cmd.extend(["--product-dir", args.product_dir])
    for factor in args.factor or []:
        cmd.extend(["--factor", factor])
    if args.face_counts:
        cmd.extend(["--face-counts", args.face_counts])
    if args.smoothing:
        cmd.extend(["--smoothing", args.smoothing])
    if args.variant_id_template:
        cmd.extend(["--variant-id-template", args.variant_id_template])

    return _run(cmd)


def _run_experiment(args: argparse.Namespace) -> int:
    run_dir = _select_run_dir(args)

    _require_file(args.base_config, "BASE_CONFIG")
    if args.variants:
        _require_file(args.variants, "CSV")
    if args.reps < 2:
        raise RuntimeError("--reps must be at least 2 for a product analysis.")
    if args.metashape_dir:
        _require_dir(args.metashape_dir, "METASHAPE_DIR")

    root = _repo_root()
    cmd = [
        sys.executable,
        str(root / "python" / "reproducibility_runner.py"),
        args.base_config,
        "--reps",
        str(args.reps),
        "--experiment-dir",
        run_dir,
    ]

    if args.variants:
        cmd.extend(["--variants", args.variants])
    if args.metashape_dir:
        cmd.extend(["--metashape-dir", args.metashape_dir])
    if args.overwrite:
        cmd.append("--overwrite")
    if args.resume:
        cmd.append("--resume")

    return _run(cmd)


def _run_analyze(args: argparse.Namespace) -> int:
    _require_file(args.manifest, "MANIFEST")
    if args.reference_ortho:
        _require_file(args.reference_ortho, "REFERENCE_ORTHO")

    root = _repo_root()
    cmd = [
        sys.executable,
        str(root / "python" / "ortho_stability_analyzer.py"),
        args.manifest,
        "--output-dir",
        args.output_dir,
    ]

    if args.grid_mode:
        cmd.extend(["--grid-mode", args.grid_mode])
    if args.reference_ortho:
        cmd.extend(["--reference-ortho", args.reference_ortho])
    if args.bands is not None:
        cmd.extend(["--bands", str(args.bands)])
    if args.stable_rmse_threshold is not None:
        cmd.extend(["--stable-rmse-threshold", str(args.stable_rmse_threshold)])
    if args.overwrite:
        cmd.append("--overwrite")

    return _run(cmd)


def _run_evaluate(args: argparse.Namespace) -> int:
    _require_dir(args.experiment_dir, "RUN_DIR")

    root = _repo_root()
    cmd = [
        sys.executable,
        str(root / "python" / "evaluate_ortho_stability.py"),
        args.experiment_dir,
    ]

    if args.skip_analyzer:
        cmd.append("--skip-analyzer")
    if args.grid_mode:
        cmd.extend(["--grid-mode", args.grid_mode])
    if args.bands is not None:
        cmd.extend(["--bands", str(args.bands)])
    if args.stable_rmse_threshold is not None:
        cmd.extend(["--stable-rmse-threshold", str(args.stable_rmse_threshold)])
    if args.no_overwrite:
        cmd.append("--no-overwrite")

    return _run(cmd)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="metashape-qc",
        description="Thin CLI wrappers for Metashape QC product analysis.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Run the Metashape workflow.")
    run.add_argument("config", metavar="CONFIG")
    run.add_argument("--metashape-dir", metavar="DIR")
    run.set_defaults(func=_run_workflow)

    prepare = subparsers.add_parser(
        "prepare",
        help="Prepare product analysis control files.",
        description=(
            "Prepare product-specific config and variants for a Metashape QC "
            "product analysis."
        ),
    )
    prepare.add_argument("--product-dir", metavar="DIR")
    prepare.add_argument("--image-dir", metavar="DIR", required=True)
    prepare.add_argument("--product-id", metavar="ID", required=True)
    prepare.add_argument("--preset", metavar="JSON", required=True)
    prepare.add_argument("--reps", metavar="N", type=int, required=True)
    prepare.add_argument("--output-root", metavar="DIR", required=True)
    prepare.add_argument("--factor", metavar="COLUMN=VALUES", action="append")
    prepare.add_argument("--face-counts", metavar="VALUES")
    prepare.add_argument("--smoothing", metavar="VALUES")
    prepare.add_argument("--variant-id-template", metavar="TEMPLATE")
    prepare.set_defaults(func=_run_prepare)

    experiment = subparsers.add_parser(
        "experiment",
        help=(
            "Run legacy reproducibility experiment replicates. "
            "Prefer run-analysis or resume-analysis for new usage."
        ),
    )
    experiment.add_argument("base_config", metavar="BASE_CONFIG")
    experiment.add_argument("--reps", metavar="N", type=int, required=True)
    experiment.add_argument("--experiment-dir", metavar="DIR", required=True)
    experiment.add_argument("--variants", metavar="CSV")
    experiment.add_argument("--metashape-dir", metavar="DIR")
    experiment.add_argument("--overwrite", action="store_true")
    experiment.add_argument("--resume", action="store_true")
    experiment.set_defaults(func=_run_experiment)

    run_analysis = subparsers.add_parser(
        "run-analysis",
        help="Run product analysis variants and replicates.",
        description="Run product analysis variants and replicates into a run directory.",
    )
    run_analysis.add_argument("base_config", metavar="CONFIG")
    run_analysis.add_argument("--reps", metavar="N", type=int, required=True)
    run_analysis.add_argument(
        "--run-dir",
        metavar="DIR",
        help="Run directory where configs, outputs, and manifest are written.",
    )
    run_analysis.add_argument(
        "--experiment-dir",
        metavar="DIR",
        help="Legacy alias for --run-dir.",
    )
    run_analysis.add_argument("--variants", metavar="CSV")
    run_analysis.add_argument("--metashape-dir", metavar="DIR")
    run_analysis.add_argument("--overwrite", action="store_true")
    run_analysis.set_defaults(func=_run_experiment, resume=False)

    resume_analysis = subparsers.add_parser(
        "resume-analysis",
        help="Resume a product analysis run.",
        description=(
            "Resume a product analysis run by skipping successful "
            "variant/replicate combinations."
        ),
    )
    resume_analysis.add_argument("base_config", metavar="CONFIG")
    resume_analysis.add_argument("--reps", metavar="N", type=int, required=True)
    resume_analysis.add_argument(
        "--run-dir",
        metavar="DIR",
        help="Run directory containing the existing manifest and outputs.",
    )
    resume_analysis.add_argument(
        "--experiment-dir",
        metavar="DIR",
        help="Legacy alias for --run-dir.",
    )
    resume_analysis.add_argument("--variants", metavar="CSV")
    resume_analysis.add_argument("--metashape-dir", metavar="DIR")
    resume_analysis.add_argument("--overwrite", action="store_true")
    resume_analysis.set_defaults(func=_run_experiment, resume=True)

    analyze = subparsers.add_parser(
        "analyze",
        help="Analyze orthomosaic stability.",
    )
    analyze.add_argument("manifest", metavar="MANIFEST")
    analyze.add_argument("--output-dir", metavar="DIR", required=True)
    analyze.add_argument(
        "--grid-mode",
        metavar="MODE",
        choices=["union", "intersection", "reference"],
    )
    analyze.add_argument("--reference-ortho", metavar="PATH")
    analyze.add_argument("--bands", metavar="N", type=int)
    analyze.add_argument("--stable-rmse-threshold", metavar="X", type=float)
    analyze.add_argument("--overwrite", action="store_true")
    analyze.set_defaults(func=_run_analyze)

    evaluate = subparsers.add_parser(
        "evaluate",
        help="Evaluate a completed product analysis run directory.",
    )
    evaluate.add_argument("experiment_dir", metavar="RUN_DIR")
    evaluate.add_argument("--skip-analyzer", action="store_true")
    evaluate.add_argument(
        "--grid-mode",
        metavar="MODE",
        choices=["union", "intersection", "reference"],
    )
    evaluate.add_argument("--bands", metavar="N", type=int)
    evaluate.add_argument("--stable-rmse-threshold", metavar="X", type=float)
    evaluate.add_argument("--no-overwrite", action="store_true")
    evaluate.set_defaults(func=_run_evaluate)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        return_code = args.func(args)
    except RuntimeError as exc:
        print(f"metashape-qc: error: {exc}", file=sys.stderr)
        return_code = 1

    sys.exit(return_code)


if __name__ == "__main__":
    main()
