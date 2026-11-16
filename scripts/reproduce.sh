#!/usr/bin/env bash
# Reproduce the BootLab simulator MVP from a clean checkout.
# Clean checkout sequence: initialize MCUboot, apply the local patch, install
# both Python package sets, build the image fixtures, then validate and run.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

git submodule update --init --recursive
./scripts/apply-mcuboot-patches.sh

echo "==> Setting up Python virtual environment"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"

echo "==> Installing MCUboot imgtool"
pip install ./vendor/mcuboot/scripts

echo "==> Building signed image corpus"
bootlab build-corpus

echo "==> Validating scenario configuration"
bootlab validate-scenarios

run_status=0
run_reported() {
    local status=0
    if "$@"; then
        :
    else
        status=$?
        echo "Step failed with exit code $status: $*" >&2
        run_status=1
    fi
}

echo "==> Running full assurance matrix"
run_reported bootlab run-matrix --allow-skip P01O --allow-skip P02O --allow-skip V02

echo "==> Generating cross-profile comparison"
run_reported bootlab compare-profiles mcuboot_swap_reference mcuboot_overwrite_reference \
    --allow-skip P01O --allow-skip P02O --allow-skip V02

echo "==> Running small deterministic fault sweep"
run_reported bootlab fault-sweep --start 0 --end 10 --features sig-ecdsa

echo "==> Done. Reports:"
echo "    evidence/report.md"
echo "    evidence/comparison.md"
echo "    evidence/fault_table.csv"
exit "$run_status"
