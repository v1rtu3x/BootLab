"""Signed image factory and manifest management.

Uses MCUboot's imgtool to generate reproducible development-only signed images
and controlled mutations for assurance testing.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


# Map imgtool key type names to MCUboot simulator cargo feature names.
KEY_TYPE_TO_CARGO_FEATURE: dict[str, str] = {
    "ecdsa-p256": "sig-ecdsa",
    "ecdsa-p384": "sig-ecdsa",
    "rsa-2048": "sig-rsa",
    "rsa-3072": "sig-rsa3072",
    "ed25519": "sig-ed25519",
}


@dataclass(frozen=True)
class ImageSpec:
    name: str
    version: str
    payload_text: str
    key_id: str
    key_type: str = "ecdsa-p256"
    mutation: str | None = None
    notes: str = ""


@dataclass(frozen=True)
class ImageRecord:
    name: str
    version: str
    key_id: str
    key_type: str
    path: str
    sha256: str
    mutation: str | None
    notes: str


class ImageFactory:
    """Build a corpus of signed MCUboot images from simple text payloads."""

    def __init__(
        self,
        corpus_dir: Path,
        keys_dir: Path,
        header_size: int = 0x200,
        slot_size: int = 0x034000,
        align: int = 8,
    ) -> None:
        self.corpus_dir = corpus_dir
        self.keys_dir = keys_dir
        self.header_size = header_size
        self.slot_size = slot_size
        self.align = align
        self.corpus_dir.mkdir(parents=True, exist_ok=True)
        self.keys_dir.mkdir(parents=True, exist_ok=True)

    def _key_path(self, key_id: str, key_type: str) -> Path:
        return self.keys_dir / f"{key_id}-{key_type}.pem"

    def _ensure_key(self, key_id: str, key_type: str) -> Path:
        key_path = self._key_path(key_id, key_type)
        if key_path.exists():
            return key_path
        subprocess.run(
            [
                "imgtool",
                "keygen",
                "-k",
                str(key_path),
                "-t",
                key_type,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return key_path

    def _write_payload(self, spec: ImageSpec) -> Path:
        payload_path = self.corpus_dir / f"{spec.name}.payload.bin"
        payload = spec.payload_text.encode("utf-8")
        # Pad payload to a deterministic size so mutated and original images are comparable.
        payload += b"\x00" * (256 - (len(payload) % 256)) if len(payload) % 256 else b""
        payload_path.write_bytes(payload)
        return payload_path

    def _sign(self, spec: ImageSpec, payload_path: Path, output_path: Path) -> None:
        key_path = self._ensure_key(spec.key_id, spec.key_type)
        cmd = [
            "imgtool",
            "sign",
            "--key",
            str(key_path),
            "--version",
            spec.version,
            "--header-size",
            str(self.header_size),
            "--slot-size",
            str(self.slot_size),
            "--align",
            str(self.align),
            "--pad-header",
            str(payload_path),
            str(output_path),
        ]
        if spec.key_type == "ed25519":
            # Ed25519 uses a pure signature variant in MCUboot by default for this lab.
            cmd.append("--pure")
        subprocess.run(cmd, check=True, capture_output=True, text=True)

    def _mutate(self, spec: ImageSpec, signed_path: Path) -> Path:
        if spec.mutation is None:
            return signed_path
        data = bytearray(signed_path.read_bytes())
        if spec.mutation == "payload_bitflip":
            # Flip a bit well inside the authenticated payload area, after header.
            flip_index = self.header_size + 64
            data[flip_index] ^= 0x01
        elif spec.mutation == "header_version_flip":
            # Flip a bit in the version field inside the image header.
            # The version is at a fixed offset in the header; this is a coarse mutation.
            data[16] ^= 0x01
        elif spec.mutation == "truncate_tlv":
            # Truncate the trailing TLV area to produce a malformed image.
            data = data[: len(data) // 2]
        else:
            raise ValueError(f"Unknown mutation: {spec.mutation}")
        mutated_path = self.corpus_dir / f"{spec.name}.bin"
        mutated_path.write_bytes(data)
        return mutated_path

    def build(self, specs: Iterable[ImageSpec]) -> list[ImageRecord]:
        records: list[ImageRecord] = []
        for spec in specs:
            payload_path = self._write_payload(spec)
            signed_path = self.corpus_dir / f"{spec.name}.signed.bin"
            self._sign(spec, payload_path, signed_path)
            final_path = self._mutate(spec, signed_path)
            sha256 = hashlib.sha256(final_path.read_bytes()).hexdigest()
            records.append(
                ImageRecord(
                    name=spec.name,
                    version=spec.version,
                    key_id=spec.key_id,
                    key_type=spec.key_type,
                    path=str(final_path.relative_to(self.corpus_dir.parent)),
                    sha256=sha256,
                    mutation=spec.mutation,
                    notes=spec.notes,
                )
            )
        return records

    def write_manifest(self, records: list[ImageRecord]) -> Path:
        manifest_path = self.corpus_dir / "manifest.json"
        manifest = {
            "header_size": self.header_size,
            "slot_size": self.slot_size,
            "align": self.align,
            "key_types": sorted({r.key_type for r in records}),
            "images": [asdict(r) for r in records],
        }
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        return manifest_path


def ensure_rotation_key(keys_dir: Path, key_type: str = "ecdsa-p256") -> Path:
    """Ensure a second trusted signing key exists for rotation scenarios."""
    keys_dir.mkdir(parents=True, exist_ok=True)
    key_path = keys_dir / f"dev-trusted-2-{key_type}.pem"
    if key_path.exists():
        return key_path
    subprocess.run(
        [
            "imgtool",
            "keygen",
            "-k",
            str(key_path),
            "-t",
            key_type,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return key_path


def default_corpus_specs() -> list[ImageSpec]:
    """Return the initial MVP image corpus specifications (ECDSA-P256 reference)."""
    return [
        ImageSpec(
            name="v1.0.0-trusted",
            version="1.0.0",
            payload_text="FIRMWARE_VERSION_1_0_0_TRUSTED_KEY",
            key_id="dev-trusted",
            notes="Baseline known-good primary image.",
        ),
        ImageSpec(
            name="v2.0.0-trusted",
            version="2.0.0",
            payload_text="FIRMWARE_VERSION_2_0_0_TRUSTED_KEY",
            key_id="dev-trusted",
            notes="Valid signed update image.",
        ),
        ImageSpec(
            name="v1.5.0-trusted",
            version="1.5.0",
            payload_text="FIRMWARE_VERSION_1_5_0_TRUSTED_KEY",
            key_id="dev-trusted",
            notes="Intermediate signed version for downgrade policy tests.",
        ),
        ImageSpec(
            name="v2.0.0-untrusted",
            version="2.0.0",
            payload_text="FIRMWARE_VERSION_2_0_0_UNTRUSTED_KEY",
            key_id="dev-untrusted",
            notes="Signed with a key not in the trusted set.",
        ),
        ImageSpec(
            name="v2.0.0-trusted-2",
            version="2.0.0",
            payload_text="FIRMWARE_VERSION_2_0_0_ROTATION_KEY",
            key_id="dev-trusted-2",
            notes="Signed with the second trusted key for rotation scenarios.",
        ),
        ImageSpec(
            name="v2.0.0-trusted-payload-flip",
            version="2.0.0",
            payload_text="FIRMWARE_VERSION_2_0_0_TRUSTED_KEY",
            key_id="dev-trusted",
            mutation="payload_bitflip",
            notes="Authenticated payload bit-flip after signing.",
        ),
        ImageSpec(
            name="v2.0.0-trusted-header-flip",
            version="2.0.0",
            payload_text="FIRMWARE_VERSION_2_0_0_TRUSTED_KEY",
            key_id="dev-trusted",
            mutation="header_version_flip",
            notes="Header version field mutation after signing.",
        ),
        ImageSpec(
            name="v2.0.0-trusted-truncated",
            version="2.0.0",
            payload_text="FIRMWARE_VERSION_2_0_0_TRUSTED_KEY",
            key_id="dev-trusted",
            mutation="truncate_tlv",
            notes="Truncated image with malformed TLV area.",
        ),
    ]


def algorithm_corpus_specs(key_type: str) -> list[ImageSpec]:
    """Return corpus variants signed with a specific algorithm.

    Names include the algorithm suffix so existing ECDSA-P256 scenarios keep
    working while new algorithm-specific scenarios can reference these images.
    """
    suffix = key_type.replace("-", "")
    return [
        ImageSpec(
            name=f"v1.0.0-trusted-{suffix}",
            version="1.0.0",
            payload_text="FIRMWARE_VERSION_1_0_0_TRUSTED_KEY",
            key_id="dev-trusted",
            key_type=key_type,
            notes=f"Baseline known-good primary image signed with {key_type}.",
        ),
        ImageSpec(
            name=f"v2.0.0-trusted-{suffix}",
            version="2.0.0",
            payload_text="FIRMWARE_VERSION_2_0_0_TRUSTED_KEY",
            key_id="dev-trusted",
            key_type=key_type,
            notes=f"Valid signed update image signed with {key_type}.",
        ),
        ImageSpec(
            name=f"v1.5.0-trusted-{suffix}",
            version="1.5.0",
            payload_text="FIRMWARE_VERSION_1_5_0_TRUSTED_KEY",
            key_id="dev-trusted",
            key_type=key_type,
            notes=f"Intermediate signed version signed with {key_type}.",
        ),
        ImageSpec(
            name=f"v2.0.0-untrusted-{suffix}",
            version="2.0.0",
            payload_text="FIRMWARE_VERSION_2_0_0_UNTRUSTED_KEY",
            key_id="dev-untrusted",
            key_type=key_type,
            notes=f"Signed with a key not in the trusted set using {key_type}.",
        ),
        ImageSpec(
            name=f"v2.0.0-trusted-payload-flip-{suffix}",
            version="2.0.0",
            payload_text="FIRMWARE_VERSION_2_0_0_TRUSTED_KEY",
            key_id="dev-trusted",
            key_type=key_type,
            mutation="payload_bitflip",
            notes=f"Authenticated payload bit-flip after signing with {key_type}.",
        ),
        ImageSpec(
            name=f"v2.0.0-trusted-header-flip-{suffix}",
            version="2.0.0",
            payload_text="FIRMWARE_VERSION_2_0_0_TRUSTED_KEY",
            key_id="dev-trusted",
            key_type=key_type,
            mutation="header_version_flip",
            notes=f"Header version field mutation after signing with {key_type}.",
        ),
        ImageSpec(
            name=f"v2.0.0-trusted-truncated-{suffix}",
            version="2.0.0",
            payload_text="FIRMWARE_VERSION_2_0_0_TRUSTED_KEY",
            key_id="dev-trusted",
            key_type=key_type,
            mutation="truncate_tlv",
            notes=f"Truncated image with malformed TLV area signed with {key_type}.",
        ),
    ]


def all_corpus_specs() -> list[ImageSpec]:
    """Return the full corpus across all supported algorithms."""
    specs: list[ImageSpec] = []
    specs.extend(default_corpus_specs())
    for key_type in ["rsa-2048", "rsa-3072", "ed25519"]:
        specs.extend(algorithm_corpus_specs(key_type))
    return specs
