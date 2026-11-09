"""Tests for the MCUboot image fuzz harness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bootlab.fuzz_image import (
    IMAGE_MAGIC,
    TLV_INFO_MAGIC,
    classify_outcome,
    mutate_header_magic,
    mutate_header_size,
    mutate_image_size,
    mutate_signature_bytes,
    mutate_tlv_lengths,
    mutate_tlv_magic,
    mutate_version_build,
    mutate_version_major,
    mutate_version_minor,
    mutate_version_revision,
    parse_image_info,
    run_verify,
)


@pytest.fixture
def synthetic_image() -> bytearray:
    """Return a minimal valid-looking MCUboot image with one ECDSA signature TLV."""
    # Header: 32 bytes, header_size=32, img_size=16.
    # 32-byte header + 16-byte image + 4-byte TLV info + 4-byte entry header + 4-byte payload = 60.
    data = bytearray(60)
    data[0:4] = IMAGE_MAGIC.to_bytes(4, "little")
    data[8:10] = (32).to_bytes(2, "little")  # header_size
    data[12:16] = (16).to_bytes(4, "little")  # img_size
    # TLV info at offset 48.
    data[48:50] = TLV_INFO_MAGIC.to_bytes(2, "little")
    # total TLV length = info header (4) + one entry (4 + 4) = 12.
    data[50:52] = (12).to_bytes(2, "little")
    # First (and only) TLV entry: type ECDSASIG (0x22), len 4.
    data[52] = 0x22
    data[54:56] = (4).to_bytes(2, "little")
    data[56:60] = b"\xab\xab\xab\xab"
    return data


def test_parse_image_info(synthetic_image: bytearray) -> None:
    info = parse_image_info(bytes(synthetic_image))
    assert info.header_size == 32
    assert info.img_size == 16
    assert info.tlv_offset == 48
    assert info.tlv_magic == TLV_INFO_MAGIC
    assert info.tlv_total == 12
    assert info.sig_tlv == (56, 4)


class TestMutators:
    """Each mutator must change the expected field/bytes."""

    @pytest.fixture
    def rng(self) -> object:
        import random

        return random.Random(42)

    @pytest.fixture
    def info(self, synthetic_image: bytearray) -> object:
        return parse_image_info(bytes(synthetic_image))

    def test_header_magic(self, synthetic_image: bytearray, info, rng) -> None:
        original = synthetic_image[0:4].copy()
        mutate_header_magic(synthetic_image, info, rng)
        assert synthetic_image[0:4] != original

    def test_header_size(self, synthetic_image: bytearray, info, rng) -> None:
        original = int.from_bytes(synthetic_image[8:10], "little")
        mutate_header_size(synthetic_image, info, rng)
        assert int.from_bytes(synthetic_image[8:10], "little") != original

    def test_version_major(self, synthetic_image: bytearray, info, rng) -> None:
        original = synthetic_image[20]
        mutate_version_major(synthetic_image, info, rng)
        assert synthetic_image[20] != original

    def test_version_minor(self, synthetic_image: bytearray, info, rng) -> None:
        original = synthetic_image[21]
        mutate_version_minor(synthetic_image, info, rng)
        assert synthetic_image[21] != original

    def test_version_revision(self, synthetic_image: bytearray, info, rng) -> None:
        original = synthetic_image[22:24].copy()
        mutate_version_revision(synthetic_image, info, rng)
        assert synthetic_image[22:24] != original

    def test_version_build(self, synthetic_image: bytearray, info, rng) -> None:
        original = synthetic_image[24:28].copy()
        mutate_version_build(synthetic_image, info, rng)
        assert synthetic_image[24:28] != original

    def test_image_size(self, synthetic_image: bytearray, info, rng) -> None:
        original = int.from_bytes(synthetic_image[12:16], "little")
        mutate_image_size(synthetic_image, info, rng)
        assert int.from_bytes(synthetic_image[12:16], "little") != original

    def test_tlv_magic(self, synthetic_image: bytearray, info, rng) -> None:
        mutate_tlv_magic(synthetic_image, info, rng)
        magic = int.from_bytes(synthetic_image[48:50], "little")
        assert magic != TLV_INFO_MAGIC

    def test_tlv_lengths(self, synthetic_image: bytearray, info, rng) -> None:
        original_total = int.from_bytes(synthetic_image[50:52], "little")
        original_entry_len = int.from_bytes(synthetic_image[54:56], "little")
        mutate_tlv_lengths(synthetic_image, info, rng)
        new_total = int.from_bytes(synthetic_image[50:52], "little")
        new_entry_len = int.from_bytes(synthetic_image[54:56], "little")
        assert new_total != original_total or new_entry_len != original_entry_len

    def test_signature_bytes(self, synthetic_image: bytearray, info, rng) -> None:
        original = synthetic_image[56:60].copy()
        mutate_signature_bytes(synthetic_image, info, rng)
        assert synthetic_image[56:60] != original


def test_classify_outcome() -> None:
    assert classify_outcome(0, "Image was correctly validated", "") == ("accepted", None)
    assert classify_outcome(1, "", "Image has an invalid hash") == ("rejected", None)
    assert classify_outcome(1, "Traceback (most recent call):", "") == ("crash", "Exception")
    assert classify_outcome(1, "", "") == ("crash", "unknown")


def test_run_verify_rejects_bad_image(tmp_path: Path) -> None:
    """Integration check that imgtool rejects a known-bad image."""
    bad_image = Path("artifacts/corpus/v2.0.0-trusted-payload-flip.bin")
    key = Path("fixtures/keys/dev-trusted-ecdsa-p256.pem")
    if not bad_image.exists() or not key.exists():
        pytest.skip("corpus or key not built")

    returncode, stdout, stderr = run_verify(bad_image, key)
    outcome, _crash_type = classify_outcome(returncode, stdout, stderr)
    assert outcome == "rejected"


def test_fuzz_harness_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run a few iterations with a mocked verifier to exercise orchestration."""
    from bootlab.fuzz_image import FuzzHarness

    base = tmp_path / "base.bin"
    key = tmp_path / "key.pem"
    base.write_bytes(b"\x00" * 64)
    key.write_text("dummy")

    harness = FuzzHarness(base_image=base, trusted_key=key, seed=0, iterations=5)

    # Force every mutation to look rejected so the campaign completes.
    monkeypatch.setattr(
        "bootlab.fuzz_image.run_verify",
        lambda _img, _key: (1, "", "Invalid hash"),
    )

    summary = harness.run()
    assert summary.total == 5
    assert summary.rejected == 5
    assert summary.accepted == 0
    assert summary.crashes == 0
    assert not summary.early_stop

    output = tmp_path / "results.json"
    harness.write_results(output)
    data = json.loads(output.read_text())
    assert data["summary"]["total"] == 5
    assert data["interesting"] == []


def test_fuzz_harness_stops_on_accept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Early stop is recorded when a mutation is unexpectedly accepted."""
    from bootlab.fuzz_image import FuzzHarness

    base = tmp_path / "base.bin"
    key = tmp_path / "key.pem"
    base.write_bytes(b"\x00" * 64)
    key.write_text("dummy")

    harness = FuzzHarness(base_image=base, trusted_key=key, seed=0, iterations=10)

    call_count = 0

    def fake_verify(_img: Path, _key: Path) -> tuple[int, str, str]:
        nonlocal call_count
        call_count += 1
        if call_count == 3:
            return 0, "Image was correctly validated", ""
        return 1, "", "Invalid hash"

    monkeypatch.setattr("bootlab.fuzz_image.run_verify", fake_verify)

    summary = harness.run()
    assert summary.early_stop
    assert summary.accepted == 1
    assert summary.total == 3
    assert len(harness.results) == 3
