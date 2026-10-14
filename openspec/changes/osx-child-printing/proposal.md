# Proposal

Issue: #96.

## Why

`test_each_interrupt_calls_back_instead_of_stopping_and_the_old_handler_returns`
(`packages/troupe/tests/test_platform_interrupts.py`) failed on macOS, Python 3.12, in PR #95's CI (run
38524210769), on a commit that changed only `tasks.md`. Its child process, `interrupt_child.py`, prints from its
interrupt callback. The test sends SIGINT as soon as it reads `READY`, and that `print` hadn't returned yet. The
callback's own `print` re-entered stdout's buffered writer and raised
`RuntimeError: reentrant call inside <_io.BufferedWriter name='<stdout>'>`. The child died, and the test read `''`
where it expected `INTERRUPTED 1`.

`troupe.platform.interrupts` already says the callback runs in the signal handler and "must be quick and safe to
call there: it asks for something to happen, it doesn't do it". troupe's one production caller follows that rule.
`cli/commands.py` hands over to the event loop "rather than print from here". The test child is the one caller that
breaks it, so the bug is in the test, not the seam. It's intermittent, so until it's fixed any PR can fail macOS CI
for no reason.

## What Changes

- **The test child's callback only records the interrupt** (it counts it). The child's main loop prints
  `INTERRUPTED <n>` outside the handler, once for each interrupt counted. The test then follows the pattern
  `interrupts.py` asks callers to follow, and an interrupt can arrive at any point in the child's output.
- **A regression test sends interrupts while the child is writing.** The child gets a mode where it writes output
  continuously, and the test interrupts it repeatedly mid-write. It checks that the child survives, counts every
  interrupt, and gets its previous handler back. In a scratch experiment on macOS, a child that prints from the
  callback died in 10 of 10 runs of this shape. A child that only counts died in 0 of 10. The race from #96 is then
  tested on every run, not only when a CI runner happens to be slow.
- **`interrupts.py`'s docstring names the hazard:** no I/O from the callback, `print` included, because the handler
  can run inside the caller's own write. The rule is already there; the example makes it harder to miss.
- What the existing tests prove is unchanged. Each interrupt calls back instead of stopping the process, and the
  previous handler comes back when the block ends. That holds for Ctrl-Break in its own process group and for a real
  Ctrl-C on Windows.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None: tests and a docstring only. No spec requirement changes. The callback rule is a code-level contract of
`troupe.platform.interrupts`, and the CLI already honours it. The change declares `skip_specs`.

## Impact

- `packages/troupe/tests/interrupt_child.py` and `packages/troupe/tests/test_platform_interrupts.py`.
- The docstring of `packages/troupe/src/troupe/platform/interrupts.py`. Its behaviour doesn't change.
- Out of scope: #81, #90 and #91. Those are other tests that assume a child is in a given state once they've read its
  output, and each is tracked on its own issue.
