# Troubleshooting a BootLab run

[Project overview](../README.md) · [Visual walkthrough](../WALKTHROUGH.md) · [Documentation map](README.md)

**Start with the layer that failed: setup, backend execution, oracle interpretation, or evidence presentation.** Scenario runs use unique run IDs, so a new run does not overwrite older records.

## 01 / Locate the problem

```mermaid
flowchart TD
    A["Command failed or result is surprising"] --> B{"CLI starts?"}
    B -->|No| S["Environment / installation / working directory"]
    B -->|Yes| C{"Backend ran?"}
    C -->|No| T["Tools / vendor sources / corpus / build errors"]
    C -->|Yes| D["Read record details and both logs"]
    D --> E["Compare actual test with the expected property"]
    classDef step fill:#12354e,color:#f4f1e8,stroke:#e7b26b;
    class A,S,T,D,E step;
```

## 02 / Environment and input problems

Commands below assume the `BootLab/` directory.

| Symptom | Likely cause | Next action |
|---|---|---|
| `bootlab: command not found` | Virtual environment inactive or package not installed | Activate `.venv/bin/activate`; install with `python -m pip install -e ".[dev]"` |
| No scenarios found | Wrong workspace or scenario directory | Check `pwd` and use the project root; `--workspace` is a global CLI option before the subcommand |
| `Image not found` | Corpus missing or wrong filename in the case | Run `bootlab build-corpus`; compare `backend_args.image` with the manifest |
| `imgtool` missing | Vendored signing tool not installed in this environment | Run `python -m pip install ./vendor/mcuboot/scripts` |
| `cargo` missing / native build failure | Rust or C build prerequisites unavailable | Check versions and compiler output; use [the toolchain guide](TOOLCHAIN.md) or [Docker](DOCKER.md) |
| Missing vendored files | Incomplete source checkout/archive | For a Git checkout, initialize dependencies with `git submodule update --init --recursive`; otherwise obtain the complete source tree |
| `mcuboot_commit: unknown` | Vendor Git metadata absent | Retain the source revision and local patch separately; do not invent a commit value |
| Baseline fails because `FAULT_INDEX` is absent | Unfiltered Cargo tests include the local fault fixture | Use `FAULT_INDEX=0 bootlab baseline` for a no-cut fixture input |

Check the installed CLI without running experiments:

```bash
bootlab --help
bootlab run-matrix --help
bootlab fault-sweep --help
bootlab fuzz-image --help
```

`fuzz-image` accepts `--iterations`, not `--max-runs`. The [reproducibility guide](REPRODUCIBILITY.md) contains the full setup sequence.

## 03 / A result passed, but the claim looks wrong

| Observation | Explanation | Inspect |
|---|---|---|
| Rejection case reports `ERROR` | Traceback, invocation issue, timeout, or ambiguous verifier output is not a clean rejection | `stderr_path` in the run record and [findings policy](FINDINGS_POLICY.md) |
| Different IDs produce similar simulator output | Several cases use the same Cargo filter | `backend_args.cargo_test` and the upstream test body |
| Direct image is rejected before Cargo runs | Image format/version, signing algorithm, trust declaration, or profile layout does not match | Error record and scenario profile/input files |
| V01 refuses an older candidate but V02 accepts it | These direct cases differ only in the downgrade-prevention feature | Compare injected hashes and structured selection records |
| Fault index zero produces no reset | Index zero is the no-cut baseline | [Counter explanation](FAULT_INJECTION.md#02--counter-behavior) |
| Positive fault index is not reached | That configuration has fewer modeled operations or did not reach the requested count | `NOT_REACHED` row and configuration-specific operation count |
| Fault sweep says missing/malformed result | Expected config identity/count set did not match test markers | Per-index stdout/stderr in the run archive |
| Profile configuration does not match a direct scenario | The direct backend supports only its validated nrf52840 layout and feature set | Profile contents and scenario `cargo_features` |
| “Rotation” case has no device activity | K01–K03 select one host verification key | [Key-case scope](../WALKTHROUGH.md#key-cases) |

Do not fix a surprising result by weakening its expectation. First establish which input, test body, and assertion actually ran.

## 04 / Fault sweep output is incomplete

The adapter requires one exact probe test, unique operation counts for every modeled configuration, and one complete result for each configuration at each requested index. Missing, malformed, duplicate, inconsistent, or unreachable results fail the sweep.

Run a bounded set of indices:

```bash
bootlab fault-sweep --start 0 --end 10 --features sig-ecdsa
```

The default sweep uses the common reachable range across configurations. Explicit out-of-range requests remain `NOT_REACHED` failures. For human inspection of probe output, use the direct-Cargo command in [the extension guide](FAULT_INJECTION.md#03--reproduce-the-extension-directly). Counts are not semantic sector/trailer labels.

## 05 / Evidence and presentation problems

| Symptom | Explanation / next action |
|---|---|
| Single case ran but matrix report is unchanged | `run-scenario` writes that case's files; `run-matrix` generates the aggregate report |
| Old and new results appear together | Select the intended `--run-id`; only `--all-runs` aggregates history |
| Comparison command exits with failure | At least one selected case failed or was skipped; read its comparison table |
| Record signature no longer verifies | Check whether a rerun or edit changed the JSON, whether the signature exists, and whether the local signer key matches |
| Container results disappeared | A `--rm` container needs an evidence bind mount for host retention; see [Docker](DOCKER.md#03--keep-results-on-the-host) |
| PNG/GIF missing | Install Pillow in the rendering environment and run `./scripts/generate-animations.sh` |
| README does not switch theme/motion | The viewer may not preserve `<picture>` media queries; use explicit still-image links or the local gallery |
| Animation text is small on a phone | Open the linked full-size still; the header also has a dedicated narrow layout |

## 06 / Prepare a useful issue or investigation note

Include the exact command and working directory, scenario ID, effective backend arguments, tool versions, vendor revision/local patch, and the relevant record and logs. For malformed-image cases, preserve the exact reproducer bytes and their hash. Describe expected and observed behavior separately, and state whether the observation came from `imgtool`, the simulator, or a physical board.

Use [the findings policy](FINDINGS_POLICY.md) to classify the observation and [the retention checklist](REPRODUCIBILITY.md#04--retain-a-reviewable-run) to keep the experiment reviewable.
