# Proposal

Issue: troupe-run/troupe#92 (Bug, `cap:platform`). Related: #90 (stops depending on `is_running`, doesn't change it).

## Why

`processes.is_running(pid)` answers a different question on each platform, and on Windows it reads "not running"
whenever it can't tell. A permission refusal proves a process exists, yet Windows reads it as ended; any other
failure is read as ended too, which is a guess. Every caller is a test that asserts a kill worked, so a wrong
`False` makes that test pass. It came in with 18b988b with no recorded decision, and nothing in the `platform` spec
says what the function means, so nothing could catch it.

## What Changes

- **One meaning on every platform: has this process ended?** `is_running(pid)` keeps its name and its `bool`
  return (design D1). `True` means it hasn't ended, `False` means it has.
- **A permission refusal reads as running on both platforms.** On Windows, `ERROR_ACCESS_DENIED` from
  `OpenProcess` now reads as running, as `PermissionError` already does on POSIX.
- **"Ended" is only said when the OS says so:** no such pid (POSIX `ESRCH`, Windows `ERROR_INVALID_PARAMETER`), or
  the process has exited. On Windows that is read from the process handle being signalled
  (`WaitForSingleObject` with a zero timeout), not from the exit code, because a process can exit with code 259,
  which is the value `STILL_ACTIVE` uses (design D3).
- **"Can't tell" is an error, never a guess.** Any other failure raises a new `ProcessStateUnknownError` naming the
  pid and the OS error. **BREAKING** for callers that relied on `is_running` never raising (only tests do).
- **A pid that can't name one process is refused.** `0`, a negative number or a `bool` raises `ValueError` naming
  the value. On POSIX, `os.kill(0, 0)` and negative pids address process groups, so today they read as "running"
  for a question that wasn't asked (design D5).
- **The POSIX zombie stays a documented limit.** An exited but unreaped child still reads as running on Linux and
  macOS; `docs/platform.md` says so, with why it doesn't affect troupe's callers (design D4).
- **Tests for every row of the issue's table** that CI can produce on each platform, real processes where possible
  and the OS-error mapping driven directly where not.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `platform`: adds the requirement "Whether a process has ended has one meaning on every platform", covering the
  three outcomes, the refusal of pids that can't name one process, and the POSIX zombie limit.

## Impact

- `packages/troupe/src/troupe/platform/processes.py`: both `is_running` implementations, two more `kernel32`
  bindings (`WaitForSingleObject`, and the `SYNCHRONIZE` access right).
- `packages/troupe/src/troupe/platform/errors.py`: `ProcessStateUnknownError`.
- `packages/troupe/tests/test_platform_processes.py`: new tests. The existing callers (`_gone_within` there, the
  grandchild checks in `test_run_host.py` and `packages/troupe-vcs-git/tests/test_git_adapter.py`) need no edit:
  a "can't tell" now fails them instead of passing them.
- `docs/platform.md`: the process-state row and the zombie limit.
- No product code calls `is_running`, so no user-facing behaviour, schema or error code changes. #90's branch
  (`windows-kill-after-child`) touches the same test file; whichever lands second rebases.
