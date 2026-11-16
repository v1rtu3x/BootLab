# Docker and devcontainer

[Project overview](../README.md) · [Visual walkthrough](../WALKTHROUGH.md) · [Documentation map](README.md)

**The container installs the host lab, applies the local simulator patch, builds fixtures, and runs a direct corpus-image simulator case.** Run the full matrix explicitly and inspect its verdict counts.

## 01 / Build from the project directory

Docker and network access for dependency installation are required. Initialize the vendor checkout before building:

```bash
git submodule update --init --recursive
docker build -t bootlab:latest .
```

The Dockerfile uses Python 3.11, Rust 1.97.1, native build tools, the editable BootLab package with pinned Python dependencies, and MCUboot's local `imgtool`. A fresh build may take several minutes; retain recorded tool versions for comparison.

## 02 / Choose the command

The image entrypoint is **`bootlab`**. Arguments after the image name are BootLab subcommands. To execute another program, override the entrypoint explicitly.

| Task | Command |
|---|---|
| Validate scenario definitions | `docker run --rm bootlab:latest validate-scenarios` |
| Run the scenario matrix | `docker run --rm bootlab:latest run-matrix` |
| Run a direct image case | `docker run --rm bootlab:latest run-scenario scenarios/D01_direct_authenticated_upgrade.yaml` |
| Build the corpus | `docker run --rm bootlab:latest build-corpus` |
| Run Python tests | `docker run --rm --entrypoint pytest bootlab:latest -v` |
| Open a shell | `docker run --rm -it --entrypoint bash bootlab:latest` |

The virtual environment is `/opt/bootlab/.venv` and its executables are on `PATH`. Read actual result counts and logs; successful image creation is evidence for that build, not a permanent guarantee for later runs.

## 03 / Keep results on the host

```mermaid
flowchart LR
    H["Host ./evidence"] <-->|"bind mount"| C["Container /opt/bootlab/evidence"]
    C --> R["record.json + logs + report"]
    classDef step fill:#12354e,color:#f4f1e8,stroke:#e7b26b;
    class H,C,R step;
```

```bash
mkdir -p evidence
docker run --rm \
  -v "$(pwd)/evidence:/opt/bootlab/evidence" \
  bootlab:latest run-matrix
```

Without a mount, results from a `--rm` container disappear when it exits. Export a run with `bootlab export-evidence` before removing the container, or mount `evidence/` and `fixtures/keys/` to retain it. Evidence bundles contain immutable inputs and public keys, never private signer keys. The image runs as root by default, so bind-mounted output may be owned by root on Linux.

## 04 / VS Code devcontainer

Open `BootLab/` in VS Code and choose **Dev Containers: Reopen in Container**. The configuration builds the same Dockerfile, mounts the selected checkout at `/workspaces/BootLab`, runs commands from that mounted checkout, and sets `PYTHONPATH` to its source tree. The image virtual environment supplies the interpreter and tools. Post-create applies the patch, builds fixtures, and validates scenarios.

The mounted development checkout is `/workspaces/BootLab`; the image installation under `/opt/bootlab` supplies the virtual environment only.

## 05 / Diagnose failures

| Symptom | Next check |
|---|---|
| Missing `vendor/mcuboot/sim/Cargo.toml` | Initialize the submodule before building |
| Build fails at the matrix step | Inspect the failing case and compiler/test output |
| “No such command: bash” or “pytest” | Use the `--entrypoint` examples above |
| Run exits with code 1 | Inspect the mounted `evidence/` report and per-case logs |
| Large image | Rust toolchain and compiled simulator artifacts are retained intentionally |

Continue with [reproducibility](REPRODUCIBILITY.md) for evidence review and retention.
