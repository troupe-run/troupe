# Tasks

## 1. Reproduce

- [ ] 1.1 Add a `busy` mode to `packages/troupe/tests/interrupt_child.py` (design D2): after `READY` it writes a line of padding continuously, with `flush=True`, until it has counted a target number of interrupts (a named constant, about 10) or the 30 s deadline passes, then prints `RESTORED <bool>` and exits 0 only if it counted them all. Leave the callback as it is for now: it still prints from the handler. Add the test `test_interrupts_arriving_while_the_child_is_writing_do_not_kill_it` to `test_platform_interrupts.py`. It reads `READY`, then works in lockstep: it sends one interrupt (`_interrupt`), reads past the padding to `INTERRUPTED <n>`, and only then sends the next. Each read has a deadline and fails naming the lines it read. It then checks `RESTORED True`, exit code 0 and empty stderr. Add a comment saying the reproduction is statistical, with the scratch result (10 of 10 runs died with a callback that prints). Verify the reproduction: run the new test 5 times on macOS, in a shell loop of `uv run pytest "packages/troupe/tests/test_platform_interrupts.py::test_interrupts_arriving_while_the_child_is_writing_do_not_kill_it"`, and see it fail each time with `RuntimeError: reentrant call` in the child's stderr. If it doesn't fail reliably, raise the target count until it does.

## 2. Fix

- [ ] 2.1 Change the child's callback to only count (design D1). The main loop, in both modes, prints `INTERRUPTED <n>` for each interrupt counted but not yet reported, and reports any outstanding ones before `RESTORED`. Verify that the 1.1 test passes in 5 runs in a row on macOS, and that `uv run pytest packages/troupe/tests/test_platform_interrupts.py` passes. Also verify that `git grep -n "print" packages/troupe/tests/interrupt_child.py` shows no `print` inside `caught()`.
- [ ] 2.2 Name the hazard in `packages/troupe/src/troupe/platform/interrupts.py`'s module docstring: the handler can run inside the caller's own write to a stream, so the callback must do no I/O, `print` included. Change no code. Verify `git diff packages/troupe/src/troupe/platform/interrupts.py` touches only the docstring.
- [ ] 2.3 Update `interrupt_child.py`'s module docstring to describe the `busy` argument and that the main loop, not the handler, prints `INTERRUPTED <n>`. Verify it by reading the docstring against the code.

## 3. Check

- [ ] 3.1 Run `uv run scripts/check.py`, and verify all gates pass (ruff, mypy --strict, the test suite).

## Workflow follow-up

- Open the PR with `Closes #96`. CI must pass on Linux, macOS and Windows, including the new test on Windows (design D3).
- Archive the change on the branch (`/opsx:archive`) before merging. There are no delta specs to sync.
- After the merge, comment on #96 with the PR and the archived change.
