"""Adapter for upstream MCUboot simulator tests and direct corpus-image runs."""

from __future__ import annotations

import os
import re
import hashlib
import struct
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from bootlab.fuzz_image import classify_outcome
from bootlab.images import SIMULATOR_ROOT_KEYS
from bootlab.scenario import Backend, ProfileSpec, Scenario


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
        if not isinstance(env_vars, dict) or any(
            not isinstance(k, str) or not isinstance(v, str)
            for k, v in env_vars.items()
        ):
            return SimulatorResult(
                -1,
                "",
                "backend_args.env must map strings to strings",
                Backend.MCUBOOT_SIM,
                scenario.backend_args,
                True,
            )
        if not isinstance(test_name, str) or not test_name.strip():
            return SimulatorResult(
                -1,
                "",
                "backend_args.cargo_test must be a non-empty test name",
                Backend.MCUBOOT_SIM,
                scenario.backend_args,
                True,
            )
        if not isinstance(features, str):
            return SimulatorResult(
                -1,
                "",
                "backend_args.cargo_features must be a string",
                Backend.MCUBOOT_SIM,
                scenario.backend_args,
                True,
            )
        cmd = ["cargo", "test"]
        if features:
            cmd.extend(["--features", features])
        env = os.environ.copy()
        env["RUST_LOG"] = "warn"
        env.update(env_vars)
        runtime_args = dict(scenario.backend_args)
        if test_name == "bootlab_direct_image":
            try:
                primary = self._direct_image(scenario.backend_args["primary_image"])
                candidate = self._direct_image(scenario.backend_args["candidate_image"])
                key_type = scenario.backend_args.get("key_type", "ecdsa-p256")
                profile_path = self.workspace / "profiles" / f"{scenario.profile}.yaml"
                profile = ProfileSpec.model_validate(
                    yaml.safe_load(profile_path.read_text())
                )
                if profile.signature.algorithm != key_type:
                    raise ValueError(
                        "profile signature algorithm does not match direct image algorithm"
                    )
                if (
                    profile.image.header_size != 0x200
                    or profile.image.align != 8
                    or profile.image.slot_size != 0x034000
                ):
                    raise ValueError(
                        "direct simulator supports a 0x200 header, align 8, and 0x34000-byte slots"
                    )
                root_key = (
                    self.workspace
                    / "vendor"
                    / "mcuboot"
                    / SIMULATOR_ROOT_KEYS[key_type]
                )
                if not root_key.is_file():
                    raise ValueError(
                        f"pinned MCUboot root key is missing: {root_key.name}"
                    )
                for label, image_path, image_ref in (
                    ("primary", primary, scenario.primary),
                    ("candidate", candidate, scenario.secondary),
                ):
                    image = image_path.read_bytes()
                    if (
                        struct.unpack_from("<H", image, 8)[0]
                        != profile.image.header_size
                    ):
                        raise ValueError(
                            f"{label} image header size conflicts with profile"
                        )
                    image_algorithm = _image_signature_algorithm(image)
                    if image_algorithm != key_type:
                        raise ValueError(
                            f"{label} image uses {image_algorithm}, expected {key_type}"
                        )
                    if normalize_image_version(
                        _image_version(image)
                    ) != normalize_image_version(image_ref.version):
                        raise ValueError(
                            f"{label} image version conflicts with its declared version"
                        )
                    verified = self._verify_direct_signature(root_key, image_path)
                    if verified != image_ref.trusted:
                        raise ValueError(
                            f"{label} signature trust result {verified} conflicts with declared trust={image_ref.trusted}"
                        )
                env["BOOTLAB_PRIMARY_IMAGE"] = str(primary)
                env["BOOTLAB_CANDIDATE_IMAGE"] = str(candidate)
                runtime_args["injected_sha256"] = {
                    "primary": hashlib.sha256(primary.read_bytes()).hexdigest(),
                    "candidate": hashlib.sha256(candidate.read_bytes()).hexdigest(),
                }
                runtime_args["direct_input_sizes"] = {
                    "primary": primary.stat().st_size,
                    "candidate": candidate.stat().st_size,
                }
            except subprocess.TimeoutExpired as exc:
                return SimulatorResult(
                    returncode=-1,
                    stdout=_output_text(exc.stdout),
                    stderr=_output_text(exc.stderr) or str(exc),
                    backend=Backend.MCUBOOT_SIM,
                    backend_args=runtime_args,
                    infrastructure_error=True,
                    timed_out=True,
                )
            except (
                KeyError,
                OSError,
                ValueError,
                RuntimeError,
                struct.error,
                yaml.YAMLError,
            ) as exc:
                return SimulatorResult(
                    -1,
                    "",
                    f"Invalid direct simulator input: {exc}",
                    Backend.MCUBOOT_SIM,
                    runtime_args,
                    True,
                )
            if "BOOTLAB_FAULT_INDEX" in env_vars:
                env["BOOTLAB_FAULT_INDEX"] = env_vars["BOOTLAB_FAULT_INDEX"]
        runtime_args["runtime_cargo_test"] = test_name
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
                backend_args=runtime_args,
                infrastructure_error=True,
                timed_out=True,
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            return SimulatorResult(
                returncode=-1,
                stdout="",
                stderr=str(exc),
                backend=Backend.MCUBOOT_SIM,
                backend_args=runtime_args,
                infrastructure_error=True,
            )

        return SimulatorResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            backend=Backend.MCUBOOT_SIM,
            backend_args=runtime_args,
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
            if key_id == "dev-trusted" and key_type in SIMULATOR_ROOT_KEYS:
                key_path = (
                    self.workspace
                    / "vendor"
                    / "mcuboot"
                    / SIMULATOR_ROOT_KEYS[key_type]
                )
            else:
                key_path = (
                    self.workspace / "fixtures" / "keys" / f"{key_id}-{key_type}.pem"
                )
                if not key_path.exists():
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

    def _direct_image(self, image_name: str) -> Path:
        path = Path(image_name)
        if path.is_absolute():
            raise ValueError("direct image names must be relative to artifacts/corpus")
        corpus = (self.workspace / "artifacts" / "corpus").resolve()
        image_path = (corpus / path).resolve()
        if not image_path.is_relative_to(corpus):
            raise ValueError("direct image path must stay within artifacts/corpus")
        data = image_path.read_bytes()
        if len(data) < 32 or struct.unpack_from("<I", data)[0] != 0x96F3B83D:
            raise ValueError(f"{image_name} is not a complete MCUboot v1 image")
        header_size, image_size = (
            struct.unpack_from("<H", data, 8)[0],
            struct.unpack_from("<I", data, 12)[0],
        )
        if (
            header_size < 32
            or header_size > len(data)
            or header_size + image_size > len(data)
        ):
            raise ValueError(f"{image_name} contains invalid header or image sizes")
        if len(data) > 0x034000:
            raise ValueError(f"{image_name} exceeds the supported 0x34000-byte slot")
        return image_path

    @staticmethod
    def _verify_direct_signature(key_path: Path, image_path: Path) -> bool:
        executable = shutil.which("imgtool")
        if executable is None:
            raise FileNotFoundError(
                "imgtool is required to validate direct image signature/trust metadata"
            )
        proc = subprocess.run(
            [executable, "verify", "-k", str(key_path), str(image_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        outcome, _ = classify_outcome(proc.returncode, proc.stdout, proc.stderr)
        if outcome not in {"accepted", "rejected"}:
            raise RuntimeError(
                f"imgtool could not establish signature trust: {(proc.stderr or proc.stdout)[:300]}"
            )
        return outcome == "accepted"


def _image_signature_algorithm(image: bytes) -> str:
    header_size, image_size = (
        struct.unpack_from("<H", image, 8)[0],
        struct.unpack_from("<I", image, 12)[0],
    )
    tlv_start = header_size + image_size
    if tlv_start + 4 > len(image):
        raise ValueError("image has no protected or unprotected TLV area")
    magic, total = struct.unpack_from("<HH", image, tlv_start)
    if magic not in {0x6907, 0x6908} or total < 4 or tlv_start + total > len(image):
        raise ValueError("image has malformed TLV metadata")
    pos = tlv_start + 4
    end = tlv_start + total
    signatures = {
        0x20: "rsa-2048",
        0x22: "ecdsa-p256",
        0x23: "rsa-3072",
        0x24: "ed25519",
        0x25: "ecdsa-p384",
    }
    found = []
    while pos + 4 <= end:
        kind, _, length = struct.unpack_from("<BBH", image, pos)
        pos += 4
        if pos + length > end:
            raise ValueError("image contains a truncated TLV entry")
        if kind in signatures:
            found.append(signatures[kind])
        pos += length
    if len(set(found)) != 1:
        raise ValueError("image must contain exactly one supported signature algorithm")
    return found[0]


def _image_version(image: bytes) -> str:
    if len(image) < 28:
        raise ValueError("image is too short to contain the complete version structure")
    major, minor, revision, build = struct.unpack_from("<BBHI", image, 20)
    return f"{major}.{minor}.{revision}+{build}"


def normalize_image_version(value: str | None) -> tuple[int, int, int, int]:
    """Parse the full MCUboot version; omitted build numbers mean build zero.

    Build participates in BootLab's exact declared-versus-observed version
    identity. MCUboot's downgrade comparator separately follows its build
    number compile-time configuration.
    """
    if not isinstance(value, str):
        raise ValueError("image version must be a string")
    version_part, separator, build_part = value.partition("+")
    components = version_part.split(".")
    if len(components) != 3 or any(not component.isdigit() for component in components):
        raise ValueError(
            f"invalid MCUboot version {value!r}; expected major.minor.revision[+build]"
        )
    major, minor, revision = (int(component) for component in components)
    if separator and not build_part.isdigit():
        raise ValueError(f"invalid MCUboot build number in version {value!r}")
    build = int(build_part) if separator else 0
    if major > 255 or minor > 255 or revision > 65535 or build > 0xFFFFFFFF:
        raise ValueError(f"MCUboot version {value!r} exceeds its field width")
    return major, minor, revision, build


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
        match = re.search(
            rf"^test\s+{re.escape(expected_test)}\s+\.\.\.\s+(ok|FAILED)$", line.strip()
        )
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
        "cargo_test_ok": result.returncode == 0
        and failed == 0
        and passed > 0
        and selected_test_executed,
        "cargo_test_executed": passed + failed,
        "cargo_execution_error": result.returncode != 0 and passed + failed == 0,
    }
