# Malformed TLV verifier finding: reproduction status

## Status

The previous version of this note claimed a `struct.error` crash and linked to
an external report directory that is not part of this repository. That crash
claim has **not been reproduced or verified in this checkout**, and no upstream
fix/report status is asserted here.

The repository pins MCUboot submodule revision
`229068b6d34688ddc7286c6d2056527b72f03cf4`. The local environment used for
this documentation change did not have `imgtool` installed and could not
resolve package-index DNS, so there is no observed failure result to report.

## Minimal experiment

After the clean-checkout setup in [REPRODUCIBILITY.md](REPRODUCIBILITY.md),
generate a signed image, corrupt its TLV total length, and inspect the verifier
outcome. Save stdout, stderr, exit status, and the mutated image hash. A nonzero
exit is not enough to call this a clean rejection: a traceback or process crash
is a separate outcome.

```bash
bootlab build-corpus
python3 - artifacts/corpus/v2.0.0-trusted.signed.bin /tmp/tlv-length-bad.bin <<'PY'
import struct
import sys

source, destination = sys.argv[1:]
data = bytearray(open(source, "rb").read())
header_size = struct.unpack_from("<H", data, 8)[0]
image_size = struct.unpack_from("<I", data, 12)[0]
tlv = header_size + image_size
magic, total = struct.unpack_from("<HH", data, tlv)
if magic == 0x6908:  # protected TLV block; advance to ordinary TLVs
    tlv += total
    magic, total = struct.unpack_from("<HH", data, tlv)
if magic != 0x6907:
    raise SystemExit(f"unexpected TLV info magic: 0x{magic:04x}")
struct.pack_into("<H", data, tlv + 2, 0xffff)
open(destination, "wb").write(data)
PY
imgtool verify -k fixtures/keys/dev-trusted-ecdsa-p256.pem /tmp/tlv-length-bad.bin
```

The command's result must be classified from the actual output. If it raises an
uncaught exception, preserve the reproducer and report it against the pinned
revision using the project's findings process. Do not describe it as a
confirmed upstream vulnerability or compliance failure without that evidence.

## Scope

The existing `S04_truncated_tlv.yaml` uses a truncated file fixture. It is not
this malformed-length experiment and does not establish parser-crash behavior.
BootLab reports host-tool behavior only; it does not claim device execution.
