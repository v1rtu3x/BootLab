"""Pure-Python fuzz harness for MCUboot signed images.

Mutates a known-good signed image and drives ``imgtool verify`` to check
whether each mutation is rejected, accepted, or crashes the verifier.
"""

from __future__ import annotations

import json
import random
import struct
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

# Offsets within the first IMAGE_HEADER_SIZE (32) bytes of an MCUboot image.
# These match the struct format used by imgtool.
OFF_MAGIC = 0
OFF_LOAD_ADDR = 4
OFF_HEADER_SIZE = 8
OFF_PROT_TLV_SIZE = 10
OFF_IMG_SIZE = 12
OFF_FLAGS = 16
OFF_VERSION_MAJOR = 20
OFF_VERSION_MINOR = 21
OFF_VERSION_REVISION = 22
OFF_VERSION_BUILD = 24

IMAGE_MAGIC = 0x96F3B83D
IMAGE_HEADER_SIZE = 32
TLV_INFO_MAGIC = 0x6907
TLV_PROT_INFO_MAGIC = 0x6908
TLV_INFO_SIZE = 4
TLV_SIZE = 4

SIG_TLV_TYPES = {0x20, 0x22, 0x23, 0x24, 0x25}

# Substrings that indicate imgtool rejected the image in the expected way.
REJECTED_HINTS = (
    "invalid",
    "Invalid",
    "No signature",
    "Wrong",
    "error",
    "Error",
    "cannot",
    "Cannot",
    "not found",
    "bad",
    "Bad",
    "failed",
    "Failed",
    "malformed",
    "Malformed",
    "does not match",
    "unable",
    "Unable",
    "was not",
)


@dataclass
class ImageInfo:
    data_len: int
    header_size: int
    img_size: int
    tlv_offset: int
    tlv_magic: int
    tlv_total: int
    sig_tlv: tuple[int, int] | None = None


@dataclass
class FuzzResult:
    iteration: int
    mutation: str
    outcome: str  # "rejected", "accepted", "crash"
    returncode: int
    stdout: str
    stderr: str
    reproducer_path: str | None = None
    crash_type: str | None = None


@dataclass
class FuzzSummary:
    seed: int
    iterations: int
    base_image: str
    trusted_key: str
    total: int
    rejected: int
    accepted: int
    crashes: int
    early_stop: bool
    stop_reason: str | None


def parse_image_info(data: bytes) -> ImageInfo:
    """Parse the header and locate the (unprotected) TLV area."""
    if len(data) < IMAGE_HEADER_SIZE:
        return ImageInfo(
            data_len=len(data),
            header_size=0,
            img_size=0,
            tlv_offset=0,
            tlv_magic=0,
            tlv_total=0,
            sig_tlv=None,
        )

    header_size = struct.unpack_from("<H", data, OFF_HEADER_SIZE)[0]
    img_size = struct.unpack_from("<I", data, OFF_IMG_SIZE)[0]
    tlv_offset = header_size + img_size
    tlv_magic = 0
    tlv_total = 0
    sig_tlv = None

    if tlv_offset + TLV_INFO_SIZE <= len(data):
        tlv_magic, tlv_total = struct.unpack_from("<HH", data, tlv_offset)
        if tlv_magic == TLV_PROT_INFO_MAGIC and tlv_offset + tlv_total + TLV_INFO_SIZE <= len(data):
            tlv_offset += tlv_total
            tlv_magic, tlv_total = struct.unpack_from("<HH", data, tlv_offset)

        if tlv_magic == TLV_INFO_MAGIC:
            sig_tlv = _find_signature_tlv(data, tlv_offset, tlv_total)

    return ImageInfo(
        data_len=len(data),
        header_size=header_size,
        img_size=img_size,
        tlv_offset=tlv_offset,
        tlv_magic=tlv_magic,
        tlv_total=tlv_total,
        sig_tlv=sig_tlv,
    )


def _find_signature_tlv(data: bytes, tlv_offset: int, tlv_total: int) -> tuple[int, int] | None:
    """Return (payload_start, payload_length) of the first signature TLV."""
    cursor = tlv_offset + TLV_INFO_SIZE
    end = tlv_offset + tlv_total
    while cursor + TLV_SIZE <= end and cursor + TLV_SIZE <= len(data):
        tlv_type, _reserved, tlv_len = struct.unpack_from("<BBH", data, cursor)
        payload_start = cursor + TLV_SIZE
        if tlv_type in SIG_TLV_TYPES:
            return payload_start, tlv_len
        cursor = payload_start + tlv_len
    return None


def _iter_tlv_entries(data: bytes, info: ImageInfo):
    """Yield (type, payload_start, payload_length) for each TLV entry."""
    if info.tlv_magic != TLV_INFO_MAGIC:
        return
    cursor = info.tlv_offset + TLV_INFO_SIZE
    end = info.tlv_offset + info.tlv_total
    while cursor + TLV_SIZE <= end and cursor + TLV_SIZE <= len(data):
        tlv_type, _reserved, tlv_len = struct.unpack_from("<BBH", data, cursor)
        yield tlv_type, cursor + TLV_SIZE, tlv_len
        cursor += TLV_SIZE + tlv_len


def _set_u16(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<H", data, offset, value & 0xFFFF)


def _set_u32(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<I", data, offset, value & 0xFFFFFFFF)


def _flip_byte(data: bytearray, offset: int, mask: int = 0x01) -> None:
    data[offset] ^= mask


def _rand_in_range(rng: random.Random, start: int, end: int) -> int:
    """Return a random int in [start, end) (empty range returns start)."""
    if end <= start:
        return start
    return rng.randrange(start, end)


# ---------------------------------------------------------------------------
# Structured mutators
# ---------------------------------------------------------------------------

def mutate_header_magic(data: bytearray, info: ImageInfo, rng: random.Random) -> str:
    """Corrupt the 4-byte image magic."""
    choices = [0x00000000, 0xDEADBEEF, IMAGE_MAGIC ^ 0xFFFFFFFF, (IMAGE_MAGIC + 1) & 0xFFFFFFFF]
    value = rng.choice(choices)
    _set_u32(data, OFF_MAGIC, value)
    return f"header_magic=0x{value:08x}"


def mutate_header_size(data: bytearray, info: ImageInfo, rng: random.Random) -> str:
    """Change header_size to an invalid but in-bounds value."""
    max_header = max(IMAGE_HEADER_SIZE, info.data_len - TLV_INFO_SIZE)
    candidates = [0, 1, IMAGE_HEADER_SIZE, info.header_size - 1, info.header_size + 1]
    candidates = [c for c in candidates if IMAGE_HEADER_SIZE <= c <= max_header or c == 0]
    if not candidates or rng.random() < 0.2:
        value = _rand_in_range(rng, IMAGE_HEADER_SIZE, max_header + 1)
    else:
        value = rng.choice(candidates)
    _set_u16(data, OFF_HEADER_SIZE, value)
    return f"header_size={value}"


def mutate_version_major(data: bytearray, info: ImageInfo, rng: random.Random) -> str:
    value = rng.randrange(256)
    data[OFF_VERSION_MAJOR] = value
    return f"version_major={value}"


def mutate_version_minor(data: bytearray, info: ImageInfo, rng: random.Random) -> str:
    value = rng.randrange(256)
    data[OFF_VERSION_MINOR] = value
    return f"version_minor={value}"


def mutate_version_revision(data: bytearray, info: ImageInfo, rng: random.Random) -> str:
    value = rng.randrange(0x10000)
    _set_u16(data, OFF_VERSION_REVISION, value)
    return f"version_revision={value}"


def mutate_version_build(data: bytearray, info: ImageInfo, rng: random.Random) -> str:
    value = rng.randrange(0x100000000)
    _set_u32(data, OFF_VERSION_BUILD, value)
    return f"version_build={value}"


def mutate_image_size(data: bytearray, info: ImageInfo, rng: random.Random) -> str:
    """Change image_size so the TLV area is mis-aligned but still in bounds."""
    max_img = max(0, info.data_len - info.header_size - TLV_INFO_SIZE)
    candidates = [0, max(0, info.img_size - 1), info.img_size + 1]
    candidates = [c for c in candidates if 0 <= c <= max_img]
    if rng.random() < 0.3 or not candidates:
        value = _rand_in_range(rng, 0, max_img + 1)
    else:
        value = rng.choice(candidates)
    _set_u32(data, OFF_IMG_SIZE, value)
    return f"image_size={value}"


def mutate_tlv_magic(data: bytearray, info: ImageInfo, rng: random.Random) -> str:
    """Corrupt the TLV info magic."""
    if info.tlv_offset + 2 <= info.data_len:
        value = rng.choice([0x0000, 0x6908, 0xDEAD, 0xFFFF, TLV_INFO_MAGIC ^ 0xFFFF])
        _set_u16(data, info.tlv_offset, value)
        return f"tlv_magic=0x{value:04x}"
    # Fallback if there is no TLV area.
    _flip_byte(data, IMAGE_HEADER_SIZE)
    return "tlv_magic_fallback_header_byte"


def mutate_tlv_lengths(data: bytearray, info: ImageInfo, rng: random.Random) -> str:
    """Mutate either the total TLV length or the length of the first entry."""
    entries = list(_iter_tlv_entries(data, info))

    # Determine whether we can truncate the total TLV area before the signature
    # entry header so the verifier no longer finds the signature.
    can_truncate_total = (
        info.tlv_offset + TLV_INFO_SIZE <= info.data_len
        and info.sig_tlv is not None
    )
    if can_truncate_total:
        sig_entry_offset = info.sig_tlv[0] - TLV_SIZE
        safe_max_total = sig_entry_offset - info.tlv_offset
        can_truncate_total = safe_max_total > TLV_INFO_SIZE

    if entries and (not can_truncate_total or rng.random() < 0.5):
        # Mutate the length of the first TLV entry.
        tlv_type, payload_start, tlv_len = entries[0]
        max_len = max(0, info.data_len - payload_start)
        candidates = [0, 1, max(0, tlv_len - 1), min(tlv_len + 1, max_len)]
        value = rng.choice(candidates) if rng.random() < 0.7 else _rand_in_range(rng, 0, max_len + 1)
        entry_offset = payload_start - TLV_SIZE
        _set_u16(data, entry_offset + 2, value)
        return f"tlv_entry_type=0x{tlv_type:02x}_length={value}"

    if can_truncate_total:
        sig_entry_offset = info.sig_tlv[0] - TLV_SIZE
        safe_max_total = sig_entry_offset - info.tlv_offset
        value = rng.choice([TLV_INFO_SIZE, safe_max_total]) if rng.random() < 0.5 else _rand_in_range(
            rng, TLV_INFO_SIZE, safe_max_total + 1
        )
        _set_u16(data, info.tlv_offset + 2, value)
        return f"tlv_total_length={value}"

    _flip_byte(data, IMAGE_HEADER_SIZE)
    return "tlv_length_fallback_header_byte"


def mutate_signature_bytes(data: bytearray, info: ImageInfo, rng: random.Random) -> str:
    """Flip or zero bytes inside the signature TLV payload."""
    if info.sig_tlv is not None:
        start, length = info.sig_tlv
        end = min(start + length, info.data_len)
        if end > start:
            if rng.random() < 0.5:
                idx = rng.randrange(start, end)
                _flip_byte(data, idx, rng.randrange(1, 256))
                return f"signature_byte_flip@{idx - start}"
            for idx in range(start, end):
                data[idx] = 0
            return "signature_zeroed"

    # Fallback: flip a byte near the end of the image.
    idx = _rand_in_range(rng, max(IMAGE_HEADER_SIZE, info.data_len // 2), info.data_len)
    if idx < info.data_len:
        _flip_byte(data, idx)
        return f"signature_fallback_byte@{idx}"
    return "no_op"


MUTATORS: list[Callable[[bytearray, ImageInfo, random.Random], str]] = [
    mutate_header_magic,
    mutate_header_size,
    mutate_version_major,
    mutate_version_minor,
    mutate_version_revision,
    mutate_version_build,
    mutate_image_size,
    mutate_tlv_magic,
    mutate_tlv_lengths,
    mutate_signature_bytes,
]


# ---------------------------------------------------------------------------
# Verification and classification
# ---------------------------------------------------------------------------

def run_verify(image_path: Path, key_path: Path) -> tuple[int, str, str]:
    """Run ``imgtool verify`` and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        ["imgtool", "verify", "-k", str(key_path), str(image_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode, result.stdout, result.stderr


def classify_outcome(returncode: int, stdout: str, stderr: str) -> tuple[str, str | None]:
    """Classify the verifier result as accepted, rejected, or crash.

    Returns a tuple of (outcome, crash_type). crash_type is a short label such
    as "struct.error" or "ValueError" when outcome is "crash".
    """
    combined = stdout + stderr
    if returncode == 0:
        return "accepted", None

    if "Traceback" in combined or "Exception" in combined:
        crash_type = None
        for line in combined.splitlines():
            if line.startswith("struct.error"):
                crash_type = "struct.error"
                break
            if line.startswith("ValueError"):
                crash_type = "ValueError"
                break
            if line.startswith("IndexError"):
                crash_type = "IndexError"
                break
            if line.startswith("KeyError"):
                crash_type = "KeyError"
                break
        return "crash", crash_type or "Exception"

    if any(hint in combined for hint in REJECTED_HINTS):
        return "rejected", None

    return "crash", "unknown"


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

class FuzzHarness:
    """Structured mutation fuzzer for MCUboot signed images."""

    def __init__(
        self,
        base_image: Path,
        trusted_key: Path,
        seed: int = 0,
        iterations: int = 1000,
        reproducers_dir: Path | None = None,
    ) -> None:
        self.base_image = Path(base_image)
        self.trusted_key = Path(trusted_key)
        self.seed = seed
        self.iterations = iterations
        self.reproducers_dir = reproducers_dir
        self.rng = random.Random(seed)
        self.base_data = self.base_image.read_bytes()
        self.info = parse_image_info(self.base_data)
        self.results: list[FuzzResult] = []
        self.summary: FuzzSummary | None = None

    def _save_reproducer(self, iteration: int, outcome: str, crash_type: str | None, data: bytes) -> Path | None:
        """Save an interesting mutated image to disk for later analysis."""
        if self.reproducers_dir is None:
            return None
        self.reproducers_dir.mkdir(parents=True, exist_ok=True)
        label = crash_type or outcome
        path = self.reproducers_dir / f"repro-{iteration:05d}-{label}.bin"
        path.write_bytes(data)
        return path

    def run(self) -> FuzzSummary:
        """Run the fuzz campaign and return a summary."""
        total = rejected = accepted = crashes = 0
        early_stop = False
        stop_reason: str | None = None

        for iteration in range(1, self.iterations + 1):
            data = bytearray(self.base_data)
            mutator = self.rng.choice(MUTATORS)
            details = mutator(data, self.info, self.rng)

            with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
                tmp_path = Path(tmp.name)
                tmp.write(data)

            try:
                returncode, stdout, stderr = run_verify(tmp_path, self.trusted_key)
            finally:
                tmp_path.unlink(missing_ok=True)

            outcome, crash_type = classify_outcome(returncode, stdout, stderr)
            total += 1

            if outcome == "rejected":
                rejected += 1
            elif outcome == "accepted":
                accepted += 1
            else:
                crashes += 1

            reproducer_path: Path | None = None
            if outcome in ("accepted", "crash"):
                reproducer_path = self._save_reproducer(iteration, outcome, crash_type, bytes(data))

            result = FuzzResult(
                iteration=iteration,
                mutation=f"{mutator.__name__}({details})",
                outcome=outcome,
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
                reproducer_path=str(reproducer_path) if reproducer_path else None,
                crash_type=crash_type,
            )
            self.results.append(result)

            if outcome in ("accepted", "crash"):
                early_stop = True
                stop_reason = f"{outcome} ({crash_type or 'n/a'}) at iteration {iteration}"
                break

        self.summary = FuzzSummary(
            seed=self.seed,
            iterations=self.iterations,
            base_image=str(self.base_image),
            trusted_key=str(self.trusted_key),
            total=total,
            rejected=rejected,
            accepted=accepted,
            crashes=crashes,
            early_stop=early_stop,
            stop_reason=stop_reason,
        )
        return self.summary

    def write_results(self, output_path: Path) -> Path:
        """Write the JSON report including summary and interesting findings."""
        if self.summary is None:
            raise RuntimeError("Run the harness before writing results")

        interesting = [asdict(r) for r in self.results if r.outcome in ("accepted", "crash")]
        report = {
            "summary": asdict(self.summary),
            "interesting": interesting,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2) + "\n")
        return output_path
