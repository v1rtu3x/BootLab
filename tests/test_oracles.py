"""Tests for oracle evaluation with mocked simulator results."""

from __future__ import annotations

from bootlab.backends.mcuboot_sim import SimulatorResult
from bootlab.oracles import evaluate
from bootlab.scenario import Backend, Category, ExpectSpec, Scenario


def _scenario(
    category: Category,
    backend: Backend,
    backend_args: dict,
    expect: ExpectSpec,
) -> Scenario:
    return Scenario(
        id="T01",
        name="test",
        category=category,
        profile="p",
        backend=backend,
        backend_args=backend_args,
        expect=expect,
    )


def test_imgtool_verify_rejected() -> None:
    scenario = _scenario(
        Category.INTEGRITY,
        Backend.IMGTOOL_VERIFY,
        {"image": "x.bin"},
        ExpectSpec(verify_rejected=True),
    )
    result = SimulatorResult(
        returncode=1,
        stdout="",
        stderr="Image has an invalid hash",
        backend=Backend.IMGTOOL_VERIFY,
        backend_args=scenario.backend_args,
    )
    oracle = evaluate(scenario, result)
    assert oracle.passed is True


def test_imgtool_verify_unexpectedly_accepted() -> None:
    scenario = _scenario(
        Category.INTEGRITY,
        Backend.IMGTOOL_VERIFY,
        {"image": "x.bin"},
        ExpectSpec(verify_rejected=True),
    )
    result = SimulatorResult(
        returncode=0,
        stdout="",
        stderr="",
        backend=Backend.IMGTOOL_VERIFY,
        backend_args=scenario.backend_args,
    )
    oracle = evaluate(scenario, result)
    assert oracle.passed is False


def test_cargo_test_baseline_passes() -> None:
    scenario = _scenario(
        Category.BASELINE,
        Backend.MCUBOOT_SIM,
        {"cargo_test": "basic_revert"},
        ExpectSpec(),
    )
    result = SimulatorResult(
        returncode=0,
        stdout="test basic_revert ... ok\ntest result: ok. 1 passed; 0 failed;",
        stderr="",
        backend=Backend.MCUBOOT_SIM,
        backend_args=scenario.backend_args,
    )
    oracle = evaluate(scenario, result)
    assert oracle.passed is True


def test_cargo_test_baseline_fails() -> None:
    scenario = _scenario(
        Category.BASELINE,
        Backend.MCUBOOT_SIM,
        {"cargo_test": "basic_revert"},
        ExpectSpec(),
    )
    result = SimulatorResult(
        returncode=101,
        stdout="test basic_revert ... FAILED\ntest result: FAILED. 0 passed; 1 failed;",
        stderr="",
        backend=Backend.MCUBOOT_SIM,
        backend_args=scenario.backend_args,
    )
    oracle = evaluate(scenario, result)
    assert oracle.passed is False


def test_infrastructure_error() -> None:
    scenario = _scenario(
        Category.BASELINE,
        Backend.MCUBOOT_SIM,
        {},
        ExpectSpec(),
    )
    result = SimulatorResult(
        returncode=-1,
        stdout="",
        stderr="cargo not found",
        backend=Backend.MCUBOOT_SIM,
        backend_args=scenario.backend_args,
        infrastructure_error=True,
    )
    oracle = evaluate(scenario, result)
    assert oracle.passed is False
    assert oracle.verdict == "ERROR"


def test_empty_imgtool_failure_is_not_expected_rejection() -> None:
    scenario = _scenario(
        Category.INTEGRITY, Backend.IMGTOOL_VERIFY, {"image": "x.bin"},
        ExpectSpec(verify_rejected=True),
    )
    result = SimulatorResult(1, "", "", Backend.IMGTOOL_VERIFY, scenario.backend_args)
    oracle = evaluate(scenario, result)
    assert not oracle.passed
    assert oracle.verdict == "ERROR"


def test_cargo_compile_failure_is_error_not_policy_evidence() -> None:
    scenario = _scenario(
        Category.VERSION, Backend.MCUBOOT_SIM, {"cargo_test": "downgrade_prevention"},
        ExpectSpec(outcome_in=["secure_refusal"]),
    )
    result = SimulatorResult(
        101, "", "error: could not compile `bootsim`", Backend.MCUBOOT_SIM,
        scenario.backend_args,
    )
    oracle = evaluate(scenario, result)
    assert not oracle.passed
    assert oracle.verdict == "ERROR"


def test_zero_matching_cargo_tests_are_not_executed() -> None:
    scenario = _scenario(
        Category.BASELINE, Backend.MCUBOOT_SIM, {"cargo_test": "basic_revert"}, ExpectSpec()
    )
    result = SimulatorResult(
        0, "test result: ok. 0 passed; 0 failed; 1 filtered out;", "",
        Backend.MCUBOOT_SIM, scenario.backend_args,
    )
    oracle = evaluate(scenario, result)
    assert not oracle.passed
    assert oracle.verdict == "NOT_EXECUTED"
