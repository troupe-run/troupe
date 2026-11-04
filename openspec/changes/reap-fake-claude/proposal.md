# Proposal

## Why

`test_a_second_run_start_is_refused` leaves its hanging stand-in `claude` running after every run (#276). On
2026-11-04 the owner's Mac had 186 of them. troupe starts a runner in a process group of its own and kills that whole
group, so a real run leaves no Claude Code behind. The plugin's test harness doesn't. It starts the runner in pytest's
process group and kills only the runner's pid, which orphans the stand-in. Running the four hanging-stand-in tests on
`main` leaves exactly one stand-in, reparented to init and still in pytest's group. The other three tests end the run
through the runner (cancel, end of input, or a kill of the stand-in itself), so the runner stops the stand-in first.
Nothing checks for a leak, so the next test that leaves one will go unnoticed too.

## What Changes

- The Claude Code runner's test harness (`plugins/runner-claude-code/tests/claude_harness.py`) starts the runner the
  way troupe's platform does, in a process group of its own on POSIX. Its `kill()` kills that group, as troupe's
  `kill_tree` does, so the stand-in goes with the runner. On Windows the runner already puts Claude Code in a job
  that is killed when the runner's handle to it closes, and the harness relies on that.
- The stand-in (`fake_claude.py`) records itself in a ledger while it runs: a file named by its pid, which it holds
  locked until it ends. `install()` writes the ledger's directory into the shim, so every stand-in that troupe's
  core tests start is recorded as well as the plugin's.
- A pytest plugin (`stand_in_guard`, loaded through `addopts` for every test path, as `protocol_guard` is) checks
  after each test that every stand-in started during it has ended. It waits a short, named time for one to end, then
  stops any still running and fails the test's teardown. The failure names the stand-in's pid and working directory,
  which is under the test's temp directory. The lock means it only ever stops a process that is still the stand-in,
  never an unrelated one that happens to have the same pid.
- The runner and core don't change. A real run's teardown already stops Claude Code. What was missing was a harness
  that tears down the way that teardown does.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `claude-code-runner`: adds a requirement that the runner's tests leave no stand-in `claude` running. The harness
  stops the runner as troupe would, and a check fails any test that leaves a stand-in behind.

## Impact

- `plugins/runner-claude-code/tests/`: `claude_harness.py` (how the runner is started and killed), `fake_claude.py`
  (the ledger, its lock, and the shim's ledger variable), and new tests of both.
- `packages/troupe/tests/stand_in_guard.py` (new), and `pyproject.toml`'s pytest `addopts` (`-p stand_in_guard`).
  It loads `fake_claude.py` by path, as `claude_stand_in.py` already does, so the plugin's tests still import
  nothing from troupe.
- No change to the runner, core, the protocol or any spec Purpose, so nothing to update in infrastructure's
  `oob/troupe-spec-purposes.json`.
- Linux, macOS and Windows, all checked in CI.
