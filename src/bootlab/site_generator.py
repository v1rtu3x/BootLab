"""Static-site dashboard generator for BootLab evidence.

Uses only the Python standard library plus the project's existing dependencies.
No Jinja2 or other templating engine is required.
"""

from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path
from typing import Any

import yaml


def _record_slug(record: dict[str, Any]) -> str:
    case_id = str(record.get("case_id", "case"))
    run_id = str(record.get("run_id", "legacy"))
    return re.sub(r"[^A-Za-z0-9_-]", "_", f"{case_id}-{run_id}")


class SiteGenerator:
    """Generate a self-contained static website from evidence records."""

    def __init__(
        self, workspace: Path, output_dir: Path, run_ids: list[str] | None = None
    ) -> None:
        self.workspace = workspace
        self.output_dir = output_dir
        self.run_ids = run_ids
        self.records: list[dict[str, Any]] = []
        self.scenarios: dict[str, dict[str, Any]] = {}
        self.mcuboot_commit = "unknown"
        self.generated_at = "unknown"

    def run(self) -> None:
        """Load evidence and scenarios, then write all site files."""
        self._load_records()
        self._load_scenarios()
        self._prepare_output()
        self._copy_referenced_logs()
        self._write_css()
        self._write_index()
        self._write_scenario_pages()
        self._write_about()

    def _load_records(self) -> None:
        runs_dir = self.workspace / "evidence" / "runs"
        run_ids = self.run_ids or sorted(
            path.name for path in runs_dir.iterdir() if path.is_dir()
        )
        record_paths = [
            record_path
            for run_id in run_ids
            for record_path in (runs_dir / run_id).rglob("record.json")
        ]
        for record_path in sorted(record_paths):
            record = json.loads(record_path.read_text())
            self.records.append(record)
            if self.mcuboot_commit == "unknown" and record.get("mcuboot_commit"):
                self.mcuboot_commit = record["mcuboot_commit"]
            if self.generated_at == "unknown" and record.get("timestamp_utc"):
                self.generated_at = record["timestamp_utc"]

    def _load_scenarios(self) -> None:
        scenarios_dir = self.workspace / "scenarios"
        for scenario_path in sorted(scenarios_dir.glob("*.yaml")):
            data = yaml.safe_load(scenario_path.read_text())
            if data and data.get("id"):
                self.scenarios[data["id"]] = data

    def _prepare_output(self) -> None:
        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)
        (self.output_dir / "scenario").mkdir(parents=True)
        (self.output_dir / "assets").mkdir(parents=True)

    def _copy_referenced_logs(self) -> None:
        for record in self.records:
            paths = [record.get("stdout_path"), record.get("stderr_path")]
            paths.extend(
                item.get("path") for item in record.get("input_sha256", {}).values()
            )
            for relative in paths:
                if not relative:
                    continue
                source = self.workspace / relative
                if source.is_file():
                    destination = self.output_dir / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)

    def _write_css(self) -> None:
        css = """\
:root {
  --bg: #f8fafc;
  --fg: #0f172a;
  --muted: #475569;
  --panel: #ffffff;
  --border: #e2e8f0;
  --pass: #16a34a;
  --pass-bg: #dcfce7;
  --fail: #dc2626;
  --fail-bg: #fee2e2;
  --accent: #2563eb;
  --accent-bg: #eff6ff;
  --shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f172a;
    --fg: #f8fafc;
    --muted: #94a3b8;
    --panel: #1e293b;
    --border: #334155;
    --pass: #22c55e;
    --pass-bg: #14532d;
    --fail: #f87171;
    --fail-bg: #7f1d1d;
    --accent: #60a5fa;
    --accent-bg: #1e3a8a;
    --shadow: 0 1px 3px rgba(0, 0, 0, 0.4);
  }
}

* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  background: var(--bg);
  color: var(--fg);
  line-height: 1.6;
}

header, footer {
  background: var(--panel);
  border-bottom: 1px solid var(--border);
  padding: 1rem 2rem;
  box-shadow: var(--shadow);
}

footer {
  border-bottom: none;
  border-top: 1px solid var(--border);
  text-align: center;
  color: var(--muted);
  font-size: 0.875rem;
}

nav {
  max-width: 1100px;
  margin: 0 auto;
  display: flex;
  gap: 1.5rem;
  align-items: center;
}

nav a {
  color: var(--accent);
  text-decoration: none;
  font-weight: 600;
}

nav a:hover { text-decoration: underline; }

main {
  max-width: 1100px;
  margin: 0 auto;
  padding: 2rem;
}

h1, h2, h3 { margin-top: 0; }

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 1rem;
  margin: 1.5rem 0;
}

.card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 0.5rem;
  padding: 1.25rem;
  box-shadow: var(--shadow);
}

.card h3 {
  margin: 0 0 0.5rem;
  font-size: 0.875rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted);
}

.card .value {
  font-size: 2rem;
  font-weight: 700;
}

.pass { color: var(--pass); }
.fail { color: var(--fail); }

.badge {
  display: inline-block;
  padding: 0.25rem 0.75rem;
  border-radius: 9999px;
  font-weight: 600;
  font-size: 0.875rem;
}

.badge-pass { background: var(--pass-bg); color: var(--pass); }
.badge-fail { background: var(--fail-bg); color: var(--fail); }
.badge-skip { background: #e2e8f0; color: #475569; }

.heatmap {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(3rem, 1fr));
  gap: 0.5rem;
  margin: 1.5rem 0;
}

.heatmap a {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 3rem;
  border-radius: 0.375rem;
  font-weight: 700;
  color: #ffffff;
  text-decoration: none;
  font-size: 0.875rem;
}

.heatmap a:hover { filter: brightness(1.1); }

.heatmap-pass { background: var(--pass); }
.heatmap-fail { background: var(--fail); }
.heatmap-skip { background: #64748b; }
.heatmap-missing { background: var(--muted); }

.panel {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 0.5rem;
  padding: 1.5rem;
  margin: 1.5rem 0;
  box-shadow: var(--shadow);
}

table {
  width: 100%;
  border-collapse: collapse;
  margin: 1rem 0;
}

th, td {
  text-align: left;
  padding: 0.75rem;
  border-bottom: 1px solid var(--border);
}

th {
  font-weight: 600;
  color: var(--muted);
  text-transform: uppercase;
  font-size: 0.75rem;
  letter-spacing: 0.05em;
}

td a { color: var(--accent); }

pre {
  background: #0f172a;
  color: #e2e8f0;
  padding: 1rem;
  border-radius: 0.5rem;
  overflow-x: auto;
  font-size: 0.875rem;
}

.back { margin-bottom: 1rem; }

.mermaid {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 0.5rem;
  padding: 1rem;
  margin: 1.5rem 0;
}
"""
        (self.output_dir / "assets" / "style.css").write_text(css)

    def _page(self, title: str, body: str, root_prefix: str = "") -> str:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)} | BootLab</title>
  <link rel="stylesheet" href="{root_prefix}assets/style.css">
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <script>mermaid.initialize({{startOnLoad: true}});</script>
</head>
<body>
  <header>
    <nav>
      <a href="{root_prefix}index.html">BootLab</a>
      <a href="{root_prefix}index.html">Matrix</a>
      <a href="{root_prefix}about.html">About</a>
    </nav>
  </header>
  <main>
{body}
  </main>
  <footer>
    Generated {html.escape(self.generated_at)} · MCUboot {html.escape(self.mcuboot_commit[:12] if self.mcuboot_commit != "unknown" else "unknown")}
  </footer>
</body>
</html>
"""

    def _write_index(self) -> None:
        total = len(self.records)
        passed = sum(1 for r in self.records if r.get("passed"))
        skipped = sum(
            1 for r in self.records if r.get("verdict") in {"SKIP", "NOT_EXECUTED"}
        )
        failed = total - passed - skipped

        cards = f"""
<div class="cards">
  <div class="card"><h3>Total</h3><div class="value">{total}</div></div>
  <div class="card"><h3>Passed</h3><div class="value pass">{passed}</div></div>
  <div class="card"><h3>Failed</h3><div class="value fail">{failed}</div></div>
  <div class="card"><h3>Skipped / not executed</h3><div class="value">{skipped}</div></div>
</div>
"""

        heatmap_cells = []
        for record in self.records:
            case_id = html.escape(record.get("case_id", "?"))
            passed_flag = record.get("passed", False)
            cls = "heatmap-pass" if passed_flag else "heatmap-fail"
            heatmap_cells.append(
                f'<a href="scenario/{case_id}.html" title="{case_id}">{case_id}</a>'
            )
            # Inject the CSS class via a separate style attribute is not needed;
            # we use a placeholder and replace below.

        heatmap_html = '<div class="heatmap">\n'
        for record in self.records:
            case_id = record.get("case_id", "?")
            slug = _record_slug(record)
            cls = (
                "heatmap-skip"
                if record.get("verdict") in {"SKIP", "NOT_EXECUTED"}
                else ("heatmap-pass" if record.get("passed") else "heatmap-fail")
            )
            heatmap_html += (
                f'  <a class="{cls}" href="scenario/{html.escape(slug)}.html" '
                f'title="{html.escape(case_id)}">{html.escape(case_id)}</a>\n'
            )
        heatmap_html += "</div>"

        matrix_rows = []
        for record in self.records:
            case_id = html.escape(record.get("case_id", "?"))
            name = html.escape(record.get("case_name", "?"))
            category = html.escape(record.get("category", "?"))
            backend = html.escape(record.get("backend", "?"))
            verdict = html.escape(str(record.get("verdict", "unknown")))
            badge = (
                "badge-skip"
                if record.get("verdict") in {"SKIP", "NOT_EXECUTED"}
                else ("badge-pass" if record.get("passed") else "badge-fail")
            )
            slug = _record_slug(record)
            matrix_rows.append(
                f"<tr>"
                f'<td><a href="scenario/{html.escape(slug)}.html">{case_id}</a></td>'
                f"<td>{name}</td>"
                f"<td>{category}</td>"
                f"<td>{backend}</td>"
                f'<td><span class="badge {badge}">{verdict}</span></td>'
                f"</tr>"
            )

        body = f"""
<h1>Assurance Matrix</h1>
<p>Green cells passed, red cells failed, and gray cells were skipped or not executed.</p>
{cards}
{heatmap_html}
<h2>Detailed Matrix</h2>
<table>
  <thead>
    <tr><th>ID</th><th>Name</th><th>Category</th><th>Backend</th><th>Verdict</th></tr>
  </thead>
  <tbody>
    {"".join(matrix_rows)}
  </tbody>
</table>
<div class="mermaid">
flowchart LR
    A([Power on]) --> B{{Primary valid?}}
    B -->|yes| C[Boot v1]
    B -->|no| D[Check secondary]
    D --> E{{Signed & compatible?}}
    E -->|no| F[Refuse update]
    E -->|yes| G{{Version policy?}}
    G -->|no| H[Reject downgrade]
    G -->|yes| I[Stage upgrade]
    I --> J{{Trial or permanent?}}
    J -->|trial| K[Boot once, revert if unconfirmed]
    J -->|permanent| L[Boot always]
</div>
"""
        (self.output_dir / "index.html").write_text(
            self._page("Assurance Matrix", body, root_prefix="")
        )

    def _write_scenario_pages(self) -> None:
        for record in self.records:
            case_id = record.get("case_id", "?")
            scenario = self.scenarios.get(case_id, {})
            page = self._scenario_page(record, scenario)
            (self.output_dir / "scenario" / f"{_record_slug(record)}.html").write_text(
                page
            )

    def _scenario_page(self, record: dict[str, Any], scenario: dict[str, Any]) -> str:
        case_id = html.escape(record.get("case_id", "?"))
        name = html.escape(record.get("case_name", "?"))
        category = html.escape(record.get("category", "?"))
        profile = html.escape(record.get("profile", "?"))
        backend = html.escape(record.get("backend", "?"))
        verdict = html.escape(str(record.get("verdict", "unknown")))
        passed = record.get("passed", False)
        badge_class = (
            "badge-skip"
            if record.get("verdict") in {"SKIP", "NOT_EXECUTED"}
            else ("badge-pass" if passed else "badge-fail")
        )
        timestamp = html.escape(record.get("timestamp_utc", "unknown"))
        elapsed = record.get("elapsed_seconds")
        elapsed_str = f"{elapsed:.3f} s" if elapsed is not None else "n/a"

        stdout_rel = record.get("stdout_path")
        stderr_rel = record.get("stderr_path")
        stdout_link = (
            f'<a href="../{stdout_rel}">{html.escape(stdout_rel)}</a>'
            if stdout_rel
            else "n/a"
        )
        stderr_link = (
            f'<a href="../{stderr_rel}">{html.escape(stderr_rel)}</a>'
            if stderr_rel
            else "n/a"
        )

        details = record.get("details", {})
        details_json = json.dumps(details, indent=2, sort_keys=True)

        notes = scenario.get("notes") or record.get("notes") or ""
        notes_html = ""
        if notes:
            notes_html = (
                '<div class="panel"><h3>Scenario Notes</h3>\n'
                f"<pre>{html.escape(str(notes).rstrip())}</pre></div>"
            )

        body = f"""
<div class="back"><a href="../index.html">&larr; Back to matrix</a></div>
<h1>{case_id} — {name}</h1>
<p><span class="badge {badge_class}">{verdict}</span></p>

<div class="panel">
  <h3>Summary</h3>
  <table>
    <tr><th>Category</th><td>{category}</td></tr>
    <tr><th>Profile</th><td>{profile}</td></tr>
    <tr><th>Backend</th><td>{backend}</td></tr>
    <tr><th>Timestamp</th><td>{timestamp}</td></tr>
    <tr><th>Elapsed</th><td>{elapsed_str}</td></tr>
    <tr><th>Stdout</th><td>{stdout_link}</td></tr>
    <tr><th>Stderr</th><td>{stderr_link}</td></tr>
  </table>
</div>

<div class="panel">
  <h3>Details JSON</h3>
  <pre>{html.escape(details_json)}</pre>
</div>

{notes_html}
"""
        return self._page(f"{case_id} — {name}", body, root_prefix="../")

    def _write_about(self) -> None:
        body = """
<h1>About BootLab</h1>
<p>
  BootLab records host image-verification results and selected MCUboot simulator
  test assertions. The simulator tests use their own fixtures; this dashboard
  does not claim direct board execution or general device assurance.
</p>

<div class="panel">
  <h3>What it answers</h3>
  <ul>
    <li>Does a corrupted update get rejected?</li>
    <li>Does an untrusted signing key result in refusal?</li>
    <li>Which selected upstream assertions ran for a scenario?</li>
    <li>Did a requested nonzero fault index reach an interruption point?</li>
  </ul>
</div>

<div class="mermaid">
flowchart TB
    A[YAML scenario] --> B[Simulator / imgtool]
    B --> C[Security oracle]
    C --> D[record.json + stdout/stderr]
    D --> E[This dashboard]
</div>

<div class="panel">
  <h3>Documentation</h3>
  <ul>
    <li><a href="../../README.md">README.md</a> — project overview and quick-start</li>
    <li><a href="../../WALKTHROUGH.md">WALKTHROUGH.md</a> — visual scenario-by-scenario guide</li>
  </ul>
</div>
"""
        (self.output_dir / "about.html").write_text(
            self._page("About", body, root_prefix="")
        )
