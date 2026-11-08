"""Markdown/HTML evidence summary generator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class Report:
    """Collects evidence records and renders an assurance report."""

    def __init__(self, workspace: Path, provenance: dict[str, Any]) -> None:
        self.workspace = workspace
        self.provenance = provenance
        self.records: list[dict[str, Any]] = []

    def add(self, record_path: Path) -> None:
        self.records.append(json.loads(record_path.read_text()))

    def render_markdown(self) -> str:
        lines: list[str] = [
            "# BootLab Assurance Report",
            "",
            f"**Generated:** {self.provenance.get('generated_at', 'unknown')}",
            f"**MCUboot commit:** `{self.provenance.get('mcuboot_commit', 'unknown')}`",
            "",
            "## Summary",
            "",
            f"Total cases: {len(self.records)}",
        ]
        passed = sum(1 for r in self.records if r.get("passed"))
        failed = sum(1 for r in self.records if not r.get("passed"))
        infra = sum(1 for r in self.records if r.get("infrastructure_error"))
        lines.extend(
            [
                f"Passed: {passed}",
                f"Failed: {failed}",
                f"Infrastructure errors: {infra}",
                "",
                "## Results",
                "",
                "| ID | Name | Category | Backend | Verdict |",
                "|---|---|---|---|---|",
            ]
        )
        for r in self.records:
            verdict = r.get("verdict", "unknown")
            if r.get("infrastructure_error"):
                verdict = f"INFRA: {verdict}"
            lines.append(
                f"| {r.get('case_id')} | {r.get('case_name')} | "
                f"{r.get('category')} | {r.get('backend')} | {verdict} |"
            )
        lines.extend(
            [
                "",
                "## Detailed evidence",
                "",
            ]
        )
        for r in self.records:
            lines.extend(
                [
                    f"### {r.get('case_id')} — {r.get('case_name')}",
                    "",
                    f"- **Category:** {r.get('category')}",
                    f"- **Profile:** {r.get('profile')}",
                    f"- **Backend:** {r.get('backend')}",
                    f"- **Verdict:** {r.get('verdict')}",
                    f"- **Elapsed:** {r.get('elapsed_seconds')} s",
                    f"- **Stdout:** {r.get('stdout_path')}",
                    f"- **Stderr:** {r.get('stderr_path')}",
                    "",
                    "```json",
                    json.dumps(r.get("details", {}), indent=2),
                    "```",
                    "",
                ]
            )
        lines.extend(
            [
                "## Limitations",
                "",
                "- This report covers simulator-based evidence only.",
                "- Simulated reset/fault injection is logical; it does not prove hardware glitch resistance.",
                "- Development signing keys are used; production key custody is out of scope.",
                "",
            ]
        )
        return "\n".join(lines) + "\n"

    def write(self, path: Path | None = None) -> Path:
        if path is None:
            path = self.workspace / "evidence" / "report.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render_markdown())
        return path

    def render_sanitized_markdown(self) -> str:
        """Render a public, sanitized report without host paths or raw logs."""
        lines: list[str] = [
            "# BootLab Assurance Report (sanitized)",
            "",
            f"**MCUboot commit:** `{self.provenance.get('mcuboot_commit', 'unknown')}`",
            f"**Total cases:** {len(self.records)}",
            "",
            "## Results",
            "",
            "| ID | Category | Profile | Backend | Verdict |",
            "|---|---|---|---|---|",
        ]
        for r in self.records:
            verdict = r.get("verdict", "unknown")
            if r.get("infrastructure_error"):
                verdict = f"INFRA: {verdict}"
            lines.append(
                f"| {r.get('case_id')} | {r.get('category')} | "
                f"{r.get('profile')} | {r.get('backend')} | {verdict} |"
            )
        lines.extend(
            [
                "",
                "## Summary",
                "",
                f"Passed: {sum(1 for r in self.records if r.get('passed'))}",
                f"Failed: {sum(1 for r in self.records if not r.get('passed'))}",
                f"Infrastructure errors: {sum(1 for r in self.records if r.get('infrastructure_error'))}",
                "",
                "## Limitations",
                "",
                "- Simulator-based evidence only.",
                "- Simulated reset/fault injection is logical; not hardware glitch resistance.",
                "- Development signing keys only; production key custody out of scope.",
                "",
            ]
        )
        return "\n".join(lines) + "\n"

    def write_sanitized(self, path: Path | None = None) -> Path:
        if path is None:
            path = self.workspace / "evidence" / "report_sanitized.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render_sanitized_markdown())
        return path
