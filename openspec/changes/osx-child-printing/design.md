# Design

## Context

See proposal.md, Why. `on_interrupt` installs a Python-level handler. CPython runs it in the main thread at the next
check for pending signals. That includes checks inside C code: when a `write` to the pipe is interrupted by a signal
(`EINTR`), the buffered writer checks for signals and runs the handler while it still holds its own lock. A handler
that writes to the same stream at that point raises `RuntimeError: reentrant call`. That's what happened in #96.

## Goals / Non-Goals

**Goals:**
- The interrupt tests pass wherever an interrupt lands relative to the child's own output.
- The race from #96 is exercised on every run, not left to CI timing.

**Non-Goals:**
- Changing `on_interrupt`'s behaviour or signature. For example, it won't defer the callback itself. The seam's
  contract is right, and its production caller follows it.
- Making stdout writes signal-safe in general.

## Decisions

### D1. The callback counts and the main loop prints

`caught()` only increments `count`. The loop keeps `reported` and prints `INTERRUPTED <n>` for each `n` from
`reported + 1` to `count`, then updates `reported`. It also drains any it hasn't reported before it prints
`RESTORED`, so an interrupt counted just as the loop ends still gets its line. The output protocol (`READY`,
`INTERRUPTED 1`, `INTERRUPTED 2`, `RESTORED <bool>`) and the exit code are unchanged, so the existing tests' reads
stay as they are.

*Alternative:* wait until the child confirms it's idle before signalling (the issue's second option). Rejected:
it's still a timing assumption, and it leaves a callback in the repo that breaks the rule `interrupts.py` states.
Related flakes (#81, #90, #91) come from exactly that kind of assumption.

### D2. A regression test where the child is writing when the interrupt lands

The child takes a new argument, `busy`. After `READY` it writes a line of padding continuously, with `flush=True`,
until it has counted a target number of interrupts or a deadline passes. It prints `INTERRUPTED <n>` from the main
loop as in D1, then `RESTORED <bool>`, and exits 0 only if it counted them all. The test works in lockstep. It sends
one interrupt, then reads past the padding until it sees `INTERRUPTED <n>`, and only then sends the next. The child
is writing all the time, so every interrupt lands while it's writing. Because the test waits for each line, a signal
can't be in flight when the child leaves the `on_interrupt` block. The test then checks `RESTORED True`, exit code 0
and an empty stderr.

The test's name claims only what it checks: that interrupts arriving *while the child is writing* don't kill it. It
can't prove that a given interrupt landed inside a `write`, so a comment says the reproduction is statistical. It
also records what the scratch experiment showed: 10 of 10 runs died with a callback that prints, and 0 of 10 with
one that counts. Task 1 reproduces the failure against the current child before the fix, so the test is seen to fail
for the right reason.

*Alternative:* call the handler directly in-process while a write is in progress. Rejected: forcing the handler to
run inside `BufferedWriter.write` needs an interrupted syscall, which a test can't arrange deterministically without
patching CPython internals. The subprocess shape is also the real one.

### D3. Bounded, on every platform

The busy test uses a fixed number of interrupts (a small constant, around 10) and the same 30 s deadline as the
existing child, so it never waits silently or indefinitely. It runs on Linux, macOS and Windows. On Windows the
interrupt is Ctrl-Break to the child's own process group, as in the existing test. A console control event doesn't
interrupt a pipe `write` with `EINTR`, so the reentrancy window may not exist there. The test still has to pass
there, and it checks the same behaviour.

## Risks / Trade-offs

- [The busy test could become flaky in its own right: an interrupt that arrives before the child installs its
  handler, or after it restores the old one, would kill it] → The test sends nothing until it has read `READY`, which
  the child prints inside the `on_interrupt` block. It sends each later interrupt only after reading the line for the
  one before, and none after the target. So no signal is ever pending when the old handler comes back.
- [A test that waits for each line could wait forever] → Each read has a deadline. The child's own 30 s deadline
  ends it, and the test fails with the lines it read rather than hanging (D3).
- [Lockstep sends fewer interrupts per second than a burst would, so each one is less likely to land inside a
  `write` syscall] → The child spends nearly all its time writing, and task 1 checks that the test fails against the
  current child before the fix. If it doesn't fail reliably, the target count goes up until it does.
