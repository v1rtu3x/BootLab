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
        stderr="",
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
        stdout="test result: ok. 1 passed; 0 failed;",
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
        stdout="test result: FAILED. 0 passed; 1 failed;",
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
    assert "infrastructure_error" in oracle.verdict
