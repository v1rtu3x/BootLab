"""Generate a shareable one-page summary of the BootLab lab."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import quote


SCENARIO_GROUPS = [
    ("Baseline", "P01, P02, P01O, P02O", "Upstream boot/update proxies; overwrite helpers can skip their main body."),
    ("Trial / confirm", "P03, P04", "Upstream revert and persistence assertions under the selected features."),
    ("Integrity", "S01, S03", "Offline verification of selected payload/header mutations."),
    ("Authenticity", "S02, S06", "Host key verification and a separate runtime bad-signature test."),
    ("Validation", "S04, S05", "Truncated-file verification and simulated slot-size rejection."),
    ("Version policy", "V01, V02", "Enabled-policy refusal assertions; the disabled helper returns early."),
    ("Fault recovery", "F01–F04, F01O–F02O", "Numeric interruption campaigns; index 0 makes no cut."),
    ("Algorithm diversity", "A01–A10", "Selected simulator and verifier checks under RSA-2048 and Ed25519."),
    ("Key selection", "K01–K03", "Host verification against a selected key; no device trust-store update."),
]

STANDARDS = [
    ("NIST SP 800-193", "Platform firmware resiliency, recovery, rollback protection"),
    ("IEC 62443-4-2", "Secure boot and software integrity"),
    ("ETSI EN 303 645", "Secure software updates, no downgrades"),
    ("OWASP Firmware Security Testing Guide", "Bootloader signature, downgrade, and fault-injection testing"),
]


def generate_onepager(workspace: Path, output: Path, provenance: dict[str, Any] | None = None) -> Path:
    """Write a Markdown one-pager summarizing the lab."""
    output.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        "# BootLab — Secure Boot & OTA Assurance Lab",
        "",
        "> One-page summary: what the lab tests, how to run it, and where the evidence lives.",
        "",
        "## What it tests",
        "",
        "When you ship an over-the-air firmware update to an embedded device, three guarantees must hold:",
        "",
        "1. **Authentic** — the update was signed by a trusted key.",
        "2. **Intact** — not a single signed bit was modified.",
        "3. **Recoverable** — power loss mid-update does not brick the device.",
        "",
        "BootLab explores those properties through **33 scenario definitions** around MCUboot and imgtool. "
        "Several definitions share an upstream test; the matrix documents their actual checks and limits.",
        "",
        "## Scenario groups",
        "",
        "| Group | Scenarios | Check and scope |",
        "|---|---|---|",
    ]

    for group, ids, guarantee in SCENARIO_GROUPS:
        lines.append(f"| **{group}** | {ids} | {guarantee} |")

    lines.extend([
        "",
        "## Run the lab",
        "",
        "Requires Python, Rust/C build tools, and the complete vendored MCUboot source. The first build can take several minutes.",
        "",
        "```bash",
        "cd BootLab",
        "python3 -m venv .venv && source .venv/bin/activate",
        "pip install -e '.[dev]'",
        "pip install ./vendor/mcuboot/scripts",
        "bootlab build-corpus",
        "bootlab run-matrix",
        "bootlab tutorial",
        "bootlab generate-site",
        "bootlab sign-evidence",
        "```",
        "",
        "## Related assurance topics",
        "",
        "These are review topics, not a compliance assessment or certification result.",
        "",
        "| Standard / guideline | Review topic |",
        "|---|---|",
    ])

    for std, coverage in STANDARDS:
        lines.append(f"| {std} | {coverage} |")

    if provenance:
        lines.extend([
            "",
            "## Provenance",
            "",
        ])
        for key, value in provenance.items():
            lines.append(f"- **{key}**: {value}")

    lines.extend([
        "",
        "## Learn more",
        "",
    ])
    for label, relative_path in [
        ("Full walkthrough", "WALKTHROUGH.md"),
        ("Threat model", "docs/THREAT_MODEL.md"),
        ("Test matrix", "docs/TEST_MATRIX.md"),
        ("Evidence limitations", "docs/LIMITATIONS.md"),
    ]:
        target = Path(os.path.relpath(workspace / relative_path, output.parent)).as_posix()
        lines.append(f"- [{label}]({quote(target, safe='/')})")
    lines.append("")

    output.write_text("\n".join(lines) + "\n")
    return output
