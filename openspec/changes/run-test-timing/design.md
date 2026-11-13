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

- A run's state follows whether its `perform` has gone, not when the OS lets go of a dead process's lock (D4).

**Non-Goals:**

- Changing what a lease is, or how `perform` takes it. The lock stays the first test; the pid only refines "held".

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

*Alternative:* run `sys._base_executable` so there's no launcher. The child then needs the venv's paths set up by
hand, and #55 found that it didn't remove that flake's cause. Waiting on the real pid works whatever starts it.

### D4. A held lease whose holder has ended is `interrupted` (owner decision, 2026-11-13)

D3 is the cause of #405 as far as anything shows. But the runs spec says `interrupted` once the `perform` "has
gone", and `lease_state` only knows whether the OS still holds the lock. Windows doesn't promise when that is:
`LockFileEx` says a terminated process's locks are released in a time that "depends upon available system
resources". So the state is tied to the process, not to the lock's release:

1. `perform`, once it holds the lease (`directory_lock(lease)` in `core/runs/perform.py`), writes `perform.pid` in
   the lease directory: its `os.getpid()` in ASCII decimal and a newline, through `core.files.replace_file`, so a
   reader never sees a half-written file. The write happens before the run's start is recorded, so a run that anyone
   can see already has its pid file.
2. `lease_state` tries the lock as now. Taken means `interrupted`, and no lease directory means
   `unfinished-elsewhere`, both as now. When the lock is held, it reads `perform.pid`:
   - a pid whose process has ended (platform `is_running` is false) means `interrupted`;
   - no file, a file that isn't one positive decimal number, a pid still running, or the OS unable to say
     (`ProcessStateUnknownError`) means `running`, as today.

Why the fallback is `running` rather than an error, even for a malformed file: the lock is still the authority, and
the pid only lets a held lock be read as gone. A wrong `interrupted` lets `discard` remove a live run's worktree. A
wrong `running` only means the state reads as it does today until the lock is released. So anything short of a pid
proven ended keeps today's answer. The owner set this rule.

Why it can't make a live run `interrupted`: the lock is held either by the `perform` that wrote the file, which is
then running, or for a moment by another reader's `lease_state` probe. That second case only happens once the
`perform` has released the lock, so it has ended or finished anyway. A reused pid can only make a dead `perform`
read as `running`, which is today's answer.

The pid file is local state under `.troupe/local/runs/<run id>/`, like the lease itself, and never committed. It
isn't an event, so it adds nothing to the history or the protocol.

*Alternative:* a short retry of the lock before saying `running`. Every query of a live run would pay the wait, and
no wait is promised to be long enough.

**Testing it on every OS.** A helper process takes the lease lock and keeps it (as `test_platform_locks.py`'s
holder does), while the lease's `perform.pid` names a process that has ended: a child the test started and waited
for. `status` and `logs` say `interrupted`. The same set-up with the pid of a live process says `running`, and so do
a missing file and a malformed one. On main, the first test fails, saying `running`.

## Risks / Trade-offs

- [The real interpreter's pid is reused before step 3 looks] → Step 3 starts straight after the launcher's wait, and
  a reused pid would only make it wait the full `WITHIN` and fail naming the pid. It can't make the test pass wrongly.
- [A pid recorded by a `perform` from before this change] → None exist outside tests: lease directories are local,
  and pre-1.0 nothing reads an old one any differently. A lease without `perform.pid` keeps today's answer.
- [Reading the pid costs `status` a file read per run with no end] → Only when the lock is held, so only for runs
  that are, or were just, running. It's one small read.
- [A Windows flake hunt isn't possible from this machine] → CI's Windows legs run the tests. The owner is asked
  whether to also run the issue's Windows flake hunt.
