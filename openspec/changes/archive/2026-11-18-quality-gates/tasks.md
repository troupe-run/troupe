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

- [x] 2.1 Add coverage, pytest-cov, lizard and pip-audit to the dev group; check the lock diff by package. Verify
      `uv sync --locked` passes. Done: the lock only adds packages (lizard, coverage, pytest-cov, pip-audit and
      pip-audit's dependencies); none changes
- [x] 2.2 `[tool.coverage.run]` in `pyproject.toml`; `quality-gates.toml` with the approved defaults. Verify
      `uv run scripts/quality_gates.py complexity --base origin/main` passes
- [x] 2.3 `scripts/check.py`: the complexity gate always, `--base`, and coverage and audit on the leg only, as
      infrastructure's; tests in `scripts/tests/`. Verify they pass, and a local full check takes about as long as
      before
- [x] 2.4 `ci.yml`: every leg fetches history and passes the base (bash and PowerShell); the Linux 3.15 leg is the
      coverage leg. Update `scripts/tests/test_ci_workflow.py`. Verify it passes
- [x] 2.5 Baselines: set each package's from this pull request's coverage leg, rounded down to 0.1; run the leg again on
      the same commit and set the tolerance from the difference (infrastructure design D4). Cite both runs. Done:
      CI run 44240981380, attempts 1 and 2, on f9f6bd6a; tolerance 0.6 (design D8)

## 2b. Runner exits and the delivered files' omission (design D6, D7)

- [x] 2b.1 `troupe_plugin_sdk.process.exit_now` with tests: plain `os._exit` without coverage loaded (never imports
      it, no `atexit`), and a process under coverage saves its data. Verify the saving test fails when the helper
      doesn't save. Done: it failed with saving removed; both pass with it
- [x] 2b.2 All six runners end through `exit_now`; a test runs the scripted runner under `coverage run` and finds its
      `exit_now` line in the saved data. Verify ruff, mypy and the import contracts. Done
- [x] 2b.3 `[tool.coverage.run] omit` uses globs for the delivered files, the mutation scripts included, and the
      complexity gate leaves them out too. Verify a coverage run of `scripts/tests` reports none of them, and CI's
      report agrees with a local one file by file. Done: none reported; CI's `scripts` is 88.5% without the
      delivered mutation files, the local figure

## 3. Weekly report (design D4)

- [x] 3.1 `.github/workflows/dependency-report.yml` and its test. Verify the test passes

## 4. Docs

- [x] 4.1 Say what the gates do and where their thresholds live in `contributing/` (or point to infrastructure's
      `docs/development-workflow.md`, "The merge gates"). Verify the docs tests pass. Done: in README.md's paragraph on
      the check, which is where the gates are listed

## Workflow follow-up

- After the merge, infrastructure's follow-up adds this repository's report to the schedule watch once it has run.
