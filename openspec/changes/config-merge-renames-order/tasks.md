# Tasks

## 1. Test first

- [x] 1.1 Pin the found history in `test_config_merge_renames.py`: every order it can arrive in gives qa, reviewer and
  the new tester, with the clash on tester. Verify: it fails on main without the saved Hypothesis database.

## 2. Fix

- [x] 2.1 In `entities.py`'s clash settling, contest a key's remaining name writes again once its renames are left out
  (design D1). Verify: the pinned test passes, and so does the saved example (run from `packages/troupe`, where the
  database is).
- [x] 2.2 Run the config merge suites and the rename properties with more examples (`--hypothesis-profile` or a raised
  `max_examples` locally, not committed). Verify: all pass.
- [x] 2.3 Run a local mutation run on `troupe.core.config.entities` over unit tests only, and put the result in the PR.
  Verify: no surviving mutant in the changed lines, or each one explained.
- [x] 2.4 `uv run scripts/check.py` passes.

## Workflow follow-up

- Draft PR closing #532; act on the review; mark ready; archive; owner merges.
