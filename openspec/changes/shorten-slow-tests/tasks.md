# Tasks

## 1. Baseline

- [x] 1.1 Record the "before" times: the local tests gate (`uv run scripts/check.py` on this branch before any code
  change, the `tests passed in …s` line), and the tests gate time for each platform from the latest full CI run on
  `main`. Verify by writing them into a scratch note for the PR body, with the run's URL.

## 2. Conformance tests (design D1)

- [x] 2.1 In `packages/troupe/tests/test_runner_conformance.py`, add `EXPIRING = RunLimits(start_timeout=10.0,
  cancel_grace=1.0, run_timeout=1.0)` with a docstring saying it's for checks expected to fail by timing out, and why
  `LIMITS` stays generous for the rest. Give `_check` a `limits` parameter (default `LIMITS`), and pass `EXPIRING` from
  `test_a_runner_that_ignores_an_unknown_option_fails_that_check` and
  `test_a_runner_that_does_not_exit_on_end_of_input_fails_that_check`. Leave their assertions unchanged. Verify:
  `uv run pytest packages/troupe/tests/test_runner_conformance.py --durations=0` passes, and both tests take a few
  seconds, not 10 to 19.
- [x] 2.2 Show that both tests still fail when their check would pass: temporarily make the fake's `ignore-eof` mode
  exit on end of input, and its `ignore-options` mode refuse the unknown option. Each test must then fail. Revert
  without committing the change. Verify by noting both failures in the PR.

## 3. Ordering state machine (design D2)

- [x] 3.1 In `packages/troupe-store-text/tests/test_ordering_state_machine.py`, change `the_order_holds` to read the
  notifications once and the branch once, keeping every assertion, and keeping `reader.notices()` after the read.
  Leave `max_examples` and `stateful_step_count` as they are. Verify: the test passes, and `--durations=0` shows it
  faster than the 23.9 s baseline.
- [x] 3.2 Differential check: with a temporary mutation that breaks the order (for example, the store skipping a
  notification number), confirm that the old invariant (on `main`) and the new one both fail. Revert without
  committing. Verify by noting the mutation and both failures in the PR.

## 4. Ctrl-C test (design D3)

- [x] 4.1 Add a comment above `test_ctrl_c_twice_shows_the_notice_twice_and_still_records_the_end` in
  `packages/troupe/tests/test_cli_runs.py`. Say that its ~10 s is the default `RUNNER_CANCEL_GRACE_SECONDS` in a real
  `troupe perform` subprocess, that the ignored cancel is what keeps the run cancelling for the second Ctrl-C, that
  `test_run_host`'s `test_a_runner_ignoring_cancel_is_killed_with_the_process_it_started` covers kill-after-grace
  quickly, and that shortening it needs a cancel-grace setting, out of scope for #84. Verify: ruff passes and the test
  still passes.

## 5. Durations on every run (spec: quality-check; design D4)

- [x] 5.1 Add `--durations=25` to the tests gate's command in `scripts/check.py` (before any `-m`), as a named
  constant with a docstring next to `PARALLEL`. Verify: `uv run scripts/check.py --scope docs` prints a
  "slowest 25 durations" block.
- [x] 5.2 Add tests in `scripts/tests/test_check_parallel.py`: the gate's command (with `PARALLEL` and the durations
  option) prints the durations table across 2 workers for a passing suite and for a failing one, and `gates()` gives
  the option for a full and a scoped check. Verify: the new tests pass, and fail with the option removed.
- [x] 5.3 Add one sentence to the `README.md` paragraph about `scripts/check.py` saying the tests gate prints the 25
  slowest tests. Verify: the docs tests pass (`uv run scripts/check.py --scope docs`).

## 6. Integration

- [ ] 6.1 Run the full `uv run scripts/check.py` and record the local "after" tests gate time alongside the baseline.
  Verify: every gate passes, and the durations table shows the four tests' new times.
- [ ] 6.2 Open the PR (`Closes #84`), with the before and after suite times locally and for each CI platform, the
  findings from 2.2 and 3.2, and a note that the conformance waits were mostly `run_timeout`, not `cancel_grace`.
  Verify: every CI job passes on Linux, macOS and Windows, and the PR body has the after-times for each platform from
  that run.

## Workflow follow-up

- Run `/opsx:archive` on the branch before merging.
- After the merge, check that #84 is closed, comment on it with the PR and the archived change, and set its roadmap
  card to Done.
