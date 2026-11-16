# Evidence boundaries and limitations

[Project overview](../README.md) · [Visual walkthrough](../WALKTHROUGH.md) · [Documentation map](README.md)

**BootLab produces host verification results and modeled MCUboot runtime results. It does not currently produce board-level secure-boot evidence.**

## 01 / Two evidence lanes

| Lane | What is executed | What a passing case supports | What it does not establish |
|---|---|---|---|
| `imgtool_verify` | `imgtool verify` against a generated corpus file and selected key | The verifier's return code matches the case expectation | Device execution, flash behavior, or deployed trust-store changes |
| `mcuboot_sim` | A named Rust simulator test with explicit Cargo features | The selected test reports at least one pass and no failures, subject to the oracle | Direct execution of BootLab's corpus image or a measured boot-version banner |

The simulator creates its own images. The YAML `primary`, `secondary`, `operation`, and expected-version fields describe scenario intent; the adapter does not inject those corpus files or independently measure every declared property. Its actual inputs are `backend_args` in [the scenarios](../scenarios/).

## 02 / Known gaps that affect interpretation

| Area | Current limit | Read the result as |
|---|---|---|
| Overwrite baseline proxies | P01O's `basic_revert` and P02O's main `norevert` helper return early in overwrite mode. The latter filter also selects `norevert_newimage`. | Cargo success alone does not demonstrate the intended boot/copy |
| V01 downgrade prevention | The upstream helper checks that primary remains unchanged, but `outcome_in` allows refusal or a new authenticated image and the wrapper's strict-refusal branch is not selected. | Upstream refusal assertions, without a direct observation of BootLab's declared older corpus image |
| V02 disabled control and mode label | The profile says swap, effective features select overwrite, and the helper returns early without downgrade prevention. V01 also executes overwrite-only. | A feature-disabled configuration check, not demonstrated downgrade acceptance |
| F01/F02/F03/F04 | Indices 0, 1, 50, and 570 are operation-counter inputs. Semantic labels such as “sector boundary” and “trailer write” are not instrumented. | Numeric fault-campaign checks, not confirmed events at those exact stages |
| F04 reachability | The helper checks final state without recording whether the requested interruption was reached. An index beyond the operation count can complete without interruption. | A passing final-state check alone does not prove a reset at index 570 |
| K01–K03 key lifecycle | Each command verifies against one explicitly selected rotation key. No device trust store is updated. | Host verification examples for matching and nonmatching keys |
| Rejection classification | The matrix's `imgtool` oracle treats a nonzero exit as rejection. A parser traceback can therefore satisfy a negative case. | Inspect stderr; a clean refusal and a verifier crash have different meanings |

## 03 / Coverage boundaries

- Runtime signature scenarios cover **ECDSA-P256, RSA-2048, and Ed25519**. The corpus also includes **RSA-3072**, but no dedicated RSA-3072 runtime scenario is in the current matrix.
- Profile files describe reference layouts; they are not automatically loaded to configure the simulator. Upstream tests may iterate multiple modeled devices.
- Logical flash-operation interruption does not measure physical brownouts, clock/voltage glitches, instruction skipping, timing leakage, or power leakage.
- Swap and overwrite modes have different recovery semantics. The overwrite cases do not establish swap-style trial, confirm, or revert behavior.
- OTA transport, update manifests, cloud authorization, secure-element provisioning, and production key custody are outside the implemented lanes.
- [Zephyr integration](ZEPHYR_INTEGRATION.md) remains an optional, incomplete path to hardware evidence.

## 04 / Evidence and repeatability

Development keys are generated locally. Fresh keys and signing randomness can change corpus bytes and hashes across clean runs. Retain the manifest and the specific inputs used for a result.

Evidence signing is optional. It authenticates the canonical JSON record using a local development signer; referenced stdout/stderr files are not hashed into that signature. A commit identifier also does not capture local vendor modifications or complete toolchain provenance.

Use [the retention checklist](REPRODUCIBILITY.md#04--retain-a-reviewable-run) to preserve the evidence supporting a claim.
