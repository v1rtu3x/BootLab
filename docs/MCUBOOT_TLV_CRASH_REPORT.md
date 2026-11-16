# MCUboot `imgtool verify` TLV length crash

## Summary

While building the BootLab fault corpus we discovered that MCUboot's `imgtool verify` command crashes with an unhandled `struct.error` when it encounters a firmware image whose TLV area contains a malformed `TLV_INFO_MAGIC` / `TLV_PROT_INFO_MAGIC` header or a TLV entry with an invalid length.

The crash is reproducible with a single byte change to the TLV length field of an otherwise valid signed image. Because the exception is not caught by the CLI, a malicious or corrupted image can terminate the verification tool rather than being rejected cleanly.

## Reproducer

A standalone reproducer, proposed patch, and visual explanation live in the external report folder:

```text
../mcuboot-imgtool-tlv-crash-report/
```

Files included:

- `reproducer.py` — generates a valid image, mutates the TLV length, and triggers `struct.error`
- `crash_repro.bin` — ready-to-use mutated image
- `proposed_fix.patch` — catch `struct.error` in `imgtool/image.py` and return a clean error
- `assets/tlv-crash-diagram.png` — static diagram of the malformed TLV layout
- `assets/tlv-crash-animation-*.gif` — animated walkthrough of the crash

## Impact

- **Availability:** an untrusted image can crash the verification tooling.
- **Security posture:** a verification failure must be a controlled rejection, not an unhandled exception.
- **Compliance:** clean error handling is expected by IEC 62443-4-2, ISO/SAE 21434, and the EU Cyber Resilience Act.

## Proposed fix

Wrap the TLV parsing loop in `imgtool/image.py` with a `try/except struct.error` block and emit a human-readable error such as:

```text
Error: image contains malformed TLV entry
```

See `../mcuboot-imgtool-tlv-crash-report/proposed_fix.patch` for the exact diff.

## References

- MCUboot: https://github.com/mcu-tools/mcuboot
- `imgtool/image.py`: https://github.com/mcu-tools/mcuboot/blob/main/scripts/imgtool/image.py
- BootLab test that exercises malformed TLVs: `scenarios/S04_truncated_tlv.yaml`
