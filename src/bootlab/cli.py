"""Command-line interface for BootLab."""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from bootlab.backends.mcuboot_sim import McubootSimAdapter
from bootlab.evidence import gather_provenance, record_evidence
from bootlab.fault_plan import probe_total_ops, sweep, write_json, write_table
from bootlab.fuzz_image import FuzzHarness
from bootlab.images import (
    ImageFactory,
    all_corpus_specs,
    default_corpus_specs,
)
from bootlab.onepager import generate_onepager
from bootlab.oracles import evaluate
from bootlab.reports import Report
from bootlab.scenario import Scenario, load_scenario


@click.group()
@click.option(
    "--workspace",
    default=".",
    type=click.Path(path_type=Path),
    help="Project workspace directory.",
)
@click.pass_context
def main(ctx: click.Context, workspace: Path) -> None:
    """BootLab — MCUboot assurance lab CLI."""
    ctx.ensure_object(dict)
    ctx.obj["workspace"] = workspace.resolve()


@main.command()
@click.option(
    "--corpus-dir",
    default="artifacts/corpus",
    type=click.Path(path_type=Path),
    help="Directory for generated images.",
)
@click.option(
    "--keys-dir",
    default="fixtures/keys",
    type=click.Path(path_type=Path),
    help="Directory for development signing keys.",
)
@click.option(
    "--algorithm",
    default="all",
    type=click.Choice(["all", "ecdsa-p256", "rsa-2048", "rsa-3072", "ed25519"]),
    help="Which signing algorithm to build corpus images for.",
)
@click.pass_context
def build_corpus(
    ctx: click.Context,
    corpus_dir: Path,
    keys_dir: Path,
    algorithm: str,
) -> None:
    """Generate the signed image corpus and manifest."""
    ws = ctx.obj["workspace"]
    factory = ImageFactory(
        corpus_dir=ws / corpus_dir,
        keys_dir=ws / keys_dir,
    )
    if algorithm == "all":
        specs = all_corpus_specs()
    elif algorithm == "ecdsa-p256":
        specs = default_corpus_specs()
    else:
        from bootlab.images import algorithm_corpus_specs

        specs = algorithm_corpus_specs(algorithm)
    records = factory.build(specs)
    manifest_path = factory.write_manifest(records)
    key_types = sorted({r.key_type for r in records})
    click.echo(f"Generated {len(records)} images -> {ws / corpus_dir}")
    click.echo(f"Key types: {', '.join(key_types)}")
    click.echo(f"Manifest written to {manifest_path}")


@main.command()
@click.option(
    "--output",
    default="evidence/baseline_log.txt",
    type=click.Path(path_type=Path),
    help="Where to write the baseline cargo test log.",
)
@click.pass_context
def baseline(ctx: click.Context, output: Path) -> None:
    """Run upstream MCUboot simulator tests and capture the log."""
    ws = ctx.obj["workspace"]
    mcuboot_sim = ws / "vendor" / "mcuboot" / "sim"
    output = ws / output
    output.parent.mkdir(parents=True, exist_ok=True)
    click.echo(f"Running upstream simulator tests in {mcuboot_sim} ...")
    with output.open("w") as fh:
        result = subprocess.run(
            ["cargo", "test"],
            cwd=mcuboot_sim,
            stdout=fh,
            stderr=subprocess.STDOUT,
            text=True,
        )
    click.echo(f"Baseline log written to {output} (exit code {result.returncode})")
    sys.exit(result.returncode)


@main.command()
@click.argument("scenario_file", type=click.Path(exists=True, path_type=Path))
@click.pass_context
def run_scenario(ctx: click.Context, scenario_file: Path) -> None:
    """Run a single scenario YAML file and record evidence."""
    ws = ctx.obj["workspace"]
    scenario = load_scenario(scenario_file)
    adapter = McubootSimAdapter(ws)
    provenance = gather_provenance(ws)

    click.echo(f"Running {scenario.id}: {scenario.name}")
    start = time.perf_counter()
    result = adapter.run(scenario)
    elapsed = time.perf_counter() - start
    oracle = evaluate(scenario, result)
    record_path = record_evidence(
        ws, scenario, oracle, result.stdout, result.stderr, elapsed, provenance
    )
    click.echo(f"  verdict: {oracle.verdict}")
    click.echo(f"  evidence: {record_path}")
    sys.exit(0 if oracle.passed else 1)


@main.command()
@click.option(
    "--scenarios-dir",
    default="scenarios",
    type=click.Path(path_type=Path),
    help="Directory containing scenario YAML files.",
)
@click.option(
    "--report",
    default="evidence/report.md",
    type=click.Path(path_type=Path),
    help="Path for the generated Markdown report.",
)
@click.option(
    "--profile",
    default=None,
    help="Only run scenarios matching this profile ID.",
)
@click.pass_context
def run_matrix(ctx: click.Context, scenarios_dir: Path, report: Path, profile: str | None) -> None:
    """Run scenario YAML files and produce an assurance report."""
    ws = ctx.obj["workspace"]
    scenarios_dir = ws / scenarios_dir
    report = ws / report
    adapter = McubootSimAdapter(ws)
    provenance = gather_provenance(ws)
    report_obj = Report(ws, provenance)

    scenario_files = sorted(scenarios_dir.glob("*.yaml"))
    if not scenario_files:
        click.echo(f"No scenario files found in {scenarios_dir}")
        sys.exit(1)

    passed = 0
    failed = 0
    for scenario_file in scenario_files:
        scenario = load_scenario(scenario_file)
        if profile is not None and scenario.profile != profile:
            continue
        click.echo(f"Running {scenario.id}: {scenario.name}")
        click.echo(f"Running {scenario.id}: {scenario.name}")
        start = time.perf_counter()
        result = adapter.run(scenario)
        elapsed = time.perf_counter() - start
        oracle = evaluate(scenario, result)
        record_path = record_evidence(
            ws, scenario, oracle, result.stdout, result.stderr, elapsed, provenance
        )
        report_obj.add(record_path)
        if oracle.passed:
            passed += 1
            click.echo(f"  PASS: {oracle.verdict}")
        else:
            failed += 1
            click.echo(f"  FAIL: {oracle.verdict}")

    report_path = report_obj.write(report)
    click.echo(f"\nReport written to {report_path}")
    click.echo(f"Passed: {passed}  Failed: {failed}")
    sys.exit(0 if failed == 0 else 1)


@main.command()
@click.option(
    "--output",
    default="evidence/report_sanitized.md",
    type=click.Path(path_type=Path),
    help="Path for the sanitized public report.",
)
@click.pass_context
def sanitize_report(ctx: click.Context, output: Path) -> None:
    """Generate a sanitized public report from existing evidence records."""
    ws = ctx.obj["workspace"]
    output = ws / output
    provenance = gather_provenance(ws)
    report = Report(ws, provenance)
    evidence_dir = ws / "evidence"
    for record_path in sorted(evidence_dir.glob("*/record.json")):
        report.add(record_path)
    path = report.write_sanitized(output)
    click.echo(f"Sanitized report written to {path}")


@main.command()
@click.argument("profile_a")
@click.argument("profile_b")
@click.option(
    "--scenarios-dir",
    default="scenarios",
    type=click.Path(path_type=Path),
    help="Directory containing scenario YAML files.",
)
@click.option(
    "--report",
    default="evidence/comparison.md",
    type=click.Path(path_type=Path),
    help="Path for the generated comparison report.",
)
@click.pass_context
def compare_profiles(
    ctx: click.Context,
    profile_a: str,
    profile_b: str,
    scenarios_dir: Path,
    report: Path,
) -> None:
    """Run two profiles and produce a comparative assurance report."""
    ws = ctx.obj["workspace"]
    scenarios_dir = ws / scenarios_dir
    report = ws / report
    adapter = McubootSimAdapter(ws)
    provenance = gather_provenance(ws)

    from bootlab.reports import Report as ReportGen

    report_a = ReportGen(ws, provenance)
    report_b = ReportGen(ws, provenance)

    for profile, report_obj in [(profile_a, report_a), (profile_b, report_b)]:
        for scenario_file in sorted(scenarios_dir.glob("*.yaml")):
            scenario = load_scenario(scenario_file)
            if scenario.profile != profile:
                continue
            click.echo(f"Running {scenario.id}: {scenario.name} ({profile})")
            start = time.perf_counter()
            result = adapter.run(scenario)
            elapsed = time.perf_counter() - start
            oracle = evaluate(scenario, result)
            record_path = record_evidence(
                ws, scenario, oracle, result.stdout, result.stderr, elapsed, provenance
            )
            report_obj.add(record_path)

    lines = [
        "# Cross-profile comparison",
        "",
        f"**Profile A:** `{profile_a}`",
        f"**Profile B:** `{profile_b}`",
        f"**MCUboot commit:** `{provenance.get('mcuboot_commit', 'unknown')}`",
        "",
        "## Result summary",
        "",
        f"| Profile | Passed | Failed | Total |",
        "|---|---|---|---|",
        f"| {profile_a} | {sum(1 for r in report_a.records if r.get('passed'))} | "
        f"{sum(1 for r in report_a.records if not r.get('passed'))} | {len(report_a.records)} |",
        f"| {profile_b} | {sum(1 for r in report_b.records if r.get('passed'))} | "
        f"{sum(1 for r in report_b.records if not r.get('passed'))} | {len(report_b.records)} |",
        "",
        "## Per-case comparison",
        "",
        "| ID | A verdict | B verdict |",
        "|---|---|---|",
    ]

    by_id_a = {r.get("case_id"): r for r in report_a.records}
    by_id_b = {r.get("case_id"): r for r in report_b.records}
    all_ids = sorted(set(by_id_a) | set(by_id_b))
    for case_id in all_ids:
        a_verdict = by_id_a.get(case_id, {}).get("verdict", "n/a")
        b_verdict = by_id_b.get(case_id, {}).get("verdict", "n/a")
        lines.append(f"| {case_id} | {a_verdict} | {b_verdict} |")

    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n")
    click.echo(f"Comparison report written to {report}")


@main.command()
@click.option(
    "--features",
    default="sig-ecdsa",
    help="Cargo features for the simulator build.",
)
@click.option(
    "--start",
    default=0,
    type=int,
    help="First fault index to test.",
)
@click.option(
    "--end",
    default=None,
    type=int,
    help="Last fault index to test (inclusive). If omitted, probes the total count.",
)
@click.option(
    "--indices",
    default=None,
    help="Comma-separated list of indices (overrides --start/--end).",
)
@click.option(
    "--csv",
    default="evidence/fault_table.csv",
    type=click.Path(path_type=Path),
    help="Output CSV path.",
)
@click.option(
    "--json",
    default="evidence/fault_table.json",
    type=click.Path(path_type=Path),
    help="Output JSON path.",
)
@click.pass_context
def fault_sweep(
    ctx: click.Context,
    features: str,
    start: int,
    end: int | None,
    indices: str | None,
    csv: Path,
    json: Path,
) -> None:
    """Run a deterministic fault-campaign sweep and emit a table."""
    ws = ctx.obj["workspace"]
    adapter = McubootSimAdapter(ws)

    if indices:
        idx_list = [int(x.strip()) for x in indices.split(",")]
    else:
        if end is None:
            max_ops = probe_total_ops(adapter, features)
            if max_ops is None:
                click.echo("Failed to probe total flash operation count")
                sys.exit(1)
            end = max_ops
            click.echo(f"Probed total ops: {end}")
        idx_list = list(range(start, end + 1))

    click.echo(f"Running fault sweep over {len(idx_list)} indices ({idx_list[0]}..{idx_list[-1]})")
    results = sweep(adapter, idx_list, features, ws)

    csv = ws / csv
    json = ws / json
    write_table(results, csv)
    write_json(results, json)

    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    click.echo(f"Fault sweep complete: {passed} passed, {failed} failed")
    click.echo(f"CSV: {csv}")
    click.echo(f"JSON: {json}")
    sys.exit(0 if failed == 0 else 1)


def _run_tutorial_scenario(ws: Path, scenario_file: Path) -> tuple[Any, Path]:
    """Run a scenario for the tutorial and return the oracle result and record path."""
    scenario = load_scenario(scenario_file)
    adapter = McubootSimAdapter(ws)
    provenance = gather_provenance(ws)
    result = adapter.run(scenario)
    oracle = evaluate(scenario, result)
    record_path = record_evidence(
        ws, scenario, oracle, result.stdout, result.stderr, None, provenance
    )
    return oracle, record_path


@main.command()
@click.option(
    "--non-interactive",
    is_flag=True,
    help="Run all tutorial steps automatically (useful for CI and demos).",
)
@click.pass_context
def tutorial(ctx: click.Context, non_interactive: bool) -> None:
    """Interactive walkthrough of BootLab scenarios."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.text import Text

    ws = ctx.obj["workspace"]
    scenarios_dir = ws / "scenarios"
    console = Console()

    def panel(title: str, body: str, style: str = "blue") -> Panel:
        return Panel(
            Text(body, justify="left"),
            title=title,
            title_align="left",
            border_style=style,
            padding=(1, 2),
        )

    def ask_step(prompt: str, choices: list[str]) -> str:
        if non_interactive:
            return choices[0]
        return Prompt.ask(
            prompt,
            choices=choices,
            default=choices[0],
            show_choices=False,
        )

    steps = [
        {
            "id": "intro",
            "title": "What is BootLab?",
            "body": (
                "BootLab is a reproducible security lab that proves your "
                "bootloader does what it promises. It wraps the official MCUboot "
                "simulator and signing tools so you can answer, with evidence:\n\n"
                "• Does a corrupted update get rejected?\n"
                "• Does an older signed image get blocked when downgrade prevention is on?\n"
                "• Does the device recover if reset happens during the flash swap?\n\n"
                "This tutorial walks through a handful of representative scenarios."
            ),
            "scenario": None,
        },
        {
            "id": "P01",
            "title": "Baseline boot (P01)",
            "body": (
                "The simplest case: a trusted v1 image boots cleanly. If this fails, "
                "nothing else can be trusted."
            ),
            "scenario": "P01_boot_v1.yaml",
        },
        {
            "id": "S01",
            "title": "Integrity check (S01)",
            "body": (
                "A single bit is flipped inside the signed payload after signing. "
                "The image must fail verification, proving integrity is enforced."
            ),
            "scenario": "S01_payload_flip.yaml",
        },
        {
            "id": "S02",
            "title": "Authenticity check (S02)",
            "body": (
                "An image is signed with an attacker-controlled key. Even if the "
                "payload is unchanged, the device must refuse it because the key is "
                "not in the trust anchor."
            ),
            "scenario": "S02_untrusted_key.yaml",
        },
        {
            "id": "F01",
            "title": "Fault recovery (F01)",
            "body": (
                "Power is cut before any destination flash write occurs during an "
                "upgrade. On the next boot the device must still converge to a valid "
                "image rather than brick itself."
            ),
            "scenario": "F01_reset_before_write.yaml",
        },
        {
            "id": "A01",
            "title": "Algorithm diversity (A01)",
            "body": (
                "The reference matrix uses ECDSA-P256, but your product may require "
                "RSA-2048 or Ed25519. This step shows the same baseline boot under an "
                "alternative signature algorithm."
            ),
            "scenario": "A01_rsa_boot_v1.yaml",
        },
        {
            "id": "reading",
            "title": "How to read evidence",
            "body": (
                "Every scenario writes a machine-readable evidence package:\n\n"
                "• evidence/<id>/record.json — verdict, config, provenance, timing\n"
                "• evidence/<id>/stdout.txt — captured standard output\n"
                "• evidence/<id>/stderr.txt — captured standard error\n\n"
                "Use these files to prove a test was run, re-run the same command later, "
                "or share sanitized results without exposing host paths."
            ),
            "scenario": None,
        },
    ]

    console.print(
        Panel(
            "[bold]BootLab Interactive Tutorial[/bold]\n"
            "Follow the prompts, or use [bold]--non-interactive[/bold] for CI/demos.",
            border_style="green",
            padding=(1, 2),
        )
    )

    for index, step in enumerate(steps, start=1):
        console.print()
        console.print(
            panel(
                f"Step {index}/{len(steps)}: {step['title']}",
                step["body"],
                style="cyan",
            )
        )

        if step["scenario"] is None:
            choice = ask_step(
                "[Enter] continue / [s] skip / [q] quit",
                ["", "s", "q"],
            )
        else:
            run_choices = ["y", "n", "s", "q"] if not non_interactive else ["y"]
            choice = ask_step(
                "[y] run scenario / [n] skip run / [s] skip step / [q] quit",
                run_choices,
            )

        if choice == "q":
            console.print(Panel("Tutorial quit.", border_style="yellow"))
            sys.exit(0)
        if choice == "s":
            console.print("  Skipped.")
            continue
        if choice == "n":
            console.print("  Skipped running scenario.")
            continue
        if step["scenario"] is None:
            continue

        scenario_file = scenarios_dir / step["scenario"]
        if not scenario_file.exists():
            console.print(
                Panel(
                    f"Scenario file not found: {scenario_file}",
                    border_style="red",
                )
            )
            continue

        with console.status(f"Running {step['id']}...", spinner="dots"):
            oracle, record_path = _run_tutorial_scenario(ws, scenario_file)

        verdict_style = "green" if oracle.passed else "red"
        verdict_text = "PASS" if oracle.passed else "FAIL"
        console.print(
            Panel(
                f"[bold {verdict_style}]{verdict_text}[/bold {verdict_style}]\n"
                f"Verdict: {oracle.verdict}\n"
                f"Evidence: {record_path}",
                title=f"{step['id']} result",
                title_align="left",
                border_style=verdict_style,
            )
        )

    console.print()
    console.print(
        Panel(
            "Tutorial complete. Run [bold]bootlab generate-site[/bold] to "
            "turn the evidence into a static dashboard.",
            border_style="green",
        )
    )


@main.command()
@click.option(
    "--output",
    default="out/site",
    type=click.Path(path_type=Path),
    help="Directory to write the generated static site.",
)
@click.pass_context
def generate_site(ctx: click.Context, output: Path) -> None:
    """Generate a self-contained static-site dashboard from evidence records."""
    from bootlab.site_generator import SiteGenerator

    ws = ctx.obj["workspace"]
    output = ws / output
    generator = SiteGenerator(ws, output)
    generator.run()
    click.echo(f"Static site written to {output}")


@main.command(name="generate-onepager")
@click.option(
    "--output",
    default="out/onepager.md",
    type=click.Path(path_type=Path),
    help="Path for the generated one-pager Markdown file.",
)
@click.pass_context
def generate_onepager_cmd(ctx: click.Context, output: Path) -> None:
    """Generate a shareable one-page summary of the BootLab lab."""
    ws = ctx.obj["workspace"]
    output = ws / output if not output.is_absolute() else output
    provenance = gather_provenance(ws)
    path = generate_onepager(ws, output, provenance)
    click.echo(f"One-pager written to {path}")


ED25519_SIGNER_KEY_PATH = Path("fixtures/keys/evidence-signer.pem")
ED25519_SIGNATURE_ALGORITHM = "Ed25519"


def _load_or_create_signer_key(key_path: Path) -> Ed25519PrivateKey:
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if key_path.exists():
        pem = key_path.read_bytes()
        return serialization.load_pem_private_key(pem, password=None)  # type: ignore[return-value]

    click.echo(
        f"WARNING: generating development-only Ed25519 signer key at {key_path}",
        err=True,
    )
    private_key = Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path.write_bytes(pem)
    return private_key


def _public_key_fingerprint(public_key: Ed25519PublicKey) -> str:
    spki = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(spki).hexdigest()[:16]


def _canonical_record_bytes(record: dict[str, Any]) -> bytes:
    record = {k: v for k, v in record.items() if k != "signatures"}
    return json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sign_record(
    record_path: Path,
    private_key: Ed25519PrivateKey,
    fingerprint: str,
) -> bool:
    record = json.loads(record_path.read_text())
    if "signatures" in record:
        record.pop("signatures")

    payload = _canonical_record_bytes(record)
    signature = private_key.sign(payload)
    sig_path = record_path.with_suffix(record_path.suffix + ".sig")
    sig_path.write_text(base64.b64encode(signature).decode("ascii"))

    record["signatures"] = [
        {
            "algorithm": ED25519_SIGNATURE_ALGORITHM,
            "key_fingerprint": fingerprint,
            "signature_path": str(sig_path.relative_to(record_path.parent.parent.parent)),
        }
    ]
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    return True


@main.command(name="sign-evidence")
@click.option(
    "--keys-dir",
    default="fixtures/keys",
    type=click.Path(path_type=Path),
    help="Directory containing the evidence signer key.",
)
@click.pass_context
def sign_evidence(ctx: click.Context, keys_dir: Path) -> None:
    """Sign all evidence records with the development Ed25519 signer key."""
    ws = ctx.obj["workspace"]
    key_path = ws / keys_dir / "evidence-signer.pem"
    private_key = _load_or_create_signer_key(key_path)
    fingerprint = _public_key_fingerprint(private_key.public_key())

    evidence_dir = ws / "evidence"
    record_paths = sorted(evidence_dir.glob("*/record.json"))
    if not record_paths:
        click.echo("No evidence records found.")
        sys.exit(0)

    signed = 0
    for record_path in record_paths:
        if _sign_record(record_path, private_key, fingerprint):
            signed += 1
            click.echo(f"Signed {record_path.relative_to(ws)}")

    click.echo(f"Signed {signed} evidence record(s) with key {fingerprint}")


@main.command(name="verify-evidence")
@click.option(
    "--keys-dir",
    default="fixtures/keys",
    type=click.Path(path_type=Path),
    help="Directory containing the evidence signer key.",
)
@click.pass_context
def verify_evidence(ctx: click.Context, keys_dir: Path) -> None:
    """Verify Ed25519 detached signatures for all evidence records."""
    ws = ctx.obj["workspace"]
    key_path = ws / keys_dir / "evidence-signer.pem"
    if not key_path.exists():
        click.echo(f"Signer key not found: {key_path}")
        sys.exit(1)

    private_key = _load_or_create_signer_key(key_path)
    public_key = private_key.public_key()
    fingerprint = _public_key_fingerprint(public_key)

    evidence_dir = ws / "evidence"
    record_paths = sorted(evidence_dir.glob("*/record.json"))
    valid = 0
    invalid = 0
    for record_path in record_paths:
        sig_path = record_path.with_suffix(record_path.suffix + ".sig")
        if not sig_path.exists():
            click.echo(f"  MISSING signature for {record_path.relative_to(ws)}")
            invalid += 1
            continue

        record = json.loads(record_path.read_text())
        sig_entry = record.get("signatures", [{}])[0]
        if sig_entry.get("key_fingerprint") != fingerprint:
            click.echo(
                f"  UNKNOWN key fingerprint for {record_path.relative_to(ws)}: "
                f"{sig_entry.get('key_fingerprint')}"
            )
            invalid += 1
            continue

        payload = _canonical_record_bytes(record)
        signature = base64.b64decode(sig_path.read_text().strip())
        try:
            public_key.verify(signature, payload)
            valid += 1
            click.echo(f"  VALID {record_path.relative_to(ws)}")
        except Exception:
            invalid += 1
            click.echo(f"  INVALID {record_path.relative_to(ws)}")

    click.echo(f"Evidence signatures: {valid} valid, {invalid} invalid")
    sys.exit(0 if invalid == 0 else 1)


def _parse_pyproject_dependencies(pyproject_path: Path) -> list[str]:
    deps: list[str] = []
    if not pyproject_path.exists():
        return deps
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]
    data = tomllib.loads(pyproject_path.read_text())
    for dep in data.get("project", {}).get("dependencies", []):
        deps.append(dep)
    return deps


def _installed_python_version(package_name: str) -> str | None:
    try:
        from importlib.metadata import version

        return version(package_name)
    except Exception:
        return None


def _parse_cargo_lock(lock_path: Path) -> dict[str, str]:
    crates: dict[str, str] = {}
    if not lock_path.exists():
        return crates
    import re
    text = lock_path.read_text()
    for block in re.split(r"\n\[\[package\]\]\n", text)[1:]:
        name_match = re.search(r'^name\s*=\s*"([^"]+)"', block, re.MULTILINE)
        version_match = re.search(r'^version\s*=\s*"([^"]+)"', block, re.MULTILINE)
        if name_match and version_match:
            crates[name_match.group(1)] = version_match.group(1)
    return crates


def _parse_cargo_toml_deps(toml_path: Path) -> list[tuple[str, str | None]]:
    deps: list[tuple[str, str | None]] = []
    if not toml_path.exists():
        return deps
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]
    data = tomllib.loads(toml_path.read_text())
    raw_deps = data.get("dependencies", {})
    for name, spec in raw_deps.items():
        if isinstance(spec, str):
            deps.append((name, spec))
        elif isinstance(spec, dict):
            deps.append((name, spec.get("version")))
        else:
            deps.append((name, None))
    return deps


@main.command(name="generate-sbom")
@click.option(
    "--output",
    default="evidence/sbom.json",
    type=click.Path(path_type=Path),
    help="Path for the generated SBOM file.",
)
@click.pass_context
def generate_sbom(ctx: click.Context, output: Path) -> None:
    """Generate a CycloneDX-like SBOM from project and dependency metadata."""
    ws = ctx.obj["workspace"]
    output = ws / output
    output.parent.mkdir(parents=True, exist_ok=True)

    pyproject_path = ws / "pyproject.toml"
    project_name = "bootlab"
    project_version = "0.0.0"
    if pyproject_path.exists():
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore[no-redef]
        data = tomllib.loads(pyproject_path.read_text())
        project_name = data.get("project", {}).get("name", project_name)
        project_version = data.get("project", {}).get("version", project_version)

    mcuboot_commit = "unknown"
    mcuboot_path = ws / "vendor" / "mcuboot"
    if (mcuboot_path / ".git").exists():
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=mcuboot_path,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            mcuboot_commit = result.stdout.strip()

    pyproject_deps = _parse_pyproject_dependencies(pyproject_path)
    python_components = []
    for dep in pyproject_deps:
        name = dep.split("[")[0].split("==")[0].split(">=")[0].split("<")[0].strip()
        version = _installed_python_version(name)
        python_components.append(
            {
                "type": "library",
                "bom-ref": f"pkg:pypi/{name}@{version or 'unknown'}",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{name}@{version or 'unknown'}",
                "scope": "required",
            }
        )

    sim_cargo_toml = mcuboot_path / "sim" / "Cargo.toml"
    root_lock = mcuboot_path / "Cargo.lock"
    lock_crates = _parse_cargo_lock(root_lock)
    rust_components = []
    for name, requested in _parse_cargo_toml_deps(sim_cargo_toml):
        version = lock_crates.get(name)
        rust_components.append(
            {
                "type": "library",
                "bom-ref": f"pkg:cargo/{name}@{version or requested or 'unknown'}",
                "name": name,
                "version": version,
                "requested": requested,
                "purl": f"pkg:cargo/{name}@{version or requested or 'unknown'}",
                "scope": "required",
            }
        )

    sbom: dict[str, Any] = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "component": {
                "type": "application",
                "bom-ref": f"pkg:generic/{project_name}@{project_version}",
                "name": project_name,
                "version": project_version,
            },
            "properties": [
                {
                    "name": "mcuboot-pinned-commit",
                    "value": mcuboot_commit,
                }
            ],
        },
        "components": [
            {
                "type": "library",
                "bom-ref": f"pkg:github/mcu-tools/mcuboot@{mcuboot_commit}",
                "name": "mcuboot",
                "version": mcuboot_commit,
                "purl": f"pkg:github/mcu-tools/mcuboot@{mcuboot_commit}",
            },
            *python_components,
            *rust_components,
        ],
    }

    output.write_text(json.dumps(sbom, indent=2) + "\n")
    click.echo(f"SBOM written to {output}")


@main.command()
@click.option(
    "--seed",
    default=0,
    type=int,
    help="Random seed for deterministic mutations.",
)
@click.option(
    "--iterations",
    default=1000,
    type=int,
    help="Number of mutations to generate.",
)
@click.option(
    "--base-image",
    default="artifacts/corpus/v2.0.0-trusted.signed.bin",
    type=click.Path(path_type=Path),
    help="Path to the signed image used as the fuzzing base.",
)
@click.option(
    "--trusted-key",
    default="fixtures/keys/dev-trusted-ecdsa-p256.pem",
    type=click.Path(path_type=Path),
    help="Trusted public/private key for imgtool verify.",
)
@click.option(
    "--output",
    default="evidence/fuzz_results.json",
    type=click.Path(path_type=Path),
    help="Path for the JSON fuzzing report.",
)
@click.option(
    "--reproducers-dir",
    default="evidence/reproducers",
    type=click.Path(path_type=Path),
    help="Directory to save reproducer images for accepted/crash findings.",
)
@click.pass_context
def fuzz_image(
    ctx: click.Context,
    seed: int,
    iterations: int,
    base_image: Path,
    trusted_key: Path,
    output: Path,
    reproducers_dir: Path,
) -> None:
    """Run a structured mutation campaign against an imgtool verify target."""
    ws = ctx.obj["workspace"]
    base_image = ws / base_image if not base_image.is_absolute() else base_image
    trusted_key = ws / trusted_key if not trusted_key.is_absolute() else trusted_key
    reproducers_dir = ws / reproducers_dir if not reproducers_dir.is_absolute() else reproducers_dir

    if not base_image.exists():
        raise click.BadParameter(f"Base image not found: {base_image}")
    if not trusted_key.exists():
        raise click.BadParameter(f"Trusted key not found: {trusted_key}")

    output = ws / output if not output.is_absolute() else output
    output.parent.mkdir(parents=True, exist_ok=True)

    harness = FuzzHarness(
        base_image=base_image,
        trusted_key=trusted_key,
        seed=seed,
        iterations=iterations,
        reproducers_dir=reproducers_dir,
    )
    summary = harness.run()
    harness.write_results(output)

    click.echo(
        f"Fuzzed {summary.total}/{summary.iterations} mutations from {base_image}"
    )
    click.echo(
        f"  rejected={summary.rejected} accepted={summary.accepted} crashes={summary.crashes}"
    )
    if summary.early_stop:
        click.echo(f"  early stop: {summary.stop_reason}")
        for r in harness.results:
            if r.outcome in ("accepted", "crash"):
                click.echo(f"  reproducer: {r.reproducer_path or 'not saved'}")
                break
    click.echo(f"Results written to {output}")

    sys.exit(1 if summary.accepted or summary.crashes else 0)


if __name__ == "__main__":
    main()
