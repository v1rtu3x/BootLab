#!/usr/bin/env bash
# Apply BootLab-specific patches to the vendored MCUboot simulator.
#
# These patches extend the upstream Rust simulator with BootLab-owned
# instrumentation. They can be applied to either the pinned submodule or a
# source-only copy. Source-only compatibility is checked against the recorded
# SHA-256 hashes of affected upstream files.
#
#   git submodule update --init --recursive
#   ./scripts/apply-mcuboot-patches.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PATCH_DIR="$REPO_ROOT/vendor/mcuboot-patches"
MCUBOOT_DIR="$REPO_ROOT/vendor/mcuboot"

if [[ ! -f "$MCUBOOT_DIR/sim/Cargo.toml" ]]; then
    echo "Error: vendor/mcuboot/sim/Cargo.toml is missing; provide the supported MCUboot source tree." >&2
    exit 1
fi
if ! command -v git >/dev/null 2>&1; then
    echo "Error: the Git patch utility is required even for source-only application." >&2
    exit 1
fi

git_available=false
if command -v git >/dev/null 2>&1 && git -C "$MCUBOOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git_available=true
    actual_revision="$(git -C "$MCUBOOT_DIR" rev-parse HEAD)"
    expected_revision="$(git -C "$REPO_ROOT" ls-tree HEAD vendor/mcuboot 2>/dev/null | awk '{print $3}')"
    if [[ -n "$expected_revision" && "$actual_revision" != "$expected_revision" ]]; then
        echo "Error: MCUboot revision $actual_revision does not match the pinned submodule $expected_revision." >&2
        exit 1
    fi
fi

validate_source_only() {
    local manifest="$1.source-hashes"
    if [[ ! -f "$manifest" ]]; then
        echo "Error: missing source compatibility manifest: $manifest" >&2
        return 1
    fi
    while read -r expected relative; do
        [[ -z "${expected:-}" || "$expected" == \#* ]] && continue
        local source="$MCUBOOT_DIR/$relative"
        if [[ "$expected" == "ABSENT" ]]; then
            if [[ -e "$source" ]]; then
                echo "Error: expected unpatched source path to be absent: $relative" >&2
                return 1
            fi
        elif [[ ! -f "$source" ]]; then
            echo "Error: required upstream source file is missing: $relative" >&2
            return 1
        else
            local actual
            actual="$(sha256sum "$source" | awk '{print $1}')"
            if [[ "$actual" != "$expected" ]]; then
                echo "Error: unsupported or modified source file $relative (SHA-256 $actual)." >&2
                return 1
            fi
        fi
    done < "$manifest"
}

for patch in "$PATCH_DIR"/*.patch; do
    if [[ -f "$patch" ]]; then
        name="$(basename "$patch")"
        if reverse_output="$(cd "$MCUBOOT_DIR" && git apply --reverse --check "$patch" 2>&1)"; then
            echo "$name is already applied."
        elif forward_output="$(cd "$MCUBOOT_DIR" && git apply --check "$patch" 2>&1)"; then
            if [[ "$git_available" == false ]]; then
                validate_source_only "$patch"
            fi
            echo "Applying $name ..."
            if ! apply_output="$(cd "$MCUBOOT_DIR" && git apply "$patch" 2>&1)"; then
                echo "Error: Git could not apply $name:" >&2
                echo "$apply_output" >&2
                exit 1
            fi
        else
            echo "Error: $name is neither applied nor cleanly applicable." >&2
            echo "Git reverse-check output:" >&2
            echo "$reverse_output" >&2
            echo "Git forward-check output:" >&2
            echo "$forward_output" >&2
            echo "Inspect the source and patch state before retrying." >&2
            exit 1
        fi
    fi
done

echo "MCUboot patches applied."
