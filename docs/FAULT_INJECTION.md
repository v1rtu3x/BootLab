# Deterministic fault injection

[Project overview](../README.md) · [Visual walkthrough](../WALKTHROUGH.md) · [Documentation map](README.md)

**Run a simulated upgrade with a selected flash-operation interruption, then inspect the resulting image and trailer checks.** The test and helper implementation live in the vendored MCUboot source.

## 01 / Implementation map

| Location | Entry point | Purpose |
|---|---|---|
| [sim/src/image.rs](../vendor/mcuboot/sim/src/image.rs) | `run_upgrade_with_fault_at(index, permanent)` | Calls the existing `try_upgrade(Some(index), permanent)` |
| Same file | `run_fault_campaign_check(index)` | Performs a permanent upgrade and checks final images/trailers; returns `true` on failure |
| [sim/tests/fault_campaign.rs](../vendor/mcuboot/sim/tests/fault_campaign.rs) | `fault_campaign_probe` | Prints operation counts for modeled configurations |
| Same file | `fault_campaign_upgrade` | Reads `FAULT_INDEX`, iterates modeled devices, and asserts the helper reports no failure |

For a swap upgrade, the helper checks the new image in primary, the old image in secondary, and final trailer flags. The old-secondary check is conditional on swap mode; trailer checks still apply to the other configured modes.

## 02 / Counter behavior

```mermaid
flowchart LR
    A["Clone flash state"] --> B["Run upgrade with counter"]
    B --> C{"Counter reaches zero?"}
    C -->|Yes| D["Stop before write / erase"]
    D --> E["Resume preserved flash"]
    C -->|No| F["Upgrade completes"]
    E --> G["Check images + trailers"]
    F --> G
    classDef step fill:#12354e,color:#f4f1e8,stroke:#e7b26b;
    class A,B,D,E,F,G step;
```

The C simulator decrements the counter **before** each counted write/erase and interrupts when the result becomes zero. Index `0` is a no-cut baseline; index `1` stops before the first counted operation. A requested index beyond the operation count also finishes without interruption. The public helper does not currently expose whether an interruption actually occurred.

## 03 / Reproduce the extension directly

From `BootLab/`, show successful-test output with `--nocapture`:

```bash
cargo test --manifest-path vendor/mcuboot/sim/Cargo.toml \
  --features sig-ecdsa --test fault_campaign \
  fault_campaign_probe -- --exact --nocapture

FAULT_INDEX=1 cargo test --manifest-path vendor/mcuboot/sim/Cargo.toml \
  --features sig-ecdsa --test fault_campaign \
  fault_campaign_upgrade -- --exact --nocapture
```

The probe prints one `FAULT_PROBE total_ops=...` line per exercised configuration. Do not assume one count applies to every layout.

The Python interface is:

```bash
bootlab fault-sweep --indices 0,1,50 --features sig-ecdsa
```

It writes sweep CSV/JSON plus per-index stdout/stderr under `evidence/fault_sweep/`. The adapter normally omits `--nocapture`, so the automatic probe can fail to see printed counts from passing tests. An explicit range or index list avoids that dependency.

## 04 / Interpret the result

A passing helper supports its final image/trailer assertions for the selected modeled configuration. It does not independently establish that the requested cut was reached, that the operation was a sector/trailer boundary, or that a physical device survives a power interruption.

Use [the fault-case walkthrough](../WALKTHROUGH.md#fault-cases) for scenario-specific counter values and [the evidence limitations](LIMITATIONS.md) for the scope of the resulting records.
