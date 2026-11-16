"""MCUboot simulator backend adapter.

This module drives named MCUboot Rust integration tests as scenario proxies
and verifies generated corpus images through imgtool. Simulator fixtures are
created by the upstream tests; the adapter does not inject corpus images into
simulator flash.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from bootlab.scenario import Backend, Scenario


class SimulatorResult:
    """Structured result from a simulator/backend invocation."""

    def __init__(
        self,
        returncode: int,
        stdout: str,
        stderr: str,
        backend: Backend,
        backend_args: dict[str, Any],
        infrastructure_error: bool = False,
        timed_out: bool = False,
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.backend = backend
        self.backend_args = backend_args
        self.infrastructure_error = infrastructure_error
        self.timed_out = timed_out

    def summary(self) -> dict[str, Any]:
        return {
            "backend": self.backend.value,
            "backend_args": self.backend_args,
            "returncode": self.returncode,
            "infrastructure_error": self.infrastructure_error,
            "timed_out": self.timed_out,
            "stdout_lines": self.stdout.splitlines(),
            "stderr_lines": self.stderr.splitlines(),
        }


class McubootSimAdapter:
    """Adapter for the upstream MCUboot Rust simulator."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.sim_dir = workspace / "vendor" / "mcuboot" / "sim"

    def run(self, scenario: Scenario) -> SimulatorResult:
        if scenario.backend == Backend.IMGTOOL_VERIFY:
            return self._run_imgtool_verify(scenario)
        if scenario.backend == Backend.MCUBOOT_SIM:
            return self._run_cargo_test(scenario)
        raise ValueError(f"Unsupported backend: {scenario.backend}")

    def _run_cargo_test(self, scenario: Scenario) -> SimulatorResult:
        test_name = scenario.backend_args.get("cargo_test", scenario.name)
        features = scenario.backend_args.get("cargo_features", "sig-ecdsa")
        env_vars = scenario.backend_args.get("env", {})
        if not isinstance(env_vars, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in env_vars.items()):
            return SimulatorResult(-1, "", "backend_args.env must map strings to strings", Backend.MCUBOOT_SIM, scenario.backend_args, True)
        if not isinstance(test_name, str) or not test_name.strip():
            return SimulatorResult(-1, "", "backend_args.cargo_test must be a non-empty test name", Backend.MCUBOOT_SIM, scenario.backend_args, True)
        if not isinstance(features, str):
            return SimulatorResult(-1, "", "backend_args.cargo_features must be a string", Backend.MCUBOOT_SIM, scenario.backend_args, True)
        cmd = ["cargo", "test"]
        if features:
            cmd.extend(["--features", features])
        env = os.environ.copy()
        env["RUST_LOG"] = "warn"
        env.update(env_vars)
        cmd.extend(["--", test_name, "--exact", "--nocapture"])
        try:
            proc = subprocess.run(
                cmd,
                cwd=self.sim_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            return SimulatorResult(
                returncode=-1,
                stdout=_output_text(exc.stdout),
                stderr=_output_text(exc.stderr),
                backend=Backend.MCUBOOT_SIM,
                backend_args=scenario.backend_args,
                infrastructure_error=True,
                timed_out=True,
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            return SimulatorResult(
                returncode=-1,
                stdout="",
                stderr=str(exc),
                backend=Backend.MCUBOOT_SIM,
                backend_args=scenario.backend_args,
                infrastructure_error=True,
            )

        return SimulatorResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            backend=Backend.MCUBOOT_SIM,
            backend_args=scenario.backend_args,
            infrastructure_error=False,
        )

    def _run_imgtool_verify(self, scenario: Scenario) -> SimulatorResult:
        image_name = scenario.backend_args.get("image")
        if not image_name:
            return SimulatorResult(
                returncode=-1,
                stdout="",
                stderr="imgtool_verify backend requires backend_args.image",
                backend=Backend.IMGTOOL_VERIFY,
                backend_args=scenario.backend_args,
                infrastructure_error=True,
            )
        image_path = self.workspace / "artifacts" / "corpus" / image_name

        key_path_arg = scenario.backend_args.get("key_path")
        if key_path_arg:
            key_path = Path(key_path_arg)
            if not key_path.is_absolute():
                key_path = self.workspace / key_path
        else:
            key_id = scenario.backend_args.get("key_id", "dev-trusted")
            key_type = scenario.backend_args.get("key_type", "ecdsa-p256")
            key_path = self.workspace / "fixtures" / "keys" / f"{key_id}-{key_type}.pem"
            if not key_path.exists():
                # Legacy key name for backwards compatibility with existing ECDSA corpus.
                legacy_path = self.workspace / "fixtures" / "keys" / f"{key_id}.pem"
                if legacy_path.exists():
                    key_path = legacy_path

        if not image_path.is_file():
            return SimulatorResult(
                returncode=-1,
                stdout="",
                stderr=f"Image not found: {image_path}",
                backend=Backend.IMGTOOL_VERIFY,
                backend_args=scenario.backend_args,
                infrastructure_error=True,
            )
        if not key_path.is_file():
            return SimulatorResult(
                returncode=-1,
                stdout="",
                stderr=f"Verification key not found: {key_path}",
                backend=Backend.IMGTOOL_VERIFY,
                backend_args=scenario.backend_args,
                infrastructure_error=True,
            )
        cmd = ["imgtool", "verify", "-k", str(key_path), str(image_path)]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        except subprocess.TimeoutExpired as exc:
            return SimulatorResult(
                returncode=-1,
                stdout=_output_text(exc.stdout),
                stderr=_output_text(exc.stderr) or str(exc),
                backend=Backend.IMGTOOL_VERIFY,
                backend_args=scenario.backend_args,
                infrastructure_error=True,
                timed_out=True,
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            return SimulatorResult(
                returncode=-1,
                stdout="",
                stderr=str(exc),
                backend=Backend.IMGTOOL_VERIFY,
                backend_args=scenario.backend_args,
                infrastructure_error=True,
            )
        return SimulatorResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            backend=Backend.IMGTOOL_VERIFY,
            backend_args=scenario.backend_args,
            infrastructure_error=False,
        )


def _output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def parse_cargo_test_result(result: SimulatorResult) -> dict[str, Any]:
    """Extract the selected Rust test identity and executed test counts."""
    stdout = _output_text(result.stdout)
    stderr = _output_text(result.stderr)
    combined = stdout + "\n" + stderr
    passed = 0
    failed = 0
    expected_test = str(result.backend_args.get("cargo_test", ""))
    selected_test_executed = False
    selected_test_status: str | None = None
    for line in combined.splitlines():
        match = re.search(rf"^test\s+{re.escape(expected_test)}\s+\.\.\.\s+(ok|FAILED)$", line.strip())
        if expected_test and match:
            selected_test_executed = True
            selected_test_status = match.group(1)
        if "test result:" in line:
            # e.g. "test result: ok. 1 passed; 0 failed; ..."
            m_passed = re.search(r"(\d+) passed", line)
            m_failed = re.search(r"(\d+) failed", line)
            line_passed = int(m_passed.group(1)) if m_passed else 0
            line_failed = int(m_failed.group(1)) if m_failed else 0
            # The integration test binary line is the one with non-zero counts.
            passed += line_passed
            failed += line_failed
    return {
        "cargo_test_passed": passed,
        "cargo_test_failed": failed,
        "selected_test": expected_test,
        "selected_test_executed": selected_test_executed,
        "selected_test_status": selected_test_status,
        "selected_test_ok": selected_test_status == "ok",
        "cargo_test_ok": result.returncode == 0 and failed == 0 and passed > 0 and selected_test_executed,
        "cargo_test_executed": passed + failed,
        "cargo_execution_error": result.returncode != 0 and passed + failed == 0,
    }
