# Proposal: run-test-timing

## Why

Two run tests fail depending on timing, and each has cost a CI round or a queued merge.

- **troupe-run/troupe#402.** `test_run_workspaces.py::test_the_start_names_the_worktree_and_worktree_made_records_its_clones`
  takes the run's first two events as `Run.Started` and `Run.WorktreeMade`. Making the worktree raises
  `workspace.waiting` once it has taken `WORKSPACE_ANNOUNCE_AFTER_SECONDS` (2 s), and that notice is recorded as
  `Run.Noticed` before `Run.WorktreeMade`, by design. On a loaded runner, `history()[1]` is the notice, and the test
  fails with `KeyError: 'clones'`. That took #379 out of the merge queue. Reproduced on this branch on macOS with the
  threshold at 0: the same `KeyError`.
- **troupe-run/troupe#405.** `test_cli_runs.py::test_logs_shows_events_on_stdout_and_notices_on_stderr` once read
  `running` on Windows where it expected `interrupted`, straight after killing the `perform` it started. The test's
  `Child` starts `sys.executable`. On Windows CI that's the venv's `python.exe`, a launcher that runs the real
  interpreter as its child in a kill-on-close job. `Child.kill()` kills and waits for the launcher, and the real
  `perform` is ended by the job a moment later, still holding the run's lease. So `logs` was right to say `running`
  at that moment. The test was waiting on the wrong process.

## What Changes

- **#402: events are found by type, not position.** The test picks `Run.Started` and `Run.WorktreeMade` out of the
  run's history by their topics. A copy of it runs with the announce threshold at 0, so a `workspace.waiting` notice
  always comes between them, and pins that. Every worktree-using test file was run with the threshold at 0
  (`test_run_workspaces.py`, `test_run_aggregate.py`, `test_run_changes.py`, `test_run_changes_recording.py`,
  `test_run_notices.py`, `test_perform.py`, `test_run_queries.py`, `test_cli_config.py`, `test_cli_runs.py`).
  Nothing else failed: the other positional reads are `[0]` (the start, always first) and `[-1]` (the end, always
  last).
- **#405: a killed `perform` is waited for itself, not its launcher.** `perform_child.py` reports its own pid with
  `STARTED`. `Child.kill()` kills the process it started, then waits, bounded and naming what it waits for, until
  that pid has ended (the platform seam's `is_running`). Every test that kills a `Child` and then reads the run's
  state gets the fix: `test_run_queries.py`'s interrupted-run tests as well as `test_cli_runs.py`'s.
- **A held lease whose holder has ended reads as `interrupted` (owner decision, 2026-11-13).** Once `perform` holds
  its run's lease, it writes its pid into the lease directory (`perform.pid`). When `lease_state` finds the lock
  held, it reads that pid and asks the platform seam whether the process has ended. If it has, the run is
  `interrupted`. A missing or unreadable pid file, a pid still running, or a process the OS can't answer for stays
  `running`, as today. This makes the state depend on whether the `perform` has gone, as the runs spec says, not on
  how soon the OS lets go of a dead process's lock. That timing isn't promised on Windows: `LockFileEx` says it
  "depends upon available system resources".

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `runs`: "A run's state is derived, never recorded as running" gains a scenario. A `perform` that has ended while
  its lease still reads as held is `interrupted`.

## Impact

- `packages/troupe/tests/test_run_workspaces.py`: the #402 test, and its threshold-0 pin.
- `packages/troupe/tests/perform_child.py` and `test_run_queries.py`'s `Child`: the perform's own pid, and waiting
  for it.
- `packages/troupe/src/troupe/core/runs/perform.py` (writes the pid) and `core/runs/queries.py` (`lease_state`
  reads it). `status`, `logs`, `accept`, `discard` and `diff` all derive state through `lease_state`.
- `contributing/runs.md`: the lease and the state table.
- No protocol, schema or dependency changes. `perform.pid` is local (`.troupe/local/`), never committed.
