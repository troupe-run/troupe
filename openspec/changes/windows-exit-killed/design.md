# Design

## Context

See proposal.md, Why, for the race. Today's state:

- `_Run.kill()` (`core/runners/host.py`) sets `run.killed = True` and calls `child.kill_tree()` only when
  `child.returncode is None`. `run_actor` then sets `ending = KILLED if run.killed else EXITED`. Every kill path goes
  through `kill()`: a violation or failed start (`_finish_process(stop_now=True)`), the grace period after
  `shutdown` or `run/cancel` (`kill_after_grace`), and the final grace in `_finish_process`.
- `returncode` is asyncio's view. It is set only after the loop has reaped the child, so it lags the real exit by an
  unknown amount on every platform.
- The `returncode` check also does a second job. On Linux and macOS, `kill_tree()` is `killpg(pid, SIGKILL)`. Once a
  child is reaped its pid, and so its group id, can be reused. Never killing a group whose leader is known to have
  been reaped protects an unrelated process group.
- `kill_tree()` on Windows is `TerminateJobObject(job, 1)`, so a killed child's exit code is 1, the same as a program
  that fails normally. `run_command`'s timeout kill (`processes.py`) uses the same `_kill_job`.
- `exit_code` is already the value `child.wait()` returned (`319eb40`). It is the one true record of how the process
  ended.

## Goals / Non-Goals

**Goals:**

- `ending` is decided after the process has ended, from facts that can't race.
- OS-specific knowledge (what a kill's exit status looks like) stays behind the `platform/processes.py` seam.
- The violation test checks a property the host guarantees, and its names say exactly that.

**Non-Goals:**

- Changing when the host kills, the grace periods, or `derive_outcome`.
- Making the scripted runner able to ignore `shutdown` just so the `after result` case has one deterministic ending.
  The real host faces runners that answer `shutdown`, and the test should cover that.
- Telling apart "troupe's kill" from "someone else's `SIGKILL` that landed after troupe sent its own" (Risks).
- #81.

## Decisions

### D1. `ending` is `killed` when troupe sent a kill *and* the exit status is the kill's

`ChildProcess` records that `kill_tree()` was called, and gains `ended_by_kill(exit_code: int) -> bool`: true when a
kill was sent and `exit_code` matches the platform's kill status. The host drops `run.killed` and sets
`ending = KILLED if child.ended_by_kill(exit_code) else EXITED`, using the `exit_code` that `_finish_process`
already returns from `wait()`.

`kill()` keeps its `returncode is None` guard, but only for the pid-reuse protection in Context. It no longer decides
`ending`. If the guard skips the kill, the child already exited, and `ended_by_kill` is false because no kill was
sent. If the kill is sent to a child that has exited but hasn't been reaped yet, the child is a zombie. Its group
still exists, so the signal is harmless, and its exit status is its own, so `ended_by_kill` is false.

Alternatives considered:

- **The host's decision** (`killed` whenever the host chose to kill). This is what the owner turned down. It would
  record "its exit code says nothing" for a runner that really exited 0. It also doesn't fix the reverse direction,
  where an `ok` run is marked `failed`.
- **Poll the OS just before killing** (`waitpid(WNOHANG)` or `GetExitCodeProcess`). This narrows the window but
  can't close it: the process can still exit between the check and the kill.
- **Decide from the exit status alone, with no record of a sent kill.** An out-of-memory kill or an operator's
  `kill -9` would then be recorded as troupe's kill. `killed` means troupe killed it, because the outcome's message
  says it "had to be killed after it didn't exit".

### D2. What a kill's exit status is, per platform

- **Linux and macOS:** a child ended by `SIGKILL` has asyncio return code `-SIGKILL` (`-9`). Troupe's kill is
  `killpg(…, SIGKILL)`, so `ended_by_kill(code)` is `code == -signal.SIGKILL`.
- **Windows:** `TerminateJobObject` sets every process in the job to an exit code the caller passes. Troupe passes a
  named module constant, `KILLED_EXIT_CODE = 0x74726B6C` (`"trkl"` in ASCII, 1953655660). It is within a `DWORD`,
  positive as a Python `int`, and not an `NTSTATUS` value (they start `0xC`/`0x8`), so tools won't read it as a crash.
  It's also far from the small codes programs exit with. `ended_by_kill(code)` is `code == KILLED_EXIT_CODE`.
  `run_command`'s timeout kill uses the same `_kill_job`, so it gets the same code. Nothing in that path reads it.

The constant is a platform fact, not a limit, so it stays in `processes.py` rather than `core/defaults.py`.
`docs/platform.md` names it.

Alternatives considered: keep `1` and decide on Windows from "a kill was sent" alone. That brings back the race on
the one platform where it fails most.

### D3. The violation test, split by what can happen

- `test_each_protocol_violation_crashes_the_run_naming_it` keeps the ten cases where nothing asked the runner to
  exit. Its name already covers its first assertions, and it keeps `ending is Ending.KILLED`. Without a `shutdown`
  or `run/cancel`, the hanging scripted runner can't exit before the kill, so `killed` is guaranteed here.
- The `after result` case moves to its own test,
  `test_a_late_event_after_the_result_crashes_the_run_whether_the_runner_answers_shutdown_first`. It asserts
  `crashed`, `runner.protocol` and the line, and then that the ending is one of the two that can happen and agrees
  with the exit code: `killed`, or `exited` with exit code 0. That is the spec scenario "The runner exits before the
  kill lands" plus the kill path. The name says the order isn't fixed.
- Each direction of the race gets a deterministic test at the seam (`test_platform_processes.py`), which is where
  the decision now lives:
  1. kill a running child, then wait: `ended_by_kill` is true.
  2. a child exits 0 by itself, and troupe kills it after it has exited but before asyncio has seen the exit:
     the race itself. The test blocks the event loop and waits at the OS level for the exit, then asserts
     `returncode` is still `None` before calling `kill_tree()`. On Linux it uses `waitid` with `WNOWAIT`, which
     doesn't reap. On macOS asyncio's watcher thread reaps the child, but it can't set `returncode` while the loop
     is blocked. On Windows `is_running` reads the real exit code. The exit code is 0 and `ended_by_kill` is false.
     This is the "late kill" in both host directions. (Added in review. A first version waited until asyncio had
     seen the exit, which is the calmer case, not the race the platform scenario describes.)
  3. a child ends itself with the kill's status (`os.kill(os.getpid(), SIGKILL)` on Linux and macOS,
     `os._exit(KILLED_EXIT_CODE)` on Windows) with no kill sent: `ended_by_kill` is false.
- The host's `ok`-result-at-grace scenario can't be timed deterministically through a real process. It is covered by
  (2), since the host now only consults `ended_by_kill` and the exit code. `test_run_outcome.py` already covers
  `EXITED`/0 with an `ok` result giving `succeeded`.

## Risks / Trade-offs

- [A runner exits with exactly `KILLED_EXIT_CODE` on Windows, after troupe sent a kill that hadn't landed] →
  recorded `killed`. This needs a kill to be in flight and an exit code no program uses. It's accepted and documented.
- [Someone else `SIGKILL`s the runner after troupe sent its own kill, on Linux or macOS] → recorded `killed`. The
  outcome is the same: troupe had already decided to end the run.
- [Windows killed runs now record exit code 1953655660 instead of 1] → nothing reads the value beyond recording it,
  and the schema allows any integer. It's marked BREAKING in the proposal. Pre-alpha, with no theatres to migrate.
- [The `after result` test still allows two endings] → that's intentional and its name says so. The guarantee that
  each ending is true is pinned by the deterministic seam tests, not by this timing-dependent one.

## Migration Plan

None. No schema or record-format change. Old `Run.Ended` records keep the ending they were written with.
