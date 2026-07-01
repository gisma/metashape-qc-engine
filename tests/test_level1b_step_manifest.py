import json
from pathlib import Path

import pytest

from metashape_qc_engine.level1b_step_manifest import (
    manifest_artifact,
    read_step_manifest,
    step_manifest_path,
    write_step_manifest,
)


def test_manifest_round_trip_has_minimum_schema_and_exact_keys(tmp_path: Path) -> None:
    artifact = tmp_path / "level1b" / "example" / "result.json"
    path = write_step_manifest(
        tmp_path,
        step="example",
        status="ok",
        inputs={"source": tmp_path / "source.tif"},
        artifacts={"result": artifact},
        candidate_id="candidate-a",
    )

    assert path == step_manifest_path(tmp_path, "example")
    assert read_step_manifest(tmp_path, "example") == {
        "step": "example",
        "status": "ok",
        "inputs": {"source": str(tmp_path / "source.tif")},
        "artifacts": {"result": str(artifact)},
        "provenance": {"candidate_id": "candidate-a"},
    }


def test_manifest_artifact_requires_the_exact_key(tmp_path: Path) -> None:
    manifest = {
        "step": "example",
        "status": "ok",
        "inputs": {},
        "artifacts": {"canonical": str(tmp_path / "canonical.json")},
        "provenance": {"candidate_id": "candidate-a"},
    }

    assert manifest_artifact(manifest, "canonical") == tmp_path / "canonical.json"
    with pytest.raises(KeyError):
        manifest_artifact(manifest, "alias")


def test_reader_rejects_wrong_step_and_extra_schema_keys(tmp_path: Path) -> None:
    path = step_manifest_path(tmp_path, "expected")
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "step": "other",
                "status": "ok",
                "inputs": {},
                "artifacts": {},
                "provenance": {},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="expected"):
        read_step_manifest(tmp_path, "expected")

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["step"] = "expected"
    payload["aliases"] = []
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        read_step_manifest(tmp_path, "expected")
