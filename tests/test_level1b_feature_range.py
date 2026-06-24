import json
from math import sqrt
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import metashape_qc_engine.level1b_feature_range as feature_range
from metashape_qc_engine.level1b_feature_range import (
    ASSIGNMENT_RULE,
    RANGER_SOURCE,
    Level1BFeatureRangeConfig,
    assign_single_ranger_to_scale_candidates,
    build_feature_statistics_command,
    build_level1b_feature_range_layout,
    build_single_ranger_candidate,
    parse_feature_statistics_xml,
    read_scale_candidates,
    run_feature_range_assignment_step,
    validate_feature_range_config,
)


def make_stack(tmp_path: Path, name: str = "feature_stack.tif") -> Path:
    path = tmp_path / name
    path.touch()
    return path


def make_scale_json(tmp_path: Path, payload: dict[str, object] | None = None) -> Path:
    path = tmp_path / "scale_candidates.json"
    if payload is None:
        payload = {
            "candidate_id": "candidate-1",
            "scale_mode": "metric_mode",
            "scale_source": "metric_radius_m",
            "pixel_size_m": 0.5,
            "pixel_area_m2": 0.25,
            "candidate_count": 2,
            "candidates": [
                {"candidate_id": "candidate-1_scale_001", "spatialr_px": 2, "minsize_px": 13},
                {"candidate_id": "candidate-1_scale_002", "spatialr_px": "3", "minsize_px": "21"},
            ],
        }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def make_config(tmp_path: Path, **overrides: object) -> Level1BFeatureRangeConfig:
    values = {
        "candidate_id": "candidate-1",
        "output_dir": tmp_path / "out",
        "feature_space_stack_path": make_stack(tmp_path),
        "feature_space_source": "scaled",
        "scale_candidates_json_path": make_scale_json(tmp_path),
        "band_count": 2,
        "ranger_multiplier": 1.5,
    }
    values.update(overrides)
    return Level1BFeatureRangeConfig(**values)


def validate(config: Level1BFeatureRangeConfig, apps: dict[str, str | None] | None = None):
    if apps is None:
        apps = {"ComputeImagesStatistics": "/fake/bin/otbcli_ComputeImagesStatistics"}
    return validate_feature_range_config(config, build_level1b_feature_range_layout(config.output_dir), apps)


def write_stats_xml(path: Path, values: list[float]) -> None:
    body = "\n".join(f'        <StatisticVector value="{value}" />' for value in values)
    path.write_text(
        f"""<?xml version="1.0" ?>
<FeatureStatistics>
    <Statistic name="mean">
        <StatisticVector value="0" />
    </Statistic>
    <Statistic name="stddev">
{body}
    </Statistic>
</FeatureStatistics>
""",
        encoding="utf-8",
    )


def test_01_layout_creates_only_ranger_dir_and_tmp_ranger_dir(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    layout = build_level1b_feature_range_layout(output_dir)

    assert list(layout) == ["ranger_dir", "tmp_ranger_dir"]
    assert layout["ranger_dir"].is_dir()
    assert layout["tmp_ranger_dir"].is_dir()
    assert sorted(path.relative_to(output_dir) for path in output_dir.rglob("*")) == [
        Path("level1b"),
        Path("level1b/ranger"),
        Path("level1b/tmp"),
        Path("level1b/tmp/ranger"),
    ]


def test_02_validation_fails_for_empty_candidate_id(tmp_path: Path) -> None:
    checks, reasons = validate(make_config(tmp_path, candidate_id=" "))

    assert checks["candidate_id_non_empty"] is False
    assert "candidate_id is empty" in reasons


def test_03_validation_fails_for_missing_feature_space_stack_path(tmp_path: Path) -> None:
    checks, reasons = validate(make_config(tmp_path, feature_space_stack_path=tmp_path / "missing.tif"))

    assert checks["feature_space_stack_path_exists"] is False
    assert "feature_space_stack_path does not exist" in reasons


def test_04_validation_fails_for_invalid_feature_space_source(tmp_path: Path) -> None:
    checks, reasons = validate(make_config(tmp_path, feature_space_source="raw"))

    assert checks["feature_space_source_valid"] is False
    assert "feature_space_source must be exactly scaled or pca" in reasons


def test_05_validation_fails_for_missing_scale_candidates_json_path(tmp_path: Path) -> None:
    checks, reasons = validate(make_config(tmp_path, scale_candidates_json_path=tmp_path / "missing.json"))

    assert checks["scale_candidates_json_path_exists"] is False
    assert "scale_candidates_json_path does not exist" in reasons


def test_06_validation_fails_for_invalid_band_count(tmp_path: Path) -> None:
    checks, reasons = validate(make_config(tmp_path, band_count=0))

    assert checks["band_count_positive_integer"] is False
    assert "band_count must be a positive integer" in reasons


def test_07_validation_fails_for_invalid_ranger_multiplier(tmp_path: Path) -> None:
    checks, reasons = validate(make_config(tmp_path, ranger_multiplier=0))

    assert checks["ranger_multiplier_numeric_positive"] is False
    assert "ranger_multiplier must be numeric and > 0" in reasons


def test_08_validation_fails_if_compute_images_statistics_is_missing(tmp_path: Path) -> None:
    checks, reasons = validate(make_config(tmp_path), {"ComputeImagesStatistics": None})

    assert checks["otb_compute_images_statistics_discoverable"] is False
    assert "no OTB ComputeImagesStatistics app discoverable" in reasons


def test_09_statistics_command_uses_compute_images_statistics_with_required_flags(tmp_path: Path) -> None:
    config = make_config(tmp_path, background_value=-7)
    layout = build_level1b_feature_range_layout(config.output_dir)
    command = build_feature_statistics_command(config, {"ComputeImagesStatistics": "/fake/bin/app"}, layout)

    assert command == [
        "otbcli_ComputeImagesStatistics",
        "-il",
        str(config.feature_space_stack_path),
        "-bv",
        "-7.0",
        "-out.xml",
        str(layout["tmp_ranger_dir"] / "feature_statistics.xml"),
    ]


def test_10_xml_parser_extracts_standard_deviations_from_real_otb_shape(tmp_path: Path) -> None:
    xml_path = tmp_path / "feature_statistics.xml"
    write_stats_xml(xml_path, [1.0, 1.0, 1.0, 0.999999, 0.999999])

    assert parse_feature_statistics_xml(xml_path, 5) == {
        "standard_deviations": [1.0, 1.0, 1.0, 0.999999, 0.999999]
    }


def test_11_xml_parser_supports_standard_deviation_descriptor_variants(tmp_path: Path) -> None:
    xml_path = tmp_path / "feature_statistics.xml"
    xml_path.write_text(
        """<FeatureStatistics>
  <Parameter name="out.std">1.25 2.5</Parameter>
  <Parameter key="standard deviation" values="3.75 5.0" />
</FeatureStatistics>
""",
        encoding="utf-8",
    )

    assert parse_feature_statistics_xml(xml_path, 4) == {"standard_deviations": [1.25, 2.5, 3.75, 5.0]}


def test_11b_xml_parser_fails_when_no_standard_deviation_values_are_present(tmp_path: Path) -> None:
    xml_path = tmp_path / "missing.xml"
    xml_path.write_text("<OTB><Mean>1</Mean></OTB>", encoding="utf-8")

    try:
        parse_feature_statistics_xml(xml_path, 2)
    except ValueError as exc:
        assert "invalid feature statistics" in str(exc)
    else:
        raise AssertionError("expected invalid feature statistics failure")


def test_11c_xml_parser_fails_when_fewer_than_band_count_standard_deviations_are_present(tmp_path: Path) -> None:
    xml_path = tmp_path / "too_few.xml"
    write_stats_xml(xml_path, [1.0])

    try:
        parse_feature_statistics_xml(xml_path, 2)
    except ValueError as exc:
        assert "invalid feature statistics" in str(exc)
    else:
        raise AssertionError("expected invalid feature statistics failure")


def test_11d_xml_parser_fails_when_selected_standard_deviation_is_nonpositive(tmp_path: Path) -> None:
    xml_path = tmp_path / "nonpositive.xml"
    write_stats_xml(xml_path, [1.0, 0.0])

    try:
        parse_feature_statistics_xml(xml_path, 2)
    except ValueError as exc:
        assert "invalid feature statistics" in str(exc)
    else:
        raise AssertionError("expected invalid feature statistics failure")


def test_12_single_ranger_candidate_derives_feature_std_l2(tmp_path: Path) -> None:
    candidate = build_single_ranger_candidate(make_config(tmp_path), {"standard_deviations": [3.0, 4.0]})

    assert candidate["feature_std_l2"] == 5.0


def test_13_single_ranger_candidate_derives_ranger_from_multiplier(tmp_path: Path) -> None:
    candidate = build_single_ranger_candidate(
        make_config(tmp_path, ranger_multiplier=2.0),
        {"standard_deviations": [3.0, 4.0]},
    )

    assert candidate["ranger"] == 10.0


def test_14_ranger_candidate_id_uses_candidate_id(tmp_path: Path) -> None:
    candidate = build_single_ranger_candidate(make_config(tmp_path), {"standard_deviations": [1.0, 2.0]})

    assert candidate["ranger_id"] == "candidate-1_ranger_001"


def test_15_ranger_source_is_feature_std_l2_times_single_multiplier(tmp_path: Path) -> None:
    candidate = build_single_ranger_candidate(make_config(tmp_path), {"standard_deviations": [1.0, 2.0]})

    assert candidate["ranger_source"] == RANGER_SOURCE


def test_16_read_scale_candidates_fails_if_candidates_key_is_missing(tmp_path: Path) -> None:
    path = make_scale_json(tmp_path, {"candidate_id": "candidate-1"})

    try:
        read_scale_candidates(path)
    except ValueError as exc:
        assert "candidates" in str(exc)
    else:
        raise AssertionError("expected missing candidates failure")


def test_17_read_scale_candidates_fails_if_required_scale_candidate_fields_are_missing(tmp_path: Path) -> None:
    for candidate in ({}, {"candidate_id": "s1"}, {"candidate_id": "s1", "spatialr_px": 2}):
        path = make_scale_json(tmp_path, {"candidates": [candidate]})
        try:
            read_scale_candidates(path)
        except ValueError as exc:
            assert "scale candidate lacks" in str(exc)
        else:
            raise AssertionError("expected required field failure")


def test_18_assignment_preserves_spatialr_px_and_minsize_px_from_step6_scale_candidates(tmp_path: Path) -> None:
    ranger = build_single_ranger_candidate(make_config(tmp_path), {"standard_deviations": [1.0, 2.0]})
    assigned = assign_single_ranger_to_scale_candidates(
        [{"candidate_id": "scale-1", "spatialr_px": "03", "minsize_px": 7.5}],
        ranger,
    )

    assert assigned[0]["spatialr_px"] == "03"
    assert assigned[0]["minsize_px"] == 7.5


def test_19_assignment_creates_exactly_one_row_per_step6_scale_candidate(tmp_path: Path) -> None:
    ranger = build_single_ranger_candidate(make_config(tmp_path), {"standard_deviations": [1.0, 2.0]})
    assigned = assign_single_ranger_to_scale_candidates(
        [
            {"candidate_id": "scale-1", "spatialr_px": 2, "minsize_px": 5},
            {"candidate_id": "scale-2", "spatialr_px": 3, "minsize_px": 8},
        ],
        ranger,
    )

    assert len(assigned) == 2


def test_20_assignment_rule_is_single_feature_range_assigned_to_each_scale_candidate(tmp_path: Path) -> None:
    ranger = build_single_ranger_candidate(make_config(tmp_path), {"standard_deviations": [1.0, 2.0]})
    assigned = assign_single_ranger_to_scale_candidates([{"candidate_id": "scale-1", "spatialr_px": 2, "minsize_px": 5}], ranger)

    assert assigned[0]["assignment_rule"] == ASSIGNMENT_RULE


def test_21_normal_run_writes_all_four_output_files(tmp_path: Path, monkeypatch) -> None:
    def fake_run(command: list[str], capture_output: bool, text: bool):
        write_stats_xml(Path(command[command.index("-out.xml") + 1]), [1.0, 1.0, 1.0, 0.999999, 0.999999])
        return feature_range.subprocess.CompletedProcess(command, 0, "ok", "")

    monkeypatch.setattr("shutil.which", lambda _name: "/fake/bin/otbcli_ComputeImagesStatistics")
    monkeypatch.setattr("metashape_qc_engine.level1b_feature_range.subprocess.run", fake_run)
    report = run_feature_range_assignment_step(make_config(tmp_path, band_count=5, ranger_multiplier=1.0))
    expected_feature_std_l2 = sqrt(1.0**2 + 1.0**2 + 1.0**2 + 0.999999**2 + 0.999999**2)

    assert report["status"] == "ok"
    assert report["feature_std_l2"] == expected_feature_std_l2
    assert report["ranger"] == expected_feature_std_l2
    assert len(report["files_written"]) == 4
    assert all(Path(path).is_file() for path in report["files_written"])


def test_22_ranger_candidates_json_has_exactly_required_keys(tmp_path: Path, monkeypatch) -> None:
    def fake_run(command: list[str], capture_output: bool, text: bool):
        write_stats_xml(Path(command[command.index("-out.xml") + 1]), [3.0, 4.0])
        return feature_range.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("shutil.which", lambda _name: "/fake/bin/otbcli_ComputeImagesStatistics")
    monkeypatch.setattr("metashape_qc_engine.level1b_feature_range.subprocess.run", fake_run)
    report = run_feature_range_assignment_step(make_config(tmp_path))
    payload = json.loads(Path(report["output_ranger_json_path"]).read_text(encoding="utf-8"))

    assert list(payload) == [
        "candidate_id",
        "feature_space_stack_path",
        "feature_space_source",
        "band_count",
        "background_value",
        "feature_statistics_xml_path",
        "feature_std_l2",
        "ranger_multiplier",
        "ranger_source",
        "ranger_count",
        "ranger_candidates",
    ]


def test_23_scale_candidates_with_ranger_json_has_exactly_required_keys(tmp_path: Path, monkeypatch) -> None:
    def fake_run(command: list[str], capture_output: bool, text: bool):
        write_stats_xml(Path(command[command.index("-out.xml") + 1]), [3.0, 4.0])
        return feature_range.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("shutil.which", lambda _name: "/fake/bin/otbcli_ComputeImagesStatistics")
    monkeypatch.setattr("metashape_qc_engine.level1b_feature_range.subprocess.run", fake_run)
    report = run_feature_range_assignment_step(make_config(tmp_path))
    payload = json.loads(Path(report["output_assigned_json_path"]).read_text(encoding="utf-8"))

    assert list(payload) == [
        "candidate_id",
        "scale_candidates_json_path",
        "ranger_candidates_json_path",
        "assignment_rule",
        "scale_candidate_count",
        "ranger_candidate_count",
        "assigned_candidate_count",
        "candidates",
    ]


def test_24_source_has_no_forbidden_raster_imports_or_workflow_symbols() -> None:
    module_source = (REPO_ROOT / "metashape_qc_engine" / "level1b_feature_range.py").read_text(encoding="utf-8")
    test_source = (REPO_ROOT / "tests" / "test_level1b_feature_range.py").read_text(encoding="utf-8")
    combined_source = module_source + "\n" + test_source
    blocked_imports = [
        "rast" + "erio",
        "os" + "geo",
        "g" + "dal",
        "num" + "py",
        "sci" + "py",
        "ski" + "mage",
        "c" + "v2",
        "P" + "IL",
        "pan" + "das",
        "geopan" + "das",
        "x" + "arr" + "ay",
        "rio" + "x" + "arr" + "ay",
        "ter" + "ra",
        "sta" + "rs",
        "link" + "2GI",
    ]
    blocked_symbols = [
        "build_" + "scale_candidates",
        "metric_" + "scale_sweep",
        "structure_" + "derived_scale_distribution",
        "recalculate_" + "spatialr",
        "recalculate_" + "minsize",
        "ranger_" + "multipliers",
        "full_" + "grid",
        "parameter_" + "grid",
        "Mean" + "Shift",
        "LS" + "MS",
        "Ho" + "over",
        "run_" + "segmentation",
    ]

    assert [symbol for symbol in blocked_imports + blocked_symbols if symbol in combined_source] == []


def test_25_protected_existing_files_are_unchanged() -> None:
    protected = [
        "metashape_qc_engine/level1b_preflight.py",
        "metashape_qc_engine/level1b_valid_mask.py",
        "metashape_qc_engine/level1b_channels.py",
        "metashape_qc_engine/level1b_scaling.py",
        "metashape_qc_engine/level1b_pca.py",
        "metashape_qc_engine/level1b_scale_distribution.py",
        "metashape_qc_engine/cli.py",
    ]

    assert feature_range.subprocess.run(["git", "diff", "--quiet", "--", *protected]).returncode == 0
