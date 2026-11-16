# Toolchain and provenance

[Project overview](../README.md) · [Visual walkthrough](../WALKTHROUGH.md) · [Documentation map](README.md)

**Record the environment used for each run.** BootLab pins its Python package baseline and Rust toolchain; platform packages and MCUboot's imgtool still follow the pinned source and host image.

## 01 / Declared baseline

| Item | Repository declaration |
|---|---|
| MCUboot upstream | [mcu-tools/mcuboot](https://github.com/mcu-tools/mcuboot) |
| Reference commit in profiles | `229068b6d34688ddc7286c6d2056527b72f03cf4` |
| BootLab package | `0.1.0` in [pyproject.toml](../pyproject.toml) |
| Python | `>=3.10`; dependencies pinned in `pyproject.toml`; Docker uses Python 3.11 |
| Rust | `1.97.1` from `rust-toolchain.toml` and the Docker build |
| Simulator extension | Patched helpers and fault tests in `vendor/mcuboot-patches/`; apply with `./scripts/apply-mcuboot-patches.sh` after submodule init; see [fault-injection reference](FAULT_INJECTION.md) |

The evidence writer records the vendor Git HEAD when available, or `unknown` otherwise. That identifier does not capture uncommitted vendor changes, submodule state, compiler flags, or the complete Python environment.

## 02 / Capture your environment

Run these from `BootLab/` with its virtual environment active and retain the output alongside the evidence:

```bash
python --version
python -m pip --version
python -m pip freeze
rustc --version
cargo --version
git --version
git -C vendor/mcuboot rev-parse HEAD
git -C vendor/mcuboot status --short
```

Use [the reproducibility guide](REPRODUCIBILITY.md) for installation. Native simulator builds also need a C compiler and the supporting build tools; the [Dockerfile](../Dockerfile) lists the container's installed packages.

## 03 / Configuration is explicit

| Field | Reference profile value |
|---|---|
| Layout label | nRF52840-style flash map |
| Upgrade mode | Swap with scratch; overwrite variants are separate |
| Primary slot | Base `0x008000`, size `0x034000` |
| Secondary slot | Base `0x03c000`, size `0x034000` |
| Scratch | Base `0x070000`, size `0x00d000` for swap profiles |
| Image header / alignment | `0x200` bytes / 8 bytes |
| Runtime signature lanes | ECDSA-P256, RSA-2048, Ed25519 |
| Additional corpus algorithm | RSA-3072 |

These are profile declarations, not hardware measurements. Direct scenarios validate the supported nrf52840 layout and reconcile Cargo features, signature algorithm, overwrite mode, downgrade mode, and slot geometry with their profile before running. Proxy tests use upstream fixtures and are not dynamically reconfigured from the full profile.

## 04 / Baseline logs

`bootlab run-matrix` writes per-case evidence and the matrix report. It does **not** create `evidence/baseline_log.txt`.

The separate `bootlab baseline` command runs unfiltered `cargo test` and captures that log. The local fault test requires `FAULT_INDEX`, so an example invocation is:

```bash
FAULT_INDEX=0 bootlab baseline
```

This uses Cargo's default features and is distinct from the signature-feature matrix. Record its actual exit status and test count; do not reuse a historical “25 passed” banner as evidence for a new checkout.
