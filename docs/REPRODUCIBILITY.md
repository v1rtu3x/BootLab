# Reproduce and retain a run

[Project overview](../README.md) · [Visual walkthrough](../WALKTHROUGH.md) · [Documentation map](README.md)

**Run from `BootLab/`, retain unique run records, and compare expectations with results.** Use `bootlab validate-scenarios` to report the current definition count. `SKIP` and `NOT_EXECUTED` are not passes.

## 01 / Prepare the workspace

Use Python 3.10+, a Rust toolchain, Git, and native C build prerequisites for the simulator. Linux is the reference host; [Docker](DOCKER.md) supplies an alternative environment.

From the project directory in an existing checkout:

```bash
git submodule update --init --recursive
./scripts/apply-mcuboot-patches.sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pip install ./vendor/mcuboot/scripts
bootlab validate-scenarios
```

Confirm `vendor/mcuboot/sim/Cargo.toml` exists. The local fault extension described in [FAULT_INJECTION.md](FAULT_INJECTION.md) must also be present for the F and algorithm-fault cases.

If you received a source archive without `.git` metadata, the Git command above does not apply. Use a complete vendored source tree and record its supplied revision separately. The evidence writer may report `mcuboot_commit: unknown`; this is preferable to assigning an unverified revision.

## 02 / Run the workflow

```mermaid
flowchart LR
    K["Development keys"] --> C["Build corpus"]
    C --> M["Run scenario definitions"]
    M --> E["JSON + stdout + stderr"]
    E --> R["Reports + review"]
    classDef step fill:#12354e,color:#f4f1e8,stroke:#e7b26b;
    class K,C,M,E,R step;
```

```bash
bootlab build-corpus
pytest -v
bootlab run-matrix --allow-skip P01O --allow-skip P02O --allow-skip V02
bootlab compare-profiles mcuboot_swap_reference mcuboot_overwrite_reference \
  --allow-skip P01O --allow-skip P02O --allow-skip V02
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
| Matrix completed | Console totals and `evidence/report.md`; inspect passes, failures, and skips |
| Case passed | `evidence/runs/<run-id>/<case_id>/record.json`, selected test identity, and assertions |
| Unexpected rejection | `stderr.txt`; distinguish a clean refusal from a traceback |
| Mode comparison | Actual features in each case; profile groups contain different case IDs |
| Fault result | Sweep row, logs, and reachability of the requested numeric index |
| Coverage claim | [Matrix notes](TEST_MATRIX.md) and [limitations](LIMITATIONS.md) |

`compare-profiles` writes a comparison report and returns failure for failed cases or skips not named with `--allow-skip`. The commands above allow only the three documented unsupported overwrite/version proxies. Every scenario run is archived beneath a unique run ID, so independent runs do not overwrite each other.

## 04 / Retain a reviewable run

Keep these artifacts together in a separate run archive:

| Artifact | Why retain it |
|---|---|
| `scenarios/` and `profiles/` | Declared intent and configuration labels |
| `evidence/runs/<run-id>/<case_id>/record.json`, stdout and stderr | Actual oracle result and raw backend output |
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

Signatures cover canonical record JSON, including hashes for referenced logs and available image inputs. Verify with `bootlab verify-evidence --public-key fixtures/keys/evidence-signer.pub.pem`; verification does not need the private signer key. Signatures establish evidence integrity, not experiment correctness. Fresh keys, signatures, and timestamps can vary between runs.

The optional [Zephyr lane](ZEPHYR_INTEGRATION.md) is not a prerequisite for this workflow.
