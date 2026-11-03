"""Deterministic fault-campaign planning and result tables."""

from __future__ import annotations

import csv
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from bootlab.backends.mcuboot_sim import McubootSimAdapter
from bootlab.scenario import Backend, Category, ExpectSpec, FaultSpec, ImageRef, Scenario


@dataclass
class FaultSweepResult:
    index: int
    passed: bool
    returncode: int
    stdout_path: str
    stderr_path: str
    note: str


def probe_total_ops(adapter: McubootSimAdapter, features: str) -> int | None:
    """Run the fault_campaign_probe test and return the maximum total_ops seen."""
    scenario = Scenario(
        id="F00",
        name="fault-campaign-probe",
        category=Category.FAULT,
        profile="mcuboot_swap_reference",
        backend=Backend.MCUBOOT_SIM,
        backend_args={
            "cargo_test": "fault_campaign_probe",
            "cargo_features": features,
        },
        expect=ExpectSpec(),
    )
    result = adapter.run(scenario)
    if result.infrastructure_error:
        return None
    max_ops: int | None = None
    for line in (result.stdout + result.stderr).splitlines():
        if line.startswith("FAULT_PROBE total_ops="):
            try:
                ops = int(line.split("=")[1])
                if max_ops is None or ops > max_ops:
                    max_ops = ops
            except ValueError:
                pass
    return max_ops


def run_fault_index(
    adapter: McubootSimAdapter,
    index: int,
    features: str,
    evidence_dir: Path,
) -> FaultSweepResult:
    """Run the fault_campaign_upgrade test for a single fault index."""
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
    passed = not result.infrastructure_error and result.returncode == 0

    idx_dir = evidence_dir / "fault_sweep" / f"index_{index}"
    idx_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = idx_dir / "stdout.txt"
    stderr_path = idx_dir / "stderr.txt"
    stdout_path.write_text(result.stdout)
    stderr_path.write_text(result.stderr)

    note = ""
    for line in (result.stdout + result.stderr).splitlines():
        if line.startswith("FAULT_RESULT"):
            note = line
            break

    return FaultSweepResult(
        index=index,
        passed=passed,
        returncode=result.returncode,
        stdout_path=str(stdout_path.relative_to(evidence_dir.parent)),
        stderr_path=str(stderr_path.relative_to(evidence_dir.parent)),
        note=note,
    )


def sweep(
    adapter: McubootSimAdapter,
    indices: list[int],
    features: str,
    workspace: Path,
) -> list[FaultSweepResult]:
    """Run a deterministic fault sweep over the requested indices."""
    evidence_dir = workspace / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    results: list[FaultSweepResult] = []
    for index in indices:
        results.append(run_fault_index(adapter, index, features, evidence_dir))
    return results


def write_table(results: list[FaultSweepResult], path: Path) -> None:
    """Write a CSV fault table."""
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["index", "passed", "returncode", "stdout_path", "stderr_path", "note"],
        )
        writer.writeheader()
        for r in results:
            writer.writerow(asdict(r))


def write_json(results: list[FaultSweepResult], path: Path) -> None:
    """Write a JSON fault table."""
    path.write_text(json.dumps([asdict(r) for r in results], indent=2) + "\n")
