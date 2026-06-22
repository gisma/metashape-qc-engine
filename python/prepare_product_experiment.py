#!/usr/bin/env python3
"""Prepare product-specific Metashape reproducibility experiment inputs."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import re
import shutil
import shlex
import sys
from pathlib import Path
from typing import Any


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".png",
    ".dng",
}

REQUIRED_PRESET_FIELDS = {
    "template_config",
    "template_variants_csv",
    "experiment_dir_template",
    "variant_id_template",
    "factors",
}

REQUIRED_CONFIG_KEYS = {
    "load_project",
    "photo_path",
    "output_path",
    "project_path",
    "project_crs",
    "camera_crs",
    "run_name",
}

CONFIG_SCALAR_OVERRIDE_KEYS = {
    "project_crs",
    "camera_crs",
    "addGCPs.gcp_crs",
}
CRS_SENTINEL = "USER_MUST_SET_PROJECT_CRS"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise RuntimeError(message)


def resolve_repo_path(path_value: str) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path
    return repo_root() / path


def quote_yaml_scalar(value: str) -> str:
    return json.dumps(value)


def find_image_files(image_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in image_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def read_preset(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            preset = json.load(f)
    except FileNotFoundError:
        fail(f"Preset file does not exist: {path}")
    except json.JSONDecodeError as exc:
        fail(f"Preset file is not valid JSON: {path}: {exc}")

    missing = sorted(REQUIRED_PRESET_FIELDS - set(preset))
    if missing:
        fail(f"Preset is missing required field(s): {', '.join(missing)}")

    string_fields = sorted(REQUIRED_PRESET_FIELDS - {"factors"})
    for field in string_fields:
        if not isinstance(preset[field], str) or not preset[field]:
            fail(f"Preset field '{field}' must be a non-empty string.")

    if not isinstance(preset["factors"], dict) or not preset["factors"]:
        fail("Preset field 'factors' must be a non-empty object.")
    for name, values in preset["factors"].items():
        if not isinstance(values, list) or not values:
            fail(f"Preset factor '{name}' must be a non-empty list.")

    return preset


def replace_top_level_scalar(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^(?P<prefix>{re.escape(key)}:\s*).*$", re.MULTILINE)
    if not pattern.search(text):
        fail(
            "Template config is missing required existing key "
            f"'{key}'. Cannot safely generate product config."
        )
    return pattern.sub(
        lambda match: f"{match.group('prefix')}{quote_yaml_scalar(value)}",
        text,
        count=1,
    )


def replace_nested_scalar(text: str, key_path: str, value: str) -> str:
    parts = key_path.split(".")
    if len(parts) == 1:
        return replace_top_level_scalar(text, key_path, value)
    if len(parts) != 2:
        fail(f"Nested scalar override is only supported for one parent level: {key_path}")
    parent, child = parts
    lines = text.splitlines(keepends=True)
    parent_index = None
    parent_indent = 0
    for index, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0 and re.match(rf"^{re.escape(parent)}:\s*(?:#.*)?$", line.strip()):
            parent_index = index
            parent_indent = indent
            break
    if parent_index is None:
        fail(
            "Template config is missing required existing key "
            f"'{parent}'. Cannot safely generate product config."
        )
    child_pattern = re.compile(rf"^(?P<indent>\s+)(?P<key>{re.escape(child)}:\s*).*$")
    for index in range(parent_index + 1, len(lines)):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= parent_indent:
            break
        match = child_pattern.match(line)
        if match:
            newline = "\n" if line.endswith("\n") else ""
            lines[index] = f"{match.group('indent')}{match.group('key')}{quote_yaml_scalar(value)}{newline}"
            return "".join(lines)
    fail(
        "Template config is missing required existing key "
        f"'{key_path}'. Cannot safely generate product config."
    )


def generate_config(
    template_config: Path,
    generated_config: Path,
    product_id: str,
    image_dir: Path,
    experiment_dir: Path,
    scalar_overrides: dict[str, str] | None = None,
) -> None:
    if not template_config.is_file():
        fail(f"Template config is missing: {template_config}")

    text = template_config.read_text(encoding="utf-8")
    missing_keys = [
        key
        for key in sorted(REQUIRED_CONFIG_KEYS)
        if not re.search(rf"^{re.escape(key)}:\s*", text, re.MULTILINE)
    ]
    if missing_keys:
        fail(
            "Template config is missing required existing key(s): "
            + ", ".join(missing_keys)
            + ". Expected existing image/project fields: "
            + ", ".join(sorted(REQUIRED_CONFIG_KEYS))
        )

    image_dir_value = str(image_dir) + "/"
    text = replace_top_level_scalar(text, "load_project", "")
    text = replace_top_level_scalar(text, "photo_path", image_dir_value)
    text = replace_top_level_scalar(
        text,
        "output_path",
        str(experiment_dir / "single_run" / "output") + "/",
    )
    text = replace_top_level_scalar(
        text,
        "project_path",
        str(experiment_dir / "single_run" / "psx") + "/",
    )
    text = replace_top_level_scalar(text, "run_name", product_id)
    for key, value in (scalar_overrides or {}).items():
        text = replace_nested_scalar(text, key, value)
    if CRS_SENTINEL in text:
        fail(
            "Generated config would still contain an unset CRS sentinel. "
            "Set project_crs and all runtime CRS fields before running."
        )

    try:
        generated_config.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        fail(
            "Could not create generated config directory: "
            f"{generated_config.parent}: {exc}"
        )

    try:
        generated_config.write_text(text, encoding="utf-8")
    except OSError as exc:
        fail(f"Could not write generated config: {generated_config}: {exc}")


def format_k(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        fail(f"Cannot apply ':k' formatting to non-integer value: {value!r}")
    if number % 1000 != 0:
        fail(
            "Cannot apply ':k' formatting to value that is not divisible by 1000: "
            f"{value!r}"
        )
    return f"{number // 1000:03d}k"


def render_variant_id(template: str, values: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        expression = match.group(1)
        if expression.endswith(":k"):
            column = expression[:-2]
            if column not in values:
                fail(f"Variant ID template references unknown factor: {column}")
            return format_k(values[column])
        if expression not in values:
            fail(f"Variant ID template references unknown factor: {expression}")
        return str(values[expression])

    variant_id = re.sub(r"\{([^{}]+)\}", replace, template)
    variant_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", variant_id.strip()).strip("_")
    if not variant_id:
        fail("Generated empty variant_id.")
    return variant_id


def parse_factor_values(raw_values: str, option_name: str) -> list[str]:
    values = [value.strip() for value in raw_values.split(",")]
    if not values or any(value == "" for value in values):
        fail(f"{option_name} must contain one or more non-empty comma-separated values.")
    return values


def parse_factor_override(raw_factor: str) -> tuple[str, list[str]]:
    if "=" not in raw_factor:
        fail("--factor must use COLUMN=VALUE1,VALUE2,... format.")
    column, raw_values = raw_factor.split("=", 1)
    column = column.strip()
    if not column:
        fail("--factor column must be non-empty.")
    return column, parse_factor_values(raw_values, "--factor")


def build_effective_factors(
    args: argparse.Namespace,
    preset: dict[str, Any],
) -> dict[str, list[Any]]:
    factors = dict(preset["factors"])

    if args.face_counts:
        factors["buildModel.face_count_custom"] = parse_factor_values(
            args.face_counts,
            "--face-counts",
        )
    if args.smoothing:
        factors["buildModel.noiterations"] = parse_factor_values(
            args.smoothing,
            "--smoothing",
        )
    for raw_factor in args.factor or []:
        column, values = parse_factor_override(raw_factor)
        factors[column] = values

    return factors


def generate_variants(
    template_variants_csv: Path,
    generated_variants_csv: Path,
    factors: dict[str, list[Any]],
    variant_id_template: str,
) -> int:
    if not template_variants_csv.is_file():
        fail(f"Template variants CSV is missing: {template_variants_csv}")

    with template_variants_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        rows = list(reader)

    if not header:
        fail(f"Template variants CSV has no header: {template_variants_csv}")
    if not rows:
        fail(f"Template variants CSV has no data rows: {template_variants_csv}")
    if "variant_id" not in header:
        fail("Template variants CSV must contain a 'variant_id' column.")

    missing_factor_columns = [
        column
        for column in factors
        if column not in header and column not in CONFIG_SCALAR_OVERRIDE_KEYS
    ]
    if missing_factor_columns:
        fail(
            "Template variants CSV is missing factor column(s): "
            + ", ".join(missing_factor_columns)
        )

    base_row = dict(rows[0])
    factor_names = [name for name in factors if name in header]
    factor_values = [factors[name] for name in factor_names]

    output_rows: list[dict[str, Any]] = []
    seen_variant_ids: set[str] = set()

    for combination in itertools.product(*factor_values):
        values = dict(zip(factor_names, combination))
        row = dict(base_row)
        row.update(values)
        row["variant_id"] = render_variant_id(variant_id_template, values)
        if row["variant_id"] in seen_variant_ids:
            fail(f"Generated duplicate variant_id: {row['variant_id']}")
        seen_variant_ids.add(row["variant_id"])
        output_rows.append(row)

    try:
        generated_variants_csv.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        fail(
            "Could not create generated variants CSV directory: "
            f"{generated_variants_csv.parent}: {exc}"
        )

    try:
        with generated_variants_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            writer.writerows(output_rows)
    except (OSError, ValueError) as exc:
        fail(f"Could not write generated variants CSV: {generated_variants_csv}: {exc}")

    return len(output_rows)


def single_factor_value(factors: dict[str, list[Any]], key: str) -> str | None:
    if key not in factors:
        return None
    values = factors[key]
    if len(values) != 1:
        fail(f"{key} must have exactly one value for generated config.yml.")
    value = str(values[0]).strip()
    if not value:
        fail(f"{key} must not be empty.")
    return value


def config_scalar_overrides_from_factors(factors: dict[str, list[Any]]) -> dict[str, str]:
    scalar_overrides = {}
    for key in sorted(CONFIG_SCALAR_OVERRIDE_KEYS):
        value = single_factor_value(factors, key)
        if value is not None:
            scalar_overrides[key] = value
    if "project_crs" in scalar_overrides and "addGCPs.gcp_crs" not in scalar_overrides:
        scalar_overrides["addGCPs.gcp_crs"] = scalar_overrides["project_crs"]
    return scalar_overrides


def format_template(template: str, values: dict[str, Any]) -> str:
    try:
        return template.format(**values)
    except KeyError as exc:
        fail(f"Preset template references unknown placeholder: {exc.args[0]}")


def shell_join(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def print_next_commands(
    generated_config: Path,
    generated_variants_csv: Path,
    experiment_dir: Path,
    reps: int,
) -> None:
    shared_args = [
        str(generated_config),
        "--variants",
        str(generated_variants_csv),
        "--reps",
        str(reps),
        "--run-dir",
        str(experiment_dir),
    ]
    commands = [
        ["metashape-qc", "run-analysis", *shared_args],
        ["metashape-qc", "resume-analysis", *shared_args],
        ["metashape-qc", "evaluate", str(experiment_dir)],
    ]

    print("Next commands:")
    for command in commands:
        print(f"  {shell_join(command)}")


def safe_overwrite_experiment_dir(
    experiment_dir: Path,
    output_root: Path,
    image_dir: Path,
    preset_path: Path,
) -> None:
    if not experiment_dir.exists():
        return
    if not experiment_dir.is_dir():
        fail(f"--overwrite target exists but is not a directory: {experiment_dir}")

    target = experiment_dir.resolve()
    protected = {
        output_root.resolve(),
        image_dir.resolve(),
        repo_root().resolve(),
        preset_path.parent.resolve(),
    }
    if target in protected:
        fail(f"Refusing to overwrite protected directory: {target}")
    if not str(target).startswith(str(output_root.resolve()) + "/"):
        fail(f"Refusing to overwrite directory outside output root: {target}")

    has_prepare_artifact = (target / "config.yml").exists() or (target / "variants.csv").exists()
    if not has_prepare_artifact and any(target.iterdir()):
        fail(
            "Refusing to overwrite existing directory without config.yml or variants.csv: "
            f"{target}"
        )

    shutil.rmtree(target)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare product-specific config and variants for a Metashape QC "
            "product analysis."
        )
    )
    parser.add_argument(
        "--product-dir",
        help=(
            "Product/project root directory. Defaults to the parent directory of "
            "--image-dir."
        ),
    )
    parser.add_argument(
        "--image-dir",
        required=True,
        help="Directory containing the input images.",
    )
    parser.add_argument(
        "--product-id",
        required=True,
        help="Project/product identifier for generated names.",
    )
    parser.add_argument(
        "--preset", required=True, help="Product analysis preset JSON file."
    )
    parser.add_argument(
        "--reps",
        required=True,
        type=int,
        help="Number of replicates to run later.",
    )
    parser.add_argument(
        "--output-root",
        required=True,
        help="Root directory for product analysis runs.",
    )
    parser.add_argument(
        "--factor",
        action="append",
        help=(
            "Override or add a factor using COLUMN=VALUE1,VALUE2,... format. "
            "May be repeated."
        ),
    )
    parser.add_argument(
        "--face-counts",
        help="Shortcut for --factor buildModel.face_count_custom=VALUE1,VALUE2,...",
    )
    parser.add_argument(
        "--smoothing",
        help="Shortcut for --factor buildModel.noiterations=VALUE1,VALUE2,...",
    )
    parser.add_argument(
        "--variant-id-template",
        help="Override the preset variant_id_template.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Safely remove the exact prepared output directory before writing it.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        image_dir = Path(args.image_dir).expanduser().resolve()
        if not image_dir.exists():
            fail(f"Image directory does not exist: {image_dir}")
        if not image_dir.is_dir():
            fail(f"Image directory is not a directory: {image_dir}")

        image_files = find_image_files(image_dir)
        if not image_files:
            fail(f"No supported image files found in image directory: {image_dir}")

        if args.product_dir:
            product_dir = Path(args.product_dir).expanduser().resolve()
            if not product_dir.is_dir():
                fail(f"Product directory does not exist: {product_dir}")
        else:
            product_dir = image_dir.parent

        if args.reps < 1:
            fail("--reps must be at least 1.")

        preset_path = resolve_repo_path(args.preset)
        preset = read_preset(preset_path)
        output_root = Path(args.output_root).expanduser().resolve()

        try:
            output_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            fail(f"Could not create output root directory: {output_root}: {exc}")

        template_values = {
            "product_id": args.product_id,
            "output_root": str(output_root),
            "reps": args.reps,
        }

        experiment_dir = Path(
            format_template(preset["experiment_dir_template"], template_values)
        ).expanduser().resolve()
        generated_config = experiment_dir / "config.yml"
        generated_variants_csv = experiment_dir / "variants.csv"

        if args.overwrite:
            safe_overwrite_experiment_dir(experiment_dir, output_root, image_dir, preset_path)

        try:
            experiment_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            fail(f"Could not create experiment directory: {experiment_dir}: {exc}")

        factors = build_effective_factors(args, preset)
        scalar_overrides = config_scalar_overrides_from_factors(factors)

        generate_config(
            resolve_repo_path(preset["template_config"]),
            generated_config,
            args.product_id,
            image_dir,
            experiment_dir,
            scalar_overrides=scalar_overrides,
        )
        variant_id_template = args.variant_id_template or preset["variant_id_template"]
        variant_count = generate_variants(
            resolve_repo_path(preset["template_variants_csv"]),
            generated_variants_csv,
            factors,
            variant_id_template,
        )

        print(f"Generated config: {generated_config}")
        print(f"Generated variants CSV: {generated_variants_csv}")
        print(f"Run directory: {experiment_dir}")
        print(f"Variants: {variant_count}")
        print(f"Replicates: {args.reps}")
        print(f"Total runs: {variant_count * args.reps}")
        print_next_commands(
            generated_config=generated_config,
            generated_variants_csv=generated_variants_csv,
            experiment_dir=experiment_dir,
            reps=args.reps,
        )
        return 0
    except RuntimeError as exc:
        print(f"prepare_product_experiment.py: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
