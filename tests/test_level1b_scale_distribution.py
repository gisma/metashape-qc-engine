import csv
import json
import math
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from metashape_qc_engine.level1b_scale_distribution import (
    JSON_FIELDS,
    SCALE_MODE,
    SCALE_SOURCE,
    Level1BScaleDistributionConfig,
    build_level1b_scale_distribution_layout,
    build_scale_candidates,
    run_scale_distribution_step,
    validate_scale_distribution_config,
)


def make_config(
    tmp_path: Path,
    **overrides: object,
) -> Level1BScaleDistributionConfig:
    values = {
        "candidate_id": "test",
        "output_dir": tmp_path / "out",
        "pixel_size_m": 0.5,
        "baseline_candidate_radii_m": (0.2, 1.0, 2.0),
    }
    values.update(overrides)
    return Level1BScaleDistributionConfig(**values)


def validate(
    config: Level1BScaleDistributionConfig,
) -> tuple[dict[str, bool], list[str]]:
    return validate_scale_distribution_config(
        config,
        build_level1b_scale_distribution_layout(config.output_dir),
    )


def test_01_layout_creates_only_scales_directory(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    layout = build_level1b_scale_distribution_layout(output_dir)

    assert list(layout) == ["scales_dir"]
    assert layout["scales_dir"].is_dir()
    assert sorted(path.relative_to(output_dir) for path in output_dir.rglob("*")) == [
        Path("level1b"),
        Path("level1b/scales"),
    ]


def test_02_explicit_baseline_order_is_preserved(tmp_path: Path) -> None:
    radii = (0.2, 0.3618081437156948, 0.6545256642949843, 3.875)
    candidates = build_scale_candidates(
        make_config(tmp_path, baseline_candidate_radii_m=radii)
    )

    assert tuple(candidate["radius_m"] for candidate in candidates) == radii
    assert [candidate["scale_index"] for candidate in candidates] == [1, 2, 3, 4]


def test_03_one_candidate_is_built_per_explicit_baseline(tmp_path: Path) -> None:
    candidates = build_scale_candidates(make_config(tmp_path))

    assert len(candidates) == 3
    assert {candidate["scale_mode"] for candidate in candidates} == {SCALE_MODE}
    assert {candidate["scale_source"] for candidate in candidates} == {
        SCALE_SOURCE
    }


def test_04_radius_m_derives_area_m2(tmp_path: Path) -> None:
    candidate = build_scale_candidates(
        make_config(tmp_path, baseline_candidate_radii_m=(2.0,))
    )[0]

    assert candidate["area_m2"] == math.pi * 2.0**2


def test_05_radius_m_derives_spatialr_px(tmp_path: Path) -> None:
    candidate = build_scale_candidates(
        make_config(
            tmp_path,
            pixel_size_m=0.6,
            baseline_candidate_radii_m=(0.2,),
        )
    )[0]

    assert candidate["spatialr_px"] == max(1, round(0.2 / 0.6))


def test_06_area_m2_derives_minsize_px(tmp_path: Path) -> None:
    candidate = build_scale_candidates(
        make_config(
            tmp_path,
            pixel_size_m=0.5,
            baseline_candidate_radii_m=(1.0,),
        )
    )[0]

    assert candidate["minsize_px"] == max(
        1,
        round((math.pi * 1.0**2) / (0.5**2)),
    )


def test_07_candidate_ids_follow_explicit_baseline_order(tmp_path: Path) -> None:
    candidates = build_scale_candidates(
        make_config(tmp_path, baseline_candidate_radii_m=(1.0, 2.0))
    )

    assert [candidate["candidate_id"] for candidate in candidates] == [
        "test_r1m_px002",
        "test_r2m_px004",
    ]


def test_08_json_records_explicit_baselines_and_metres(tmp_path: Path) -> None:
    report = run_scale_distribution_step(make_config(tmp_path))
    payload = json.loads(Path(report["output_json_path"]).read_text(encoding="utf-8"))

    assert payload["scale_mode"] == "explicit_baseline_candidates"
    assert payload["scale_source"] == "config.baseline_candidate_radii_m"
    assert payload["radius_unit"] == "m"
    assert payload["baseline_candidate_radii_m"] == [0.2, 1.0, 2.0]
    assert payload["candidates"][0]["ranger"] is None


def test_09_csv_ranger_is_na(tmp_path: Path) -> None:
    report = run_scale_distribution_step(make_config(tmp_path))

    with Path(report["output_csv_path"]).open(
        newline="",
        encoding="utf-8",
    ) as file_obj:
        rows = list(csv.DictReader(file_obj))

    assert rows[0]["ranger"] == "NA"


def test_10_validation_fails_for_empty_candidate_id(tmp_path: Path) -> None:
    checks, reasons = validate(make_config(tmp_path, candidate_id=" "))

    assert checks["candidate_id_non_empty"] is False
    assert "candidate_id is empty" in reasons


def test_11_validation_fails_for_nonpositive_pixel_size_m(tmp_path: Path) -> None:
    checks, reasons = validate(make_config(tmp_path, pixel_size_m=0))

    assert checks["pixel_size_m_valid"] is False
    assert "pixel_size_m must be numeric and > 0" in reasons


def test_12_validation_requires_baseline_candidate_radii(tmp_path: Path) -> None:
    missing_checks, missing_reasons = validate(
        make_config(tmp_path, baseline_candidate_radii_m=None)
    )
    empty_checks, empty_reasons = validate(
        make_config(tmp_path, baseline_candidate_radii_m=())
    )

    assert missing_checks["baseline_candidate_radii_m_present"] is False
    assert "baseline_candidate_radii_m is required" in missing_reasons
    assert empty_checks["baseline_candidate_radii_m_non_empty"] is False
    assert "baseline_candidate_radii_m must be non-empty" in empty_reasons


def test_13_validation_rejects_invalid_baseline_values(tmp_path: Path) -> None:
    for values in (
        (0.0, 1.0),
        (-1.0, 1.0),
        (1.0, float("inf")),
        (1.0, float("nan")),
        (True, 1.0),
    ):
        checks, reasons = validate(
            make_config(tmp_path, baseline_candidate_radii_m=values)
        )
        assert checks["baseline_candidate_radii_m_values_valid"] is False
        assert any("finite numeric metre values > 0" in reason for reason in reasons)


def test_14_validation_rejects_duplicates_and_unsorted_radii(tmp_path: Path) -> None:
    for values in ((0.2, 0.2, 1.0), (1.0, 0.2)):
        checks, reasons = validate(
            make_config(tmp_path, baseline_candidate_radii_m=values)
        )
        assert checks["baseline_candidate_radii_m_strictly_increasing"] is False
        assert (
            "baseline_candidate_radii_m must be strictly increasing with no duplicates"
            in reasons
        )


def test_15_channel_metadata_and_labels_do_not_change_baselines(tmp_path: Path) -> None:
    channel_report = (
        tmp_path / "out" / "level1b" / "channels" / "channel_report.json"
    )
    channel_report.parent.mkdir(parents=True, exist_ok=True)
    channel_report.write_text(
        json.dumps(
            {
                "channel_names": ["TEX_100M", "TEX_200M"],
                "dglcm_pc1_large_radius_m": 999.0,
            }
        ),
        encoding="utf-8",
    )
    radii = (0.2, 1.0, 3.875)

    candidates = build_scale_candidates(
        make_config(tmp_path, baseline_candidate_radii_m=radii)
    )

    assert tuple(candidate["radius_m"] for candidate in candidates) == radii


def test_16_normal_run_writes_csv_and_json(tmp_path: Path) -> None:
    report = run_scale_distribution_step(make_config(tmp_path))

    assert report["status"] == "ok"
    assert Path(report["output_csv_path"]).is_file()
    assert Path(report["output_json_path"]).is_file()
    assert report["files_written"] == [
        report["output_csv_path"],
        report["output_json_path"],
    ]


def test_17_output_json_has_exactly_required_keys(tmp_path: Path) -> None:
    report = run_scale_distribution_step(make_config(tmp_path))
    payload = json.loads(Path(report["output_json_path"]).read_text(encoding="utf-8"))

    assert tuple(payload) == JSON_FIELDS


def test_18_source_contains_no_scale_inference_or_label_parsing() -> None:
    source = (
        REPO_ROOT / "metashape_qc_engine" / "level1b_scale_distribution.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "structure_derived_scale_distribution",
        "metric_scale_sweep",
        "_texture_radius_from_role",
        "texture_support_max_m",
        "patch_radius_quantiles",
        "upper_radius_factor",
        "max_candidate_radius_fraction",
        "proxy_structure_mode",
        "channel_report",
        "TEX_100M",
        "TEX_200M",
    )

    assert [value for value in forbidden if value in source] == []


def test_19_protected_existing_files_are_unchanged(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    first = run_scale_distribution_step(config)
    csv_path = Path(first["output_csv_path"])
    json_path = Path(first["output_json_path"])
    csv_before = csv_path.read_text(encoding="utf-8")
    json_before = json_path.read_text(encoding="utf-8")

    second = run_scale_distribution_step(config)

    assert second["status"] == "failed"
    assert second["files_written"] == []
    assert csv_path.read_text(encoding="utf-8") == csv_before
    assert json_path.read_text(encoding="utf-8") == json_before
