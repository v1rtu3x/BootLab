# Docker and devcontainer

[Project overview](../README.md) · [Visual walkthrough](../WALKTHROUGH.md) · [Documentation map](README.md)

**The container packages the host lab and warms simulator caches during its build.** It runs `bootlab build-corpus` and `bootlab run-matrix` before producing the image, so build-time test failures stop the build.

## 01 / Build from the project directory

Docker and network access for dependency installation are required. Initialize the vendor checkout before building:

```bash
git submodule update --init --recursive
docker build -t bootlab:latest .
```

The Dockerfile uses Python 3.11 and installs Rust stable, native build tools, the editable BootLab package, and MCUboot's local `imgtool`. A fresh build may take several minutes. The base image and dependency versions are not all pinned; retain tool versions for comparison.

## 02 / Choose the command

The image entrypoint is **`bootlab`**. Arguments after the image name are BootLab subcommands. To execute another program, override the entrypoint explicitly.

| Task | Command |
|---|---|
| Run all 33 defined cases | `docker run --rm bootlab:latest run-matrix` |
| Run one case | `docker run --rm bootlab:latest run-scenario scenarios/P01_boot_v1.yaml` |
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

Without a mount, results from a `--rm` container disappear when it exits. The image also contains its build-time corpus and evidence; keep the container image or export relevant inputs when archiving a run. The image runs as root by default, so bind-mounted output may be owned by root on Linux.

## 04 / VS Code devcontainer

Open `BootLab/` in VS Code and choose **Dev Containers: Reopen in Container**. The configuration builds the same Dockerfile, selects the container virtual environment, installs Python/Rust/YAML editor extensions, and runs `bootlab run-matrix` as its post-create command.

Confirm the working directory and package source when editing: the Docker image installs the package editable at `/opt/bootlab`, while a development workspace may be mounted at a separate path. Run commands from the intended workspace and reinstall with `python -m pip install -e ".[dev]"` there if needed.

## 05 / Diagnose failures

| Symptom | Next check |
|---|---|
| Missing `vendor/mcuboot/sim/Cargo.toml` | Initialize the submodule before building |
| Build fails at the matrix step | Inspect the failing case and compiler/test output |
| “No such command: bash” or “pytest” | Use the `--entrypoint` examples above |
| Run exits with code 1 | Inspect the mounted `evidence/` report and per-case logs |
| Large image | Rust toolchain and compiled simulator artifacts are retained intentionally |

Continue with [reproducibility](REPRODUCIBILITY.md) for evidence review and retention.
