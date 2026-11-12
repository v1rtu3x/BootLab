#!/usr/bin/env bash
# Apply BootLab-specific patches to the vendored MCUboot simulator.
#
# These patches extend the upstream Rust simulator with deterministic fault
# campaign helpers used by the BootLab Python harness. Run this after
# initializing the submodule:
#
#   git submodule update --init --recursive
#   ./scripts/apply-mcuboot-patches.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PATCH_DIR="$REPO_ROOT/vendor/mcuboot-patches"
MCUBOOT_DIR="$REPO_ROOT/vendor/mcuboot"

if ! git -C "$MCUBOOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Error: vendor/mcuboot is not initialized." >&2
    echo "Run: git submodule update --init --recursive" >&2
    exit 1
fi

cd "$MCUBOOT_DIR"

for patch in "$PATCH_DIR"/*.patch; do
    if [[ -f "$patch" ]]; then
        echo "Applying $(basename "$patch") ..."
        git apply "$patch"
    fi
done

echo "MCUboot patches applied."
