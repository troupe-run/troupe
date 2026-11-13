# Design: run-test-timing

## Context

See proposal.md, "Why". The two parts share nothing but their kind: a test that assumed an order or a moment that
timing doesn't guarantee.

- `history(made, run_id)` in `test_run_workspaces.py` returns each recorded event's state, in order. The topic
  (`Run.Started`, `Run.Noticed`, `Run.WorktreeMade`, ...) is on the stored event, and the file already reads it
  (`topics()`, `topics_besides_notices()`, added for #336/#357, the same kind of flake).
- `Child` (`test_run_queries.py`, also used by `test_cli_runs.py`, `test_run_notices.py` and
  `test_run_workspaces.py`) runs `perform_child.py` with `sys.executable`. On Windows under `uv run`, that's
  `.venv\Scripts\python.exe`, a launcher whose child is the real interpreter (troupe #92, #55).
- `lease_state` (`core/runs/queries.py`) tries the run's lease lock with `timeout=0`: taken means `interrupted`, held
  means `running`. Locks are `msvcrt.locking` on Windows and `flock` elsewhere (`platform/locks.py`). Lock fds are
  opened with `os.open`, so they're not inheritable, and no troupe spawn sets `close_fds=False`. A runner can't hold
  its perform's lease.

## Goals / Non-Goals

**Goals:**

- Each of the two tests passes whatever the timing, and checks what it did before.
- A regression of either is caught deterministically, not by waiting for a loaded runner.

**Non-Goals:**

- Changing how a run's state is derived. See D3 for why the product is right as it is, and what would show
  otherwise.

## Decisions

### D1. Find a run's events by topic

A helper in `test_run_workspaces.py`, `event_of(made, run_id, topic)`, returns the state of the one recorded event
with that topic, failing with the topics it found if there isn't exactly one. The #402 test reads `Run.Started` and
`Run.WorktreeMade` through it.

*Alternative:* filter out `Run.Noticed` and keep the positions, as `topics_besides_notices` does. That still assumes
the order of everything else, which the test doesn't need, and `[:2]` would still read the wrong event if another
kind of event were ever recorded between the two.

### D2. Pin it with the threshold at 0

A second test runs the same body with `defaults.WORKSPACE_ANNOUNCE_AFTER_SECONDS` at 0 (monkeypatched, as
`test_a_slow_worktree_operation_is_announced_naming_it` does). It also asserts that at least one `workspace.waiting`
was recorded before `Run.WorktreeMade`, so the pin can't pass by the notice not happening. On main this test fails
with the `KeyError` from #402, and that failing run is recorded in the PR.

The other positional reads in the file are `[0]`, the start, which is always recorded first, and `[-1]`, the end,
always last. The whole file, and the other eight files that run worktrees, passed with the threshold at 0 for every
test (a pytest plugin that monkeypatches it, from outside the repository). So none of them needs changing.

### D3. Wait for the perform's own process (#405)

`perform_child.py` prints `STARTED <run id> <pid>`, its own `os.getpid()`. `Child` keeps both. `Child.kill()`:

1. kills the process it started (the launcher on Windows CI, the interpreter elsewhere), and waits for it, as now;
2. if the perform's own pid is still running (platform `is_running`), ends it too (`os.kill(pid, signal.SIGTERM)`,
   which on Windows is `TerminateProcess`). Normally the launcher's job has already ended it, but nothing in the test
   should depend on how the launcher is built;
3. waits with `wait_until` (bounded by `WITHIN`, naming the pid) until that pid has ended.

After that the perform is gone, so `interrupted` is the only right answer. The #405 test's assertion message carries
the time from the kill to the end of step 3, and the time from then to `logs` returning, for any later Windows
failure.

Why the product needn't change: on Windows, a handle's byte-range locks are released when it's cleaned up (closed),
and a process's handles are closed during its exit, before the process object is signalled. So once `is_running`
says a process has ended, its locks are free. The `LockFileEx` documentation's warning, that unlocking "depends upon
available system resources", is about a process that is still terminating. That's the window the old test sat in.

*Alternative considered and dropped:* perform records its pid in the lease, and `lease_state` treats a held lock
whose holder has ended as `interrupted`. That would be the fix if Windows held a lock past its holder's end. The
reasoning above says it doesn't, and D3's diagnostics would show it if it did. Building it now would add a recorded
file and a second source of truth for a case not shown to exist.

*Alternative:* run `sys._base_executable` so there's no launcher. The child then needs the venv's paths set up by
hand, and #55 found that it didn't remove that flake's cause. Waiting on the real pid works whatever starts it.

## Risks / Trade-offs

- [The real interpreter's pid is reused before step 3 looks] → Step 3 starts straight after the launcher's wait, and
  a reused pid would only make it wait the full `WITHIN` and fail naming the pid. It can't make the test pass wrongly.
- [Windows does hold the lock past the process's end after all] → The test fails with the timings in its message,
  and that's raised as a product issue (the dropped alternative in D3), not retried away.
- [A Windows flake hunt isn't possible from this machine] → CI's Windows legs run the tests. The owner is asked
  whether to also run the issue's Windows flake hunt.
