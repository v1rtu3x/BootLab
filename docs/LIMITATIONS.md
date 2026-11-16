# Evidence boundaries and limitations

[Project overview](../README.md) · [Visual walkthrough](../WALKTHROUGH.md) · [Documentation map](README.md)

**BootLab produces host verification results and modeled MCUboot runtime results. It does not currently produce board-level secure-boot evidence.**

## 01 / Two evidence lanes

| Lane | What is executed | What a passing case supports | What it does not establish |
|---|---|---|---|
| `imgtool_verify` | `imgtool verify` against a generated corpus file and selected key | A zero exit means accepted; a recognized validation error means rejected | Device execution, flash behavior, or deployed trust-store changes |
| `mcuboot_sim` direct | `bootlab_direct_image` injects corpus bytes into modeled nrf52840 primary and candidate slots | Input hashes, selected bootloader image/version, and final modeled recovery state match assertions | Real application execution, physical flash, or hardware behavior |
| `mcuboot_sim` proxy | A named exact upstream Rust simulator test with explicit Cargo features | The selected test identity and nonzero executed-test count, with no test failures | Behavior for BootLab corpus bytes; proxy tests use upstream-generated fixtures |

Direct cases validate image layout, header, version, signature algorithm, declared trust result, and root key before injection. Rust-reported hashes are checked against the exact host-side input bytes. Other simulator cases still create their own images. Scenario fields are executable only where validated and consumed by the backend.

## 02 / Known gaps that affect interpretation

| Area | Current limit | Read the result as |
|---|---|---|
| Direct image scope | D01–D03, V01/V02, and D06 inject declared corpus files and report selected image/version. | They establish bootloader image selection in the model, not application execution |
| Remaining proxy cases | P01–P04, A01–A04, A09–A10, S05–S06 and other helper tests use upstream-created fixtures. | Interpret results as upstream test assertions; they do not cover BootLab corpus bytes |
| Fault campaigns | Records include each modeled configuration, requested index, reachability, operation count, recovery outcome, and image/trailer checks. | Exact operation type and address are not instrumented; F03/F04 remain numeric indices, not semantic sector/trailer events |
| K01–K03 key lifecycle | Each command verifies against one explicitly selected rotation key. No device trust store is updated. | Host verification examples for matching and nonmatching keys |
| Rejection classification | Only recognized image-validation errors count as negative rejection. Tracebacks, invocation errors, missing dependencies, timeouts, and ambiguous output do not pass. | Inspect structured backend outcome and captured stderr |

## 03 / Coverage boundaries

- Runtime signature scenarios cover **ECDSA-P256, RSA-2048, and Ed25519**. The corpus also includes **RSA-3072**, but no dedicated RSA-3072 runtime scenario is in the current matrix.
- Direct profiles are checked against the nrf52840 model layout. Proxy tests can iterate multiple upstream modeled devices; profile labels do not reconfigure those fixtures.
- Logical flash-operation interruption does not measure physical brownouts, clock/voltage glitches, instruction skipping, timing leakage, or power leakage.
- Swap and overwrite modes have different recovery semantics. The overwrite cases do not establish swap-style trial, confirm, or revert behavior.
- OTA transport, update manifests, cloud authorization, secure-element provisioning, and production key custody are outside the implemented lanes.
- [Zephyr integration](ZEPHYR_INTEGRATION.md) remains an optional, incomplete path to hardware evidence.

## 04 / Evidence and repeatability

Development keys are generated locally. Fresh keys and signing randomness can change corpus bytes and hashes across clean runs. Retain the manifest and the specific inputs used for a result.

Evidence signing is optional. It authenticates canonical record JSON, including hashes for logs and archived immutable inputs. Verification accepts public material and checks signatures and artifacts. Exported bundles include the public signer key and can be verified elsewhere. A valid signature establishes evidence integrity, not experiment correctness. Provenance records interpreter, package/tool versions, source state, and patch identity; this is not complete toolchain attestation.

Use [the retention checklist](REPRODUCIBILITY.md#04--retain-a-reviewable-run) to preserve the evidence supporting a claim.
