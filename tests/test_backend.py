from __future__ import annotations

import shutil
import struct
import subprocess
from pathlib import Path

from bootlab.backends import mcuboot_sim
from bootlab.backends.mcuboot_sim import (
    McubootSimAdapter,
    SimulatorResult,
    _image_version,
    normalize_image_version,
)
from bootlab.scenario import Scenario


def _version_image(major: int, minor: int, revision: int, build: int) -> bytes:
    image = bytearray(28)
    struct.pack_into("<BBHI", image, 20, major, minor, revision, build)
    return bytes(image)


def test_image_version_parses_revision_boundaries_and_build_number() -> None:
    assert _image_version(_version_image(1, 0, 255, 7)) == "1.0.255+7"
    assert _image_version(_version_image(1, 0, 256, 9)) == "1.0.256+9"
    assert _image_version(_version_image(1, 0, 65535, 0xFFFFFFFF)) == (
        "1.0.65535+4294967295"
    )

    assert normalize_image_version("1.2.3") == normalize_image_version("1.2.3+0")
    assert normalize_image_version("1.2.3+1") > normalize_image_version("1.2.3+0")


def test_direct_image_preverification_timeout_is_structured(
    tmp_path: Path, monkeypatch
) -> None:
    source = Path(__file__).resolve().parents[1]
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    shutil.copy(
        source / "profiles" / "mcuboot_overwrite_reference.yaml",
        profile_dir / "mcuboot_overwrite_reference.yaml",
    )
    key_dir = tmp_path / "vendor" / "mcuboot"
    key_dir.mkdir(parents=True)
    (key_dir / mcuboot_sim.SIMULATOR_ROOT_KEYS["ecdsa-p256"]).write_bytes(b"test key")
    corpus = tmp_path / "artifacts" / "corpus"
    corpus.mkdir(parents=True)
    primary = corpus / "primary.bin"
    candidate = corpus / "candidate.bin"
    for image, major in ((primary, 1), (candidate, 2)):
        data = bytearray(512)
        struct.pack_into("<I", data, 0, 0x96F3B83D)
        struct.pack_into("<H", data, 8, 0x200)
        struct.pack_into("<BBHI", data, 20, major, 0, 0, 0)
        image.write_bytes(data)

    scenario = Scenario.model_validate(
        {
            "id": "D01",
            "name": "timeout-direct-preverification",
            "category": "baseline",
            "profile": "mcuboot_overwrite_reference",
            "primary": {"name": "primary", "version": "1.0.0", "trusted": True},
            "secondary": {
                "name": "candidate",
                "version": "2.0.0",
                "trusted": True,
            },
            "operation": "stage_then_upgrade",
            "backend": "mcuboot_sim",
            "backend_args": {
                "cargo_test": "bootlab_direct_image",
                "cargo_features": "sig-ecdsa overwrite-only",
                "primary_image": "primary.bin",
                "candidate_image": "candidate.bin",
                "expected_selection": "candidate",
                "key_type": "ecdsa-p256",
            },
            "fault": {"type": "none"},
            "expect": {
                "outcome_in": ["new_authenticated_image"],
                "booted_version": "2.0.0",
            },
        }
    )
    adapter = McubootSimAdapter(tmp_path)
    monkeypatch.setattr(adapter, "_direct_image", lambda name: corpus / name)
    monkeypatch.setattr(
        mcuboot_sim, "_image_signature_algorithm", lambda _data: "ecdsa-p256"
    )
    monkeypatch.setattr(mcuboot_sim, "_image_version", lambda data: f"{data[20]}.0.0+0")

    def timeout(_key: Path, _image: Path) -> bool:
        raise subprocess.TimeoutExpired(
            ["imgtool", "verify"],
            60,
            output=b"partial stdout",
            stderr=b"partial stderr",
        )

    monkeypatch.setattr(adapter, "_verify_direct_signature", timeout)
    result: SimulatorResult = adapter.run(scenario)
    assert result.infrastructure_error is True
    assert result.timed_out is True
    assert result.returncode == -1
    assert result.stdout == "partial stdout"
    assert result.stderr == "partial stderr"
