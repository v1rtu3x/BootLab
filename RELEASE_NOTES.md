# Release notes

## BootLab completion pass

- Added a committed MCUboot simulator extension that consumes declared corpus image bytes and emits structured image-selection and modeled-recovery observations.
- Added direct cases for authenticated upgrade, payload tampering, untrusted signing keys, downgrade prevention with a paired identical-image control, and reached interruption recovery.
- Made fault campaign results complete and per-configuration, with strict test identity, marker consistency, reachability, and recovery checks. The default sweep uses the common reachable index range.
- Made scenario/profile validation reject empty inventories, unsupported fields, mismatched features/layouts, and inconsistent fault declarations.
- Made evidence run-scoped and portable, retaining immutable tested inputs and supporting public-key verification of exported archives.
- Hardened source-only MCUboot patch application, provenance collection, key handling, and CI setup. Added pinned Python dependencies and Rust toolchain, plus formatting checks.
- Added regression tests and a reproducible direct-simulator demo. See [the sanitized direct-run sample](docs/examples/sample-direct-run-report.md).

## Remaining limits

- Simulator interruption is logical; there is no physical power-cut or hardware testing.
- Direct observations establish bootloader image selection, not application execution.
- The simulator reports numeric operation indices rather than flash address/operation semantics.
- Several algorithm and legacy scenario rows still exercise upstream fixtures or host-side image verification rather than injecting direct corpus images.
- The reproduced S04 `struct.error` is an `imgtool 2.1.0` host-verifier crash on the truncated TLV fixture. It is not a device result or an upstream vulnerability determination.
- Docker image build and container smoke execution are configured in CI but were not locally verified because this environment cannot connect to the Docker daemon.
