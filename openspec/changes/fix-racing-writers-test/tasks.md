# Tasks

## 1. Reproduce

- [ ] 1.1 Add a test of a new `outcome(stdout)` helper in `packages/troupe-store-text/tests/test_processes.py`, fed the real stdout from the failing CI run (`"waiting C:\\...\\.troupe\\local\\.lock\nintegrity-error\n"`, plus CRLF line endings as Windows writes them): it returns `integrity-error`. Also: a bare outcome returns itself, and an unexpected line before the outcome fails, naming that line. Before the helper exists, verify the reproduction: the racing test's current expression (`stdout.strip()`) on that real stdout gives `"waiting …\nintegrity-error"`, not `"integrity-error"`

## 2. Fix

- [ ] 2.1 Implement `outcome(stdout)`: split the output into lines, take the last as the outcome, and assert every earlier line starts with `waiting ` (the child's `on_wait` announcement), naming any line that doesn't. Verify the 1.1 tests pass
- [ ] 2.2 Read every child's outcome through `outcome()`: the racing-writers test and the cross-process subscription test, keeping their assertions (exactly one `integrity-error` and one `recorded`, one event in the stream; the subscription woken). Verify `uv run pytest packages/troupe-store-text/tests/test_processes.py` passes, and that `git grep -n "communicate(timeout=60)\[0\].strip()" packages/` returns nothing

## 3. Check

- [ ] 3.1 Run `uv run scripts/check.py`, and verify all gates pass

## Workflow follow-up

- Open the PR with `Closes #43`; CI must pass on Linux, macOS and Windows.
- Archive the change on the branch (`/opsx:archive`) before merging. There are no delta specs to sync.
- After the merge, comment on #43 with the PR and the archived change.
