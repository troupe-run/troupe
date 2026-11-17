# Proposal: quality-gates

## Why

troupe-run/infrastructure#321 (owner, 2026-11-17) decided that every pull request in troupe, infrastructure and
website must pass coverage, complexity and dependency-audit gates; infrastructure#322 and #324 build them, with
defaults the owner approved on 2026-11-18. The measures are one module, `scripts/quality_gates.py`, written in
infrastructure and delivered here with the guard's files (infrastructure#328). This change is troupe's adoption. troupe
measures no coverage or complexity today, and nothing audits `uv.lock` on a pull request.

Measuring coverage showed one gap in troupe itself: a runner starts with nothing from troupe's environment, so
coverage.py's subprocess measurement never reaches runner code, and every runner package reads far lower than its tests
exercise (runner-scripted 51.8%, runner-claude-code 61.1%). The owner decided on 2026-11-18 that the runner policy
passes exactly one variable, coverage.py's own, and nothing else.

## What Changes

- **Runner environment:** `defaults.RUNNER_ENVIRONMENT` passes `COVERAGE_PROCESS_CONFIG` from troupe's environment,
  and nothing else. It holds coverage settings, never a secret, and is set only when troupe runs under coverage.
- `quality-gates.toml`: troupe's thresholds. One coverage package per workspace member and one for `scripts`, with
  baselines from CI's coverage leg when the gate lands and an 80% floor for a new package; a complexity limit of 25,
  tests, delivered files and generated code excluded; the `uv.lock` audit, blocking high and critical advisories that
  have a fix.
- `scripts/check.py` runs the complexity gate on every check, local and in every CI leg, and coverage and the audit on
  the Linux, Python 3.15 leg only (`QUALITY_GATES_LEG=true` under GitHub Actions; never locally).
- `.github/workflows/ci.yml`: every leg fetches the history it needs and passes each event's base; the Linux 3.15 leg
  is the coverage leg.
- `.github/workflows/dependency-report.yml`: the weekly "Dependency advisories" issue, with a board job using the
  `board` environment infrastructure#328 creates here.
- Dev dependencies: coverage, pytest-cov, lizard, pip-audit.

## Capabilities

### New Capabilities

None. The gates' behaviour is infrastructure's `quality-gates` spec.

### Modified Capabilities

- `actor-runners`: a runner's environment holds coverage.py's subprocess variable when troupe has it, and still
  nothing else of troupe's.
- `quality-check`: the check runs the complexity gate everywhere and the coverage and audit gates on one CI leg, with
  troupe's thresholds in `quality-gates.toml`; a weekly report covers the advisories no gate blocks on.

## Impact

- `packages/troupe/src/troupe/core/defaults.py` and its tests; `scripts/check.py` and its tests; `pyproject.toml`,
  `uv.lock`; `.github/workflows/ci.yml` and its tests; new `quality-gates.toml` and
  `.github/workflows/dependency-report.yml`; `contributing/` where the check is described.
- Lands after infrastructure#328 merges and its delivery of `scripts/quality_gates.py` is applied; the runner policy
  part can land first.
