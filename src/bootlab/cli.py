"""Command-line interface for BootLab."""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
import tarfile
import time
from dataclasses import asdict
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
from bootlab.evidence import (
    begin_run,
    gather_provenance,
    latest_run_id,
    record_evidence,
)
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
from bootlab.scenario import (
    ALGORITHM_FEATURE,
    Backend,
    ProfileSpec,
    Scenario,
    load_scenario,
)


APPROVED_SKIP_CODES: dict[str, str] = {}


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


def _scenario_catalog(scenarios_dir: Path) -> list[tuple[Path, Scenario]]:
    files = sorted(scenarios_dir.glob("*.yaml"))
    scenarios = [(path, _load_scenario(path)) for path in files]
    ids = [scenario.id for _, scenario in scenarios]
    duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
    if duplicates:
        raise click.ClickException(f"Duplicate scenario IDs: {', '.join(duplicates)}")
    return scenarios


def _load_scenario(path: Path) -> Scenario:
    try:
        return load_scenario(path)
    except Exception as exc:
        raise click.ClickException(f"Invalid scenario {path}: {exc}") from exc


def _validate_skip_ids(allow_skip: tuple[str, ...], scenarios: list[Scenario]) -> None:
    known_ids = {scenario.id for scenario in scenarios}
    unknown = set(allow_skip) - known_ids
    if unknown:
        raise click.ClickException(
            f"Unknown --allow-skip scenario ID(s): {', '.join(sorted(unknown))}"
        )
    unsupported = set(allow_skip) - set(APPROVED_SKIP_CODES)
    if unsupported:
        raise click.ClickException(
            f"Scenario IDs are not approved for skips: {', '.join(sorted(unsupported))}"
        )


def _selected_run_ids(workspace: Path, run_id: str | None, all_runs: bool) -> list[str]:
    if run_id and all_runs:
        raise click.ClickException("choose either --run-id or --all-runs")
    runs_dir = workspace / "evidence" / "runs"
    if all_runs:
        return (
            sorted(path.name for path in runs_dir.iterdir() if path.is_dir())
            if runs_dir.is_dir()
            else []
        )
    selected = run_id or latest_run_id(workspace)
    if not selected:
        raise click.ClickException(
            "No run archive found; run a scenario or matrix first"
        )
    if not (runs_dir / selected).is_dir():
        raise click.ClickException(f"Run archive not found: {selected}")
    return [selected]


def _record_paths_for_runs(workspace: Path, run_ids: list[str]) -> list[Path]:
    return sorted(
        path
        for run_id in run_ids
        for path in (workspace / "evidence" / "runs" / run_id).rglob("record.json")
    )


def _is_approved_skip(
    case_id: str, verdict: str, details: dict[str, Any], allow_skip: tuple[str, ...]
) -> bool:
    return (
        verdict == "SKIP"
        and case_id in allow_skip
        and details.get("skip_code") == APPROVED_SKIP_CODES.get(case_id)
        and bool(details.get("reason"))
    )


def _load_profile(path: Path) -> ProfileSpec:
    import yaml

    try:
        profile = ProfileSpec.model_validate(yaml.safe_load(path.read_text()))
        if profile.id != path.stem:
            raise ValueError(
                f"profile id {profile.id!r} must match filename {path.stem!r}"
            )
        return profile
    except Exception as exc:
        raise click.ClickException(f"Invalid profile {path}: {exc}") from exc


def _validate_scenario_profile(scenario: Scenario, profile: ProfileSpec) -> None:
    if scenario.backend != Backend.MCUBOOT_SIM:
        key_type = scenario.backend_args.get("key_type", profile.signature.algorithm)
        if key_type != profile.signature.algorithm:
            raise click.ClickException(
                f"Scenario {scenario.id} key_type {key_type!r} conflicts with profile algorithm {profile.signature.algorithm!r}"
            )
        return
    features = set(
        str(scenario.backend_args.get("cargo_features", "sig-ecdsa")).split()
    )
    algorithm_feature = ALGORITHM_FEATURE[profile.signature.algorithm]
    signatures = features.intersection(ALGORITHM_FEATURE.values())
    if signatures != {algorithm_feature}:
        raise click.ClickException(
            f"Scenario {scenario.id} Cargo signature feature {sorted(signatures)} conflicts with profile algorithm {profile.signature.algorithm!r}"
        )
    if scenario.backend_args.get("cargo_test") == "bootlab_direct_image":
        if (
            profile.device.name != "nrf52840"
            or profile.device.align != 8
            or profile.device.erased_value != 0xFF
        ):
            raise click.ClickException(
                f"Scenario {scenario.id} direct simulator supports only nrf52840 align=8 erased=0xff"
            )
        if (
            profile.device.primary_slot.size != 0x034000
            or profile.device.secondary_slot.size != 0x034000
        ):
            raise click.ClickException(
                f"Scenario {scenario.id} direct simulator requires 0x34000-byte slots"
            )
        if (
            profile.device.primary_slot.base != 0x008000
            or profile.device.secondary_slot.base != 0x03C000
        ):
            raise click.ClickException(
                f"Scenario {scenario.id} direct simulator slot bases do not match the nrf52840 model"
            )
        if (
            scenario.backend_args.get("key_type", profile.signature.algorithm)
            != profile.signature.algorithm
        ):
            raise click.ClickException(
                f"Scenario {scenario.id} direct input key_type conflicts with profile signature algorithm"
            )
        if profile.signature.key_id != "dev-trusted":
            raise click.ClickException(
                f"Scenario {scenario.id} direct simulator profile must use MCUboot's pinned dev-trusted root key"
            )
    for feature, expected in (
        ("overwrite-only", profile.image.overwrite_only),
        ("downgrade-prevention", profile.image.downgrade_prevention),
    ):
        if (feature in features) != expected:
            raise click.ClickException(
                f"Scenario {scenario.id} feature {feature!r} conflicts with profile effective configuration"
            )


@main.command(name="validate-scenarios")
@click.option("--scenarios-dir", default="scenarios", type=click.Path(path_type=Path))
@click.option("--profiles-dir", default="profiles", type=click.Path(path_type=Path))
@click.pass_context
def validate_scenarios(
    ctx: click.Context, scenarios_dir: Path, profiles_dir: Path
) -> None:
    """Validate scenario schemas and references without running the simulator."""
    ws = ctx.obj["workspace"]
    catalog = _scenario_catalog(ws / scenarios_dir)
    if not catalog:
        raise click.ClickException("Scenario inventory must not be empty")
    profile_files = sorted((ws / profiles_dir).glob("*.yaml"))
    profiles = {path.stem: _load_profile(path) for path in profile_files}
    unknown = sorted({scenario.profile for _, scenario in catalog} - set(profiles))
    if unknown:
        raise click.ClickException(f"Unknown profile(s): {', '.join(unknown)}")
    for _, scenario in catalog:
        _validate_scenario_profile(scenario, profiles[scenario.profile])
    categories: dict[str, int] = {}
    for _, scenario in catalog:
        categories[scenario.category.value] = (
            categories.get(scenario.category.value, 0) + 1
        )
    click.echo(
        f"Validated {len(catalog)} scenario definitions across {len(profiles)} profile files"
    )
    click.echo(
        "Definitions by category: "
        + ", ".join(f"{key}={value}" for key, value in sorted(categories.items()))
    )


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
        simulator_key_dir=ws / "vendor" / "mcuboot",
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
            [
                "cargo",
                "test",
                "--",
                "--skip",
                "bootlab_direct_image",
                "--skip",
                "fault_campaign_probe",
                "--skip",
                "fault_campaign_upgrade",
            ],
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
    scenario = _load_scenario(scenario_file)
    adapter = McubootSimAdapter(ws)
    provenance = gather_provenance(ws)
    run_id = begin_run(ws, "scenario", provenance, {"scenario_id": scenario.id})

    click.echo(f"Running {scenario.id}: {scenario.name}")
    start = time.perf_counter()
    result = adapter.run(scenario)
    elapsed = time.perf_counter() - start
    oracle = evaluate(scenario, result)
    record_path = record_evidence(
        ws,
        scenario,
        oracle,
        result.stdout,
        result.stderr,
        elapsed,
        provenance,
        result,
        run_id,
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
    default=None,
    type=click.Path(path_type=Path),
    help="Path for the generated Markdown report.",
)
@click.option(
    "--profile",
    default=None,
    help="Only run scenarios matching this profile ID.",
)
@click.option(
    "--allow-skip",
    multiple=True,
    help="Scenario ID whose explicit SKIP is expected for this run.",
)
@click.pass_context
def run_matrix(
    ctx: click.Context,
    scenarios_dir: Path,
    report: Path | None,
    profile: str | None,
    allow_skip: tuple[str, ...],
) -> None:
    """Run scenario YAML files and produce an assurance report."""
    ws = ctx.obj["workspace"]
    scenarios_dir = ws / scenarios_dir
    adapter = McubootSimAdapter(ws)
    provenance = gather_provenance(ws)
    report_obj = Report(ws, provenance)

    catalog = _scenario_catalog(scenarios_dir)
    if not catalog:
        click.echo(f"No scenario files found in {scenarios_dir}")
        sys.exit(1)
    _validate_skip_ids(allow_skip, [scenario for _, scenario in catalog])
    run_id = begin_run(
        ws,
        "matrix",
        provenance,
        {
            "profile": profile,
            "scenario_ids": [
                scenario.id
                for _, scenario in catalog
                if profile is None or scenario.profile == profile
            ],
            "approved_skip_ids": list(allow_skip),
        },
    )
    report = ws / report if report else ws / "evidence" / "runs" / run_id / "report.md"

    passed = 0
    failed = 0
    skipped = 0
    unallowed_skips = 0
    selected = 0
    for scenario_file, scenario in catalog:
        if profile is not None and scenario.profile != profile:
            continue
        selected += 1
        click.echo(f"Running {scenario.id}: {scenario.name}")
        start = time.perf_counter()
        result = adapter.run(scenario)
        elapsed = time.perf_counter() - start
        oracle = evaluate(scenario, result)
        record_path = record_evidence(
            ws,
            scenario,
            oracle,
            result.stdout,
            result.stderr,
            elapsed,
            provenance,
            result,
            run_id,
        )
        report_obj.add(record_path)
        if oracle.passed:
            passed += 1
            click.echo(f"  PASS: {oracle.verdict}")
        elif _is_approved_skip(scenario.id, oracle.verdict, oracle.details, allow_skip):
            skipped += 1
            click.echo(f"  {oracle.verdict}: {oracle.details.get('reason', '')}")
        elif oracle.verdict == "SKIP":
            skipped += 1
            unallowed_skips += 1
            click.echo(f"  SKIP (unapproved): {oracle.details.get('reason', '')}")
        else:
            failed += 1
            click.echo(f"  FAIL: {oracle.verdict}")

    if selected == 0:
        raise click.ClickException(f"No scenarios matched profile {profile!r}")
    report_path = report_obj.write(report)
    click.echo(f"\nReport written to {report_path}")
    click.echo(f"Passed: {passed}  Failed: {failed}  Skipped: {skipped}")
    click.echo(
        f"Expected skips: {skipped - unallowed_skips}  Unapproved skips: {unallowed_skips}"
    )
    sys.exit(0 if failed == 0 and unallowed_skips == 0 else 1)


@main.command()
@click.option(
    "--output",
    default=None,
    type=click.Path(path_type=Path),
    help="Path for the sanitized public report.",
)
@click.option(
    "--run-id", default=None, help="Run archive to report; defaults to the latest run."
)
@click.option(
    "--all-runs", is_flag=True, help="Aggregate all historical runs explicitly."
)
@click.pass_context
def sanitize_report(
    ctx: click.Context, output: Path | None, run_id: str | None, all_runs: bool
) -> None:
    """Generate a sanitized public report from existing evidence records."""
    ws = ctx.obj["workspace"]
    selected_runs = _selected_run_ids(ws, run_id, all_runs)
    output = (
        ws / output
        if output
        else ws / "evidence" / "runs" / selected_runs[-1] / "report_sanitized.md"
    )
    provenance = gather_provenance(ws)
    report = Report(ws, provenance)
    for record_path in _record_paths_for_runs(ws, selected_runs):
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
    default=None,
    type=click.Path(path_type=Path),
    help="Path for the generated comparison report.",
)
@click.option(
    "--allow-skip",
    multiple=True,
    help="Scenario ID whose explicit SKIP is expected for this comparison.",
)
@click.pass_context
def compare_profiles(
    ctx: click.Context,
    profile_a: str,
    profile_b: str,
    scenarios_dir: Path,
    report: Path | None,
    allow_skip: tuple[str, ...],
) -> None:
    """Run two profiles and produce a comparative assurance report."""
    ws = ctx.obj["workspace"]
    scenarios_dir = ws / scenarios_dir
    # The report is placed under the same invocation archive as its case records.
    adapter = McubootSimAdapter(ws)
    provenance = gather_provenance(ws)

    from bootlab.reports import Report as ReportGen

    report_a = ReportGen(ws, provenance)
    report_b = ReportGen(ws, provenance)
    catalog = _scenario_catalog(scenarios_dir)
    _validate_skip_ids(allow_skip, [scenario for _, scenario in catalog])
    profiles_found = {scenario.profile for _, scenario in catalog}
    unknown = {profile_a, profile_b} - profiles_found
    if unknown:
        raise click.ClickException(f"Unknown profile(s): {', '.join(sorted(unknown))}")
    run_id = begin_run(
        ws,
        "profile-comparison",
        provenance,
        {"profiles": [profile_a, profile_b], "approved_skip_ids": list(allow_skip)},
    )

    for profile, report_obj in [(profile_a, report_a), (profile_b, report_b)]:
        for scenario_file, scenario in catalog:
            if scenario.profile != profile:
                continue
            click.echo(f"Running {scenario.id}: {scenario.name} ({profile})")
            start = time.perf_counter()
            result = adapter.run(scenario)
            elapsed = time.perf_counter() - start
            oracle = evaluate(scenario, result)
            record_path = record_evidence(
                ws,
                scenario,
                oracle,
                result.stdout,
                result.stderr,
                elapsed,
                provenance,
                result,
                run_id,
            )
            report_obj.add(record_path)

    if not report_a.records or not report_b.records:
        raise click.ClickException(
            "Both profile selections must contain at least one scenario"
        )
    report = (
        ws / report if report else ws / "evidence" / "runs" / run_id / "comparison.md"
    )
    lines = [
        "# Cross-profile comparison",
        "",
        f"**Profile A:** `{profile_a}`",
        f"**Profile B:** `{profile_b}`",
        f"**MCUboot commit:** `{provenance.get('mcuboot_commit', 'unknown')}`",
        "",
        "## Result summary",
        "",
        "| Profile | Passed | Failed | Skipped | Total |",
        "|---|---|---|---|---|",
        f"| {profile_a} | {sum(1 for r in report_a.records if r.get('passed'))} | "
        f"{sum(1 for r in report_a.records if not r.get('passed') and not _is_approved_skip(r.get('case_id', ''), r.get('verdict', ''), r.get('details', {}), allow_skip))} | "
        f"{sum(1 for r in report_a.records if r.get('verdict') == 'SKIP')} | {len(report_a.records)} |",
        f"| {profile_b} | {sum(1 for r in report_b.records if r.get('passed'))} | "
        f"{sum(1 for r in report_b.records if not r.get('passed') and not _is_approved_skip(r.get('case_id', ''), r.get('verdict', ''), r.get('details', {}), allow_skip))} | "
        f"{sum(1 for r in report_b.records if r.get('verdict') == 'SKIP')} | {len(report_b.records)} |",
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
    records = report_a.records + report_b.records
    unsuccessful = sum(
        1
        for item in records
        if not item.get("passed")
        and not _is_approved_skip(
            item.get("case_id", ""),
            item.get("verdict", ""),
            item.get("details", {}),
            allow_skip,
        )
    )
    skipped = sum(1 for item in records if item.get("verdict") == "SKIP")
    click.echo(
        f"Profile cases: {sum(1 for item in records if item.get('passed'))} passed, {unsuccessful} failed/unapproved, {skipped} skipped"
    )
    sys.exit(0 if unsuccessful == 0 else 1)


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
    "csv_output",
    default=None,
    type=click.Path(path_type=Path),
    help="Output CSV path.",
)
@click.option(
    "--json",
    "json_output",
    default=None,
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
    csv_output: Path | None,
    json_output: Path | None,
) -> None:
    """Run a deterministic fault-campaign sweep and emit a table."""
    ws = ctx.obj["workspace"]
    adapter = McubootSimAdapter(ws)

    if indices is not None:
        if not indices.strip():
            raise click.ClickException("--indices selection must not be empty")
        try:
            pieces = [x.strip() for x in indices.split(",")]
            if any(not piece for piece in pieces):
                raise ValueError("empty entry")
            idx_list = [int(x) for x in pieces]
        except ValueError as exc:
            raise click.ClickException(
                "--indices must be comma-separated non-negative integers"
            ) from exc
        if not idx_list:
            raise click.ClickException("--indices selection must not be empty")
        if any(i < 0 for i in idx_list):
            raise click.ClickException("fault indices must be >= 0")
        if len(idx_list) != len(set(idx_list)):
            raise click.ClickException("fault indices must not contain duplicates")
    else:
        if start < 0 or (end is not None and end < 0):
            raise click.ClickException("fault range values must be >= 0")
        if end is not None and end < start:
            raise click.ClickException("--end must be greater than or equal to --start")
        if end is None:
            max_ops = probe_total_ops(adapter, features)
            if max_ops is None:
                click.echo("Failed to probe total flash operation count")
                sys.exit(1)
            end = min(max_ops.values())
            click.echo(
                f"Probed {len(max_ops)} modeled configurations; sweeping common reachable indices 0..{end}"
            )
        idx_list = list(range(start, end + 1))

    provenance = gather_provenance(ws)
    run_id = begin_run(
        ws, "fault-sweep", provenance, {"indices": idx_list, "features": features}
    )
    click.echo(f"Running fault sweep {run_id} over {len(idx_list)} indices")
    try:
        results = sweep(adapter, idx_list, features, ws, run_id)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    run_dir = ws / "evidence" / "runs" / run_id
    csv_path = ws / csv_output if csv_output else run_dir / "fault_table.csv"
    json_path = ws / json_output if json_output else run_dir / "fault_table.json"
    write_table(results, csv_path)
    write_json(results, json_path)
    for row in results:
        if row.configuration is None:
            continue
        row_dir = run_dir / "fault_sweep" / f"index_{row.index}" / row.configuration
        row_dir.mkdir(parents=True, exist_ok=True)
        record_data = asdict(row)
        stdout_file = ws / "evidence" / "runs" / run_id / row.stdout_path
        stderr_file = ws / "evidence" / "runs" / run_id / row.stderr_path
        record_data.update(
            {
                "run_id": run_id,
                "case_id": f"F{row.index:03d}:{row.configuration}",
                "stdout_path": str(stdout_file.relative_to(ws)),
                "stderr_path": str(stderr_file.relative_to(ws)),
                "stdout_sha256": hashlib.sha256(stdout_file.read_bytes()).hexdigest(),
                "stderr_sha256": hashlib.sha256(stderr_file.read_bytes()).hexdigest(),
                "input_sha256": {},
            }
        )
        (row_dir / "record.json").write_text(json.dumps(record_data, indent=2) + "\n")

    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    unsupported = sum(1 for r in results if r.outcome == "NOT_REACHED")
    click.echo(
        f"Fault sweep complete: {passed} passed, {failed} failed, {unsupported} not reached"
    )
    click.echo(f"CSV: {csv_path}")
    click.echo(f"JSON: {json_path}")
    sys.exit(0 if failed == 0 else 1)


def _run_tutorial_scenario(
    ws: Path, scenario_file: Path, run_id: str
) -> tuple[Any, Path]:
    """Run a scenario for the tutorial and return the oracle result and record path."""
    scenario = _load_scenario(scenario_file)
    adapter = McubootSimAdapter(ws)
    provenance = gather_provenance(ws)
    result = adapter.run(scenario)
    oracle = evaluate(scenario, result)
    record_path = record_evidence(
        ws,
        scenario,
        oracle,
        result.stdout,
        result.stderr,
        None,
        provenance,
        result,
        run_id,
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
    tutorial_run_id = begin_run(ws, "tutorial", gather_provenance(ws))

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
                "BootLab runs reproducible MCUboot simulator checks and image-tool "
                "validation, with input hashes and explicit observations. The lab "
                "shows which behavior was exercised and where a simulator proxy "
                "or unsupported case remains.\n\n"
                "• Does a corrupted update get rejected?\n"
                "• Does an older signed image get blocked when downgrade prevention is on?\n"
                "• Does the device recover if reset happens during the flash swap?\n\n"
                "This tutorial walks through a handful of representative scenarios."
            ),
            "scenario": None,
        },
        {
            "id": "D01",
            "title": "Authenticated upgrade (D01)",
            "body": (
                "This case injects the declared trusted v1 primary and trusted v2 candidate "
                "into the MCUboot simulator. It checks selected image and version; it does "
                "not start the application or test hardware."
            ),
            "scenario": "D01_direct_authenticated_upgrade.yaml",
        },
        {
            "id": "S01",
            "title": "Integrity check (S01)",
            "body": (
                "A single bit is flipped inside a signed candidate. MCUboot must retain "
                "the valid primary image in the modeled simulator."
            ),
            "scenario": "D02_direct_payload_tamper.yaml",
        },
        {
            "id": "S02",
            "title": "Authenticity check (S02)",
            "body": (
                "An otherwise valid candidate is signed by a key absent from MCUboot's "
                "modeled root trust. The direct simulator must retain the trusted primary."
            ),
            "scenario": "D03_direct_untrusted_signer.yaml",
        },
        {
            "id": "F01",
            "title": "Fault recovery (F01)",
            "body": (
                "A modeled interruption at operation index 1 is asserted as reached. "
                "The subsequent boot must select the valid candidate and report recovery."
            ),
            "scenario": "D06_direct_interruption_recovery.yaml",
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
                "Every invocation writes a machine-readable run archive:\n\n"
                "• evidence/runs/<run-id>/<id>/record.json — verdict, config, provenance, timing\n"
                "• stdout_path and stderr_path in the record — captured backend output\n\n"
                "Use the exact test identity, declared expectations, and observed details to inspect what ran. "
                "Signatures bind record and artifact hashes; they do not establish hardware behavior."
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

    tutorial_failed = False
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
            oracle, record_path = _run_tutorial_scenario(
                ws, scenario_file, tutorial_run_id
            )
        tutorial_failed = tutorial_failed or not oracle.passed

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
    if tutorial_failed:
        console.print(
            "Tutorial scenarios included one or more failed evidence records."
        )
        sys.exit(1)


@main.command()
@click.option(
    "--output",
    default="out/site",
    type=click.Path(path_type=Path),
    help="Directory to write the generated static site.",
)
@click.option(
    "--run-id", default=None, help="Run archive for the dashboard; defaults to latest."
)
@click.option("--all-runs", is_flag=True, help="Aggregate historical runs explicitly.")
@click.pass_context
def generate_site(
    ctx: click.Context, output: Path, run_id: str | None, all_runs: bool
) -> None:
    """Generate a self-contained static-site dashboard from evidence records."""
    from bootlab.site_generator import SiteGenerator

    ws = ctx.obj["workspace"]
    output = ws / output
    selected_runs = _selected_run_ids(ws, run_id, all_runs)
    generator = SiteGenerator(ws, output, selected_runs)
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
            "signature_path": sig_path.name,
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
@click.option(
    "--run-id", default=None, help="Run archive to sign; defaults to the latest run."
)
@click.option(
    "--all-runs", is_flag=True, help="Sign all historical run archives explicitly."
)
@click.pass_context
def sign_evidence(
    ctx: click.Context, keys_dir: Path, run_id: str | None, all_runs: bool
) -> None:
    """Sign all evidence records with the development Ed25519 signer key."""
    ws = ctx.obj["workspace"]
    key_path = ws / keys_dir / "evidence-signer.pem"
    private_key = _load_or_create_signer_key(key_path)
    fingerprint = _public_key_fingerprint(private_key.public_key())

    run_ids = _selected_run_ids(ws, run_id, all_runs)
    record_paths = _record_paths_for_runs(ws, run_ids)
    if not record_paths:
        raise click.ClickException(
            "The selected run archive contains no evidence records"
        )

    signed = 0
    for record_path in record_paths:
        if _sign_record(record_path, private_key, fingerprint):
            signed += 1
            click.echo(f"Signed {record_path.relative_to(ws)}")

    click.echo(f"Signed {signed} evidence record(s) with key {fingerprint}")
    public_path = key_path.with_suffix(".pub.pem")
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    click.echo(f"Public verification key: {public_path}")


@main.command(name="verify-evidence")
@click.option(
    "--public-key",
    default="fixtures/keys/evidence-signer.pub.pem",
    type=click.Path(path_type=Path, dir_okay=False),
    help="Public Ed25519 key used to verify signatures.",
)
@click.option(
    "--run-id", default=None, help="Run archive to verify; defaults to the latest run."
)
@click.option(
    "--all-runs", is_flag=True, help="Verify all historical run archives explicitly."
)
@click.pass_context
def verify_evidence(
    ctx: click.Context, public_key: Path, run_id: str | None, all_runs: bool
) -> None:
    """Verify evidence records and referenced artifacts with a public key."""
    ws = ctx.obj["workspace"]
    public_path = public_key if public_key.is_absolute() else ws / public_key
    if not public_path.is_file():
        raise click.ClickException(f"Public verification key not found: {public_path}")
    try:
        verifier = serialization.load_pem_public_key(public_path.read_bytes())
    except Exception as exc:
        raise click.ClickException(
            f"Could not load public verification key: {exc}"
        ) from exc
    if not isinstance(verifier, Ed25519PublicKey):
        raise click.ClickException("Public verification key must be Ed25519")
    fingerprint = _public_key_fingerprint(verifier)

    run_ids = _selected_run_ids(ws, run_id, all_runs)
    record_paths = _record_paths_for_runs(ws, run_ids)
    if not record_paths:
        raise click.ClickException("No evidence records found to verify")
    valid = 0
    invalid = 0
    for record_path in record_paths:
        sig_path = record_path.with_suffix(record_path.suffix + ".sig")
        if not sig_path.exists():
            click.echo(f"  MISSING signature for {record_path.relative_to(ws)}")
            invalid += 1
            continue

        try:
            record = json.loads(record_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            click.echo(
                f"  INVALID {record_path.relative_to(ws)}: unreadable record ({exc})"
            )
            invalid += 1
            continue
        signatures = record.get("signatures")
        if not isinstance(signatures, list) or len(signatures) != 1:
            click.echo(
                f"  INVALID {record_path.relative_to(ws)}: missing or malformed signature entry"
            )
            invalid += 1
            continue
        sig_entry = signatures[0]
        if not isinstance(sig_entry, dict):
            click.echo(
                f"  INVALID {record_path.relative_to(ws)}: malformed signature entry"
            )
            invalid += 1
            continue
        if sig_entry.get("key_fingerprint") != fingerprint:
            click.echo(
                f"  UNKNOWN key fingerprint for {record_path.relative_to(ws)}: "
                f"{sig_entry.get('key_fingerprint')}"
            )
            invalid += 1
            continue

        payload = _canonical_record_bytes(record)
        try:
            signature = base64.b64decode(sig_path.read_text().strip(), validate=True)
        except Exception:
            invalid += 1
            click.echo(
                f"  INVALID signature encoding for {record_path.relative_to(ws)}"
            )
            continue
        try:
            verifier.verify(signature, payload)
            artifact_ok = True
            for field in ("stdout", "stderr"):
                artifact = record.get(f"{field}_path")
                expected_hash = record.get("details", {}).get(f"{field}_sha256")
                # Hashes are top-level in current records; tolerate older format only for signature checks.
                expected_hash = record.get(f"{field}_sha256", expected_hash)
                artifact_path = ws / artifact if artifact else None
                if (
                    not artifact_path
                    or not artifact_path.is_file()
                    or not expected_hash
                    or hashlib.sha256(artifact_path.read_bytes()).hexdigest()
                    != expected_hash
                ):
                    artifact_ok = False
            for input_info in record.get("input_sha256", {}).values():
                input_path = ws / input_info["path"]
                if (
                    not input_path.is_file()
                    or hashlib.sha256(input_path.read_bytes()).hexdigest()
                    != input_info["sha256"]
                ):
                    artifact_ok = False
                if input_info.get("kind") == "public_key" and input_path.is_file():
                    try:
                        _, public_der = _evidence_public_key_bytes(
                            input_path.read_bytes()
                        )
                        if hashlib.sha256(public_der).hexdigest() != record.get(
                            "public_key_fingerprint"
                        ):
                            artifact_ok = False
                    except Exception:
                        artifact_ok = False
            scenario_config = record.get("scenario_configuration")
            if scenario_config is not None:
                scenario_bytes = json.dumps(
                    scenario_config, sort_keys=True, separators=(",", ":")
                ).encode()
                if hashlib.sha256(scenario_bytes).hexdigest() != record.get(
                    "scenario_sha256"
                ):
                    artifact_ok = False
            if not artifact_ok:
                raise ValueError(
                    "referenced artifact hash mismatch or missing artifact"
                )
            valid += 1
            click.echo(f"  VALID {record_path.relative_to(ws)}")
        except Exception as exc:
            invalid += 1
            click.echo(f"  INVALID {record_path.relative_to(ws)}: {exc}")

    click.echo(f"Evidence signatures: {valid} valid, {invalid} invalid")
    sys.exit(0 if invalid == 0 else 1)


def _evidence_public_key_bytes(pem: bytes) -> tuple[bytes, bytes]:
    try:
        key = serialization.load_pem_public_key(pem)
    except (ValueError, TypeError):
        key = serialization.load_pem_private_key(pem, password=None).public_key()
    return (
        key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ),
        key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ),
    )


@main.command(name="export-evidence")
@click.option(
    "--run-id", default=None, help="Run archive to export; defaults to the latest run."
)
@click.option(
    "--output",
    default=None,
    type=click.Path(path_type=Path),
    help="Output tar.gz bundle.",
)
@click.pass_context
def export_evidence(
    ctx: click.Context, run_id: str | None, output: Path | None
) -> None:
    """Export one portable run bundle with public verification material only."""
    ws = ctx.obj["workspace"]
    selected = _selected_run_ids(ws, run_id, False)[0]
    run_dir = ws / "evidence" / "runs" / selected
    if not _record_paths_for_runs(ws, [selected]):
        raise click.ClickException(
            "The selected run archive contains no evidence records"
        )
    output_path = (
        ws / output if output else ws / "evidence" / "exports" / f"{selected}.tar.gz"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    public_key = ws / "fixtures" / "keys" / "evidence-signer.pub.pem"
    if not public_key.is_file():
        raise click.ClickException(
            "Public evidence key missing; run bootlab sign-evidence first"
        )
    with tarfile.open(output_path, "w:gz") as archive:
        archive.add(run_dir, arcname=f"evidence/runs/{selected}", recursive=True)
        archive.add(public_key, arcname="fixtures/keys/evidence-signer.pub.pem")
        usage = (
            "BootLab evidence export\n\n"
            "Verify from the extracted bundle root with:\n"
            f"  bootlab --workspace . verify-evidence --run-id {selected}\n\n"
            "This bundle contains public verification material and immutable run inputs; it excludes private keys.\n"
        ).encode()
        info = tarfile.TarInfo("README-verify.txt")
        info.size = len(usage)
        import io

        archive.addfile(info, io.BytesIO(usage))
    click.echo(f"Exported {selected} to {output_path}")


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
    reproducers_dir = (
        ws / reproducers_dir if not reproducers_dir.is_absolute() else reproducers_dir
    )

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
