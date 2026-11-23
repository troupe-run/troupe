# Tasks

## 1. Raise the check legs' limit

- [x] 1.1 Set `timeout-minutes: 30` on `check-legs` in `.github/workflows/ci.yml`, and leave every other job's limit
  alone. Verify: `git diff` shows that one line changed, and the workflow still parses
  (`python3 -c 'import yaml; yaml.safe_load(open(".github/workflows/ci.yml"))'`, and actionlint where the check runs
  it).
- [x] 1.2 Say 30 minutes wherever the code states the legs' limit: the stall-limit comment in `pyproject.toml`, the
  `HTTP_RETRIES` docstring in `scripts/install_check.py`, and `STALL_LIMIT_CEILING`'s docstring in
  `scripts/tests/test_check_parallel.py`. Their numbers stay: 300 s and 600 s still fit 30 minutes less a Windows leg
  of up to 20. Verify: `git grep -n -iE "(^|[^0-9])20[- ]?min|timeout-minutes: 20" -- ':!openspec/changes/archive'`
  lists only `release-install-check.yml` (`git grep -E` has no `\b`, which hid these three at first).

## 2. Verify

- [x] 2.1 `uv run scripts/check.py` passes before the commit.

## Workflow follow-up

- Draft PR closing #508 (not #382), act on Claude's review, archive on the branch, mark it ready.
- On the ready PR, every leg passes under the new limit. A leg that runs past 20 minutes and still passes shows the
  limit took effect; the job log's duration is the evidence.
- After the merge, check #508 is closed and its card says Done; #382 stays open.
