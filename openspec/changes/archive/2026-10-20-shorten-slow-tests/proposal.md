# Proposal

## Why

Four tests spend most of their time waiting out limits much longer than the behaviour they check needs (#84). Since
#83 the suite runs one xdist worker per CPU, so the longest single test sets the floor for the tests gate's wall time,
and cutting these waits shortens every local run, commit hook and CI job directly. Nothing records test durations
either, so the next slowdown is noticed by feel rather than read from a log.

Measured on this branch (macOS, one process, `--durations=0`):

| Test | Time | Where the time goes |
|---|---|---|
| `test_ordering_state_machine.py::TestTheatre::runTest` | 23.9 s | git subprocesses. The invariant reads the notifications twice and the branch twice on every step: about 5 s of repeated reads |
| `test_runner_conformance.py::test_a_runner_that_does_not_exit_on_end_of_input_fails_that_check` | 19.3 s | `run_timeout` 10 s, plus `cancel_grace` 3 s three times |
| `test_runner_conformance.py::test_a_runner_that_ignores_an_unknown_option_fails_that_check` | 10.3 s | `run_timeout` 10 s |
| `test_cli_runs.py::test_ctrl_c_twice_shows_the_notice_twice_and_still_records_the_end` | 10.6 s (#84's figure) | troupe's default 10 s cancel grace in a real `troupe` process |

The issue puts both conformance tests down to `cancel_grace`. Reading `check_runner` shows that most of it is
`run_timeout`: the fake runner never sends a result, so the whole-run check that ends every conformance run waits out
the full 10 s. A shorter `cancel_grace` alone would save about 6 s, not 25.

## What Changes

- **The two failing-runner conformance tests get their own short limits** (a short `cancel_grace` and `run_timeout`,
  with `start_timeout` left generous). They expect their check to fail by timing out, and a shorter limit can't make
  that check pass. The tests that expect a runner to *pass* keep today's generous `LIMITS`, because a real Python
  runner on a loaded Windows worker has to exit within it. Both tests still assert the same check and the same
  problem text.
- **The ordering state machine's invariant reads each value once per step.** It reads the notifications once and the
  branch once, and checks everything against those. Every assertion stays. `max_examples=8` and
  `stateful_step_count=12` don't change, so the coverage trade-off the issue warns about doesn't move.
- **The Ctrl-C test stays as it is, with a comment saying why.** Its 10 s is troupe's default
  `RUNNER_CANCEL_GRACE_SECONDS` in a real `troupe` subprocess, which a test can't shorten without a new product
  setting, and `test_run_host` already covers the kill-after-grace path quickly. The owner chose this on 2026-10-20,
  over a scripted-runner "exit after an ignored cancel" option (which would add a timing race) and over a
  cancel-grace setting (a product feature larger than #84).
- **`scripts/check.py` runs pytest with `--durations=25`**, in the full check and in scoped checks, so every local
  run, commit hook and CI job prints the 25 slowest tests.
- **The PR records the suite time before and after**, locally and for each CI platform.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `quality-check`: the check prints the slowest tests' durations on every run, full or scoped.

## Impact

- `scripts/check.py` (the tests gate's pytest arguments) and `scripts/tests/` (a test that the durations print under
  xdist).
- Tests only, elsewhere: `packages/troupe/tests/test_runner_conformance.py`,
  `packages/troupe-store-text/tests/test_ordering_state_machine.py` and `packages/troupe/tests/test_cli_runs.py` (a
  comment). No product code changes, and no limit's default changes.
- Every check's output gets a "slowest 25 durations" block before pytest's summary.
