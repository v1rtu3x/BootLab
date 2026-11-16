"""Per-case evidence records and provenance."""

from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bootlab.oracles import OracleResult
from bootlab.backends.mcuboot_sim import SimulatorResult, parse_cargo_test_result
from bootlab.fuzz_image import classify_outcome
from bootlab.scenario import Scenario


@dataclass
class EvidenceRecord:
    run_id: str
    provenance: dict[str, Any]
    case_id: str
    case_name: str
    category: str
    profile: str
    backend: str
    effective_command: list[str]
    backend_args: dict[str, Any]
    mcuboot_commit: str
    assertion_result: str
    verdict: str
    passed: bool
    infrastructure_error: bool
    exit_status: int
    backend_outcome: str
    timestamp_utc: str
    elapsed_seconds: float | None
    stdout_path: str | None
    stderr_path: str | None
    details: dict[str, Any]
    evaluated_assertions: dict[str, Any]
    notes: str
    scenario_sha256: str
    scenario_configuration: dict[str, Any]
    stdout_sha256: str
    stderr_sha256: str
    input_sha256: dict[str, dict[str, str]]
    public_key_fingerprint: str | None


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
    root_result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=workspace, capture_output=True, text=True)
    dirty_result = subprocess.run(["git", "status", "--porcelain"], cwd=workspace, capture_output=True, text=True)
    patch = workspace / "vendor" / "mcuboot-patches" / "0001-fault-campaign-public-api.patch"
    tool_versions: dict[str, str] = {}
    for tool in ("python3", "cargo", "rustc", "imgtool"):
        try:
            version = subprocess.run([tool, "--version"], capture_output=True, text=True, timeout=10)
            if version.returncode == 0:
                tool_versions[tool] = (version.stdout or version.stderr).strip().splitlines()[0]
        except (OSError, subprocess.TimeoutExpired):
            continue
    return {
        "bootlab_commit": root_result.stdout.strip() if root_result.returncode == 0 else "unknown",
        "bootlab_dirty": bool(dirty_result.stdout.strip()),
        "mcuboot_commit": commit,
        "mcuboot_dirty": bool(subprocess.run(["git", "status", "--porcelain"], cwd=mcuboot, capture_output=True, text=True).stdout.strip()) if (mcuboot / ".git").exists() else None,
        "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest() if patch.is_file() else None,
        "tool_versions": tool_versions,
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
    backend_result: SimulatorResult,
) -> Path:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8]
    evidence_dir = workspace / "evidence" / "runs" / run_id / scenario.id
    evidence_dir.mkdir(parents=True, exist_ok=True)

    stdout_path = evidence_dir / "stdout.txt"
    stderr_path = evidence_dir / "stderr.txt"
    stdout_path.write_text(stdout)
    stderr_path.write_text(stderr)

    scenario_configuration = scenario.model_dump(mode="json")
    scenario_bytes = json.dumps(scenario_configuration, sort_keys=True, separators=(",", ":")).encode()
    input_hashes: dict[str, dict[str, str]] = {}
    public_key_fingerprint: str | None = None
    for arg in ("image", "key_path"):
        value = scenario.backend_args.get(arg)
        if value:
            path = Path(value)
            if not path.is_absolute():
                path = workspace / (Path("artifacts/corpus") / path if arg == "image" else path)
            if path.is_file():
                try:
                    recorded_path = str(path.relative_to(workspace))
                except ValueError:
                    recorded_path = str(path)
                input_hashes[arg] = {"path": recorded_path, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    if scenario.backend.value == "imgtool_verify":
        image_name = scenario.backend_args.get("image")
        key_arg = scenario.backend_args.get("key_path")
        if key_arg:
            verification_key = Path(key_arg)
            if not verification_key.is_absolute():
                verification_key = workspace / verification_key
        else:
            key_id = scenario.backend_args.get("key_id", "dev-trusted")
            key_type = scenario.backend_args.get("key_type", "ecdsa-p256")
            verification_key = workspace / "fixtures" / "keys" / f"{key_id}-{key_type}.pem"
            if not verification_key.is_file():
                verification_key = workspace / "fixtures" / "keys" / f"{key_id}.pem"
        if image_name:
            image_path = workspace / "artifacts" / "corpus" / image_name
            if image_path.is_file():
                input_hashes["image"] = {"path": str(image_path.relative_to(workspace)), "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest()}
        if verification_key.is_file():
            from cryptography.hazmat.primitives import serialization

            key_obj = serialization.load_pem_private_key(verification_key.read_bytes(), password=None)
            public_der = key_obj.public_key().public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            public_key_fingerprint = hashlib.sha256(public_der).hexdigest()
    if backend_result.infrastructure_error:
        backend_outcome = "timeout" if backend_result.timed_out else "infrastructure_error"
    elif scenario.backend.value == "imgtool_verify":
        backend_outcome = classify_outcome(backend_result.returncode, stdout, stderr)[0]
    else:
        parsed_result = parse_cargo_test_result(backend_result)
        backend_outcome = (
            "execution_error" if parsed_result["cargo_execution_error"]
            else "test_not_executed" if not parsed_result["selected_test_executed"]
            else "test_passed" if parsed_result["cargo_test_ok"]
            else "test_failed"
        )
    record = EvidenceRecord(
        run_id=run_id,
        provenance=provenance,
        case_id=scenario.id,
        case_name=scenario.name,
        category=scenario.category.value,
        profile=scenario.profile,
        backend=scenario.backend.value,
        effective_command=_effective_command(workspace, scenario),
        backend_args=scenario.backend_args,
        mcuboot_commit=provenance.get("mcuboot_commit", "unknown"),
        assertion_result=(
            "pass" if oracle_result.passed
            else "skip" if oracle_result.verdict in {"SKIP", "NOT_EXECUTED"}
            else "fail"
        ),
        verdict=oracle_result.verdict,
        passed=oracle_result.passed,
        infrastructure_error=oracle_result.verdict in {"ERROR", "TIMEOUT", "infrastructure_error"},
        exit_status=backend_result.returncode,
        backend_outcome=backend_outcome,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        elapsed_seconds=elapsed,
        stdout_path=str(stdout_path.relative_to(workspace)),
        stderr_path=str(stderr_path.relative_to(workspace)),
        details=oracle_result.details,
        evaluated_assertions=oracle_result.details,
        notes=scenario.notes,
        scenario_sha256=hashlib.sha256(scenario_bytes).hexdigest(),
        scenario_configuration=scenario_configuration,
        stdout_sha256=hashlib.sha256(stdout.encode()).hexdigest(),
        stderr_sha256=hashlib.sha256(stderr.encode()).hexdigest(),
        input_sha256=input_hashes,
        public_key_fingerprint=public_key_fingerprint,
    )

    record_path = evidence_dir / "record.json"
    record_path.write_text(json.dumps(asdict(record), indent=2) + "\n")
    return record_path


def _effective_command(workspace: Path, scenario: Scenario) -> list[str]:
    args = scenario.backend_args
    if scenario.backend.value == "mcuboot_sim":
        command = ["cargo", "test"]
        features = args.get("cargo_features", "sig-ecdsa")
        if features:
            command.extend(["--features", features])
        command.extend(["--", args.get("cargo_test", scenario.name), "--exact", "--nocapture"])
        return command

    image = args.get("image", "")
    key_arg = args.get("key_path")
    if key_arg:
        key_path = Path(key_arg)
        if not key_path.is_absolute():
            key_path = workspace / key_path
    else:
        key_id = args.get("key_id", "dev-trusted")
        key_type = args.get("key_type", "ecdsa-p256")
        key_path = workspace / "fixtures" / "keys" / f"{key_id}-{key_type}.pem"
        if not key_path.is_file():
            key_path = workspace / "fixtures" / "keys" / f"{key_id}.pem"
    image_path = workspace / "artifacts" / "corpus" / image
    return ["imgtool", "verify", "-k", str(key_path), str(image_path)]
