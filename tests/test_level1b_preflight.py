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
        "input_contract",
        "mask_contract",
        "band_roles",
        "declared_channels",
        "mask_status",
        "contract_checks",
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


def test_rgb_omitted_band_roles_succeeds_and_reports_rgb_roles(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
        )
    )

    assert report["status"] == "ok"
    assert report["input_contract"] == "rgb"
    assert report["band_roles"] == ["red", "green", "blue"]
    assert report["declared_channels"] is None


def test_rgb_exact_band_roles_succeeds(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
            band_roles=["red", "green", "blue"],
        )
    )

    assert report["status"] == "ok"
    assert report["input_contract"] == "rgb"
    assert report["band_roles"] == ["red", "green", "blue"]


def test_rgb_wrong_band_roles_fails_rgb_contract(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
            band_roles=["red", "green", "nir"],
        )
    )

    assert report["status"] == "failed"
    assert report["input_contract"] == "invalid"
    assert report["contract_checks"]["rgb_band_roles_valid"] is False
    assert "rgb band_roles must be exactly red, green, blue" in report["failure_reasons"]


def test_rgb_declared_channels_fails_rgb_contract(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
            declared_channels=["red", "green", "blue"],
        )
    )

    assert report["status"] == "failed"
    assert report["input_contract"] == "invalid"
    assert report["contract_checks"]["rgb_declared_channels_absent"] is False
    assert "rgb input must not declare generic channels" in report["failure_reasons"]


def test_multichannel_without_declared_channels_fails_contract(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="multichannel",
        )
    )

    assert report["status"] == "failed"
    assert report["input_contract"] == "invalid"
    assert report["contract_checks"]["multichannel_declared_channels_present"] is False
    assert "multichannel input requires declared_channels" in report["failure_reasons"]


def test_multichannel_with_declared_channels_succeeds(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="multichannel",
            declared_channels=["red", "nir"],
        )
    )

    assert report["status"] == "ok"
    assert report["input_contract"] == "multichannel"
    assert report["band_roles"] is None
    assert report["declared_channels"] == ["red", "nir"]


def test_multichannel_empty_declared_channel_fails_contract(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="multichannel",
            declared_channels=["red", " "],
        )
    )

    assert report["status"] == "failed"
    assert report["declared_channels"] == ["red", ""]
    assert report["contract_checks"]["multichannel_declared_channels_non_empty"] is False
    assert "declared_channels must not contain empty values" in report["failure_reasons"]


def test_multichannel_duplicate_declared_channels_fails_contract(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="multichannel",
            declared_channels=["red", "red"],
        )
    )

    assert report["status"] == "failed"
    assert report["contract_checks"]["multichannel_declared_channels_unique"] is False
    assert "declared_channels must be unique" in report["failure_reasons"]


def test_multichannel_band_roles_length_mismatch_fails_contract(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="multichannel",
            declared_channels=["red", "nir"],
            band_roles=["reflectance"],
        )
    )

    assert report["status"] == "failed"
    assert report["contract_checks"]["multichannel_band_roles_valid"] is False
    assert (
        "multichannel band_roles length must match declared_channels"
        in report["failure_reasons"]
    )


def test_multichannel_empty_band_role_fails_contract(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="multichannel",
            declared_channels=["red", "nir"],
            band_roles=["reflectance", " "],
        )
    )

    assert report["status"] == "failed"
    assert report["band_roles"] == ["reflectance", ""]
    assert report["contract_checks"]["multichannel_band_roles_valid"] is False
    assert "multichannel band_roles must not contain empty values" in report["failure_reasons"]


def test_multichannel_declared_channels_and_matching_band_roles_succeeds(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="multichannel",
            declared_channels=["red", "nir"],
            band_roles=["reflectance", "reflectance"],
        )
    )

    assert report["status"] == "ok"
    assert report["input_contract"] == "multichannel"
    assert report["declared_channels"] == ["red", "nir"]
    assert report["band_roles"] == ["reflectance", "reflectance"]


def test_mask_required_existing_valid_mask_path_succeeds_with_provided_status(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    mask_path = tmp_path / "valid-mask.tif"
    mask_path.touch()

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
            valid_mask_path=mask_path,
            mask_contract="required",
        )
    )

    assert report["status"] == "ok"
    assert report["mask_contract"] == "required"
    assert report["mask_status"] == "provided"


def test_mask_required_no_valid_mask_path_fails_with_missing_required_status(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
            mask_contract="required",
        )
    )

    assert report["status"] == "failed"
    assert report["mask_status"] == "missing_required"
    assert "valid_mask_path is required by mask_contract" in report["failure_reasons"]


def test_mask_required_missing_valid_mask_path_fails_with_missing_path_status(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
            valid_mask_path=tmp_path / "missing-mask.tif",
            mask_contract="required",
        )
    )

    assert report["status"] == "failed"
    assert report["mask_status"] == "missing_path"
    assert "valid_mask_path does not exist" in report["failure_reasons"]


def test_mask_optional_no_valid_mask_path_succeeds_with_not_provided_optional_status(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
            mask_contract="optional",
        )
    )

    assert report["status"] == "ok"
    assert report["mask_status"] == "not_provided_optional"


def test_mask_optional_existing_valid_mask_path_succeeds_with_provided_status(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    mask_path = tmp_path / "valid-mask.tif"
    mask_path.touch()

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
            valid_mask_path=mask_path,
            mask_contract="optional",
        )
    )

    assert report["status"] == "ok"
    assert report["mask_status"] == "provided"


def test_mask_optional_missing_valid_mask_path_fails_with_missing_path_status(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
            valid_mask_path=tmp_path / "missing-mask.tif",
            mask_contract="optional",
        )
    )

    assert report["status"] == "failed"
    assert report["mask_status"] == "missing_path"
    assert "valid_mask_path does not exist" in report["failure_reasons"]


def test_mask_absent_no_valid_mask_path_succeeds_with_declared_absent_status(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
            mask_contract="absent",
        )
    )

    assert report["status"] == "ok"
    assert report["mask_status"] == "declared_absent"


def test_mask_absent_valid_mask_path_fails_with_forbidden_when_absent_status(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    mask_path = tmp_path / "valid-mask.tif"
    mask_path.touch()

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
            valid_mask_path=mask_path,
            mask_contract="absent",
        )
    )

    assert report["status"] == "failed"
    assert report["mask_status"] == "forbidden_when_absent"
    assert (
        "valid_mask_path must be omitted when mask_contract is absent"
        in report["failure_reasons"]
    )


def test_mask_invalid_contract_fails_with_invalid_contract_status(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
            mask_contract="sometimes",
        )
    )

    assert report["status"] == "failed"
    assert report["mask_contract"] == "sometimes"
    assert report["mask_status"] == "invalid_contract"
    assert "mask_contract must be one of required, optional, absent" in report["failure_reasons"]


def test_report_includes_input_and_mask_contract_keys(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
        )
    )

    assert {
        "input_contract",
        "mask_contract",
        "band_roles",
        "declared_channels",
        "mask_status",
        "contract_checks",
    } <= set(report)


def test_contract_checks_has_exactly_required_input_and_mask_contract_keys(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
        )
    )

    assert set(report["contract_checks"]) == {
        "input_contract_valid",
        "rgb_band_roles_valid",
        "rgb_declared_channels_absent",
        "multichannel_declared_channels_present",
        "multichannel_declared_channels_non_empty",
        "multichannel_declared_channels_unique",
        "multichannel_band_roles_valid",
        "mask_contract_valid",
        "mask_path_requirement_valid",
    }


def test_no_processing_performed_remains_true_for_input_and_mask_contracts(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
        )
    )

    assert report["no_processing_performed"] is True


def test_default_runtime_and_alias_tmp_dir_semantics_remain_unchanged(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    output_dir = tmp_path / "out"
    custom_tmp = tmp_path / "custom-tmp"

    default_report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-default",
            input_path=make_input(tmp_path, "default.tif"),
            output_dir=output_dir,
            input_type="rgb",
        )
    )
    custom_report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-custom",
            input_path=make_input(tmp_path, "custom.tif"),
            output_dir=tmp_path / "out-custom",
            tmp_dir=custom_tmp,
            input_type="rgb",
        )
    )

    assert default_report["default_tmp_dir"] == str(output_dir / "level1b" / "tmp")
    assert default_report["runtime_tmp_dir"] == default_report["default_tmp_dir"]
    assert default_report["tmp_dir"] == default_report["runtime_tmp_dir"]
    assert custom_report["default_tmp_dir"] == str(tmp_path / "out-custom" / "level1b" / "tmp")
    assert custom_report["runtime_tmp_dir"] == str(custom_tmp)
    assert custom_report["tmp_dir"] == custom_report["runtime_tmp_dir"]


def test_memory_field_absent_from_report_and_source(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
        )
    )
    source = (REPO_ROOT / "metashape_qc_engine" / "level1b_preflight.py").read_text(
        encoding="utf-8"
    )

    assert "ram" + "_mb" not in report
    assert "ram" + "_mb" not in source


def test_source_contains_no_forbidden_runner_or_import_symbols() -> None:
    source = (REPO_ROOT / "metashape_qc_engine" / "level1b_preflight.py").read_text(
        encoding="utf-8"
    )
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
        "num" + "py",
    ]

    assert not re.search("|".join(forbidden), source)


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


def test_missing_gdal_edit_fails_preflight(tmp_path: Path, monkeypatch) -> None:
    def missing_gdal_edit(executable_name: str) -> str | None:
        if executable_name == "gdal_edit.py":
            return None
        return fake_otb_path(executable_name)

    monkeypatch.setattr("shutil.which", missing_gdal_edit)

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=make_input(tmp_path),
            output_dir=tmp_path / "out",
            input_type="rgb",
        )
    )

    assert report["status"] == "failed"
    assert report["checks"]["gdal_edit_discoverable"] is False
    assert "missing required executable: gdal_edit.py" in report["failure_reasons"]


def test_module_source_omits_forbidden_controller_symbols() -> None:
    source = (REPO_ROOT / "metashape_qc_engine" / "level1b_preflight.py").read_text(
        encoding="utf-8"
    )
    assert {
        "DimensionalityReduction",
        "HaralickTextureExtraction",
        "MeanShiftSmoothing",
        "LSMSSegmentation",
        "LSMSVectorization",
        "HooverCompareSegmentation",
    } <= set(DEFAULT_REQUIRED_OTB_APPS)
    assert "LocalStatisticExtraction" not in DEFAULT_REQUIRED_OTB_APPS
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
        "num" + "py",
    ]

    assert not re.search("|".join(forbidden), source)
