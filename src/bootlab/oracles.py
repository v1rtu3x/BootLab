"""Mode-aware security-property oracles.

An oracle evaluates whether a simulator/backend result matches the declared
security expectation for a scenario. It must not rely solely on a "success"
log line; it inspects return codes, test counts, and backend-specific output.
"""

from __future__ import annotations

import re
from typing import Any

from bootlab.backends.mcuboot_sim import SimulatorResult, parse_cargo_test_result
from bootlab.fuzz_image import classify_outcome
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
            verdict="TIMEOUT" if result.timed_out else "ERROR",
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
    outcome, crash_type = classify_outcome(result.returncode, result.stdout, result.stderr)
    if outcome not in {"accepted", "rejected"}:
        verdict = "TIMEOUT" if outcome == "timeout" else "ERROR"
        return OracleResult(False, verdict, {"backend_outcome": outcome, "crash_type": crash_type})
    verified = outcome == "accepted"
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
            "backend_outcome": outcome,
        },
    )


def _evaluate_cargo_test(scenario: Scenario, result: SimulatorResult) -> OracleResult:
    parsed = parse_cargo_test_result(result)
    expect = scenario.expect

    if parsed["cargo_execution_error"]:
        return OracleResult(False, "ERROR", {**parsed, "reason": "Cargo failed before executing the selected test"})
    if not parsed["selected_test_executed"]:
        return OracleResult(False, "NOT_EXECUTED", {**parsed, "reason": "The selected test did not produce an execution record"})

    # Safety invariant: no scenario should result in an invalid image being booted.
    if expect.invalid_image_booted:
        # If the test framework explicitly expects an invalid boot, the scenario
        # itself is misconfigured for this MVP.
        return OracleResult(
            passed=False,
            verdict="fail: scenario expects invalid image boot (not supported)",
            details={"expected_invalid_image_booted": True},
        )

    if (
        scenario.category == Category.BASELINE
        and "overwrite-only" in str(scenario.backend_args.get("cargo_features", "")).split()
        and scenario.backend_args.get("cargo_test") in {"basic_revert", "norevert"}
    ):
        return OracleResult(False, "SKIP", {
            **parsed,
            "reason": "Pinned upstream helper returns early in overwrite-only mode; scenario behavior was not exercised",
        })

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
        if not parsed["cargo_test_ok"]:
            return OracleResult(False, "FAIL", {
                **parsed,
                "reason": "The selected Cargo test failed; it cannot establish downgrade policy behavior",
            })
        features = set(str(scenario.backend_args.get("cargo_features", "")).split())
        if "downgrade-prevention" in features:
            return OracleResult(True, "PASS: UPSTREAM_PROXY_REFUSAL", {
                **parsed,
                "observed_outcome": "secure_refusal",
                "observation_scope": "upstream simulator internal image assertions",
                "direct_declared_image_input": False,
            })
        # With the feature disabled, the pinned helper returns early. Cargo's
        # green result is a no-op and cannot establish older-image acceptance.
        return OracleResult(False, "SKIP", {
            **parsed,
            "reason": "Feature-disabled upstream helper returns early; acceptance was not observed",
        })
    elif scenario.category == Category.FAULT:
        env = scenario.backend_args.get("env", {})
        try:
            fault_index = int(env.get("FAULT_INDEX"))
        except (AttributeError, TypeError, ValueError):
            return OracleResult(False, "ERROR", {**parsed, "reason": "fault scenario requires an integer FAULT_INDEX"})
        marker_pattern = re.compile(
            rf"FAULT_RESULT\s+configuration=(\S+)\s+index={fault_index}\s+reached=(true|false)\s+operation_count=(-?\d+)\s+"
            r"recovery_ok=(true|false)\s+primary_image_valid=(true|false)\s+secondary_image_valid=(true|false)\s+"
            r"primary_trailer_valid=(true|false)\s+secondary_trailer_valid=(true|false)"
        )
        markers = [marker_pattern.fullmatch(line.strip()) for line in (result.stdout + "\n" + result.stderr).splitlines()]
        markers = [marker for marker in markers if marker]
        if not markers:
            return OracleResult(False, "NOT_EXECUTED", {**parsed, "reason": "required FAULT_RESULT record is missing"})
        configuration_ids = [marker.group(1) for marker in markers]
        if len(configuration_ids) != len(set(configuration_ids)):
            return OracleResult(False, "ERROR", {
                **parsed,
                "reason": "fault result configuration identities are duplicated",
                "configurations": configuration_ids,
            })
        observations = [
            {
                "configuration": marker.group(1),
                "reached": marker.group(2) == "true",
                "operation_count": int(marker.group(3)),
                "recovery_ok": marker.group(4) == "true",
                "primary_image_valid": marker.group(5) == "true",
                "secondary_image_valid": marker.group(6) == "true",
                "primary_trailer_valid": marker.group(7) == "true",
                "secondary_trailer_valid": marker.group(8) == "true",
            }
            for marker in markers
        ]
        reached = all(item["reached"] for item in observations)
        passed = (
            parsed["cargo_test_ok"]
            and all(item["recovery_ok"] for item in observations)
            and all(item["primary_image_valid"] and item["primary_trailer_valid"] for item in observations)
            and ("overwrite-only" in str(scenario.backend_args.get("cargo_features", "")).split()
                 or all(item["secondary_image_valid"] and item["secondary_trailer_valid"] for item in observations))
            and (fault_index == 0 or reached)
        )
        if fault_index > 0 and not reached:
            verdict = "FAIL: requested interruption was NOT_REACHED"
        elif passed and fault_index == 0:
            verdict = "PASS: NO_CUT_BASELINE"
        else:
            verdict = "PASS: REACHED" if passed else "FAIL: fault-campaign recovery did not converge"
        details = {
            **parsed,
            "fault_index": fault_index,
            "interruption_reached": reached,
            "fault_results": observations,
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
