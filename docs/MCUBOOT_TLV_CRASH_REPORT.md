# Malformed TLV verifier finding: reproduction status

## Status

The earlier crash claim has now been reproduced by the BootLab S04 run. With
the generated `v2.0.0-trusted-truncated.bin` fixture and pinned `imgtool 2.1.0`,
`imgtool verify` exits nonzero and raises `struct.error: unpack requires a
buffer of 4 bytes` while parsing the truncated TLV. S04 now records this exact
host-side verifier crash as its expected observation; other exceptions remain
errors. This is not a claim about MCUboot device behavior or an upstream
vulnerability determination.

The run used a separate patched copy of the pinned MCUboot revision
`229068b6d34688ddc7286c6d2056527b72f03cf4`. The test record captures the
verifier output, exit status, fixture hash, and package version.
Observed S04 truncated-file fixture SHA-256:
`0cfd2e85296a7005c8dcd8b274bbd61b1cb523a9a52b93671fe4da9d404804f3`.

## Minimal experiment

After the clean-checkout setup in [REPRODUCIBILITY.md](REPRODUCIBILITY.md),
generate a signed image, corrupt its TLV total length, and inspect the verifier
outcome. Save stdout, stderr, exit status, and the mutated image hash. A nonzero
exit is not enough to call this a clean rejection: a traceback or process crash
is a separate outcome.

```bash
bootlab build-corpus
imgtool getpub -k vendor/mcuboot/root-ec-p256.pem -e pem -o /tmp/dev-trusted-public.pem
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
imgtool verify -k /tmp/dev-trusted-public.pem /tmp/tlv-length-bad.bin
```

`dev-trusted` uses MCUboot's pinned simulator root key. `imgtool getpub`
derives a temporary public-only PEM for verification; a generated local private
key under `fixtures/keys/` is not required.

The command's result must be classified from the actual output. A traceback is
a host-tool crash, not a secure refusal. Do not describe this as a confirmed
upstream vulnerability or compliance failure without the upstream findings
process and assessment.

## Scope

S04 uses a truncated file fixture. It is not the malformed-length experiment
above, which mutates a specific TLV length. BootLab reports host-tool behavior
only; it does not claim device execution.
