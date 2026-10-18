# Proposal

## Why

The check step in CI roughly doubled between 12 and 13 October (#83): Ubuntu from ~1.25 to ~2.8 minutes, macOS from
~2.1 to ~4.7, Windows from ~2.6 to ~5.0, while the test count grew only about 25% (1,259 to 1,623). The suite runs in
one process, and almost all of its time is waiting, not computing: locally, 200 of 206 s is spent inside tests, and
six files that wait on subprocesses, grace periods or file watching take 64% of it. With one process every wait adds
straight to the total, and Windows and macOS, which start processes slowly, pay the most. Running the tests across
several processes is the largest cut available, and every local run, commit and CI job gets it through
`scripts/check.py`. The two Windows flakes #83 named as blockers (#81, and the wait that returned early, #112) are
fixed and closed by flake-hunt, whose Windows campaign came back clean.

## What Changes

- **`scripts/check.py` runs the tests with pytest-xdist** (`-n auto`, work-stealing distribution), for the full
  check and for scoped checks alike. Local runs, the commit hook and CI all get it, because they all run the same
  script. pytest-xdist is a dev dependency only.
- **Running `pytest` directly stays one process.** The option lives in `check.py`, not in the pytest configuration,
  so a developer narrowing to one test, the flake hunt's rounds and the scripts' own tests behave as they do today.
- **The protocol guard's end-of-run check works across workers.** Today it fails a full run when a catalogued error
  or notice code was never raised by troupe's own source, and it keeps that tally in a module-level set. Under xdist
  each worker would see only its own share, so every worker would report codes "unexercised" that another worker
  raised. Workers will send what they saw to the controller, which runs the check once, on the union.
- **The commit guard's tag rule is shown to hold in a parallel run.** `guard_pytest` (delivered from
  troupe-run/infrastructure) records reads per process. A test here proves that an untagged docs read still fails a
  parallel run. If it doesn't, the fix belongs in infrastructure and this change waits for it.
- **Shared state between workers is checked, not assumed:** the environment, the working directory, the hypothesis
  example database, the guards' module-level state, and anything a test writes outside `tmp_path`. A test that only
  passes alone is fixed. Marking a test serial is a last resort, used only when serial is the honest answer, with the
  reason given; it would come back to this change as a design update first.
- **Verified the way #83 asks:** CI passes on every job, five runs out of five, and the pull request records the check
  step's time per platform before and after.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `quality-check`: the check runs the tests across several processes, full and scoped; a full run's
  every-code-was-raised check holds whatever the number of workers; and "every test run keeps the declaration true"
  holds for parallel runs as well as serial ones.

## Impact

- `scripts/check.py` (the tests gate's command) and its tests in `scripts/tests/test_check_scope.py`.
- `packages/troupe/tests/protocol_guard.py`: the coverage tally moves from one process to the controller.
- `pyproject.toml` and `uv.lock`: pytest-xdist in the dev group.
- Any test found to share state across workers.
- Unchanged: the flake hunt (it runs pytest itself, with its own rounds and workers), `guard_pytest.py` (owned by
  infrastructure, unless the check above shows it needs a fix there), and CI's workflow, which already runs
  `scripts/check.py`.
- Separate: #84 (shorten the slowest tests' waits, print durations on every run). It helps either way, and its
  `--durations` works under xdist. After this change, the single longest test bounds the suite's wall time, so #84
  matters more.
