from pathlib import Path
import shutil

from click.testing import CliRunner

from bootlab.backends.mcuboot_sim import SimulatorResult
from bootlab import cli as cli_module
from bootlab.cli import main
from bootlab.scenario import Backend


def _fake_run(workspace: Path, monkeypatch, output_for):
    class FakeAdapter:
        def __init__(self, _workspace):
            pass

        def run(self, scenario):
            return output_for(scenario)

    monkeypatch.setattr("bootlab.cli.McubootSimAdapter", FakeAdapter)


def _copy_scenarios(workspace: Path, *scenario_names: str) -> Path:
    source = Path(__file__).resolve().parents[1] / "scenarios"
    target = workspace / "scenarios"
    target.mkdir(parents=True)
    for name in scenario_names:
        (target / name).write_bytes((source / name).read_bytes())
    return target


def test_unknown_matrix_profile_fails_before_backend_execution() -> None:
    workspace = Path(__file__).resolve().parents[1]
    result = CliRunner().invoke(
        main,
        [
            "--workspace",
            str(workspace),
            "run-matrix",
            "--profile",
            "misspelled-profile",
        ],
    )
    assert result.exit_code != 0
    assert "No scenarios matched profile" in result.output


def test_fault_sweep_rejects_empty_and_reversed_selections() -> None:
    workspace = Path(__file__).resolve().parents[1]
    runner = CliRunner()
    empty = runner.invoke(
        main, ["--workspace", str(workspace), "fault-sweep", "--indices", ""]
    )
    reversed_range = runner.invoke(
        main,
        ["--workspace", str(workspace), "fault-sweep", "--start", "5", "--end", "2"],
    )
    assert empty.exit_code != 0
    assert "must not be empty" in empty.output
    assert reversed_range.exit_code != 0
    assert "greater than or equal" in reversed_range.output
    duplicates = runner.invoke(
        main,
        ["--workspace", str(workspace), "fault-sweep", "--indices", "1,1"],
    )
    assert duplicates.exit_code != 0
    assert "must not contain duplicates" in duplicates.output


def test_unknown_profile_comparison_fails_before_backend_execution() -> None:
    workspace = Path(__file__).resolve().parents[1]
    result = CliRunner().invoke(
        main,
        [
            "--workspace",
            str(workspace),
            "compare-profiles",
            "misspelled-profile",
            "mcuboot_swap_reference",
        ],
    )
    assert result.exit_code != 0
    assert "Unknown profile" in result.output


def test_approved_skip_cannot_hide_zero_executed_tests(
    tmp_path: Path, monkeypatch
) -> None:
    _copy_scenarios(tmp_path, "V02_downgrade_disabled_control.yaml")
    monkeypatch.setitem(
        cli_module.APPROVED_SKIP_CODES, "V02", "DECLARED_UNSUPPORTED_CONFIGURATION"
    )

    def no_tests(scenario):
        return SimulatorResult(
            0,
            "test result: ok. 0 passed; 0 failed; 24 filtered out;",
            "",
            Backend.MCUBOOT_SIM,
            scenario.backend_args,
        )

    _fake_run(tmp_path, monkeypatch, no_tests)
    result = CliRunner().invoke(
        main,
        [
            "--workspace",
            str(tmp_path),
            "run-matrix",
            "--scenarios-dir",
            "scenarios",
            "--profile",
            "mcuboot_overwrite_reference",
            "--allow-skip",
            "V02",
        ],
    )
    assert result.exit_code != 0
    assert "NOT_EXECUTED" in result.output or "FAIL" in result.output


def test_approved_skip_cannot_hide_failed_execution(
    tmp_path: Path, monkeypatch
) -> None:
    _copy_scenarios(tmp_path, "V02_downgrade_disabled_control.yaml")
    monkeypatch.setitem(
        cli_module.APPROVED_SKIP_CODES, "V02", "DECLARED_UNSUPPORTED_CONFIGURATION"
    )

    def executed_noop(scenario):
        name = scenario.backend_args["cargo_test"]
        return SimulatorResult(
            1,
            f"test {name} ... FAILED\ntest result: FAILED. 0 passed; 1 failed; 23 filtered out;",
            "",
            Backend.MCUBOOT_SIM,
            scenario.backend_args,
        )

    _fake_run(tmp_path, monkeypatch, executed_noop)
    result = CliRunner().invoke(
        main,
        [
            "--workspace",
            str(tmp_path),
            "run-matrix",
            "--scenarios-dir",
            "scenarios",
            "--profile",
            "mcuboot_overwrite_reference",
            "--allow-skip",
            "V02",
        ],
    )
    assert result.exit_code != 0
    assert "FAIL" in result.output or "NOT_EXECUTED" in result.output


def test_compare_profiles_does_not_allow_missing_execution(
    tmp_path: Path, monkeypatch
) -> None:
    _copy_scenarios(tmp_path, "P01_boot_v1.yaml", "V02_downgrade_disabled_control.yaml")

    def no_tests(scenario):
        return SimulatorResult(
            0,
            "test result: ok. 0 passed; 0 failed; 24 filtered out;",
            "",
            Backend.MCUBOOT_SIM,
            scenario.backend_args,
        )

    _fake_run(tmp_path, monkeypatch, no_tests)
    result = CliRunner().invoke(
        main,
        [
            "--workspace",
            str(tmp_path),
            "compare-profiles",
            "mcuboot_swap_reference",
            "mcuboot_overwrite_reference",
            "--scenarios-dir",
            "scenarios",
        ],
    )
    assert result.exit_code != 0
    assert "failed/unapproved" in result.output


def test_allow_skip_rejects_unknown_or_unregistered_ids() -> None:
    workspace = Path(__file__).resolve().parents[1]
    result = CliRunner().invoke(
        main,
        [
            "--workspace",
            str(workspace),
            "run-matrix",
            "--profile",
            "mcuboot_swap_reference",
            "--allow-skip",
            "F01",
        ],
    )
    assert result.exit_code != 0
    assert "not approved for skips" in result.output


def test_validate_scenarios_rejects_empty_inventory(tmp_path: Path) -> None:
    (tmp_path / "scenarios").mkdir()
    shutil.copytree(
        Path(__file__).resolve().parents[1] / "profiles",
        tmp_path / "profiles",
    )
    result = CliRunner().invoke(
        main,
        ["--workspace", str(tmp_path), "validate-scenarios"],
    )
    assert result.exit_code != 0
    assert "must not be empty" in result.output


def test_validate_scenarios_rejects_profile_typo_before_backend(
    tmp_path: Path, monkeypatch
) -> None:
    source = Path(__file__).resolve().parents[1]
    shutil.copytree(source / "profiles", tmp_path / "profiles")
    _copy_scenarios(tmp_path, "D01_direct_authenticated_upgrade.yaml")
    profile_path = tmp_path / "profiles" / "mcuboot_overwrite_reference.yaml"
    profile_path.write_text(
        profile_path.read_text() + "\nmisspelled_profile_field: true\n"
    )

    def backend_must_not_run(_workspace):
        raise AssertionError("backend construction must not happen during validation")

    monkeypatch.setattr(cli_module, "McubootSimAdapter", backend_must_not_run)
    result = CliRunner().invoke(
        main,
        ["--workspace", str(tmp_path), "validate-scenarios"],
    )
    assert result.exit_code != 0
    assert "misspelled_profile_field" in result.output
