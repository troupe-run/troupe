# Proposal

Issue: #206.

## Why

`test_claude_terminated_by_someone_else_ends_the_run_with_no_result`
(`plugins/runner-claude-code/tests/test_claude_code_runner.py`) failed once on `check (ubuntu-latest, Python 3.15)` in
CI run 41172944756 (#205, a CI-and-scripts-only head) with `assert ['init', 'log'] == ['init']`. The other 11 legs
passed.

The test sends SIGTERM to the stand-in claude as soon as the stand-in's record holds `argv`. `fake_claude.py` writes
that record **before** it writes the fixture's init line to stdout. If the signal lands between the two, Claude Code
has ended before its init, and the runner does what the spec's "Claude Code exits before its init" scenario says: a
synthetic `init`, an error `log` naming exit code 143, and no `result`. That is the `['init', 'log']` CI saw. The
runner is right; the test didn't wait for the state its name is about, a Claude Code run that is under way (it has
reported its init) when someone else terminates it.

## What Changes

- **The test waits for the runner's `init` event before it sends SIGTERM**, as
  `test_cancel_mid_run_stops_claude_before_the_runner_exits_and_sends_no_more_events` just above it already does. The
  kill can then only land after Claude Code's init.
- **What it asserts is unchanged in substance:** the first event is `init`, from Claude Code's init record (it has an
  `engine`, so it isn't the synthetic one), no event follows it, the runner exits 143, and its standard error says
  Claude Code exited with code 143 and sent no result.
- **The other tests that stop the stand-in early were checked for the same race, and none has it** (design D3): each
  either sends no events after the stop by spec (cancel, end of input) or asserts nothing about events.
- **The race is shown before the fix and gone after it**, deterministically rather than by load: with the stand-in
  delaying its output (`FAKE_CLAUDE_WAIT_MS`), the old test fails with `['init', 'log']` every time, and the fixed
  test passes (design D2).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None: tests only. The claude-code-runner spec's "Claude Code exits before its init" and "Terminated without a result"
scenarios already describe both sides of the race, and the runner's behaviour doesn't change. The change declares
`skip_specs`.

## Impact

- `plugins/runner-claude-code/tests/test_claude_code_runner.py`: the one test.
- No production code, fixtures, stand-in or harness changes.
