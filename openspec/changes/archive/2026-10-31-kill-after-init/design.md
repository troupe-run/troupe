# Design

## Context

See proposal.md, "Why", for the race. The relevant mechanics:

- `fake_claude.py`'s `main()` installs its SIGTERM handler (exit 143), writes its record with `pid`, reads stdin,
  writes the record again with `argv` and the rest, then writes the fixture's lines to stdout and, with
  `FAKE_CLAUDE_HANG=1`, hangs. `FAKE_CLAUDE_WAIT_MS` delays the fixture's lines.
- `_hanging_after_init` gives the stand-in a fixture of one init line (`INIT_LINE`, `claude_code_version` 9.9.9) and
  makes it hang after it.
- The runner maps Claude Code's init record to an `init` event whose `engine` names `claude-code` and the record's
  version. When Claude Code's output ends with no init, `Mapper.finish` sends a synthetic `init` (no `engine`) and an
  error `log`.
- `Session.message()` reads one message; `Session.rest()` reads every message until the runner's output ends.

## Goals / Non-Goals

**Goals:**
- The test only ever terminates a Claude Code that has reported its init, so it checks the state its name is about.
- It still fails if the runner sends any event after init, sends a `result`, or exits other than 143.

**Non-Goals:**
- No change to the runner, the stand-in or the harness. The runner's handling of a kill before init is right and is
  already covered by `test_claude_exiting_before_its_init_gives_a_synthetic_init_a_log_and_no_result`.

## Decisions

### D1: Read messages until the `init` event, then kill

The test reads messages after `run/start` until the first `run/event`, asserts it is `init` with an `engine` (version
9.9.9, from `INIT_LINE`), then waits for the record's `argv` (for the pid) and sends SIGTERM. The events it then reads
with `rest()` must be none; the old `== ["init"]` becomes `== []` on the remaining events, with the `init` checked
before the kill. This is the same pattern as the cancel test above it, so the two read alike.

Asserting the `engine` matters: a synthetic `init` also has type `init`, so without it the test couldn't tell a real
init from the runner's stand-in for a missing one.

- *Alternative: have the stand-in write its record after its init line.* Every test that waits on `argv` would then
  shift, and the record's "written before output" ordering is what lets the cancel test act before output ends.
- *Alternative: a delay before the kill.* It narrows the window without closing it.

### D2: Show the race deterministically, before and after

Before the fix, run the old test with `FAKE_CLAUDE_WAIT_MS` set (for example 2000) on the stand-in, added locally to
`_hanging_after_init`'s environment and not committed. The kill then always lands before init, and the test fails with
`['init', 'log']`, which is CI's failure. With the fix and the same delay, the test passes, because it waits for init
whatever the delay. Then revert the delay. This proves both that the cause is the one the issue names and that the fix
removes it, without a load run.

### D3: The other early stops don't share the race

Each test that stops the stand-in once its record appears was checked:

| Test | Stop | Why it has no race |
|---|---|---|
| `test_cancel_mid_run_stops_claude_before_the_runner_exits_and_sends_no_more_events` | `run/cancel` | Already waits for `init` first; and cancel sends no events either way |
| `test_end_of_input_mid_run_stops_claude_and_then_the_runner_exits` | stdin closed | End of input stops Claude Code as cancel does, sending no events, and the test asserts none: only exit 0, the stand-in gone and the private files removed. "Mid run" holds once Claude Code is started, init or not |
| `test_the_stand_in_exits_143_on_sigterm_as_claude_code_does` (`test_claude_code_fake.py`) | SIGTERM | Runs the stand-in directly and asserts only its exit code; its handler is installed before the record is written |
| `test_cancelling_a_claude_code_run_ends_it_cancelled_within_the_grace` (`packages/troupe/tests/test_claude_code_host.py`) | host cancel | Asserts the outcome (`cancelled`, exited, within the grace). A cancelled runner sends no events, and a cancelled run with no result is `cancelled` whether or not init came |

## Risks / Trade-offs

- [The test now waits for init, so a runner that never sends init could hang it] → `Session.message()` is bounded:
  it fails with "the runner ended its output" at end of output, and its queue read raises `queue.Empty` after the
  harness's `TIMEOUT`. The cancel test already relies on the same bound.
