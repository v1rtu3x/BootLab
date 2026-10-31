"""Mode-aware security-property oracles.

An oracle evaluates whether a simulator/backend result matches the declared
security expectation for a scenario. It must not rely solely on a "success"
log line; it inspects return codes, test counts, and backend-specific output.
"""

from __future__ import annotations

from typing import Any

from bootlab.backends.mcuboot_sim import SimulatorResult, parse_cargo_test_result
from bootlab.scenario import Backend, Category, ExpectSpec, Scenario


class OracleResult:
    """Outcome of an oracle evaluation."""

    def __init__(
        self,
        passed: bool,
        verdict: str,
        details: dict[str, Any],
    ) -> None:
        self.passed = passed
        self.verdict = verdict
        self.details = details

    def summary(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "verdict": self.verdict,
            **self.details,
        }


def evaluate(scenario: Scenario, result: SimulatorResult) -> OracleResult:
    """Evaluate a simulator result against a scenario's expectations."""
    if result.infrastructure_error:
        return OracleResult(
            passed=False,
            verdict="infrastructure_error",
            details={
                "reason": "Harness or backend failed to execute",
                "stderr_snippet": result.stderr[:500],
            },
        )

    if scenario.backend == Backend.IMGTOOL_VERIFY:
        return _evaluate_imgtool_verify(scenario, result)
    if scenario.backend == Backend.MCUBOOT_SIM:
        return _evaluate_cargo_test(scenario, result)
    return OracleResult(
        passed=False,
        verdict="unsupported_backend",
        details={"backend": getattr(scenario.backend, "value", scenario.backend)},
    )


def _evaluate_imgtool_verify(scenario: Scenario, result: SimulatorResult) -> OracleResult:
    expect = scenario.expect
    verified = result.returncode == 0
    expect_verified = not expect.verify_rejected
    passed = verified == expect_verified
    if verified and expect.verify_rejected:
        verdict = "fail: invalid image was accepted by imgtool verify"
    elif not verified and not expect.verify_rejected:
        verdict = "fail: valid image was rejected by imgtool verify"
    else:
        verdict = "pass"
    return OracleResult(
        passed=passed,
        verdict=verdict,
        details={
            "imgtool_returncode": result.returncode,
            "expected_verified": expect_verified,
            "actual_verified": verified,
        },
    )


def _evaluate_cargo_test(scenario: Scenario, result: SimulatorResult) -> OracleResult:
    parsed = parse_cargo_test_result(result)
    expect = scenario.expect

    # Safety invariant: no scenario should result in an invalid image being booted.
    if expect.invalid_image_booted:
        # If the test framework explicitly expects an invalid boot, the scenario
        # itself is misconfigured for this MVP.
        return OracleResult(
            passed=False,
            verdict="fail: scenario expects invalid image boot (not supported)",
            details={"expected_invalid_image_booted": True},
        )

    # For positive cases (boot, upgrade, trial, confirm) the upstream cargo test
    # should pass. For negative runtime cases the test should fail or show 0
    # passed; we classify those separately via the scenario category.
    if scenario.category in (Category.BASELINE, Category.TRIAL):
        passed = parsed["cargo_test_ok"]
        verdict = "pass" if passed else "fail: positive scenario cargo test did not pass"
        details = {
            "expected": "cargo_test_ok",
            "cargo_test_ok": parsed["cargo_test_ok"],
            "passed_count": parsed["cargo_test_passed"],
            "failed_count": parsed["cargo_test_failed"],
        }
    elif scenario.category == Category.VERSION:
        # The upstream `downgrade_prevention` test uses REV_DEPS (a downgrade)
        # and asserts that the downgrade is *accepted*. Therefore it passes when
        # downgrade prevention is DISABLED and fails when ENABLED.
        # V01 (enabled): expect cargo test to fail -> downgrade was rejected.
        # V02 (disabled): expect cargo test to pass -> downgrade was allowed.
        expect_enabled = scenario.expect.outcome_in == ["secure_refusal"]
        expect_pass = not expect_enabled
        passed = parsed["cargo_test_ok"] == expect_pass
        if expect_enabled:
            verdict = "pass" if passed else "fail: downgrade was not rejected"
        else:
            verdict = "pass (control)" if passed else "fail: control did not behave as expected"
        details = {
            "expected_cargo_test_ok": expect_pass,
            "cargo_test_ok": parsed["cargo_test_ok"],
            "passed_count": parsed["cargo_test_passed"],
            "failed_count": parsed["cargo_test_failed"],
        }
    elif scenario.category == Category.FAULT:
        passed = parsed["cargo_test_ok"]
        verdict = "pass" if passed else "fail: fault-campaign recovery did not converge"
        details = {
            "expected_cargo_test_ok": True,
            "cargo_test_ok": parsed["cargo_test_ok"],
            "passed_count": parsed["cargo_test_passed"],
            "failed_count": parsed["cargo_test_failed"],
        }
    elif scenario.category in (Category.INTEGRITY, Category.AUTHENTICITY, Category.VALIDATION):
        # Negative runtime cases (expected refusal) should pass because the
        # invalid image is rejected. Positive runtime cases should also pass.
        passed = parsed["cargo_test_ok"]
        if "secure_refusal" in scenario.expect.outcome_in and len(scenario.expect.outcome_in) == 1:
            verdict = "pass (rejection)" if passed else "fail: invalid image was not rejected"
        else:
            verdict = "pass" if passed else "fail: validation scenario cargo test did not pass"
        details = {
            "expected_cargo_test_ok": True,
            "cargo_test_ok": parsed["cargo_test_ok"],
            "passed_count": parsed["cargo_test_passed"],
            "failed_count": parsed["cargo_test_failed"],
        }
    else:
        passed = parsed["cargo_test_ok"]
        verdict = "pass" if passed else "fail"
        details = {
            "cargo_test_ok": parsed["cargo_test_ok"],
            "passed_count": parsed["cargo_test_passed"],
            "failed_count": parsed["cargo_test_failed"],
        }

    return OracleResult(passed=passed, verdict=verdict, details=details)
