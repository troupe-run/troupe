# Design

## Context

See proposal.md for why. What exists on main (69d6c27), in `packages/troupe/src/troupe/platform/processes.py`:

- **POSIX** (`is_running`, line 262): `os.kill(pid, 0)`. `ProcessLookupError` → `False`; `PermissionError` →
  `True`; success → `True`. Any other `OSError` propagates unnamed. `pid` isn't checked, so `0` and negative values
  address process groups and read as `True`.
- **Windows** (line 233): `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`; any failure → `False`. Then
  `GetExitCodeProcess`; failure → `False`; otherwise `code == STILL_ACTIVE (259)`. So a process that exited with
  259 reads as running, and access denied reads as ended.
- Callers: only tests. `_gone_within` and an `assert processes.is_running(grandchild)` in
  `test_platform_processes.py`; polling loops then `assert not is_running(...)` in `test_run_host.py:386` and
  `troupe-vcs-git/tests/test_git_adapter.py:155`. `test_run_queries.py`'s "is_running" is an unrelated test name.
- Platform errors live in `troupe.platform.errors` and are turned into `TroupeError`s at the core call site that
  catches them (for example `host.py` with `LineTooLongError`); there is no exhaustive table to extend.
- CI runs Linux, macOS and Windows (`ci.yml`); GitHub's runners run as a non-root user on Linux and macOS, and as an
  elevated administrator on Windows.

## Goals / Non-Goals

**Goals:**
- The same three outcomes, from the same evidence, on every platform (spec: platform, "Whether a process has
  ended has one meaning on every platform").
- Each platform's decision table tested on every platform, not only where its OS calls exist.

**Non-Goals:**
- Detecting an unreaped zombie on Linux or macOS (D4).
- Detecting pid reuse. A pid that has ended and been reused reads as running on every platform, as it does today;
  callers ask within seconds of a kill, so the window is the OS's reuse delay.
- Any product caller of `is_running`, or a `TroupeError` code for the new error. One is added when core first
  calls it.
- Changing what #90 changes (the race test's wait). #90 stops depending on `is_running`; this keeps whatever
  depends on it honest.

**Must stay the same** (each gets a test that passes on main before the change, per the differential-testing rule):
- POSIX: a live child reads `True`; a waited-for child reads `False`; a process owned by another user reads `True`;
  an unreaped child reads `True`.
- Windows: a live child reads `True`; a fully gone pid reads `False`.

## Decisions

### D1. Keep `is_running(pid) -> bool`; "can't tell" raises

`True` is "hasn't ended", `False` is "ended", and a third outcome is `ProcessStateUnknownError`. Every caller
already asks "is it still running?" in a loop or an assert, so the name and return type fit; an exception means a
"can't tell" fails those tests loudly instead of reading as either answer.

Alternatives: a rename to `has_ended` (inverts every caller for no change in meaning); a three-valued enum (lets a
caller quietly treat "unknown" as one of the others, which is the bug being fixed).

### D2. Each platform's decision is a pure function over what the OS said

The OS calls stay thin and platform-gated; the mapping from their result to an outcome is two module-level pure
functions, defined on every platform:

- `_posix_outcome(pid, error: OSError | None) -> bool`: no error → running; `ESRCH` → ended; `EPERM` → running;
  anything else → `ProcessStateUnknownError(pid, error)`.
- `_windows_outcome(pid, open_error: int | None, wait_result: int | None, wait_error: int | None) -> bool`:
  open failed with `ERROR_INVALID_PARAMETER` (87) → ended; with `ERROR_ACCESS_DENIED` (5) → running; any other open
  error → unknown. Opened: `WAIT_OBJECT_0` (0) → ended; `WAIT_TIMEOUT` (258) → running; `WAIT_FAILED` or anything
  else → unknown, carrying the wait's error.

This lets every row of #92's table, and every OS error not in it, be tested on all three CI platforms, while real
processes test the rows each platform can produce. It matches by error code, not by exception class, so the
mapping is the same whichever Python wrapper raised it.

Alternative: test only through real processes. The access-denied, can't-tell and wait-failed rows can't be
produced reliably on CI, so they'd go untested.

### D3. Windows reads "ended" from the signalled handle, not the exit code

Open with `PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE` and call `WaitForSingleObject(handle, 0)`. A process
handle is signalled exactly when the process has exited, so this has no reserved value. `GetExitCodeProcess` can't
tell a process that exited with 259 from one still running (Microsoft's documentation warns of this).

Adding `SYNCHRONIZE` can only turn a successful open into `ERROR_ACCESS_DENIED`, which reads as running: the same
answer the process would have had. It cannot make a live process read as ended.

Alternative: keep `GetExitCodeProcess` and treat 259 as running. Rejected: it is the one guess the issue asks to
remove that has a cheap exact replacement.

### D4. The POSIX zombie stays a documented limit

`os.kill(pid, 0)` succeeds for a zombie. Options considered:

- `waitpid(pid, WNOHANG)`: works only for our own children and reaps them, stealing the exit status from asyncio's
  child watcher or `subprocess.Popen`. Rejected outright.
- Linux `/proc/<pid>/stat` state `Z`: cheap, but Linux-only. macOS would need `sysctl(KERN_PROC_PID)` through
  ctypes and `kinfo_proc`'s layout. Doing one and not the other rebuilds the inconsistency this change removes;
  doing both adds two OS-specific paths for a case no caller hits.

No caller is affected: troupe's own children are reaped by asyncio or `Popen.wait`, and a killed child's
grandchildren are reparented to init (or a subreaper), which reaps them. `docs/platform.md` gains the limit, and a
POSIX-only test pins it under a name that says it is the limit.

### D5. A pid that can't name one process is a `ValueError`, checked before any OS call

`pid` must be an `int`, not a `bool`, from 1 to `2**31 - 1` (POSIX `pid_t` is a signed 32-bit integer; `os.kill`
would raise `OverflowError` past it, and ctypes would silently truncate it on Windows, asking about a different
pid). Found while applying: the bound was not in the first draft. On POSIX `0` and negatives signal a process group;
on Windows `0` is the System Idle Process. The message names the value and says a pid is a positive integer. It is
a `ValueError`, not a `PlatformError`, because it is the caller's mistake, not the OS's.

### D6. `ProcessStateUnknownError(pid, error)`

A `PlatformError` with `pid`, the OS error code (`errno` on POSIX, the Windows error number on Windows) and its
text. Message: `can't tell whether process {pid} has ended: {text} (error {code})`. On Windows the error is built
from `ctypes.get_last_error()` at the failing call, so it names that call's error, not a later one.

### D7. Tests

In `test_platform_processes.py`, under the new requirement's heading:

- **Decision tables, every platform**: each row of D2 for both functions, parametrised; and a Hypothesis property
  that any errno or Windows error outside the known ones raises `ProcessStateUnknownError` carrying that pid and
  code.
- **Real processes, every platform**: a live child reads running; a waited-for child reads ended; a child that
  exited with 259 reads ended (held on Windows, waited for on POSIX); `0`, `-1` and `True` are refused.
- **Windows only**: an exited child whose `Popen` still holds its handle reads ended; a child that gives its own
  process an empty DACL reads running (opening it is refused even to an elevated administrator, who holds
  SeDebugPrivilege disabled); the System process (pid 4) reads running. The empty-DACL child is the
  access-denied reproduction: pid 4 may be openable on CI (found while applying, from a side review).
- **POSIX only**: pid 1 reads running when not root (skipped as root, saying why, since root may signal it and the
  refusal branch wouldn't be reached); an unreaped child reads running, named as the documented limit.
- **OS error path**: monkeypatching `os.kill` to raise `EINVAL` (POSIX) shows the real function raises
  `ProcessStateUnknownError`, so the wiring between the OS call and D2 is tested, not only D2.

The existing callers' tests stay unchanged and must still pass on all three platforms.

## Risks / Trade-offs

- [A reaped pid is reused before the "ended" test asserts] → assert at once after the wait; the reuse window on
  every OS is far longer than that. A failure would read as "running", which is visible, not a false pass.
- [Windows CI is elevated, so pid 4 may open successfully and take the wait path, not the access-denied one] →
  the test's name claims only that the System process reads running, which is true on either path, and it is a
  non-strict xfail before the fix so main's answer is reported either way. The empty-DACL child produces the
  refusal for certain, and the D2 table covers the mapping. The PR records which path pid 4 took.
- [A test that relied on `is_running` never raising now fails with `ProcessStateUnknownError`] → intended: that
  test was passing on a guess. Investigate rather than catch.

## Migration Plan

None: no product code or stored data depends on `is_running`. Rollback is reverting the commit.

## Open Questions

- Which branch Windows CI takes for pid 4 (access denied or wait). Recorded in the PR; it changes no decision.
