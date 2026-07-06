from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[1]
SHELL_WRAPPER = (
    REPO_ROOT
    / "metashape_qc_engine"
    / "run_level1b_dumb_with_user_header.sh"
)


def test_shell_wrapper_is_environment_only_and_syntax_valid() -> None:
    subprocess.run(["bash", "-n", str(SHELL_WRAPPER)], check=True)
    source = SHELL_WRAPPER.read_text(encoding="utf-8")

    for obsolete in (
        "CANDIDATE_ID",
        "USE_PCA",
        "PCA_COMPONENTS",
        "RAM_MB",
        "DRY_RUN",
        "REQUIRE_STEP9",
        "OTB_BIN_DIR",
        "_driver_logs",
        "_driver_reports",
    ):
        assert obsolete not in source
    assert source.count("tee -a") == 1
    assert 'SHELL_LOG="$RUN_ROOT/level1b_chain.log"' in source
    assert source.count(
        "python3 -m metashape_qc_engine.level1b.dumb_runner"
    ) == 2
    assert 'export LEVEL1B_OTB_GDAL_DATA_ORIG="${GDAL_DATA:-}"' in source
    assert 'export LEVEL1B_OTB_PROJ_LIB_ORIG="${PROJ_LIB:-}"' in source
    assert "unset GDAL_DATA PROJ_LIB" in source
    assert "--rgb-ortho" in source
    assert "--out-dir" in source
    assert "--overwrite" in source


def test_shell_wrapper_contains_no_scientific_step_policy() -> None:
    source = SHELL_WRAPPER.read_text(encoding="utf-8").lower()
    for forbidden in (
        "scale_values",
        "ranger",
        "perturbation",
        "midpoint",
        "gain_share",
        "candidate_response_surface",
        "quality class",
    ):
        assert forbidden not in source
