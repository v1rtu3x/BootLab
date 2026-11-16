#!/usr/bin/env bash
# Quick demo script for BootLab.
# Run from the project root with the virtual environment activated.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

echo "==> BootLab quick demo"
echo

echo "==> 1. Build corpus"
bootlab build-corpus

echo
echo "==> 2. Run a single baseline scenario"
bootlab run-scenario scenarios/P01_boot_v1.yaml

echo
echo "==> 3. Run a single fault scenario"
bootlab run-scenario scenarios/F01_reset_before_write.yaml

echo
echo "==> 4. Run full matrix"
bootlab run-matrix

echo
echo "==> 5. Show summary"
grep -E '^Total cases:|^Passed:|^Failed:' evidence/report.md || true

echo
echo "Demo complete. See evidence/report.md for the full report."
