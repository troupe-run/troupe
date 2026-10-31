# Design

## Context

See proposal.md, "Why", for the three occurrences and the job-assignment gap. The mechanics this design relies on:

- **The log.** `scripts/check.py` runs `pytest -n auto --dist worksteal --durations=25`, and xdist reports each
  finished test as a dot, never naming a test that is still running. The Windows 3.12 leg of run 41024790045 collected 3001 items, printed 98% at
  08:21:16, and was stopped at 08:31:50 with `2977 passed, 22 skipped`. An xdist worker always holds the test after
  the one it is running, because pytest's run protocol needs `nextitem`. So two unfinished tests means one stuck test.
  The `KeyboardInterrupt` at `threading.py:359` is the controller waiting on its queue, which says nothing about the
  worker.
- **`asyncio` waits for the pipes.** In CPython 3.12 `base_subprocess`, `Process.wait()` resolves its waiter only in
  `_call_connection_lost`. That runs from `_try_finish`, and only once the process has exited **and** every pipe has
  disconnected. A process outside the job that holds the child's stdout keeps `wait()` waiting forever, even though the
  child itself has exited.
- **The gap.** `processes.start` on Windows calls `asyncio.create_subprocess_exec(..., creationflags=
  CREATE_NEW_PROCESS_GROUP)` and then `_new_job_for(process.pid)`. `run_to_completion` does the same with
  `subprocess.Popen`. The child runs from the moment it's created. A virtual environment's `python.exe` is a launcher
  that starts the real interpreter as its child at once, and that child gets the launcher's standard handles
  (memory/windows-ci-process-test-traps). The tests start their stand-in runners (`fake_claude.py`, the scripted
  runner, the protocol stand-ins) through `sys.executable`, which is that launcher.
- **The pattern already exists.** `scripts/flake_hunt.py` starts each round with `CREATE_SUSPENDED`, assigns it to a
  kill-on-close job, and resumes it with `NtResumeProcess` (flake-hunt design, "Windows"). runner-contract's design
  named the same fix "if CI ever shows a leak".
- **Stack dumps under xdist.** pytest's built-in faulthandler plugin, with `faulthandler_timeout`, dumps every thread
  of a test's process once that test has run past the limit. Checked before this design, in a scratch directory on
  macOS: `pytest -n 2` with `faulthandler_timeout = 2` and a test sleeping 4 s printed `Timeout (0:00:02)!` and a frame
  `test_stall.py, line 7 in test_stuck_here` to the controller's output, and both tests passed. Windows is not yet
  checked; D1's test does that in CI.

## Goals / Non-Goals

**Goals:**
- A test stuck in the check names itself in the log, on every platform, well before the job's timeout.
- The test that hung on Windows is named from evidence, and its cause is fixed so it can't block.
- No Windows child can start a process outside its job, through either way of starting a child.
- Waiting for a child that has exited ends, whatever output a caller left unread (D6, the cause D3 found).
- The test that hung bounds its own wait, so a regression fails it, naming the limit, instead of hanging CI.

**Non-Goals:**
- A per-test timeout or a new test dependency. A test that can block bounds itself (memory/no-per-test-timeout), and
  the dump is diagnostic only.
- Changing the CI job's 20-minute timeout or the matrix. The temporary hunt workflow (D3) is a separate file that
  never reaches `main`.
- POSIX's documented limitation, a grandchild that starts its own session and so leaves the group. It is a different
  mechanism, and nothing here suggests it plays a part.
- Raising the timeout on any other test, or an audit of every `await child.wait()` in the suite. If the dump names a
  pattern several tests share, that is recorded as a follow-up issue on the board, not widened here.

## Decisions

### D1: The stall limit is pytest's `faulthandler_timeout`, 300 s, in `pyproject.toml`

`[tool.pytest.ini_options]` gains `faulthandler_timeout = 300`, with a comment naming #187. It's the one place the
limit is set (project context: every limit is a named setting with its default in one place). Every pytest run reads
it: the check, a direct `pytest`, and the flake hunt's rounds.

- **Why 300 s.** The slowest test on Windows takes 87 s
  (`test_one_command_after_any_merge_leaves_every_file_as_the_merged_config_renders_it`, run 41024790045's durations).
  A full Windows check takes 7.5–10 minutes. The hang started about 9.5 minutes into the job, so a dump at +5 minutes
  lands about 5 minutes before the job's timeout. A shorter limit would dump healthy slow tests on a loaded runner. A
  longer one could be cut off by the timeout. 300 s is also the value the flake hunt already uses (`STALL_SECONDS`).
- **The flake hunt reads it rather than repeating it.** `--stall` defaults to none. Without it, the hunt passes no
  `-o faulthandler_timeout`, so its rounds use the configuration's limit. With it, the hunt passes the given value as
  now. `STALL_SECONDS` is removed, and `contributing/flake-hunt.md`'s options table says the default comes from
  `pyproject.toml`. The hunt's `tail()` still finds the dump by `Timeout (`.
- **Tested on every OS.** A new test in `scripts/tests/test_check_parallel.py`, beside the parallel tests, writes a temporary pytest root with
  `faulthandler_timeout = 1`, a test that sleeps 3 s and a quick one. It runs pytest the way the check does
  (`-n 2 --dist worksteal`) and asserts three things: the output holds `Timeout (` and a frame naming the sleeping
  test's function; the run passes; and a quick-only run holds no `Timeout (`. A second test reads `pyproject.toml` and
  asserts `faulthandler_timeout` is set and between the slowest-test margin and the job timeout less the suite
  (named constants in the test: above 120 s, at most 600 s), so the first spec requirement's bounds can be falsified.
  CI's Windows legs then prove the dump reaches the log there.
- *Alternative: pytest-timeout.* It names the test too, but it fails it, and its thread method ends the whole worker.
  It's a new dependency, it turns a slow-but-fine test on a loaded runner into a failure, and it is the per-test
  timeout the project chose not to have.
- *Alternative: verbose output (`-v`) in CI.* xdist prints a test's name when it finishes, not when it starts, so a
  test that never finishes still goes unnamed.
- *Alternative: set it in `check.py`.* Direct runs and the flake hunt would then have their own limit, or none, and
  the number would live in two places.

### D2: The dump goes out alone, and the fix only once the hang is identified

If the suspended start (D4) shipped with the dump, a hang that stopped would prove nothing. The cure would be
confirmed only by its absence, at a rate low enough that absence means little. So the commits are ordered and pushed
in three stages (tasks):

1. The stack dump (D1) alone, pushed, and the PR marked ready so its legs run.
2. Reruns of the Windows 3.12 job on that head until a dump names the stuck test, or the stopping rule (D3) is reached.
3. The proof of the gap (D4's failing test), the fix, and the hung test's own bound (D5), pushed after.

The deterministic test for the gap (D4) can be written and run locally at any point, because it fails on any OS
where the window is widened. It just isn't pushed until stage 3.

### D3: Catch it with parallel copies of the Windows 3.12 check, with a stopping rule set in advance

The owner chose to mark the PR ready after the dump push, ahead of a clean review, so that its legs run (2026-10-31).
Then, once the rate below was measured, the owner chose parallel copies over one-at-a-time reruns (2026-10-31).

- **The rate.** From 2026-10-27 to 2026-10-31, the latest attempt of each CI run had 73 Windows 3.12 legs pass, 19
  fail and 12 cancelled, mostly by newer pushes. The three known hangs were all on attempts that a rerun later
  replaced, so they aren't in those counts. That's about 3 hangs in roughly 100 leg runs, about 3%, and with so few
  hangs the true rate could plausibly be anywhere from about 1% to 8%.
- **How.** A temporary workflow, `.github/workflows/hang-hunt-187.yml`, runs on pushes to this branch only. It runs
  40 copies of the Windows 3.12 leg's check (`uv run scripts/check.py`, the same steps, Python and 20-minute timeout
  as `ci.yml`), with `fail-fast: false`. It doesn't touch `ci.yml`, so nothing about the required checks or the
  merge queue changes. The org's concurrent-job limit queues the copies in batches, so a batch takes about two
  legs' time. A batch is repeated with `gh run rerun <run-id>`. The same workflow runs one batch on the fixed head
  (task 5.2), and is then deleted in a push of its own, so it never reaches `main`.
- **Stopping rule.** Up to two batches, 80 copies. At 3%, one batch catches the hang with a probability of about 70%
  (1 − 0.97⁴⁰), and two batches about 91%. The parallel copies also load the runner pool the way a busy day does,
  rather than one job at a time.
- **If a dump names a test.** Stop. Record the test, its stack and the run in tasks.md and in a comment on #187, then
  go on to stage 3.
- **If the dump names a different cause** than a wait on a pipe that a process outside the job is holding: the
  design is updated before any code for it is written. That cause is fixed in this change, and D4 still lands, since
  the owner chose to fix the gap either way.
- **If nothing hangs within the rule.** Stop and ask the owner before stage 3, with the counts. The issue's
  "identified" can't be claimed, so it's the owner's call whether to land the fix with #187 left open for a later
  dump, or to keep hunting.

Only the 3.12 leg has hung, so only it is copied.
- *Alternative: one-at-a-time reruns (`gh run rerun --job`).* The plan this replaced: about 60% for 30 reruns at
  3%, over 4–5 hours.

**Outcome (2026-10-31).** No hunt was needed. The first CI run with the dump (run 41194587297, the stage 1 push)
hung on Windows 3.12 itself. At 11:01:35 the dump named `test_a_line_over_the_maximum_is_an_error_naming_the_maximum`
(`packages/troupe/tests/test_platform_processes.py`), stuck under `asyncio.run` in its helper `_first_line`, with the
event loop idle in the proactor's `_poll`. The same `BaseSubprocessTransport` warning followed when the job was
stopped. That is a different cause from the job gap (D6). The hunt workflow was never pushed. It runs once, on the
fixed head, as task 5.2's check.

### D4: Windows starts the child suspended, assigns it to the job, then resumes it

In `troupe.platform.processes`, both Windows paths add `CREATE_SUSPENDED` (`0x4`) to their creation flags
(`_WINDOWS_CREATION_FLAGS`). `_new_job_for(pid)` then makes the kill-on-close job, opens the process with
`PROCESS_SET_QUOTA | PROCESS_TERMINATE | PROCESS_SUSPEND_RESUME`, assigns it to the job, and resumes it with
`ntdll.NtResumeProcess`, the flake hunt's code and order. Both callers keep calling `_new_job_for` as before, so no
caller changes beyond the flags.

- **Failure.** If any step fails, `_new_job_for` closes the job (which kills the child if it was assigned) and raises
  an `OSError` naming the step and the pid. A non-zero NTSTATUS from the resume becomes an `OSError` with the status
  in hex. The callers' existing failure paths then kill the child (`TerminateProcess` through the `Popen`/asyncio
  handle; a suspended process can be terminated) and wait for it. Before this change, a failure after the job was
  made leaked the job's handle.
- **asyncio is unaffected by the suspension.** `create_subprocess_exec` returns once `CreateProcess` has returned and
  the pipes are connected to the proactor. Neither step needs the child to run.
- **Proved first, deterministically.** A new test in `packages/troupe/tests/test_platform_processes.py` widens the
  window on purpose:
  - The child's first statement starts a grandchild that inherits its stdout and sleeps. The child then writes the
    grandchild's pid to a file in `tmp_path`, prints it, and sleeps.
  - The test sets a module-level hook, `_before_job_assignment: Callable[[int], None]` (a no-op by default). The seam
    calls it on Windows between creating the child and putting it in its job. The test's hook waits up to a short
    named limit (`ESCAPE_WINDOW`, 5 s) for the pid file to appear.
  - The test then reads the grandchild's pid from stdout, kills the tree, and asserts two things: `wait()` returns
    within a named limit (`WAIT_LIMIT`, through `asyncio.wait_for`), and the grandchild is gone.
  - **Today's code:** the child runs during the hook, so the grandchild exists before the job does and escapes it. It
    holds stdout, so `wait()` fails at `WAIT_LIMIT` instead of hanging. This reproduces the hang deterministically.
  - **With the fix:** the child is suspended during the hook, so no pid file appears. The hook gives up after
    `ESCAPE_WINDOW`, the child is put in the job and resumed, and its grandchild starts inside the job. The test
    passes.
  - **On POSIX:** the hook isn't called, and the group holds the grandchild, so the test passes on every OS.
  - A matching test covers `run_to_completion` through its timeout path, asserting the grandchild is gone and the
    failure names the timeout.
  - The hook lets the test control the window rather than guess at it with a sleep.
- **Docs.** The module docstring and `contributing/platform.md`'s process table say "started suspended, assigned to
  the job, then resumed". The "Windows job assignment" limitation is removed.
- *Alternative: resume through the main thread's handle (`ResumeThread`).* Neither `Popen` nor asyncio keeps the
  thread handle, and enumerating threads with Toolhelp is more code for the same result. `NtResumeProcess` is
  undocumented, but the flake hunt has relied on it on CI's Windows runners since #100.
- *Alternative: `PROC_THREAD_ATTRIBUTE_JOB_LIST` (create the process inside the job).* `subprocess` doesn't expose
  the attribute list beyond `handle_list`, so this would mean writing `CreateProcess` in ctypes and losing asyncio's
  pipe plumbing.

### D5: The hung test bounds its own wait

The test D3 named, `test_a_line_over_the_maximum_is_an_error_naming_the_maximum`, gets a named limit on the wait that
hung: its helper `_first_line` bounds `await child.wait()` with `WAIT_LIMIT`. That is `asyncio.wait_for` around the await, with a
module-level constant and a failure message naming the limit and what it waited for, in the style of
`INPUT_OPEN_LIMIT` (`plugins/runner-scripted/tests/test_scripted_runner.py`). A regression then fails that test,
naming the limit, instead of hanging the leg. The helper is shared with the 5 MiB test, which gets the same bound.

### D6: Waiting for a child that has exited reads its paused output to the end

**The cause D3 found.** `asyncio.StreamReader` pauses reading its pipe once its buffer holds more than twice its
limit, and resumes only when a reader drains it below the limit. `read_line` raises `LineTooLongError` when
`readuntil` overruns the limit. If the whole over-long line had arrived first, the stream is left paused, and nothing
will ever read it again. The child then exits, but its pipe's end-of-file is never read, the pipe never disconnects,
and asyncio's `Process.wait()` (which waits for every pipe, see Context) never returns. In `_first_line`, the child
writes 2 MiB and a line feed against a 1 MiB limit (a pause at 2 MiB), and whether the reader overran before or after
the whole line arrived is a race. Reproduced deterministically on macOS: a child that writes the over-long line, then
keeps running, read only once the line has arrived, leaves `wait()` waiting after `kill_tree()`. Read straight away,
the stream never pauses and `wait()` returns.

**It isn't only a test's problem.** The run host (`core/runners/host.py`) turns `LineTooLongError` into a protocol
violation, then `_finish_process` kills the runner, waits out the grace, kills it again, and then calls `await
child.wait()` with no bound. On this path that call never returns. That breaks "never wait silently or
indefinitely".

**The fix, in the seam.** `ChildProcess.wait()` waits for asyncio's `wait()` in steps of `_POLL_SECONDS`. Once the
child's exit code is known (`returncode` is set when the process exits, whatever its pipes are doing), it resumes
reading any of the child's output pipes that is paused (`get_pipe_transport(1/2)`, `is_reading()`,
`resume_reading()`, all public transport API). The rest of the output then reaches the stream and its end-of-file
is read, the pipes disconnect, and the wait ends. The stream keeps its paused flag, so it doesn't pause again, and it
keeps everything the child wrote, so nothing is dropped from a stream a caller may still read.

- Only after exit. While the child runs, the pause is what stops an unread child filling memory. After exit, all
  that's left is what's already in the pipe. A grandchild still holding the pipe could keep writing, and that is
  read into the stream, a known cost. A grandchild that escaped the job is what D4 rules out.
- *Alternative: return on the exit code alone, without waiting for the pipes.* A caller that waits and then
  releases would then close pipes that still hold output, and lose it. The current guarantee, that output has
  ended when `wait()` returns, stays.
- *Alternative: have `read_line` discard the over-long line so the stream resumes.* That reaches into the
  `StreamReader`'s private buffer, and leaves a stream positioned mid-line for any later read.
- **Proof.** A new seam test does what the hang needed: a child writes 2 MiB and a line feed, flushes, then sleeps.
  The test waits (bounded) until the stdout pipe has paused, then reads (`LineTooLongError`), kills the tree, and
  asserts `wait()` returns within `WAIT_LIMIT`. Without the fix it fails at the limit, deterministically, on every OS.
  With it, it passes.
- **Spec.** platform gains "Waiting for a child ends once it has exited, whatever output was left unread", with the
  over-long line as its scenario.

## Risks / Trade-offs

- [The hang may not recur within the rerun budget] → D3 says ahead of time when to stop. The owner decides between
  landing the fix with #187 still open and continuing to rerun. "Identified" is not claimed without a dump.
- [A dump at 300 s could flag a healthy slow test on a loaded runner] → The dump changes no outcome. It costs only log
  lines, and the slowest test is 87 s, well under the limit.
- [The dump might not reach the log on Windows] → D1's test runs on the Windows legs in the first push, so a dump that
  doesn't reach the log fails CI before any reruns are spent.
- [`NtResumeProcess` is undocumented] → It's what the flake hunt uses on the same runners. A failure is raised with
  its NTSTATUS rather than ignored, and the child is killed, never left suspended.
- [Marking the PR ready before the review is clean departs from the usual order] → The owner chose it for this change.
- [A temporary workflow that lingers would run on every push to this branch] → It's deleted after 5.2's batch, in a
  push of its own, and 5.3 checks it isn't in the tree.
  Claude's review is still acted on before archiving, and the owner still merges.
- [40 to 80 Windows jobs for D3, and 40 more for 5.2, on the org's shared runner pool] → Copies queue behind the
  org's concurrent-job limit rather than failing, and the workflow runs only on this branch. It is deleted before
  the PR can merge, and a test in task 5.3 checks that it's gone.
