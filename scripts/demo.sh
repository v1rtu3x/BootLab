#!/usr/bin/env bash
# Run the six direct corpus-image simulator cases from the project root.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

if ! command -v bootlab >/dev/null 2>&1; then
    echo "bootlab is not on PATH; activate the project virtual environment first." >&2
    exit 1
fi

bootlab build-corpus
bootlab validate-scenarios
for scenario in \
    D01_direct_authenticated_upgrade \
    D02_direct_payload_tamper \
    D03_direct_untrusted_signer \
    V01_downgrade_enabled \
    V02_downgrade_disabled_control \
    D06_direct_interruption_recovery; do
    echo "==> $scenario"
    bootlab run-scenario "scenarios/${scenario}.yaml"
done

echo "Direct simulator demo complete. Each case is archived under evidence/runs/<run-id>/."
