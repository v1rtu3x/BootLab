from pathlib import Path

from click.testing import CliRunner

from bootlab.cli import main


def test_unknown_matrix_profile_fails_before_backend_execution() -> None:
    workspace = Path(__file__).resolve().parents[1]
    result = CliRunner().invoke(
        main, ["--workspace", str(workspace), "run-matrix", "--profile", "misspelled-profile"]
    )
    assert result.exit_code != 0
    assert "No scenarios matched profile" in result.output


def test_fault_sweep_rejects_empty_and_reversed_selections() -> None:
    workspace = Path(__file__).resolve().parents[1]
    runner = CliRunner()
    empty = runner.invoke(main, ["--workspace", str(workspace), "fault-sweep", "--indices", ""])
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
            "--workspace", str(workspace), "compare-profiles",
            "misspelled-profile", "mcuboot_swap_reference",
        ],
    )
    assert result.exit_code != 0
    assert "Unknown profile" in result.output
