# Tasks

No load-heavy run is needed: the regression tests force the condition deterministically. If a confirming hunt is run,
it is `scripts/flake_hunt.py --load 2` at most, announced first, only while the 1-minute load is under ~40.

## 1. Reproduce the hang in a test first (D1, D4)

- [x] 1.1 In `scripts/tests/workspace/test_flake_campaign.py`, add
  `test_a_stop_landing_inside_the_wait_on_a_hunt_still_stops_promptly` (POSIX only, skip naming why): a child that
  exits with code 3 after a short pause, its `_waitpid_lock` swapped for a wrapper that takes the real lock and then
  calls `signal.raise_signal(SIGINT)` once, a watchdog that releases the real lock after a named bound, and a check
  that `wait()` raises `Stopped` within the bound with `returncode == 3` and the watchdog unfired. Assert the
  `_waitpid_lock` precondition first. Verify it **fails on today's code** (run the same body against today's
  `wait(process)`, which has no stop handling) and record what it showed here.
  *Done (2026-11-14):* on today's code it failed after 30.1 s with "the campaign was still waiting on an exited hunt
  after 30s". The campaign had printed "stopping", then could only see the hunt exit once the watchdog released
  `Popen`'s lock.
- [x] 1.2 Add `test_a_stop_between_hunts_records_the_hunt_and_runs_no_more`: a two-hunt campaign whose stand-in for the
  direct hunt raises a real `SIGINT` and returns a clean outcome. Expect one hunt recorded, `stopped` true in
  `campaign.json`, and exit 130 from `main`. Verify it fails on today's code (the hunt goes unrecorded) and record that.
  *Done:* on today's code it failed with `assert [] == [('direct-3.12-load0', 'clean')]`, because the
  `KeyboardInterrupt` unwound out of the finished hunt before it was recorded. With the fix, the stand-in also takes
  the `stopping` event that `run_direct` now receives.

## 2. Ctrl-C becomes a stop request (D2)

- [x] 2.1 In `scripts/flake_campaign.py`, add a context manager that installs `SIGINT` (and on Windows `SIGBREAK`)
  handlers that set a `threading.Event`, and restores the previous handlers on exit. Use it in `campaign()`, replacing
  the `SIGBREAK` handling and the `except KeyboardInterrupt` between hunts. Verify with
  `uv run pytest scripts/tests/workspace/test_flake_campaign.py`.
- [x] 2.2 Make `wait(process, stopping)` check the event rather than catch `KeyboardInterrupt`, keeping the
  `STOP_WAIT_SECONDS` grace, the kill, the printed line, and `Stopped`. Check the event after `uv sync`, the image
  build, `docker cp`, and before each hunt. Record a hunt stopped before it ran as stopped. Verify that 1.1 and 1.2
  now pass, and that the end-to-end interrupt test passes unchanged, its SIGABRT trap included (D5).
- [x] 2.3 Update the module docstrings and comments that describe Ctrl-C handling, and `contributing/flake-hunt.md` if
  it describes the campaign's stop. Verify by grepping for `KeyboardInterrupt` in `scripts/flake_campaign.py`, which
  should find no handler or `except` left (only `stop_requests`' docstring, which explains why).
  *Done:* the grep finds only the docstring. `contributing/flake-hunt.md` describes the stop in terms that haven't
  changed ("stops the running hunt cleanly, runs no more, and still writes the report"), so it stays as it is. At the
  owner's request, design D3 now records the check of every other `Popen` wait under Ctrl-C.

## 3. Verify

- [x] 3.1 Run `uv run mypy --platform win32` over `scripts/flake_campaign.py` and its test, since Windows-only branches
  are type-checked there. Then run the full `uv run scripts/check.py`, with its output written to a scratch file. Verify
  both pass.
  *Done:* mypy passes for darwin and win32. `check.py` passed every gate: 6372 passed, 17 skipped, in 4 min 2 s.
- [x] 3.2 Run the new tests 20 times in a row (`pytest --count` isn't installed, so use a loop of single runs, not
  load). Verify that all pass.
  *Done:* 20 of 20 passed. No stray processes were left.

## Workflow follow-up

- Draft PR closing #358, Claude review, CI on Linux, macOS and Windows, then `/opsx:archive` on the branch.
- After the merge: confirm #358 is closed and its card says Done.
