"""Per-case evidence records and provenance."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from bootlab.oracles import OracleResult
from bootlab.backends.mcuboot_sim import SimulatorResult, parse_cargo_test_result
from bootlab.fuzz_image import classify_outcome
from bootlab.scenario import Scenario
from bootlab.images import SIMULATOR_ROOT_KEYS


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
    declared_expectations: dict[str, Any]
    stdout_sha256: str
    stderr_sha256: str
    input_sha256: dict[str, dict[str, str]]
    public_key_fingerprint: str | None


def gather_provenance(workspace: Path) -> dict[str, Any]:
    mcuboot = workspace / "vendor" / "mcuboot"
    root_commit = _git_output(workspace, "rev-parse", "HEAD")
    root_status = _git_output(workspace, "status", "--porcelain")
    mcuboot_commit = _git_output(mcuboot, "rev-parse", "HEAD")
    mcuboot_status = _git_output(mcuboot, "status", "--porcelain")
    patch = (
        workspace
        / "vendor"
        / "mcuboot-patches"
        / "0001-fault-campaign-public-api.patch"
    )
    patch_state = (
        _patch_state(mcuboot, patch)
        if patch.is_file() and mcuboot.is_dir()
        else "unavailable"
    )
    tool_versions = {"python": platform.python_version()}
    tool_paths: dict[str, str | None] = {"python": sys.executable}
    for tool in ("cargo", "rustc", "imgtool"):
        executable = shutil.which(tool)
        tool_paths[tool] = executable
        if not executable:
            tool_versions[tool] = "unavailable"
            continue
        if tool == "imgtool":
            try:
                tool_versions[tool] = f"imgtool {version('imgtool')}"
            except PackageNotFoundError:
                tool_versions[tool] = "unavailable"
            continue
        try:
            result = subprocess.run(
                [executable, "--version"], capture_output=True, text=True, timeout=10
            )
            output = (result.stdout or result.stderr).strip().splitlines()
            tool_versions[tool] = (
                output[0] if result.returncode == 0 and output else "unknown"
            )
        except (OSError, subprocess.SubprocessError):
            tool_versions[tool] = "unavailable"
    package_versions: dict[str, str] = {}
    for package in (
        "bootlab",
        "click",
        "cryptography",
        "pydantic",
        "PyYAML",
        "rich",
        "imgtool",
    ):
        try:
            package_versions[package] = version(package)
        except PackageNotFoundError:
            package_versions[package] = "unavailable"
    return {
        "bootlab_commit": root_commit or "unknown",
        "bootlab_dirty": None if root_status is None else bool(root_status),
        "mcuboot_commit": mcuboot_commit or "unknown",
        "mcuboot_dirty": None if mcuboot_status is None else bool(mcuboot_status),
        "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest()
        if patch.is_file()
        else None,
        "patch_application": patch_state,
        "python_executable": sys.executable,
        "python_environment": os.environ.get("VIRTUAL_ENV")
        or (str(sys.prefix) if sys.prefix != sys.base_prefix else "system"),
        "python_prefix": sys.prefix,
        "python_base_prefix": sys.base_prefix,
        "tool_paths": tool_paths,
        "tool_versions": tool_versions,
        "package_versions": package_versions,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _git_output(cwd: Path, *args: str) -> str | None:
    if not (cwd / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _patch_state(source: Path, patch: Path) -> str:
    if shutil.which("git") is None:
        return "unknown"
    try:
        forward = subprocess.run(
            ["git", "apply", "--check", str(patch)],
            cwd=source,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if forward.returncode == 0:
            return "not_applied"
        reverse = subprocess.run(
            ["git", "apply", "--reverse", "--check", str(patch)],
            cwd=source,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if reverse.returncode == 0:
            return "applied"
        return "partial_or_incompatible"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def new_run_id() -> str:
    return (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )


def begin_run(
    workspace: Path,
    kind: str,
    provenance: dict[str, Any],
    configuration: dict[str, Any] | None = None,
) -> str:
    run_id = new_run_id()
    run_dir = workspace / "evidence" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "run_id": run_id,
        "kind": kind,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provenance": provenance,
        "configuration": configuration or {},
    }
    (run_dir / "run.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return run_id


def latest_run_id(workspace: Path) -> str | None:
    runs = workspace / "evidence" / "runs"
    candidates: list[tuple[str, str]] = []
    if not runs.is_dir():
        return None
    for run_dir in runs.iterdir():
        manifest = run_dir / "run.json"
        if manifest.is_file():
            try:
                candidates.append(
                    (
                        json.loads(manifest.read_text()).get("created_at", ""),
                        run_dir.name,
                    )
                )
            except (OSError, json.JSONDecodeError):
                continue
    return max(candidates)[1] if candidates else None


def _public_key_bytes(pem: bytes) -> tuple[bytes, bytes]:
    from cryptography.hazmat.primitives import serialization

    try:
        key = serialization.load_pem_public_key(pem)
    except (ValueError, TypeError):
        key = serialization.load_pem_private_key(pem, password=None).public_key()
    public_pem = key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_der = key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return public_pem, public_der


def _resolve_input_path(workspace: Path, scenario: Scenario, arg: str) -> Path | None:
    value = scenario.backend_args.get(arg)
    if not value or not isinstance(value, str):
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    direct = workspace / path
    if direct.is_file():
        return direct
    return workspace / "artifacts" / "corpus" / path


def _resolve_verification_key(workspace: Path, scenario: Scenario) -> Path | None:
    key_arg = scenario.backend_args.get("key_path")
    if key_arg:
        key_path = Path(key_arg)
        return key_path if key_path.is_absolute() else workspace / key_path
    if scenario.backend.value != "imgtool_verify":
        return None
    key_id = scenario.backend_args.get("key_id", "dev-trusted")
    key_type = scenario.backend_args.get("key_type", "ecdsa-p256")
    if key_id == "dev-trusted" and key_type in SIMULATOR_ROOT_KEYS:
        return workspace / "vendor" / "mcuboot" / SIMULATOR_ROOT_KEYS[key_type]
    candidate = workspace / "fixtures" / "keys" / f"{key_id}-{key_type}.pem"
    legacy = workspace / "fixtures" / "keys" / f"{key_id}.pem"
    return candidate if candidate.is_file() else legacy


def _public_scenario_configuration(scenario: Scenario) -> dict[str, Any]:
    configuration = scenario.model_dump(mode="json")
    args = configuration.get("backend_args", {})
    if args.get("key_path"):
        args["key_path"] = "<provided-key; public key archived separately>"
    env = args.get("env", {})
    for key in ("BOOTLAB_PRIMARY_IMAGE", "BOOTLAB_CANDIDATE_IMAGE"):
        if env.get(key):
            env[key] = "<input image archived by content hash>"
    return configuration


def _public_backend_args(scenario: Scenario) -> dict[str, Any]:
    args = json.loads(json.dumps(scenario.backend_args))
    if args.get("key_path"):
        args["key_path"] = "<provided-key; public key archived separately>"
    env = args.get("env", {})
    for key in ("BOOTLAB_PRIMARY_IMAGE", "BOOTLAB_CANDIDATE_IMAGE"):
        if env.get(key):
            env[key] = "<input image archived by content hash>"
    return args


def record_evidence(
    workspace: Path,
    scenario: Scenario,
    oracle_result: OracleResult,
    stdout: str,
    stderr: str,
    elapsed: float | None,
    provenance: dict[str, Any],
    backend_result: SimulatorResult,
    run_id: str | None = None,
) -> Path:
    run_id = run_id or new_run_id()
    evidence_dir = workspace / "evidence" / "runs" / run_id / scenario.id
    evidence_dir.mkdir(parents=True, exist_ok=True)

    stdout_path = evidence_dir / "stdout.txt"
    stderr_path = evidence_dir / "stderr.txt"
    stdout_path.write_text(stdout)
    stderr_path.write_text(stderr)

    scenario_configuration = _public_scenario_configuration(scenario)
    scenario_bytes = json.dumps(
        scenario_configuration, sort_keys=True, separators=(",", ":")
    ).encode()
    input_hashes: dict[str, dict[str, str]] = {}
    public_key_fingerprint: str | None = None
    input_errors: list[str] = []
    input_dir = evidence_dir / "inputs" / "sha256"
    for arg in ("image", "primary_image", "candidate_image"):
        path = _resolve_input_path(workspace, scenario, arg)
        if path is None:
            continue
        if not path.is_file():
            input_errors.append(f"{arg} input does not exist: {path.name}")
            continue
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        input_dir.mkdir(parents=True, exist_ok=True)
        archived = input_dir / f"{digest}.bin"
        if not archived.exists():
            archived.write_bytes(payload)
        input_hashes[arg] = {
            "path": str(archived.relative_to(workspace)),
            "sha256": digest,
            "size": len(payload),
        }
    if scenario.backend.value == "imgtool_verify":
        verification_key = _resolve_verification_key(workspace, scenario)
        if verification_key is None:
            input_errors.append("verification key is not configured")
        elif not verification_key.is_file():
            input_errors.append(
                f"verification key does not exist: {verification_key.name}"
            )
        else:
            try:
                public_pem, public_der = _public_key_bytes(
                    verification_key.read_bytes()
                )
                public_key_fingerprint = hashlib.sha256(public_der).hexdigest()
                input_dir.mkdir(parents=True, exist_ok=True)
                public_path = input_dir / f"public-key-{public_key_fingerprint}.pem"
                if not public_path.exists():
                    public_path.write_bytes(public_pem)
                input_hashes["verification_public_key"] = {
                    "path": str(public_path.relative_to(workspace)),
                    "sha256": hashlib.sha256(public_pem).hexdigest(),
                    "kind": "public_key",
                }
            except Exception as exc:
                input_errors.append(f"verification key could not be read: {exc}")
    record_details = dict(oracle_result.details)
    if input_errors:
        record_details["evidence_input_errors"] = input_errors
    record_passed = oracle_result.passed and not input_errors
    record_verdict = oracle_result.verdict
    if input_errors and oracle_result.passed:
        record_verdict = "ERROR: EVIDENCE_INPUT"
    if backend_result.infrastructure_error:
        backend_outcome = (
            "timeout" if backend_result.timed_out else "infrastructure_error"
        )
    elif scenario.backend.value == "imgtool_verify":
        backend_outcome = classify_outcome(backend_result.returncode, stdout, stderr)[0]
    else:
        parsed_result = parse_cargo_test_result(backend_result)
        backend_outcome = (
            "execution_error"
            if parsed_result["cargo_execution_error"]
            else "test_not_executed"
            if not parsed_result["selected_test_executed"]
            else "test_passed"
            if parsed_result["cargo_test_ok"]
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
        backend_args=_public_backend_args(scenario),
        mcuboot_commit=provenance.get("mcuboot_commit", "unknown"),
        assertion_result=(
            "pass" if record_passed else "skip" if record_verdict == "SKIP" else "fail"
        ),
        verdict=record_verdict,
        passed=record_passed,
        infrastructure_error=bool(input_errors)
        or record_verdict in {"ERROR", "TIMEOUT", "infrastructure_error"},
        exit_status=backend_result.returncode,
        backend_outcome=backend_outcome,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        elapsed_seconds=elapsed,
        stdout_path=str(stdout_path.relative_to(workspace)),
        stderr_path=str(stderr_path.relative_to(workspace)),
        details=record_details,
        evaluated_assertions=record_details,
        notes=scenario.notes,
        scenario_sha256=hashlib.sha256(scenario_bytes).hexdigest(),
        scenario_configuration=scenario_configuration,
        declared_expectations=scenario.expect.model_dump(mode="json"),
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
        command.extend(
            ["--", args.get("cargo_test", scenario.name), "--exact", "--nocapture"]
        )
        return command

    return [
        "imgtool",
        "verify",
        "-k",
        "<archived-public-key>",
        "<archived-image-input>",
    ]
