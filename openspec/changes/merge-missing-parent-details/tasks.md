# Tasks

## 1. Tests first

- [ ] 1.1 Add a unit test that merges an in-memory history whose event names a parent that isn't there, and checks the
  error's code, path and details (`line`, `event`, `missingParent`, `onlyIn`). Verify: it fails on main (the protocol
  guard refuses the details).
- [ ] 1.2 Add an integration test in `test_config_merge.py` that records config twice in a git theatre, removes the
  first segment, and reads config. Verify: it fails on main the same way.

## 2. Fix

- [ ] 2.1 Give `_check_parents` in `core/config/merge.py` the `line` and `event` details, and the same in
  `tests/merge_oracle.py`. Verify: both tests pass.
- [ ] 2.2 Run a local mutation run on `troupe.core.config.merge` over unit tests only, and note the result for
  `_check_parents` in the PR. Verify: no surviving mutant in the details it builds, or each survivor explained.
- [ ] 2.3 `uv run scripts/check.py` passes.

## Workflow follow-up

- Draft PR closing #506; act on the review; mark ready; archive; owner merges.
