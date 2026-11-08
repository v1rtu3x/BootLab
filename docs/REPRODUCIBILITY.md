# Reproduce and retain a run

[Project overview](../README.md) · [Visual walkthrough](../WALKTHROUGH.md) · [Documentation map](README.md)

**Run from `BootLab/`, retain the actual records, and compare expectations with results.** There are currently **33 scenario YAML files**. A complete run should execute all 33; this guide does not promise that every environment will pass.

## 01 / Prepare the workspace

Use Python 3.10+, a Rust toolchain, Git, and native C build prerequisites for the simulator. Linux is the reference host; [Docker](DOCKER.md) supplies an alternative environment.

From the project directory in an existing checkout:

```bash
git submodule update --init --recursive
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pip install ./vendor/mcuboot/scripts
```

Confirm `vendor/mcuboot/sim/Cargo.toml` exists. The local fault extension described in [FAULT_INJECTION.md](FAULT_INJECTION.md) must also be present for the F and algorithm-fault cases.

If you received a source archive without `.git` metadata, the Git command above does not apply. Use a complete vendored source tree and record its supplied revision separately. The evidence writer may report `mcuboot_commit: unknown`; this is preferable to assigning an unverified revision.

## 02 / Run the workflow

```mermaid
flowchart LR
    K["Development keys"] --> C["Build corpus"]
    C --> M["Run 33 scenarios"]
    M --> E["JSON + stdout + stderr"]
    E --> R["Reports + review"]
    classDef step fill:#12354e,color:#f4f1e8,stroke:#e7b26b;
    class K,C,M,E,R step;
```

```bash
bootlab build-corpus
pytest -v
bootlab run-matrix
bootlab compare-profiles mcuboot_swap_reference mcuboot_overwrite_reference
bootlab fault-sweep --start 0 --end 10 --features sig-ecdsa
bootlab sanitize-report
```

`--end 10` is inclusive: this sweep checks 11 numeric indices. Supplying an explicit range avoids depending on the automatic operation-count probe, whose successful-test output may be captured by Cargo.

For a single case:

```bash
bootlab run-scenario scenarios/P01_boot_v1.yaml
```

The convenience script `./scripts/reproduce.sh` creates the environment, installs dependencies, builds the corpus, runs the matrix, compares the two reference profiles, and sweeps indices 0–10. It stops on a failing step. It does **not** run pytest, sanitize reports, or sign records.

## 03 / Read the result

| Check | What to inspect |
|---|---|
| Matrix completed | Console total and `evidence/report.md`; current unfiltered total is 33 |
| Case passed | `evidence/<case_id>/record.json`, its backend arguments, and oracle details |
| Unexpected rejection | `stderr.txt`; distinguish a clean refusal from a traceback |
| Mode comparison | Actual features in each case; profile groups contain different case IDs |
| Fault result | Sweep row, logs, and reachability of the requested numeric index |
| Coverage claim | [Matrix notes](TEST_MATRIX.md) and [limitations](LIMITATIONS.md) |

`compare-profiles` writes a comparison report but does not return a failing exit code for failed cases. Inspect its table rather than using command completion as a pass signal. Re-running cases overwrites their evidence directories; finalize all runs before signing.

## 04 / Retain a reviewable run

Keep these artifacts together in a separate run archive:

| Artifact | Why retain it |
|---|---|
| `scenarios/` and `profiles/` | Declared intent and configuration labels |
| `evidence/<case_id>/record.json`, `stdout.txt`, `stderr.txt` | Actual oracle result and raw backend output |
| `evidence/report.md`, `comparison.md`, `fault_table.csv`, `fault_table.json` | Aggregate and sweep results, when generated |
| `artifacts/corpus/manifest.json` and tested image bytes | Input hashes and exact test inputs |
| Tool versions and local vendor patch | Provenance beyond the base commit |
| `evidence/report_sanitized.md` | Reviewed public summary, when generated |

Optional artifact commands:

```bash
bootlab sign-evidence
bootlab verify-evidence
bootlab generate-sbom
bootlab generate-site
bootlab generate-onepager
```

Signatures cover canonical record JSON, not the contents of referenced log files. The current verification CLI uses the local signer PEM. Freshly generated development keys and signature randomness can change corpus hashes; repeatability means retaining inputs and configuration, not expecting identical bytes from every fresh environment.

The optional [Zephyr lane](ZEPHYR_INTEGRATION.md) is not a prerequisite for this workflow.
