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

If you received a source archive without `.git` metadata, initialize the source tree by other means and record its supplied revision separately. `apply-mcuboot-patches.sh` checks the SHA-256 manifest in `vendor/mcuboot-patches/` before applying to a source-only tree. It accepts the pinned source, is safe to rerun after the exact patch is applied, and rejects a partial or incompatible patch. The evidence writer may report `mcuboot_commit: unknown`; this is preferable to assigning an unverified revision.

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
bootlab run-matrix
bootlab compare-profiles mcuboot_policy_downgrade_enabled mcuboot_overwrite_reference
bootlab run-scenario scenarios/S01_payload_flip.yaml
bootlab fault-sweep --indices 0,1 --features sig-ecdsa
bootlab sanitize-report
```

The sweep records one result per modeled configuration. By default it uses the common range supported by every probed configuration. An explicitly requested index that a configuration cannot reach is recorded as `NOT_REACHED` and fails the command.

For a single case:

```bash
bootlab run-scenario scenarios/D01_direct_authenticated_upgrade.yaml
```

The convenience script `./scripts/reproduce.sh` creates the environment, applies the patch, builds the corpus, validates scenarios, runs the matrix and profile comparison, and sweeps indices 0 and 1. It captures each step's exit code, continues to preserve diagnostics, then exits nonzero if any step failed. It does **not** run pytest, sanitize reports, or sign records.

For a short, genuine direct-image terminal demonstration, run `./scripts/demo.sh`. It rebuilds the corpus and executes the six direct image scenarios; each is stored in its own run archive.

## 03 / Read the result

| Check | What to inspect |
|---|---|
| Matrix completed | Console totals and `evidence/runs/<run-id>/report.md`; inspect passes, failures, and skips |
| Case passed | `evidence/runs/<run-id>/<case_id>/record.json`, selected test identity, and assertions |
| Unexpected rejection | `stderr.txt`; distinguish a clean refusal from a traceback |
| Mode comparison | Actual features in each case; profile groups contain different case IDs |
| Fault result | Sweep row, logs, and reachability of the requested numeric index |
| Coverage claim | [Matrix notes](TEST_MATRIX.md) and [limitations](LIMITATIONS.md) |

`compare-profiles` writes a comparison report within its invocation run and fails for failed cases or unapproved skips. No current scenario is registered for an approved skip. A single run ID groups all records produced by one matrix, comparison, or sweep; separate invocations never overwrite one another.

## 04 / Retain a reviewable run

Keep these artifacts together in a separate run archive:

| Artifact | Why retain it |
|---|---|
| `scenarios/` and `profiles/` | Declared intent and configuration labels |
| `evidence/runs/<run-id>/<case_id>/record.json`, logs, `inputs/sha256/` | Actual oracle result, raw backend output, immutable tested image/key bytes |
| `evidence/runs/<run-id>/report.md`, `comparison.md`, fault table | Aggregate and per-configuration sweep results |
| Tool versions and local vendor patch | Provenance beyond the base commit |
| `evidence/runs/<run-id>/report_sanitized.md` | Reviewed public summary, when generated |

Optional artifact commands:

```bash
RUN_ID="$(ls -1 evidence/runs | sort | tail -n 1)"
bootlab sign-evidence --run-id "$RUN_ID"
bootlab verify-evidence --run-id "$RUN_ID"
bootlab export-evidence --run-id "$RUN_ID" --output /tmp/bootlab-run.tar.gz
mkdir -p /tmp/bootlab-export && tar -xzf /tmp/bootlab-run.tar.gz -C /tmp/bootlab-export
cd /tmp/bootlab-export
bootlab --workspace . verify-evidence --run-id "$RUN_ID" --public-key fixtures/keys/evidence-signer.pub.pem
bootlab generate-sbom
bootlab generate-site
bootlab generate-onepager
```

Signing, verification, reports, and dashboards default to the latest run. `--run-id` selects one archive; `--all-runs` explicitly aggregates or verifies all history where supported. Signatures cover canonical record JSON, including hashes for logs and archived image inputs. The exported bundle includes the public signer key and works without private keys or the current corpus. Signatures establish evidence integrity, not experiment correctness. Fresh timestamps and randomized signatures can vary between runs.

The optional [Zephyr lane](ZEPHYR_INTEGRATION.md) is not a prerequisite for this workflow.
