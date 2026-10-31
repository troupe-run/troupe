# Tasks

## 1. Reproduce

- [ ] 1.1 Show the race deterministically on the unchanged test (design D2): locally add `wait_ms="2000"` to `_hanging_after_init`'s `_env` call, uncommitted. Verify: `uv run pytest plugins/runner-claude-code/tests/test_claude_code_runner.py -k terminated_by_someone_else` fails with `['init', 'log'] == ['init']`, CI's failure; record the output here

## 2. Fix

- [ ] 2.1 In `test_claude_terminated_by_someone_else_ends_the_run_with_no_result`, read messages until the first `run/event`, assert it is `init` with `engine.version` `9.9.9`, then wait for the record's `argv`, send SIGTERM, and assert the events in `rest()` are `[]`; the exit code (143) and the standard-error check stay (design D1). Verify: with the 1.1 delay still in place, the same pytest command passes
- [ ] 2.2 Remove the 1.1 delay. Verify: the pytest command passes, and `git diff` shows only the test's own change
- [ ] 2.3 Check the fixed test still fails for what it's named for: temporarily make the stand-in write one more line after its init before hanging (a `log`-mapped record, e.g. a `system` record of another subtype, appended to `_hanging_after_init`'s fixture), so an event follows init. Verify: the test fails on the `rest()` assertion; then revert, and `git diff` shows only 2.1's change

## 3. Verify

- [ ] 3.1 Run `uv run scripts/check.py`, and verify all gates pass (record the counts here)

## Workflow follow-up

- Open the PR as a draft with `Closes #206`; CI must pass on Linux, macOS and Windows (the test is skipped on Windows).
- Act on Claude's review of the last push, then archive the change on the branch (`/opsx:archive`) before merging. There are no delta specs to sync.
- After the merge, comment on #206 with the PR and the archived change, and check its card on the roadmap board says Done.
