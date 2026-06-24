import json
from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from metashape_qc_engine.level1b_preflight import (
    DEFAULT_REQUIRED_OTB_APPS,
    LEGACY_SMALL_REGIONS_MERGING_APP,
    Level1BPreflightConfig,
    discover_required_otb_apps,
    run_preflight,
)


def fake_otb_path(executable_name: str) -> str:
    return f"/fake/bin/{executable_name}"


def make_input(tmp_path: Path, name: str = "input.tif") -> Path:
    input_path = tmp_path / name
    input_path.touch()
    return input_path


def test_existing_input_valid_candidate_and_discovered_apps_returns_ok(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    input_path = make_input(tmp_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=input_path,
            output_dir=tmp_path / "out",
            input_type="rgb",
        )
    )

    assert report["status"] == "ok"
    assert report["candidate_id"] == "candidate-1"
    assert report["input_path"] == str(input_path)
    assert report["required_otb_apps"] == list(DEFAULT_REQUIRED_OTB_APPS)
    assert report["checks"]["candidate_id_non_empty"] is True
    assert report["checks"]["input_path_exists"] is True
    assert report["checks"]["input_suffix_raster_like"] is True
    assert report["checks"]["required_otb_apps_discoverable"] is True
    assert report["no_processing_performed"] is True


def test_missing_input_path_returns_failed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=tmp_path / "missing.tif",
            output_dir=tmp_path / "out",
            input_type="rgb",
        )
    )

    assert report["status"] == "failed"
    assert report["checks"]["input_path_exists"] is False
    assert "input_path does not exist" in report["failure_reasons"][0]


def test_empty_candidate_id_returns_failed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id=" ",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="multichannel",
        )
    )

    assert report["status"] == "failed"
    assert report["checks"]["candidate_id_non_empty"] is False
    assert "candidate_id is empty" in report["failure_reasons"]


def test_invalid_input_type_returns_failed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="pan",
        )
    )

    assert report["status"] == "failed"
    assert report["checks"]["input_type_valid"] is False
    assert "input_type must be exactly 'rgb' or 'multichannel'" in report["failure_reasons"]


def test_missing_valid_mask_path_returns_failed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
            valid_mask_path=tmp_path / "missing-mask.tif",
        )
    )

    assert report["status"] == "failed"
    assert report["checks"]["valid_mask_path_exists"] is False
    assert any(reason.startswith("valid_mask_path does not exist") for reason in report["failure_reasons"])


def test_candidate_state_string_failed_returns_failed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
            candidate_state="failed",
        )
    )

    assert report["status"] == "failed"
    assert report["checks"]["candidate_state_not_failed"] is False
    assert "candidate_state is failed" in report["failure_reasons"]


def test_candidate_state_mapping_failed_returns_failed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
            candidate_state={"status": "failed"},
        )
    )

    assert report["status"] == "failed"
    assert report["checks"]["candidate_state_not_failed"] is False


def test_output_layout_and_preflight_report_are_created(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    output_dir = tmp_path / "out"

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=output_dir,
            input_type="rgb",
        )
    )

    level1b_dir = output_dir / "level1b"
    default_tmp_dir = level1b_dir / "tmp"
    report_path = level1b_dir / "reports" / "preflight.json"
    assert level1b_dir.is_dir()
    assert default_tmp_dir.is_dir()
    assert (level1b_dir / "logs").is_dir()
    assert (level1b_dir / "reports").is_dir()
    assert report["default_tmp_dir"] == str(default_tmp_dir)
    assert report["runtime_tmp_dir"] == str(default_tmp_dir)
    assert report["tmp_dir"] == report["runtime_tmp_dir"]
    assert report["checks"]["default_tmp_dir_created"] is True
    assert report["checks"]["runtime_tmp_dir_created"] is True
    assert report_path.is_file()
    report_json = json.loads(report_path.read_text(encoding="utf-8"))
    assert "ram" + "_mb" not in report_json
    assert report_json == report


def test_custom_tmp_dir_is_created_and_reported(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    output_dir = tmp_path / "out"
    custom_tmp = tmp_path / "custom-tmp"

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=output_dir,
            tmp_dir=custom_tmp,
            input_type="rgb",
        )
    )

    default_tmp_dir = output_dir / "level1b" / "tmp"
    assert default_tmp_dir.is_dir()
    assert custom_tmp.is_dir()
    assert report["default_tmp_dir"] == str(default_tmp_dir)
    assert report["runtime_tmp_dir"] == str(custom_tmp)
    assert report["tmp_dir"] == report["runtime_tmp_dir"]
    assert report["checks"]["default_tmp_dir_created"] is True
    assert report["checks"]["runtime_tmp_dir_created"] is True

    report_json = json.loads(
        (output_dir / "level1b" / "reports" / "preflight.json").read_text(encoding="utf-8")
    )
    assert report_json["default_tmp_dir"] == str(default_tmp_dir)
    assert report_json["runtime_tmp_dir"] == str(custom_tmp)
    assert report_json["tmp_dir"] == report_json["runtime_tmp_dir"]
    assert "ram" + "_mb" not in report_json


def test_preflight_json_contains_required_schema_values(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    output_dir = tmp_path / "out"
    input_path = make_input(tmp_path)

    run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=input_path,
            output_dir=output_dir,
            input_type="rgb",
        )
    )
    report = json.loads(
        (output_dir / "level1b" / "reports" / "preflight.json").read_text(encoding="utf-8")
    )

    assert {
        "candidate_id",
        "input_path",
        "input_type",
        "output_dir",
        "default_tmp_dir",
        "runtime_tmp_dir",
        "tmp_dir",
        "required_otb_apps",
        "app_availability",
        "small_regions_merging_app",
        "checks",
        "status",
        "failure_reasons",
        "timestamp",
        "no_processing_performed",
    } <= set(report)
    assert report["candidate_id"] == "candidate-1"
    assert report["input_path"] == str(input_path)
    assert report["input_type"] == "rgb"
    assert report["output_dir"] == str(output_dir)
    assert report["default_tmp_dir"] == str(output_dir / "level1b" / "tmp")
    assert report["runtime_tmp_dir"] == report["default_tmp_dir"]
    assert report["tmp_dir"] == report["runtime_tmp_dir"]
    assert report["no_processing_performed"] is True
    assert "ram" + "_mb" not in report


def test_accepted_raster_like_suffixes_return_ok(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    for suffix in (".tif", ".tiff", ".vrt", ".img", ".jp2"):
        report = run_preflight(
            Level1BPreflightConfig(
                candidate_id=f"candidate-{suffix[1:]}",
                input_path=make_input(tmp_path, f"input{suffix}"),
                output_dir=tmp_path / f"out-{suffix[1:]}",
                input_type="rgb",
            )
        )
        assert report["status"] == "ok"
        assert report["checks"]["input_suffix_raster_like"] is True


def test_rejected_input_suffix_returns_failed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path, "input.txt"),
            output_dir=tmp_path / "out",
            input_type="rgb",
        )
    )

    assert report["status"] == "failed"
    assert report["checks"]["input_suffix_raster_like"] is False
    assert any("input_path suffix must be one of" in reason for reason in report["failure_reasons"])


def test_discovery_uses_shutil_which_only(monkeypatch) -> None:
    calls: list[str] = []

    def record_which(executable_name: str) -> str:
        calls.append(executable_name)
        return fake_otb_path(executable_name)

    monkeypatch.setattr("shutil.which", record_which)

    availability, small_regions_merging_app = discover_required_otb_apps(DEFAULT_REQUIRED_OTB_APPS)

    assert small_regions_merging_app == "SmallRegionsMerging"
    assert set(availability) == set(DEFAULT_REQUIRED_OTB_APPS) | {LEGACY_SMALL_REGIONS_MERGING_APP}
    expected_calls: list[str] = []
    for app in DEFAULT_REQUIRED_OTB_APPS:
        expected_calls.append(f"otbcli_{app}")
        if app == "SmallRegionsMerging":
            expected_calls.append(f"otbcli_{LEGACY_SMALL_REGIONS_MERGING_APP}")
    assert calls == expected_calls


def test_small_regions_merging_prefers_primary_when_both_exist(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    availability, small_regions_merging_app = discover_required_otb_apps(DEFAULT_REQUIRED_OTB_APPS)

    assert small_regions_merging_app == "SmallRegionsMerging"
    assert availability["SmallRegionsMerging"]["available"] is True
    assert availability[LEGACY_SMALL_REGIONS_MERGING_APP]["available"] is True


def test_legacy_small_regions_merging_is_reported_only_when_primary_missing(monkeypatch) -> None:
    def only_legacy(executable_name: str) -> str | None:
        if executable_name == "otbcli_SmallRegionsMerging":
            return None
        return fake_otb_path(executable_name)

    monkeypatch.setattr("shutil.which", only_legacy)

    availability, small_regions_merging_app = discover_required_otb_apps(DEFAULT_REQUIRED_OTB_APPS)

    assert small_regions_merging_app == LEGACY_SMALL_REGIONS_MERGING_APP
    assert availability["SmallRegionsMerging"]["available"] is False
    assert availability[LEGACY_SMALL_REGIONS_MERGING_APP]["available"] is True


def test_missing_primary_and_legacy_small_regions_merging_fails(tmp_path: Path, monkeypatch) -> None:
    def no_small_regions(executable_name: str) -> str | None:
        if executable_name in {
            "otbcli_SmallRegionsMerging",
            f"otbcli_{LEGACY_SMALL_REGIONS_MERGING_APP}",
        }:
            return None
        return fake_otb_path(executable_name)

    monkeypatch.setattr("shutil.which", no_small_regions)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
        )
    )

    assert report["status"] == "failed"
    assert report["small_regions_merging_app"] is None
    assert any(
        "SmallRegionsMerging or " in reason and LEGACY_SMALL_REGIONS_MERGING_APP in reason
        for reason in report["failure_reasons"]
    )


def test_missing_any_non_legacy_required_otb_app_fails(tmp_path: Path, monkeypatch) -> None:
    missing_app = "BandMathX"

    def one_missing(executable_name: str) -> str | None:
        if executable_name == f"otbcli_{missing_app}":
            return None
        return fake_otb_path(executable_name)

    monkeypatch.setattr("shutil.which", one_missing)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
        )
    )

    assert report["status"] == "failed"
    assert report["checks"]["required_otb_apps_discoverable"] is False
    assert any(missing_app in reason for reason in report["failure_reasons"])


def test_module_source_omits_forbidden_controller_symbols() -> None:
    source = (REPO_ROOT / "metashape_qc_engine" / "level1b_preflight.py").read_text(
        encoding="utf-8"
    )
    assert {
        "MeanShiftSmoothing",
        "LSMSSegmentation",
        "LSMSVectorization",
        "HooverCompareSegmentation",
    } <= set(DEFAULT_REQUIRED_OTB_APPS)
    assert LEGACY_SMALL_REGIONS_MERGING_APP == "LSMSSmallRegionsMerging"

    forbidden = [
        "run_" + "otb_app",
        "OTB" + "Command" + "Result",
        "OTB" + "Command" + "Error",
        "sub" + "process",
        "sub" + "process.run",
        r"\b" + "ti" + r"me\b",
        "ti" + "me.monotonic",
        "link" + "2GI",
        "raster" + "io",
        "os" + "geo",
        "g" + "dal",
        "num" + "py",
    ]

    assert not re.search("|".join(forbidden), source)
