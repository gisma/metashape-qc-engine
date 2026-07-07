from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from metashape_qc_engine import level1ab_sensitivity_runner as sensitivity


def _study(tmp_path: Path) -> dict:
    return {
        "schema_version": 1,
        "study": {
            "id": "test-study",
            "output_root": str(tmp_path / "study"),
            "overwrite": False,
        },
        "level1a": {
            "image_dir": str(tmp_path / "images"),
            "product_id": "test_product",
            "project_crs": "EPSG::32632",
            "preset": "config/experiments/presets/rgb_mesh_ortho_fast_screening_v1.json",
            "replicates": 2,
            "metashape_dir": "",
            "factors": {
                "alignPhotos.downscale": [1],
                "buildModel.face_count_custom": [50000],
                "buildModel.noiterations": [5],
                "buildOrthomosaic.orthoRes": [0.05],
            },
        },
        "level1b": {
            "base_config": "config/level1b_default.yaml",
            "wrapper": "metashape_qc_engine/run_level1b_dumb_with_user_header.sh",
            "otb_root": "",
            "profiles": [
                {"id": "baseline", "overrides": {}},
                {
                    "id": "narrow",
                    "overrides": {
                        "candidate_pre_screening.radius_max_m": 2.0,
                    },
                },
            ],
            "sources": {
                "selected_product": {"profile_ids": ["baseline", "narrow"]},
                "level1a_variants": {
                    "variant_ids": ["ds1_fc050k_smooth5_or0.05"],
                    "profile_ids": ["baseline"],
                },
            },
        },
    }


def test_plan_is_explicit_and_materializes_profile_configs(tmp_path: Path) -> None:
    config = _study(tmp_path)

    plan = sensitivity.write_plan(config)

    rows = plan.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1 + 5  # two Level-1A replicates plus three Level-1B runs
    baseline = tmp_path / "study" / "level1b" / "configs" / "baseline.yaml"
    narrow = tmp_path / "study" / "level1b" / "configs" / "narrow.yaml"
    baseline_cfg = yaml.safe_load(baseline.read_text(encoding="utf-8"))
    narrow_cfg = yaml.safe_load(narrow.read_text(encoding="utf-8"))
    assert baseline_cfg["level1b"]["candidate_pre_screening"]["radius_max_m"] == 4.0
    assert narrow_cfg["level1b"]["candidate_pre_screening"]["radius_max_m"] == 2.0


def test_unknown_profile_override_is_rejected(tmp_path: Path) -> None:
    config = _study(tmp_path)
    config["level1b"]["profiles"][0]["overrides"] = {
        "candidate_pre_screening.not_a_parameter": 1,
    }

    with pytest.raises(ValueError, match="Unknown Level-1B override path"):
        sensitivity.materialize_level1b_profiles(config)


def test_level1b_sources_use_selected_and_explicit_variant_orthos(
    tmp_path: Path,
) -> None:
    config = _study(tmp_path)
    _, experiment_dir, _ = sensitivity.level1a_paths(config)
    selected_ortho = tmp_path / "selected.tif"
    selected_product = {
        "primary_variant_id": "selected_variant",
        "product_modes": {"median_ortho": {"path": str(selected_ortho)}},
    }
    experiment_dir.mkdir(parents=True)
    (experiment_dir / "selected_product.json").write_text(
        json.dumps(selected_product), encoding="utf-8"
    )

    sources = sensitivity.level1b_sources(config)

    assert [source["run_id"] for source in sources] == [
        "selected_product__baseline",
        "selected_product__narrow",
        "variant_ds1_fc050k_smooth5_or0.05__baseline",
    ]
    assert sources[0]["ortho"] == str(selected_ortho)
    assert sources[2]["ortho"].endswith(
        "stability_union/variants/ds1_fc050k_smooth5_or0.05/median_ortho.tif"
    )


def test_level1b_runner_passes_profile_config_to_existing_wrapper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _study(tmp_path)
    config["level1b"]["sources"]["selected_product"]["profile_ids"] = [
        "narrow"
    ]
    config["level1b"]["sources"]["level1a_variants"]["variant_ids"] = []
    _, experiment_dir, _ = sensitivity.level1a_paths(config)
    selected_ortho = tmp_path / "selected.tif"
    selected_ortho.write_bytes(b"ortho")
    experiment_dir.mkdir(parents=True)
    (experiment_dir / "selected_product.json").write_text(
        json.dumps(
            {
                "primary_variant_id": "selected",
                "product_modes": {"median_ortho": {"path": str(selected_ortho)}},
            }
        ),
        encoding="utf-8",
    )
    captured = {}

    def fake_run(command, *, env=None):
        captured["command"] = command
        captured["env"] = env
        return 0

    monkeypatch.setattr(sensitivity, "run_command", fake_run)

    results = sensitivity.run_level1b(config)

    assert results[0]["return_code"] == 0
    assert captured["command"][0] == "bash"
    assert captured["env"]["ORTHO"] == str(selected_ortho)
    assert captured["env"]["LEVEL1B_CONFIG"].endswith(
        "level1b/configs/narrow.yaml"
    )
    assert captured["env"]["OVERWRITE"] == "0"
