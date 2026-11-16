# BootLab — reproducible secure-boot & OTA assurance lab
#
# Build:
#   docker build -t bootlab:latest .
#
# Run the full matrix:
#   docker run --rm bootlab:latest run-matrix
#
# Run a single scenario:
#   docker run --rm bootlab:latest run-scenario scenarios/P01_boot_v1.yaml
#
# Interactive shell inside the lab:
#   docker run --rm -it bootlab:latest bash

FROM python:3.11-slim-bookworm

# Avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies: git, cargo tooling, C build tools, and curl for rustup.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    cmake \
    curl \
    git \
    libssl-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Install Rust stable toolchain for the MCUboot simulator.
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:$PATH
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain 1.97.1
RUN rustc --version && cargo --version

# Set the working directory for the lab.
WORKDIR /opt/bootlab

# Copy the project into the image.  Keep this layer cheap to rebuild by relying
# on .dockerignore to omit heavy/generated directories.
COPY . /opt/bootlab/

# Ensure the vendored MCUboot submodule is present.  When the build context was
# produced from a clean checkout without --recurse-submodules, this fails fast
# with a clear error instead of producing cryptic cargo failures later.
RUN test -f vendor/mcuboot/sim/Cargo.toml || \
    (echo "ERROR: vendor/mcuboot is missing. Clone with --recurse-submodules or run 'git submodule update --init --recursive'." && exit 1)

# Patch the pinned simulator tree idempotently before installing or running it.
RUN ./scripts/apply-mcuboot-patches.sh

# Create a Python virtual environment and install the lab plus MCUboot imgtool.
RUN python3 -m venv .venv && \
    . .venv/bin/activate && \
    pip install --upgrade pip && \
    pip install -e ".[dev]" && \
    pip install ./vendor/mcuboot/scripts

# Activate the virtual environment for all subsequent RUN/CMD/ENTRYPOINT layers.
ENV VIRTUAL_ENV=/opt/bootlab/.venv \
    PATH=/opt/bootlab/.venv/bin:$PATH

# Build fixtures and perform a bounded CLI smoke check during image creation.
RUN bootlab build-corpus
RUN bootlab validate-scenarios && bootlab run-scenario scenarios/D01_direct_authenticated_upgrade.yaml

# Make the CLI the default entrypoint; users can still override with `bash`.
ENTRYPOINT ["bootlab"]
