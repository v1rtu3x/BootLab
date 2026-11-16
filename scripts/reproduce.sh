#!/usr/bin/env bash
# Reproduce the BootLab simulator MVP from a clean checkout.
# Assumes this repository was cloned with submodules:
#   git clone --recurse-submodules <repo>
# Or, after a shallow clone, run:
#   git submodule update --init --recursive

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

echo "==> Setting up Python virtual environment"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"

echo "==> Installing MCUboot imgtool"
pip install ./vendor/mcuboot/scripts

echo "==> Building signed image corpus"
bootlab build-corpus

echo "==> Running full assurance matrix"
bootlab run-matrix

echo "==> Generating cross-profile comparison"
bootlab compare-profiles mcuboot_swap_reference mcuboot_overwrite_reference

echo "==> Running small deterministic fault sweep"
bootlab fault-sweep --start 0 --end 10 --features sig-ecdsa

echo "==> Done. Reports:"
echo "    evidence/report.md"
echo "    evidence/comparison.md"
echo "    evidence/fault_table.csv"
