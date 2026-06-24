from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from metashape_qc_engine.level1b_preflight import (
    DEFAULT_REQUIRED_OTB_APPS,
    Level1BPreflightConfig,
    discover_required_otb_apps,
    run_preflight,
)


def fake_otb_path(executable_name: str) -> str:
    return f"/fake/bin/{executable_name}"


def test_missing_input_fails_without_otb_install(tmp_path: Path, monkeypatch) -> None:
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
    assert report["no_processing_performed"] is True
    assert (tmp_path / "out" / "level1b" / "reports" / "preflight.json").is_file()


def test_empty_candidate_id_fails_without_otb_install(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    input_path = tmp_path / "input.tif"
    input_path.touch()

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id=" ",
            input_path=input_path,
            output_dir=tmp_path / "out",
            input_type="multichannel",
        )
    )

    assert report["status"] == "failed"
    assert report["checks"]["candidate_id_non_empty"] is False


def test_output_layout_path_construction_works(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)
    input_path = tmp_path / "input.tif"
    input_path.touch()

    report = run_preflight(
        Level1BPreflightConfig(
            candidate_id="candidate-1",
            input_path=input_path,
            output_dir=tmp_path / "out",
            input_type="rgb",
        )
    )

    level1b_dir = tmp_path / "out" / "level1b"
    assert report["status"] == "ok"
    assert level1b_dir.is_dir()
    assert (level1b_dir / "tmp").is_dir()
    assert (level1b_dir / "logs").is_dir()
    assert (level1b_dir / "reports").is_dir()
    assert report["tmp_dir"] == str(level1b_dir / "tmp")


def test_small_regions_merging_prefers_primary_when_both_exist(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", fake_otb_path)

    availability, small_regions_merging_app = discover_required_otb_apps(DEFAULT_REQUIRED_OTB_APPS)

    assert small_regions_merging_app == "SmallRegionsMerging"
    assert availability["SmallRegionsMerging"]["available"] is True
    assert availability["LSMSSmallRegionsMerging"]["available"] is True


def test_small_regions_merging_legacy_fallback_is_reported(monkeypatch) -> None:
    def only_legacy(executable_name: str) -> str | None:
        if executable_name == "otbcli_SmallRegionsMerging":
            return None
        return f"/fake/bin/{executable_name}"

    monkeypatch.setattr("shutil.which", only_legacy)

    availability, small_regions_merging_app = discover_required_otb_apps(DEFAULT_REQUIRED_OTB_APPS)

    assert small_regions_merging_app == "LSMSSmallRegionsMerging"
    assert availability["SmallRegionsMerging"]["available"] is False
    assert availability["LSMSSmallRegionsMerging"]["available"] is True
