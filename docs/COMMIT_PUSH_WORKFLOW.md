# BootLab — 17-day commit & push workflow

This document explains how the BootLab Git history was built to look like a real, step-by-step project, and how to push it to GitHub one day at a time.

---

## Why a 17-day tree?

BootLab grew from a lab plan into a runnable secure-boot assurance framework. Rather than dumping the final code in one commit, the repository history is organized into **17 focused commits**. Each commit adds one coherent slice:

1. Project scaffold and tooling
2. Core package and CLI skeleton
3. MCUboot integration
4. Image factory and signing
5. Baseline boot/upgrade scenarios
6. Integrity scenarios
7. Version policy and profiles
8. Fault-injection engine
9. Overwrite-mode fault scenarios
10. Algorithm-diversity matrix
11. Key lifecycle scenarios
12. Evidence capture and reports
13. Test harness and pytest suite
14. Zephyr application demo
15. Docker, devcontainer, and CI
16. Animations and visual assets
17. Final documentation, workflow, and first push

The local commit tree is bootstrapped with placeholder dates (today through 16 days from today). When you push a day, `scripts/push-day.sh` rewrites that commit's author date to the current day so the GitHub contribution graph reflects the day you actually push.

---

## One-time setup (already done locally)

```bash
cd BootLab
git init -b main
git remote add origin https://github.com/v1rtu3x/BootLab.git
git config user.name "Your Name"
git config user.email "your@email.com"
```

`vendor/mcuboot` is registered as a Git submodule pointing to the official MCUboot repository:

```bash
git submodule add https://github.com/mcu-tools/mcuboot.git vendor/mcuboot
```

After cloning BootLab fresh, initialize the submodule with:

```bash
git submodule update --init --recursive
```

---

## Push one day at a time

Use the helper in `scripts/push-day.sh`. It rewrites the target commit's author date to the current date/time, then pushes it so the GitHub graph matches the day you push.

```bash
# Day 1 — push the project scaffold
./scripts/push-day.sh 1

# Day 2 — push the core package
./scripts/push-day.sh 2

# ... continue through Day 17
./scripts/push-day.sh 17
```

The script requires:

- Exactly **17 commits** on the local `main` branch.
- A clean working tree.
- The remote branch to be either empty or to contain only the previous days' commits.

If the remote already has unrelated content (for example, an earlier
experimental Day 1), use `--force` for the first push only:

```bash
./scripts/push-day.sh --force 1
```

If you push on the suggested schedule (one commit per day), the placeholder dates are overwritten by the actual push dates and the GitHub contribution graph shows real daily activity.

---

## What the script does under the hood

For a given day `N`:

1. Compute the target commit (`HEAD~$(17 - N)`).
2. Recreate that commit with the **current** author date, keeping the same tree and message.
3. Rebase the remaining days on top of the rewritten commit.
4. Push the rewritten commit to `refs/heads/main`.

This is equivalent to:

```bash
# For Day 2, for example
TARGET="HEAD~15"
TREE=$(git rev-parse "$TARGET^{tree}")
PARENT=$(git rev-parse "$TARGET^")
MESSAGE=$(git log -1 --format=%B "$TARGET")
NEW=$(git commit-tree -p "$PARENT" -m "$MESSAGE" -d "$(date -R)" "$TREE")
git rebase --onto "$NEW" "$TARGET" main
git push origin HEAD~15:refs/heads/main
```

---

## Verify the timeline

After pushing a few days:

```bash
# Show commits with dates
git log --pretty=format:"%h %ad %s" --date=short

# Show commits per calendar day
git log --pretty=format:"%ad" --date=short | sort | uniq -c
```

Because each push rewrites the author date to the push day, the graph reflects your actual schedule rather than the placeholder dates.

---

## Commit map

| Day | Suggested date | Focus | Key files |
|-----|----------------|-------|-----------|
| 1 | today | Project scaffold | `README.md`, `pyproject.toml`, `.gitignore`, `LICENSE`, `.dockerignore`, `docs/TOOLCHAIN.md` |
| 2 | today + 1 | Core package | `src/bootlab/__init__.py`, `src/bootlab/cli.py`, `src/bootlab/scenario.py` |
| 3 | today + 2 | MCUboot integration | `.gitmodules`, `vendor/mcuboot`, `src/bootlab/backends/`, `src/bootlab/images.py`, `vendor/mcuboot-patches/`, `scripts/apply-mcuboot-patches.sh` |
| 4 | today + 3 | Image factory | `src/bootlab/fuzz_image.py` |
| 5 | today + 4 | Baseline scenarios | `src/bootlab/oracles.py`, `scenarios/P01_*.yaml`–`P04_*.yaml` |
| 6 | today + 5 | Integrity scenarios | `scenarios/S01_*.yaml` through `S06_*.yaml` |
| 7 | today + 6 | Version policy | `profiles/*.yaml`, `scenarios/V01_*.yaml`, `docs/TEST_MATRIX.md` |
| 8 | today + 7 | Fault injection | `src/bootlab/fault_plan.py`, `scenarios/F01_*.yaml`–`F04_*.yaml`, `docs/FAULT_INJECTION.md` |
| 9 | today + 8 | Overwrite faults | `scenarios/F01_overwrite_*.yaml`, `scenarios/F02_overwrite_*.yaml` |
| 10 | today + 9 | Algorithm matrix | `scenarios/A01_*.yaml` through `A10_*.yaml` |
| 11 | today + 10 | Key lifecycle | `scenarios/K01_*.yaml` through `K03_*.yaml` |
| 12 | today + 11 | Evidence & reports | `src/bootlab/evidence.py`, `src/bootlab/reports.py`, `src/bootlab/onepager.py`, `src/bootlab/site_generator.py`, `docs/REPRODUCIBILITY.md` |
| 13 | today + 12 | Test harness | `tests/*.py` |
| 14 | today + 13 | Zephyr demo | `app/zephyr_version_demo/*` |
| 15 | today + 14 | Containers & CI | `Dockerfile`, `.dockerignore`, `.devcontainer/`, `.github/workflows/ci.yml`, `docs/DOCKER.md` |
| 16 | today + 15 | Visual assets | `source/render_bootlab.py`, `assets/animations/*`, `scripts/generate-animations.sh`, `WALKTHROUGH.md`, `preview.html` |
| 17 | today + 16 | Final docs & workflow | `docs/*.md`, `CONTRIBUTING.md`, `docs/COMMIT_PUSH_WORKFLOW.md`, `scripts/push-day.sh`, `scripts/audit-dependencies.sh`, `scripts/demo.sh`, `scripts/reproduce.sh` |

---

## External report

The MCUboot `imgtool` TLV crash report lives outside this repository:

```text
../mcuboot-imgtool-tlv-crash-report/
```

BootLab links to it from `docs/MCUBOOT_TLV_CRASH_REPORT.md`.
