from __future__ import annotations

import json
import sys
import tarfile
from pathlib import Path

from click.testing import CliRunner
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from bootlab.backends.mcuboot_sim import Backend, SimulatorResult
from bootlab.cli import main
from bootlab.evidence import (
    begin_run,
    gather_provenance,
    latest_run_id,
    record_evidence,
)
from bootlab.oracles import OracleResult
from bootlab.scenario import Scenario


def _scenario(key_path: Path, name: str = "evidence-key-check") -> Scenario:
    return Scenario(
        id="E02" if name == "latest-second-run" else "E01",
        name=name,
        category="integrity",
        profile="mcuboot_swap_reference",
        backend=Backend.IMGTOOL_VERIFY,
        backend_args={"image": "sample.bin", "key_path": str(key_path)},
    )


def _record(workspace: Path, key_path: Path, name: str = "evidence-key-check") -> Path:
    scenario = _scenario(key_path, name)
    run_id = begin_run(workspace, "test", gather_provenance(workspace))
    result = SimulatorResult(
        -1,
        "",
        "backend unavailable",
        Backend.IMGTOOL_VERIFY,
        scenario.backend_args,
        infrastructure_error=True,
    )
    return record_evidence(
        workspace,
        scenario,
        OracleResult(False, "ERROR", {"reason": "backend unavailable"}),
        "captured stdout",
        "captured stderr",
        0.1,
        gather_provenance(workspace),
        result,
        run_id,
    )


def _keypair(keys_dir: Path) -> tuple[Path, Path]:
    keys_dir.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    private_path = keys_dir / "private.pem"
    public_path = keys_dir / "public.pem"
    private_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_path, public_path


def test_provenance_handles_source_archive_and_missing_git(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "vendor" / "mcuboot").mkdir(parents=True)
    patch_dir = tmp_path / "vendor" / "mcuboot-patches"
    patch_dir.mkdir()
    (patch_dir / "0001-fault-campaign-public-api.patch").write_text("patch")
    monkeypatch.setattr(
        "bootlab.evidence.shutil.which", lambda tool: None if tool == "git" else None
    )
    provenance = gather_provenance(tmp_path)
    assert provenance["bootlab_commit"] == "unknown"
    assert provenance["mcuboot_commit"] == "unknown"
    assert provenance["bootlab_dirty"] is None
    assert provenance["mcuboot_dirty"] is None
    assert provenance["patch_application"] == "unknown"
    assert provenance["python_executable"] == sys.executable
    assert provenance["python_environment"] == (
        str(sys.prefix) if sys.prefix != sys.base_prefix else "system"
    )


def test_record_archives_public_key_for_private_and_public_inputs(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "artifacts" / "corpus" / "sample.bin"
    sample.parent.mkdir(parents=True)
    sample.write_bytes(b"immutable test image")
    private, public = _keypair(tmp_path / "keys")

    private_record = _record(tmp_path, private)
    public_record = _record(tmp_path, public)
    private_data = json.loads(private_record.read_text())
    public_data = json.loads(public_record.read_text())
    assert (
        private_data["public_key_fingerprint"] == public_data["public_key_fingerprint"]
    )
    for data in (private_data, public_data):
        key_input = data["input_sha256"]["verification_public_key"]
        archived = tmp_path / key_input["path"]
        assert b"BEGIN PUBLIC KEY" in archived.read_bytes()
        assert b"BEGIN PRIVATE KEY" not in archived.read_bytes()
        assert data["details"]["reason"] == "backend unavailable"


def test_invalid_and_missing_verification_keys_are_recorded(tmp_path: Path) -> None:
    (tmp_path / "artifacts" / "corpus").mkdir(parents=True)
    (tmp_path / "artifacts" / "corpus" / "sample.bin").write_bytes(b"image")
    malformed = tmp_path / "bad.pem"
    malformed.write_text("not a key")

    for key_path, expected in (
        (malformed, "could not be read"),
        (tmp_path / "missing.pem", "does not exist"),
    ):
        record_path = _record(tmp_path, key_path)
        data = json.loads(record_path.read_text())
        assert any(
            expected in issue for issue in data["details"]["evidence_input_errors"]
        )


def test_evidence_input_error_downgrades_authoritative_oracle_result(
    tmp_path: Path,
) -> None:
    scenario = _scenario(tmp_path / "missing-public.pem")
    run_id = begin_run(tmp_path, "test", gather_provenance(tmp_path))
    backend_result = SimulatorResult(
        0,
        "",
        "",
        Backend.IMGTOOL_VERIFY,
        scenario.backend_args,
    )
    oracle = OracleResult(True, "pass", {"actual_verified": True})

    record_path = record_evidence(
        tmp_path,
        scenario,
        oracle,
        "",
        "",
        0.01,
        gather_provenance(tmp_path),
        backend_result,
        run_id,
    )

    record = json.loads(record_path.read_text())
    assert record["verdict"] == "ERROR: EVIDENCE_INPUT"
    assert record["passed"] is False
    assert oracle.verdict == record["verdict"]
    assert oracle.passed is record["passed"]


def test_consecutive_runs_and_historical_report_selection(tmp_path: Path) -> None:
    image = tmp_path / "artifacts" / "corpus" / "sample.bin"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"image")
    private, _ = _keypair(tmp_path / "keys")

    first_record = _record(tmp_path, private, "historical-first-run")
    first_run = first_record.parents[1].name
    second_record = _record(tmp_path, private, "latest-second-run")
    second_run = second_record.parents[1].name
    assert first_run != second_run
    assert first_record.is_file()
    assert second_record.is_file()
    assert latest_run_id(tmp_path) == second_run

    output = tmp_path / "historical-report.md"
    result = CliRunner().invoke(
        main,
        [
            "--workspace",
            str(tmp_path),
            "sanitize-report",
            "--run-id",
            first_run,
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert output.is_file()
    assert "| E01 |" in output.read_text()
    assert "| E02 |" not in output.read_text()


def test_exported_run_verifies_without_private_key_and_detects_tampering(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    image = workspace / "artifacts" / "corpus" / "sample.bin"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"portable image bytes")
    private, _ = _keypair(workspace / "fixtures" / "keys")
    scenario_record = _record(workspace, private)
    run_id = scenario_record.parents[1].name

    runner = CliRunner()
    signed = runner.invoke(
        main,
        ["--workspace", str(workspace), "sign-evidence", "--run-id", run_id],
    )
    assert signed.exit_code == 0, signed.output
    archive = workspace / "portable.tar.gz"
    exported = runner.invoke(
        main,
        [
            "--workspace",
            str(workspace),
            "export-evidence",
            "--run-id",
            run_id,
            "--output",
            str(archive),
        ],
    )
    assert exported.exit_code == 0, exported.output

    extracted = tmp_path / "elsewhere"
    extracted.mkdir()
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(extracted, filter="data")
    portable = extracted / "evidence" / "runs" / run_id
    public_key = extracted / "fixtures" / "keys" / "evidence-signer.pub.pem"
    assert (extracted / "fixtures" / "keys" / "evidence-signer.pem").exists() is False

    verify_args = [
        "--workspace",
        str(extracted),
        "verify-evidence",
        "--run-id",
        run_id,
        "--public-key",
        str(public_key),
    ]
    verified = runner.invoke(main, verify_args)
    assert verified.exit_code == 0, verified.output

    input_record = next(portable.rglob("record.json"))
    original_record = input_record.read_bytes()
    input_data = json.loads(input_record.read_text())
    input_path = extracted / input_data["input_sha256"]["image"]["path"]
    input_path.write_bytes(b"tampered image bytes")
    tampered = runner.invoke(main, verify_args)
    assert tampered.exit_code != 0
    assert "INVALID" in tampered.output

    input_path.write_bytes(b"portable image bytes")
    stdout_path = extracted / input_data["stdout_path"]
    stdout_path.write_text("changed stdout")
    changed_log = runner.invoke(main, verify_args)
    assert changed_log.exit_code != 0
    stdout_path.write_text("captured stdout")

    changed_record = json.loads(input_record.read_text())
    changed_record["case_name"] = "changed record"
    input_record.write_text(json.dumps(changed_record, indent=2) + "\n")
    changed_json = runner.invoke(main, verify_args)
    assert changed_json.exit_code != 0
    input_record.write_bytes(original_record)

    input_path.unlink()
    missing_artifact = runner.invoke(main, verify_args)
    assert missing_artifact.exit_code != 0
    input_path.write_bytes(b"portable image bytes")

    input_record.with_suffix(".json.sig").unlink()
    missing_sig = runner.invoke(main, verify_args)
    assert missing_sig.exit_code != 0
    assert "MISSING signature" in missing_sig.output
