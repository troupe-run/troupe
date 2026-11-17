# Tasks

Load rule for every full run below: check `uptime` first, start only when the 1-minute load is under 40, and run one
at a time.

## 1. The runner policy (design D1)

- [x] 1.1 Tests first in `packages/troupe/tests/test_platform_environment.py`: the runner policy passes
      `COVERAGE_PROCESS_CONFIG` with the source's value; it passes no other variable, including `COVERAGE_FILE`,
      `COVERAGE_PROCESS_START` and credentials (a property test over generated sources). Verify they fail on main
- [x] 1.2 Change `defaults.RUNNER_ENVIRONMENT` and its docstring, and `contributing/platform.md` and
      `contributing/runners.md`, which describe the policy. Verify 1.1 passes, and the existing "selects nothing from
      the parent" test is renamed for what it now checks. Done: 13 passed; both new tests failed on main first

## 2. Adoption (design D2, D3), after the delivery of `scripts/quality_gates.py`

- [ ] 2.1 Add coverage, pytest-cov, lizard and pip-audit to the dev group; check the lock diff by package. Verify
      `uv sync --locked` passes
- [ ] 2.2 `[tool.coverage.run]` in `pyproject.toml`; `quality-gates.toml` with the approved defaults. Verify
      `uv run scripts/quality_gates.py complexity --base origin/main` passes
- [ ] 2.3 `scripts/check.py`: the complexity gate always, `--base`, and coverage and audit on the leg only, as
      infrastructure's; tests in `scripts/tests/`. Verify they pass, and a local full check takes about as long as
      before
- [ ] 2.4 `ci.yml`: every leg fetches history and passes the base (bash and PowerShell); the Linux 3.15 leg is the
      coverage leg. Update `scripts/tests/test_ci_workflow.py`. Verify it passes
- [ ] 2.5 Baselines: set each package's from this pull request's coverage leg, rounded down to 0.1; run the leg again on
      the same commit and set the tolerance from the difference (infrastructure design D4). Cite both runs

## 3. Weekly report (design D4)

- [ ] 3.1 `.github/workflows/dependency-report.yml` and its test. Verify the test passes

## 4. Docs

- [ ] 4.1 Say what the gates do and where their thresholds live in `contributing/` (or point to infrastructure's
      `docs/development-workflow.md`, "The merge gates"). Verify the docs tests pass

## Workflow follow-up

- After the merge, infrastructure's follow-up adds this repository's report to the schedule watch once it has run.
