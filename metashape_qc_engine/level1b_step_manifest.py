from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


MANIFEST_KEYS = ("step", "status", "inputs", "artifacts", "provenance")


def step_manifest_path(output_dir: str | Path, step: str) -> Path:
    return Path(output_dir) / "level1b" / "manifests" / f"{step}.json"


def write_step_manifest(
    output_dir: str | Path,
    *,
    step: str,
    status: str,
    inputs: Mapping[str, str | Path],
    artifacts: Mapping[str, str | Path],
    candidate_id: str,
) -> Path:
    path = step_manifest_path(output_dir, step)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "step": step,
        "status": status,
        "inputs": {name: str(value) for name, value in inputs.items()},
        "artifacts": {name: str(value) for name, value in artifacts.items()},
        "provenance": {"candidate_id": str(candidate_id)},
    }
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def read_step_manifest(
    output_dir: str | Path,
    step: str,
) -> dict[str, object]:
    path = step_manifest_path(output_dir, step)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or set(manifest) != set(MANIFEST_KEYS):
        raise ValueError(f"Invalid Level-1b manifest schema: {path}")
    if manifest["step"] != step:
        raise ValueError(
            f"Invalid Level-1b manifest step {manifest['step']!r}; expected {step!r}"
        )
    if not isinstance(manifest["status"], str):
        raise ValueError(f"Invalid Level-1b manifest status: {path}")
    for key in ("inputs", "artifacts", "provenance"):
        if not isinstance(manifest[key], dict):
            raise ValueError(f"Invalid Level-1b manifest {key}: {path}")
    for key in ("inputs", "artifacts"):
        if not all(
            isinstance(name, str) and isinstance(value, str)
            for name, value in manifest[key].items()
        ):
            raise ValueError(f"Invalid Level-1b manifest {key} paths: {path}")
    if set(manifest["provenance"]) != {"candidate_id"} or not isinstance(
        manifest["provenance"]["candidate_id"], str
    ):
        raise ValueError(f"Invalid Level-1b manifest provenance: {path}")
    return manifest


def manifest_artifact(manifest: Mapping[str, object], key: str) -> Path:
    artifacts = manifest["artifacts"]
    if not isinstance(artifacts, dict):
        raise ValueError("Invalid Level-1b manifest artifacts")
    return Path(artifacts[key])
