# Design: an interrupted flake campaign always stops

## Context

`scripts/flake_campaign.py` runs hunts one after another, each a child process (`flake_hunt.py` directly, or
`docker run`). It runs them in its own process group, so a terminal's Ctrl-C reaches the campaign and its hunt
together. The hunt stops its rounds and writes its summary. The campaign gives it `STOP_WAIT_SECONDS` (60 s) to do
that, then writes the report and exits 130. Today the campaign takes Ctrl-C as Python's default `KeyboardInterrupt`,
raised wherever its main thread is. `wait()` catches it around a loop of `Popen.poll()` and `Popen.wait(WAIT_SECONDS)`.
The short waits exist because Windows can't interrupt a wait with no timeout.

## Goals / Non-Goals

**Goals:**

- Find the cause of #358 and fix it, with a test that forces the cause and fails on today's code.
- Keep what a stopped campaign does: the hunt gets its stop limit to write a summary, no more hunts run, the report
  marks the campaign stopped, and it exits 130.
- Keep the end-to-end test's SIGABRT stack dump as a backstop.

**Non-Goals:**

- Changing `flake_hunt.py` (D3).
- Widening any timeout.
- Handling `SIGTERM`. It was never handled, and nothing sends it in the tested path.

## Decisions

### D1. The cause: a `KeyboardInterrupt` inside `Popen.wait` leaves its lock held

On POSIX, `Popen._wait(timeout)` in CPython 3.12 and 3.13 (checked on 3.12.14 and 3.13.18) loops like this:

```python
if self._waitpid_lock.acquire(False):
    try:
        ...waitpid(WNOHANG)...
    finally:
        self._waitpid_lock.release()
...
time.sleep(delay)
```

Python runs signal handlers at checks the interpreter makes after calls, including right after `acquire(False)`
returns. A `SIGINT` delivered during the acquire, or in the few instructions before it, raises `KeyboardInterrupt`
with the lock taken and the `try` not yet entered, so nothing releases the lock. After that:

- `poll()` (`_internal_poll`) returns `None` whenever it can't take the lock ("something else is busy calling
  waitpid"), so the campaign's stop loop sees a running hunt for the full `STOP_WAIT_SECONDS`, even though the hunt
  has exited (as the failing log shows: its summary was written 0.9 s after the interrupt).
- `kill()` polls first, sees `None`, and signals the zombie. That succeeds.
- `wait()` with no timeout then blocks on `with self._waitpid_lock` for ever.

**This fits the failure.** At the time, the test waited exactly 60 s, the campaign's own limit, and the campaign was
stuck at least that long. The campaign's closing lines weren't flushed back then, so the log couldn't show how far it
got. The window is a few bytecodes in each pass of a 50 ms sleep loop, so the failure is rare. A loaded runner
stretches those instructions and makes it likelier. Nothing in it is specific to macOS.

**Proof.** A script in the scratchpad swaps `process._waitpid_lock` for a wrapper. The wrapper takes the real lock,
then calls `signal.raise_signal(SIGINT)` once, which runs the handler right there, as a Ctrl-C landing at that moment
would. Running today's `flake_campaign.wait()` against a child that exits after 0.3 s, with `STOP_WAIT_SECONDS` set to
2 s, it printed "stopping" and then hung until a watchdog released the lock after 10 s. Without the watchdog it hangs
for ever.

**Ruled out:**

- **Pipes:** the campaign captures nothing from the hunt, which writes straight to the inherited stdout.
- **The hunt not exiting:** its worker threads are daemons that have returned by the time it summarises, it has no
  atexit work, and its rounds run in their own sessions and are killed with `SIGKILL`.
- **A second interrupt:** the test sends one `SIGINT` to the group.
- **Process groups:** the hunt is in the campaign's group, and its rounds are in sessions of their own.

### D2. Ctrl-C becomes a stop request (a flag), never an exception

While `campaign()` runs, a context manager installs handlers for `SIGINT`, and for `SIGBREAK` on Windows, that only
set a `threading.Event`. It restores the previous handlers afterwards. Code that waits checks the event:

- `wait(process, stopping)` loops `poll()` and `wait(WAIT_SECONDS)` until the hunt exits or a stop is requested. On a
  stop it prints the same line as before, keeps waiting up to `STOP_WAIT_SECONDS` for the hunt to exit, kills it if
  it doesn't, and raises `Stopped`, as before. No exception can now land inside `subprocess`. That also removes the
  smaller window between `waitpid` reaping the hunt and `Popen` recording its status, where the exit code was lost
  and `poll()` reported 0.
- After `uv sync`, `docker build` and `docker cp`, and before each hunt, the campaign checks the event and stops. On
  POSIX those tools are in the campaign's process group, and on Windows they share its console, so they got the
  Ctrl-C too. A hunt stopped before it ran is recorded as stopped, with no summary.
- A hunt that ends on its own while a stop is requested keeps the outcome it ended with. The campaign then runs no
  more hunts and is reported stopped.

**Alternatives considered:**

- *Repair or avoid `Popen`'s lock* (reset `_waitpid_lock`, or call `os.waitpid` directly): this depends on CPython's
  private internals, and it leaves `KeyboardInterrupt` free to land in every other blocking call.
- *Block `SIGINT` with `pthread_sigmask` around waits:* POSIX only, so Windows would still need a second mechanism.
- *Wait in a helper thread:* the main thread would still take the exception somewhere, so it only moves the problem.

The flag removes the whole class of bug: an asynchronous exception partway through library code.

### D3. `flake_hunt.py` is unchanged

The hunt's main thread waits on worker threads with `Thread.join(timeout)`, not on `Popen`. Its rounds' `Popen` calls
run in worker threads, which never receive signal handlers. Once it has caught the interrupt, it ignores `SIGINT` for
the whole stop. The failing run shows it stopping and summarising correctly. Nothing here needs it to change, and
changing it would widen this fix without a reproduced fault.

### D4. The regression test forces the exact moment with a real signal

`test_a_stop_landing_inside_the_wait_on_a_hunt_still_stops_promptly`:

1. Start a child that exits with a known code after a short pause.
2. Swap its `_waitpid_lock` for a wrapper that takes the real lock, then calls `signal.raise_signal(SIGINT)` once.
3. Call `wait()` under the campaign's stop handling. Expect `Stopped` within a named bound, with the child's own
   exit code recorded.

A watchdog timer releases the real lock if the bound passes, so a regression fails the test instead of hanging it. The
test fails if the watchdog fired. It first asserts that `Popen` still has a `_waitpid_lock` that is a lock, so a CPython
change fails loudly instead of quietly skipping the check. It's POSIX only, because Windows' `Popen` waits with
`WaitForSingleObject` and has no such lock. The skip says so.

A second unit test covers the stop between hunts. A stand-in for the direct hunt raises a real `SIGINT` and returns
clean. The campaign must record that hunt, run no second hunt, report itself stopped, and exit 130 from `main`.

The end-to-end interrupt test and its SIGABRT stack dump are unchanged (D5).

### D5. The stack-dump trap stays

`PYTHONFAULTHANDLER=1` and the `SIGABRT` to the process group on overrun stay in the end-to-end test. If some other
cause turns up, the job log will show its stack.

## Risks / Trade-offs

- **A `SIGINT` sent to the campaign alone** (`kill -INT <pid>`, not a terminal's Ctrl-C) during `uv sync` now waits for
  the sync to finish, then stops. Before, Python raised the interrupt while the campaign waited on uv, and uv carried
  on. Either way uv isn't stopped, so this is no loss. Ctrl-C at a terminal reaches uv itself, as before.
- **A hung child step with no timeout,** such as a `docker build` that ignores Ctrl-C, can't be cut short by
  another Ctrl-C. It couldn't be on Windows before either, and a second Ctrl-C was already suppressed during a stop.
- **The test relies on a private CPython attribute.** That's acceptable for a regression test, because it checks the
  attribute exists first and fails if it doesn't.
