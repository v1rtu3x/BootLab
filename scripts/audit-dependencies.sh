#!/usr/bin/env bash
# Run dependency audits for Rust (cargo-audit) and Python (pip-audit).
# Writes results to evidence/dependency_audit.json.
# Missing audit tools are treated as warnings, not failures.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
EVIDENCE_DIR="${PROJECT_ROOT}/evidence"
OUTPUT="${EVIDENCE_DIR}/dependency_audit.json"

mkdir -p "${EVIDENCE_DIR}"

CARGO_AUDIT_AVAILABLE=0
PIP_AUDIT_AVAILABLE=0

if command -v cargo-audit >/dev/null 2>&1; then
    CARGO_AUDIT_AVAILABLE=1
else
    echo "WARNING: cargo-audit is not installed; skipping Rust dependency audit" >&2
fi

if command -v pip-audit >/dev/null 2>&1; then
    PIP_AUDIT_AVAILABLE=1
else
    echo "WARNING: pip-audit is not installed; skipping Python dependency audit" >&2
fi

CARGO_OUTPUT=""
CARGO_EXIT=0
if [ "${CARGO_AUDIT_AVAILABLE}" -eq 1 ]; then
    CARGO_OUTPUT=$(cd "${PROJECT_ROOT}/vendor/mcuboot/sim" && cargo audit --json 2>&1) || CARGO_EXIT=$?
fi

PIP_OUTPUT=""
PIP_EXIT=0
if [ "${PIP_AUDIT_AVAILABLE}" -eq 1 ]; then
    if [ -d "${PROJECT_ROOT}/.venv" ]; then
        PIP_OUTPUT=$(pip-audit --virtual-environment "${PROJECT_ROOT}/.venv" --format=json 2>&1) || PIP_EXIT=$?
    else
        PIP_OUTPUT=$(pip-audit --format=json 2>&1) || PIP_EXIT=$?
    fi
fi

export _CARGO_AUDIT_OUTPUT="${CARGO_OUTPUT}"
export _PIP_AUDIT_OUTPUT="${PIP_OUTPUT}"

python3 - "${CARGO_AUDIT_AVAILABLE}" "${CARGO_EXIT}" "${PIP_AUDIT_AVAILABLE}" "${PIP_EXIT}" "${OUTPUT}" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone

cargo_available = sys.argv[1] == "1"
cargo_exit = int(sys.argv[2])
pip_available = sys.argv[3] == "1"
pip_exit = int(sys.argv[4])
output_path = sys.argv[5]

cargo_output = os.environ.get("_CARGO_AUDIT_OUTPUT", "")
pip_output = os.environ.get("_PIP_AUDIT_OUTPUT", "")

def parse_json(text):
    text = text.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"parse_error": True, "raw": text}

result = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "tools": {
        "cargo-audit": {"available": cargo_available, "exit_code": cargo_exit},
        "pip-audit": {"available": pip_available, "exit_code": pip_exit},
    },
    "cargo_audit": parse_json(cargo_output) if cargo_available else None,
    "pip_audit": parse_json(pip_output) if pip_available else None,
}

with open(output_path, "w") as fh:
    json.dump(result, fh, indent=2)
    fh.write("\n")

print(f"Dependency audit report written to {output_path}")
PY

exit 0
