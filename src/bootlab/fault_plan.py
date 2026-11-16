"""Deterministic fault-campaign planning and result tables."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from bootlab.backends.mcuboot_sim import McubootSimAdapter
from bootlab.scenario import Backend, Category, ExpectSpec, FaultSpec, Scenario


@dataclass
class FaultSweepResult:
    index: int
    configuration: str | None
    operation_count: int | None
    recovery_ok: bool | None
    primary_image_valid: bool | None
    secondary_image_valid: bool | None
    primary_trailer_valid: bool | None
    secondary_trailer_valid: bool | None
    passed: bool
    outcome: str
    reached: bool
    returncode: int
    stdout_path: str
    stderr_path: str
    note: str


def probe_total_ops(adapter: McubootSimAdapter, features: str) -> dict[str, int] | None:
    """Run the exact probe and retain operation counts per modeled configuration."""
    scenario = Scenario(
        id="F00",
        name="fault-campaign-probe",
        category=Category.BASELINE,
        profile="mcuboot_swap_reference",
        backend=Backend.MCUBOOT_SIM,
        backend_args={
            "cargo_test": "fault_campaign_probe",
            "cargo_features": features,
        },
        expect=ExpectSpec(),
    )
    result = adapter.run(scenario)
    from bootlab.backends.mcuboot_sim import parse_cargo_test_result

    parsed = parse_cargo_test_result(result)
    if (
        result.infrastructure_error
        or not parsed["cargo_test_ok"]
        or parsed["cargo_test_executed"] != 1
    ):
        return None
    counts: dict[str, int] = {}
    for line in (result.stdout + result.stderr).splitlines():
        if line.startswith("FAULT_PROBE"):
            match = re.fullmatch(
                r"FAULT_PROBE configuration=(\S+) total_ops=(\d+)", line.strip()
            )
            if not match:
                return None
            config_id, operations = match.group(1), int(match.group(2))
            if operations <= 0 or config_id in counts:
                return None
            counts[config_id] = operations
    if not counts:
        return None
    return counts


def run_fault_index(
    adapter: McubootSimAdapter,
    index: int,
    features: str,
    evidence_dir: Path,
    expected_configurations: dict[str, int],
) -> list[FaultSweepResult]:
    """Run the fault_campaign_upgrade test for a single fault index."""
    if index < 0:
        raise ValueError("fault index must be >= 0")
    scenario = Scenario(
        id=f"F{index:03d}",
        name=f"fault-campaign-index-{index}",
        category=Category.FAULT,
        profile="mcuboot_swap_reference",
        backend=Backend.MCUBOOT_SIM,
        backend_args={
            "cargo_test": "fault_campaign_upgrade",
            "cargo_features": features,
            "env": {"FAULT_INDEX": str(index)},
        },
        fault=FaultSpec(type="reset", index=index),
        expect=ExpectSpec(),
    )
    result = adapter.run(scenario)
    from bootlab.backends.mcuboot_sim import parse_cargo_test_result

    parsed = parse_cargo_test_result(result)

    idx_dir = evidence_dir / f"index_{index}"
    idx_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = idx_dir / "stdout.txt"
    stderr_path = idx_dir / "stderr.txt"
    stdout_path.write_text(result.stdout)
    stderr_path.write_text(result.stderr)

    lines = (result.stdout + "\n" + result.stderr).splitlines()
    markers = []
    marker_pattern = re.compile(
        r"FAULT_RESULT configuration=(\S+) index=(\d+) reached=(true|false) operation_count=(-?\d+) "
        r"recovery_ok=(true|false) primary_image_valid=(true|false) secondary_image_valid=(true|false) "
        r"primary_trailer_valid=(true|false) secondary_trailer_valid=(true|false)"
    )
    malformed_result = False
    for line in lines:
        if line.startswith("FAULT_RESULT") and not marker_pattern.fullmatch(
            line.strip()
        ):
            malformed_result = True
        match = marker_pattern.fullmatch(line.strip())
        if match:
            config_id, observed_index, reached_text, operations, *states = (
                match.groups()
            )
            if int(observed_index) == index:
                markers.append(
                    (
                        config_id,
                        int(operations),
                        reached_text == "true",
                        *[state == "true" for state in states],
                        line,
                    )
                )

    if malformed_result:
        return [
            FaultSweepResult(
                index=index,
                configuration=None,
                operation_count=None,
                passed=False,
                recovery_ok=None,
                primary_image_valid=None,
                secondary_image_valid=None,
                primary_trailer_valid=None,
                secondary_trailer_valid=None,
                outcome="ERROR",
                reached=False,
                returncode=result.returncode,
                stdout_path=str(stdout_path.relative_to(evidence_dir.parent)),
                stderr_path=str(stderr_path.relative_to(evidence_dir.parent)),
                note="malformed FAULT_RESULT record",
            )
        ]
    if not markers:
        outcome = (
            "ERROR"
            if result.infrastructure_error or parsed["cargo_execution_error"]
            else "NOT_EXECUTED"
            if not parsed["selected_test_executed"]
            else "MISSING_RESULT"
        )
        return [
            FaultSweepResult(
                index=index,
                configuration=None,
                operation_count=None,
                passed=False,
                recovery_ok=None,
                primary_image_valid=None,
                secondary_image_valid=None,
                primary_trailer_valid=None,
                secondary_trailer_valid=None,
                outcome=outcome,
                reached=False,
                returncode=result.returncode,
                stdout_path=str(stdout_path.relative_to(evidence_dir.parent)),
                stderr_path=str(stderr_path.relative_to(evidence_dir.parent)),
                note="",
            )
        ]

    config_ids = [marker[0] for marker in markers]
    if len(config_ids) != len(set(config_ids)):
        return [
            FaultSweepResult(
                index=index,
                configuration=None,
                operation_count=None,
                passed=False,
                recovery_ok=None,
                primary_image_valid=None,
                secondary_image_valid=None,
                primary_trailer_valid=None,
                secondary_trailer_valid=None,
                outcome="ERROR",
                reached=False,
                returncode=result.returncode,
                stdout_path=str(stdout_path.relative_to(evidence_dir.parent)),
                stderr_path=str(stderr_path.relative_to(evidence_dir.parent)),
                note="configuration result identities are missing or duplicated",
            )
        ]
    if set(config_ids) != set(expected_configurations):
        missing = sorted(set(expected_configurations) - set(config_ids))
        unexpected = sorted(set(config_ids) - set(expected_configurations))
        return [
            FaultSweepResult(
                index=index,
                configuration=config_id,
                operation_count=None,
                passed=False,
                recovery_ok=None,
                primary_image_valid=None,
                secondary_image_valid=None,
                primary_trailer_valid=None,
                secondary_trailer_valid=None,
                outcome="MISSING_RESULT"
                if config_id in missing
                else "UNEXPECTED_CONFIGURATION",
                reached=False,
                returncode=result.returncode,
                stdout_path=str(stdout_path.relative_to(evidence_dir.parent)),
                stderr_path=str(stderr_path.relative_to(evidence_dir.parent)),
                note=f"expected all probed configurations; missing={missing}, unexpected={unexpected}",
            )
            for config_id in (missing + unexpected)
        ]
    rows: list[FaultSweepResult] = []
    for (
        config_id,
        operations,
        reached,
        recovery_ok,
        primary_image,
        secondary_image,
        primary_trailer,
        secondary_trailer,
        note,
    ) in markers:
        state_consistent = recovery_ok == all(
            (primary_image, secondary_image, primary_trailer, secondary_trailer)
        )
        complete_run = (
            not result.infrastructure_error
            and parsed["cargo_test_ok"]
            and parsed["cargo_test_executed"] == 1
            and parsed["selected_test"] == "fault_campaign_upgrade"
        )
        if result.infrastructure_error:
            outcome = "ERROR"
        elif not parsed["selected_test_executed"]:
            outcome = "NOT_EXECUTED"
        elif not complete_run:
            outcome = "EXECUTION_FAILED"
        elif index == 0:
            outcome = "NO_CUT_BASELINE"
        elif reached:
            outcome = "REACHED"
        else:
            outcome = "NOT_REACHED"
        expected_operations = expected_configurations[config_id]
        count_matches = (
            operations == expected_operations
            if index == 0 or not reached
            else operations >= expected_operations
        )
        reachability_ok = (not reached) if index == 0 else reached
        passed = bool(
            complete_run
            and state_consistent
            and count_matches
            and recovery_ok
            and reachability_ok
        )
        rows.append(
            FaultSweepResult(
                index=index,
                configuration=config_id,
                operation_count=operations,
                recovery_ok=recovery_ok,
                primary_image_valid=primary_image,
                secondary_image_valid=secondary_image,
                primary_trailer_valid=primary_trailer,
                secondary_trailer_valid=secondary_trailer,
                passed=passed,
                outcome=outcome,
                reached=reached,
                returncode=result.returncode,
                stdout_path=str(stdout_path.relative_to(evidence_dir.parent)),
                stderr_path=str(stderr_path.relative_to(evidence_dir.parent)),
                note=(
                    note
                    if state_consistent and count_matches
                    else f"{note}; state_consistent={state_consistent}; operation_count_matches_probe={count_matches}"
                ),
            )
        )
    return rows


def sweep(
    adapter: McubootSimAdapter,
    indices: list[int],
    features: str,
    workspace: Path,
    run_id: str | None = None,
) -> list[FaultSweepResult]:
    """Run a deterministic fault sweep over the requested indices."""
    if not indices:
        raise ValueError("fault selection must not be empty")
    if any(index < 0 for index in indices):
        raise ValueError("fault indices must be >= 0")
    if len(indices) != len(set(indices)):
        raise ValueError("fault indices must not contain duplicates")
    expected_configurations = probe_total_ops(adapter, features)
    if not expected_configurations:
        raise RuntimeError(
            "fault probe did not return complete, unique configuration operation counts"
        )
    evidence_dir = (
        workspace
        / "evidence"
        / "runs"
        / (run_id or "unarchived-fault-sweep")
        / "fault_sweep"
    )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    results: list[FaultSweepResult] = []
    for index in indices:
        results.extend(
            run_fault_index(
                adapter, index, features, evidence_dir, expected_configurations
            )
        )
    return results


def write_table(results: list[FaultSweepResult], path: Path) -> None:
    """Write a CSV fault table."""
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "index",
                "configuration",
                "operation_count",
                "reached",
                "recovery_ok",
                "primary_image_valid",
                "secondary_image_valid",
                "primary_trailer_valid",
                "secondary_trailer_valid",
                "passed",
                "outcome",
                "returncode",
                "stdout_path",
                "stderr_path",
                "note",
            ],
        )
        writer.writeheader()
        for r in results:
            writer.writerow(asdict(r))


def write_json(results: list[FaultSweepResult], path: Path) -> None:
    """Write a JSON fault table."""
    path.write_text(json.dumps([asdict(r) for r in results], indent=2) + "\n")
