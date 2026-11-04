# Proposal

## Why

`test_a_second_run_start_is_refused` leaves its hanging stand-in `claude` running after every run (#276). On
2026-11-04 the owner's Mac had 186 of them. troupe starts a runner in a process group of its own and kills that whole
group, so a real run leaves no Claude Code behind. The plugin's test harness doesn't. It starts the runner in pytest's
process group and kills only the runner's pid, which orphans the stand-in. Running the four hanging-stand-in tests on
`main` leaves exactly one stand-in, reparented to init and still in pytest's group. The other three tests end the run
through the runner (cancel, end of input, or a kill of the stand-in itself), so the runner stops the stand-in first.
Nothing checks for a leak, so the next test that leaves one would go unnoticed too.

## What Changes

- The Claude Code runner's test harness (`plugins/runner-claude-code/tests/claude_harness.py`) starts the runner the
  way troupe's platform does, in a process group of its own on POSIX. Its `kill()` kills that group, as troupe's
  `kill_tree` does, so the stand-in goes with the runner. On Windows the runner already puts Claude Code in a job
  that is killed when the runner's handle to it closes, and the harness relies on that.
- The runner tests' `sessions` fixture checks at teardown that each session's stand-in has ended, once its runner is
  killed. It reads the stand-in's pid from the record every runner test already has it write. A stand-in still running
  after a short, named wait fails the test, naming its pid and workspace.
- `test_a_second_run_start_is_refused` waits for its stand-in's record before it ends, so the check sees the stand-in
  it started.
- The runner and core don't change. A real run's teardown already stops Claude Code. What was missing was a harness
  that tears down the way that teardown does.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `claude-code-runner`: adds two requirements. The runner's tests stop it as troupe would, and a runner test that
  leaves its stand-in `claude` running fails.

## Impact

- `plugins/runner-claude-code/tests/claude_harness.py` (how the runner is started and killed, and the check) and
  `test_claude_code_runner.py` (the fixture, a test of the kill, and the wait in the #276 test).
- No change to the runner, core, the protocol, the configuration or any spec Purpose, so nothing to update in
  infrastructure's `oob/troupe-spec-purposes.json`.
- Linux, macOS and Windows, all checked in CI.
