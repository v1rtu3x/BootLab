"""Mutation tests for oracle evaluation.

Each test deliberately corrupts a simulator result or scenario expectation
and asserts that the oracle correctly reports failure.
"""

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


def _cargo_result(stdout: str, returncode: int = 0) -> SimulatorResult:
    return SimulatorResult(
        returncode=returncode,
        stdout=stdout,
        stderr="",
        backend=Backend.MCUBOOT_SIM,
        backend_args={"cargo_test": "basic_revert"},
    )


def test_imgtool_rejected_but_returncode_zero() -> None:
    """A scenario expecting rejection must fail if imgtool accepts the image."""
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
    assert "accepted" in oracle.verdict


def test_baseline_cargo_test_fails() -> None:
    """A positive baseline scenario must fail when the cargo test does not pass."""
    scenario = _scenario(
        Category.BASELINE,
        Backend.MCUBOOT_SIM,
        {"cargo_test": "basic_revert"},
        ExpectSpec(),
    )
    result = _cargo_result("test result: FAILED. 0 passed; 1 failed;", returncode=101)
    oracle = evaluate(scenario, result)
    assert oracle.passed is False
    assert "cargo test did not pass" in oracle.verdict


def test_invalid_image_booted_expectation_rejected() -> None:
    """A scenario expecting an invalid image to boot is unsupported in the MVP."""
    scenario = _scenario(
        Category.INTEGRITY,
        Backend.MCUBOOT_SIM,
        {"cargo_test": "basic_revert"},
        ExpectSpec(invalid_image_booted=True),
    )
    result = _cargo_result("test result: ok. 1 passed; 0 failed;")
    oracle = evaluate(scenario, result)
    assert oracle.passed is False
    assert "invalid image boot" in oracle.verdict


def test_version_enabled_but_cargo_passes() -> None:
    """Downgrade-prevention-enabled scenario fails if cargo test passes."""
    scenario = _scenario(
        Category.VERSION,
        Backend.MCUBOOT_SIM,
        {"cargo_test": "downgrade_prevention"},
        ExpectSpec(outcome_in=["secure_refusal"]),
    )
    result = _cargo_result("test result: ok. 1 passed; 0 failed;")
    oracle = evaluate(scenario, result)
    assert oracle.passed is False
    assert "downgrade was not rejected" in oracle.verdict


def test_version_disabled_but_cargo_fails() -> None:
    """Downgrade-prevention-disabled control fails if cargo test fails."""
    scenario = _scenario(
        Category.VERSION,
        Backend.MCUBOOT_SIM,
        {"cargo_test": "downgrade_prevention"},
        ExpectSpec(outcome_in=["new_authenticated_image"]),
    )
    result = _cargo_result("test result: FAILED. 0 passed; 1 failed;", returncode=101)
    oracle = evaluate(scenario, result)
    assert oracle.passed is False
    assert "control" in oracle.verdict


def test_fault_scenario_cargo_test_fails() -> None:
    """A fault-campaign recovery scenario must fail when cargo test fails."""
    scenario = _scenario(
        Category.FAULT,
        Backend.MCUBOOT_SIM,
        {"cargo_test": "some_fault_test"},
        ExpectSpec(),
    )
    result = _cargo_result("test result: FAILED. 0 passed; 1 failed;", returncode=101)
    oracle = evaluate(scenario, result)
    assert oracle.passed is False
    assert "recovery" in oracle.verdict


def test_unsupported_backend() -> None:
    """An unsupported backend must be reported as a failure."""
    scenario = Scenario.model_construct(
        id="T01",
        name="test",
        category=Category.BASELINE,
        profile="p",
        backend=Backend.MCUBOOT_SIM,
        backend_args={},
        expect=ExpectSpec(),
    )
    # Mutate to an unsupported backend value after bypassing enum validation.
    object.__setattr__(scenario, "backend", "unknown_backend")
    result = _cargo_result("test result: ok. 1 passed; 0 failed;")
    oracle = evaluate(scenario, result)
    assert oracle.passed is False
    assert "unsupported_backend" in oracle.verdict


def test_infrastructure_error() -> None:
    """An infrastructure error must always fail regardless of expectations."""
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


def test_baseline_positive_with_zero_passed_count() -> None:
    """A positive baseline must fail if parsed passed_count is zero."""
    scenario = _scenario(
        Category.BASELINE,
        Backend.MCUBOOT_SIM,
        {"cargo_test": "basic_revert"},
        ExpectSpec(),
    )
    # returncode 0 but no tests actually ran/passed.
    result = _cargo_result("test result: ok. 0 passed; 0 failed;")
    oracle = evaluate(scenario, result)
    assert oracle.passed is False
    assert oracle.details["passed_count"] == 0


def test_validation_invalid_image_not_rejected() -> None:
    """A validation scenario expecting refusal must fail if cargo test fails."""
    scenario = _scenario(
        Category.VALIDATION,
        Backend.MCUBOOT_SIM,
        {"cargo_test": "bad_test"},
        ExpectSpec(outcome_in=["secure_refusal"]),
    )
    result = _cargo_result("test result: FAILED. 0 passed; 1 failed;", returncode=101)
    oracle = evaluate(scenario, result)
    assert oracle.passed is False
    assert "not rejected" in oracle.verdict


def test_authenticity_invalid_image_not_rejected() -> None:
    """An authenticity scenario expecting refusal must fail if cargo test fails."""
    scenario = _scenario(
        Category.AUTHENTICITY,
        Backend.MCUBOOT_SIM,
        {"cargo_test": "untrusted_key"},
        ExpectSpec(outcome_in=["secure_refusal"]),
    )
    result = _cargo_result("test result: FAILED. 0 passed; 1 failed;", returncode=101)
    oracle = evaluate(scenario, result)
    assert oracle.passed is False
    assert "not rejected" in oracle.verdict


def test_imgtool_expected_accept_but_rejected() -> None:
    """A scenario expecting successful verification must fail if imgtool rejects."""
    scenario = _scenario(
        Category.AUTHENTICITY,
        Backend.IMGTOOL_VERIFY,
        {"image": "x.bin"},
        ExpectSpec(verify_rejected=False),
    )
    result = SimulatorResult(
        returncode=1,
        stdout="",
        stderr="invalid signature",
        backend=Backend.IMGTOOL_VERIFY,
        backend_args=scenario.backend_args,
    )
    oracle = evaluate(scenario, result)
    assert oracle.passed is False
    assert "rejected" in oracle.verdict
