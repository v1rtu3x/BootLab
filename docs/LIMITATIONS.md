# Evidence boundaries and limitations

[Project overview](../README.md) · [Visual walkthrough](../WALKTHROUGH.md) · [Documentation map](README.md)

**BootLab produces host verification results and modeled MCUboot runtime results. It does not currently produce board-level secure-boot evidence.**

## 01 / Two evidence lanes

| Lane | What is executed | What a passing case supports | What it does not establish |
|---|---|---|---|
| `imgtool_verify` | `imgtool verify` against a generated corpus file and selected key | A zero exit means accepted; a recognized validation error means rejected | Device execution, flash behavior, or deployed trust-store changes |
| `mcuboot_sim` | A named exact Rust simulator test with explicit Cargo features | The selected test identity and a nonzero executed-test count are present, with no test failures | Direct execution of BootLab's corpus image or a measured boot-version banner |

The simulator creates its own images. The YAML `primary`, `secondary`, `operation`, and expected-version fields describe scenario intent; the adapter does not inject those corpus files or independently measure every declared property. Its actual inputs are `backend_args` in [the scenarios](../scenarios/).

## 02 / Known gaps that affect interpretation

| Area | Current limit | Read the result as |
|---|---|---|
| Overwrite baseline proxies | P01O's `basic_revert` and P02O's main `norevert` helper return early in overwrite mode. The latter filter also selects `norevert_newimage`. | Cargo success alone does not demonstrate the intended boot/copy |
| V01/V02 downgrade policy | V01's enabled upstream helper asserts the simulator's internal primary image remains unchanged; V02's disabled helper returns early. Neither injects BootLab's declared corpus pair. | V01 is labeled an upstream proxy refusal; V02 is `SKIP` and does not establish acceptance |
| Fault campaigns | Records include device name, alignment, erased value, requested index, reached flag, operation count, recovery outcome, and final image/trailer validity checks. | Exact write/erase type and address are not instrumented; F03/F04 remain numeric indices, not semantic sector/trailer events |
| K01–K03 key lifecycle | Each command verifies against one explicitly selected rotation key. No device trust store is updated. | Host verification examples for matching and nonmatching keys |
| Rejection classification | Only recognized image-validation errors count as negative rejection. Tracebacks, invocation errors, missing dependencies, timeouts, and ambiguous output do not pass. | Inspect structured backend outcome and captured stderr |

## 03 / Coverage boundaries

- Runtime signature scenarios cover **ECDSA-P256, RSA-2048, and Ed25519**. The corpus also includes **RSA-3072**, but no dedicated RSA-3072 runtime scenario is in the current matrix.
- Profile files describe reference layouts; they are not automatically loaded to configure the simulator. Upstream tests may iterate multiple modeled devices.
- Logical flash-operation interruption does not measure physical brownouts, clock/voltage glitches, instruction skipping, timing leakage, or power leakage.
- Swap and overwrite modes have different recovery semantics. The overwrite cases do not establish swap-style trial, confirm, or revert behavior.
- OTA transport, update manifests, cloud authorization, secure-element provisioning, and production key custody are outside the implemented lanes.
- [Zephyr integration](ZEPHYR_INTEGRATION.md) remains an optional, incomplete path to hardware evidence.

## 04 / Evidence and repeatability

Development keys are generated locally. Fresh keys and signing randomness can change corpus bytes and hashes across clean runs. Retain the manifest and the specific inputs used for a result.

Evidence signing is optional. It authenticates canonical record JSON, including hashes for referenced logs and available inputs. Verification accepts a public key and checks referenced hashes. A valid signature establishes evidence integrity, not experiment correctness. Local dirty state and the patch hash are recorded; this is not complete toolchain attestation.

Use [the retention checklist](REPRODUCIBILITY.md#04--retain-a-reviewable-run) to preserve the evidence supporting a claim.
