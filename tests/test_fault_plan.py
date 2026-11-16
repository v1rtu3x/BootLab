from pathlib import Path

import pytest

from bootlab.backends.mcuboot_sim import Backend, SimulatorResult
from bootlab.fault_plan import probe_total_ops, run_fault_index, sweep


class FakeAdapter:
    def __init__(self, result: SimulatorResult):
        self.result = result

    def run(self, _scenario):
        return self.result


def _result(index: int, reached: bool, operation_count: int = 406) -> SimulatorResult:
    return SimulatorResult(
        returncode=0,
        stdout=(
            f"FAULT_RESULT configuration=nrf52840-align-8-erased-ff index={index} reached={str(reached).lower()} "
            f"operation_count={operation_count} recovery_ok=true primary_image_valid=true "
            "secondary_image_valid=true primary_trailer_valid=true secondary_trailer_valid=true\n"
            "test fault_campaign_upgrade ... ok\n"
            "test result: ok. 1 passed; 0 failed; 1 filtered out;"
        ),
        stderr="",
        backend=Backend.MCUBOOT_SIM,
        backend_args={"cargo_test": "fault_campaign_upgrade"},
    )


def test_nonzero_unreached_index_does_not_pass(tmp_path: Path) -> None:
    row = run_fault_index(
        FakeAdapter(_result(570, False)),
        570,
        "sig-ecdsa",
        tmp_path,
        {"nrf52840-align-8-erased-ff": 406},
    )[0]
    assert row.passed is False
    assert row.outcome == "NOT_REACHED"
    assert row.reached is False


def test_reached_index_records_operation_count(tmp_path: Path) -> None:
    row = run_fault_index(
        FakeAdapter(_result(1, True)),
        1,
        "sig-ecdsa",
        tmp_path,
        {"nrf52840-align-8-erased-ff": 406},
    )[0]
    assert row.passed is True
    assert row.outcome == "REACHED"
    assert row.configuration == "nrf52840-align-8-erased-ff"
    assert row.operation_count == 406
    assert row.primary_image_valid is True
    assert row.primary_trailer_valid is True


def test_fault_selection_validation() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        sweep(FakeAdapter(_result(0, False)), [], "sig-ecdsa", Path("/tmp/empty"))
    with pytest.raises(ValueError, match="must be >= 0"):
        sweep(FakeAdapter(_result(-1, False)), [-1], "sig-ecdsa", Path("/tmp/negative"))


def test_probe_preserves_counts_per_configuration() -> None:
    result = SimulatorResult(
        0,
        "FAULT_PROBE configuration=nrf52840-align-8-erased-ff total_ops=406\n"
        "FAULT_PROBE configuration=stm32f4-align-16-erased-00 total_ops=403\n"
        "test fault_campaign_probe ... ok\n"
        "test result: ok. 1 passed; 0 failed;",
        "",
        Backend.MCUBOOT_SIM,
        {"cargo_test": "fault_campaign_probe"},
    )
    assert probe_total_ops(FakeAdapter(result), "sig-ecdsa") == {
        "nrf52840-align-8-erased-ff": 406,
        "stm32f4-align-16-erased-00": 403,
    }


def test_no_cut_baseline_is_distinct_from_reached_fault(tmp_path: Path) -> None:
    row = run_fault_index(
        FakeAdapter(_result(0, False)),
        0,
        "sig-ecdsa",
        tmp_path,
        {"nrf52840-align-8-erased-ff": 406},
    )[0]
    assert row.passed is True
    assert row.outcome == "NO_CUT_BASELINE"
    assert row.reached is False


def test_malformed_and_inconsistent_fault_results_fail(tmp_path: Path) -> None:
    malformed = _result(1, True)
    malformed.stdout = malformed.stdout.replace("recovery_ok=true", "recovery_ok=yes")
    row = run_fault_index(
        FakeAdapter(malformed),
        1,
        "sig-ecdsa",
        tmp_path,
        {"nrf52840-align-8-erased-ff": 406},
    )[0]
    assert row.passed is False
    assert row.outcome == "ERROR"

    inconsistent = _result(1, True)
    inconsistent.stdout = inconsistent.stdout.replace(
        "primary_image_valid=true", "primary_image_valid=false"
    )
    row = run_fault_index(
        FakeAdapter(inconsistent),
        1,
        "sig-ecdsa",
        tmp_path,
        {"nrf52840-align-8-erased-ff": 406},
    )[0]
    assert row.passed is False
    assert "state_consistent=False" in row.note


def test_fault_result_requires_every_probed_configuration(tmp_path: Path) -> None:
    row = run_fault_index(
        FakeAdapter(_result(1, True)),
        1,
        "sig-ecdsa",
        tmp_path,
        {"nrf52840-align-8-erased-ff": 406, "stm32f4-align-16-erased-00": 403},
    )
    assert len(row) == 1
    assert row[0].passed is False
    assert row[0].outcome == "MISSING_RESULT"
