# Tasks

## 1. Raise the check legs' limit

- [x] 1.1 Set `timeout-minutes: 30` on `check-legs` in `.github/workflows/ci.yml`, and leave every other job's limit
  alone. Verify: `git diff` shows that one line changed, and the workflow still parses
  (`python3 -c 'import yaml; yaml.safe_load(open(".github/workflows/ci.yml"))'`, and actionlint where the check runs
  it).
- [x] 1.2 Confirm no doc or spec outside `openspec/changes/archive/` states the check legs' 20-minute figure. Verify:
  `git grep -n -iE "\b20[- ]?min|timeout-minutes: 20"` lists only archived changes and `release-install-check.yml`.

## 2. Verify

- [x] 2.1 `uv run scripts/check.py` passes before the commit.

## Workflow follow-up

- Draft PR closing #508 (not #382), act on Claude's review, archive on the branch, mark it ready.
- On the ready PR, every leg passes under the new limit. A leg that runs past 20 minutes and still passes shows the
  limit took effect; the job log's duration is the evidence.
- After the merge, check #508 is closed and its card says Done; #382 stays open.
