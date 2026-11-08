"""Per-case evidence records and provenance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bootlab.oracles import OracleResult
from bootlab.scenario import Scenario


@dataclass
class EvidenceRecord:
    case_id: str
    case_name: str
    category: str
    profile: str
    backend: str
    backend_args: dict[str, Any]
    mcuboot_commit: str
    assertion_result: str
    verdict: str
    passed: bool
    infrastructure_error: bool
    timestamp_utc: str
    elapsed_seconds: float | None
    stdout_path: str | None
    stderr_path: str | None
    details: dict[str, Any]
    notes: str


def gather_provenance(workspace: Path) -> dict[str, Any]:
    mcuboot = workspace / "vendor" / "mcuboot"
    commit = "unknown"
    if (mcuboot / ".git").exists():
        import subprocess

        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=mcuboot,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            commit = result.stdout.strip()
    return {
        "mcuboot_commit": commit,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def record_evidence(
    workspace: Path,
    scenario: Scenario,
    oracle_result: OracleResult,
    stdout: str,
    stderr: str,
    elapsed: float | None,
    provenance: dict[str, Any],
) -> Path:
    evidence_dir = workspace / "evidence" / scenario.id
    evidence_dir.mkdir(parents=True, exist_ok=True)

    stdout_path = evidence_dir / "stdout.txt"
    stderr_path = evidence_dir / "stderr.txt"
    stdout_path.write_text(stdout)
    stderr_path.write_text(stderr)

    record = EvidenceRecord(
        case_id=scenario.id,
        case_name=scenario.name,
        category=scenario.category.value,
        profile=scenario.profile,
        backend=scenario.backend.value,
        backend_args=scenario.backend_args,
        mcuboot_commit=provenance.get("mcuboot_commit", "unknown"),
        assertion_result="pass" if oracle_result.passed else "fail",
        verdict=oracle_result.verdict,
        passed=oracle_result.passed,
        infrastructure_error="infrastructure_error" in oracle_result.verdict,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        elapsed_seconds=elapsed,
        stdout_path=str(stdout_path.relative_to(workspace)),
        stderr_path=str(stderr_path.relative_to(workspace)),
        details=oracle_result.details,
        notes=scenario.notes,
    )

    record_path = evidence_dir / "record.json"
    record_path.write_text(json.dumps(asdict(record), indent=2) + "\n")
    return record_path
