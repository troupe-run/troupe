# Proposal

## Why

CI's check legs are cancelled at 20 minutes, and Windows legs now run 19m52s–20m19s (#504, #505). A leg that runs
over fails `check`, so pull requests are dropped from the merge queue. The owner decided (2026-11-23, on #382) to give
the legs 30 minutes now, as its own small change, while #382 stays open for the cause: fewer expensive OS operations,
chosen later from numbers. Closes troupe#508.

## What Changes

- `.github/workflows/ci.yml`: the `check-legs` job's `timeout-minutes` goes from 20 to 30.
- That one job runs the check on every OS and Python for pull requests, merge groups (the merge-queue path) and
  pushes to main, so all three get the new limit. No other job runs the full check, and no other job changes:
  `changes` and `check` keep 5 minutes, and `release-install-check.yml`'s install job keeps its own 20.
- Three comments state the legs' 20-minute figure, and say 30 instead: the stall-limit comment in `pyproject.toml`,
  the `HTTP_RETRIES` docstring in `scripts/install_check.py` and `STALL_LIMIT_CEILING`'s docstring in
  `scripts/tests/test_check_parallel.py`. Their numbers (300 s, 600 s) still fit, so no value changes.
- No doc or spec states the figure. Only archived changes mention it, and archives are history,
  so they stay as they are.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. No requirement names the legs' time limit (`quality-check` and `installation` describe what the legs run, not
how long they may take). The change sets `skip_specs: true`.

## Impact

- `.github/workflows/ci.yml`, plus comments in `pyproject.toml`, `scripts/install_check.py` and
  `scripts/tests/test_check_parallel.py`. No behaviour outside CI changes, so it uses `ci:` commits and release-please
  sees no release-bearing change.
- A leg that hangs now holds a runner up to 10 minutes longer before it's cancelled.
- #382 stays open. This PR closes #508, not #382.
