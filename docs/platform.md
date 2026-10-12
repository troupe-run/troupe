# The platform seam

`troupe.platform` is the one place where troupe's behaviour depends on the operating system. Everything else in
troupe calls it and sees one behaviour on Linux, macOS and Windows. An import contract keeps OS-specific modules
(`fcntl`, `msvcrt`, `termios`, `signal`, `ctypes` and others) out of every other package.

`troupe.platform` raises its own small exceptions. `troupe.core` wraps each call, supplies the defaults from
`troupe.core.defaults`, and turns failures into structured errors with a code, the problem and the fix.

| What | Where | Linux and macOS | Windows |
|---|---|---|---|
| Atomic file replacement | `platform/files.py` | Temporary file in the same directory, fsynced, given the original's permission bits, renamed over the target. The directory is then fsynced. | The same, except a directory can't be fsynced (NTFS journals the rename). A read-only target stays read-only: the flag is lifted only for the rename. |
| A replacement target that is open elsewhere | `platform/files.py` | Never blocks: the rename succeeds and the other program keeps the old contents. | Windows refuses the rename while another program has the file open. troupe retries with backoff, says which file it is waiting for after `REPLACE_ANNOUNCE_AFTER_SECONDS`, and fails with `replace.in-use` after `REPLACE_TIMEOUT_SECONDS`. |
| Reading a file that is being replaced | `platform/files.py` | Always sees the old or the new file. | Opening the file can briefly fail while a replace completes. `read_bytes` retries that, bounded and announced like a replacement, so the reader still gets one complete version. |
| Directory locks | `platform/locks.py` | `fcntl.flock` on `<directory>/.lock` | `msvcrt.locking` on the first byte of `<directory>/.lock` |
| Paths shown to people | `platform/paths.py` | `~/Projects/theatre` | `~\Projects\theatre` |
| Starting a child process | `platform/processes.py` | A new session, so the child leads its own process group. Only the caller's variables are passed. | A new process group, and the child is assigned at once to a new job object created with kill-on-close. `SYSTEMROOT` is always passed, because Python and sockets need it. |
| Killing a child and everything it started | `platform/processes.py` | `SIGKILL` to the process group | The job is terminated. If troupe itself dies, the job's last handle closes and the tree dies with it. |
| Reading a child's output | `platform/processes.py` | Line by line, with a caller-set maximum; a longer line is an error naming the maximum, never a hang | The same |

## Locks

- **Lock file:** a lock is an OS-level exclusive lock on an empty file, `.lock`, inside the directory it protects.
  The OS releases it when the holder exits, even after a crash, so there is no stale-lock clean-up. The file
  stays in place; it is never deleted, because deleting it would race with a process waiting on it.
- **Waits are never silent:** a waiting process says what it is waiting for after `LOCK_ANNOUNCE_AFTER_SECONDS`,
  and gives up with `lock.timeout` after `LOCK_TIMEOUT_SECONDS`.
- **No self-deadlock:** taking a lock the same process already holds fails immediately with
  `lock.already-held`.

## Child processes

- **Explicit environment:** a child gets only the variables its caller names, plus `MINIMUM_ENVIRONMENT` (empty on
  Linux and macOS, `SYSTEMROOT` on Windows). Nothing else is passed through, so a host secret can't leak into a
  runner by habit.
- **Command lookup:** the command is resolved to an absolute path with the caller's search path before the child
  starts, so the child doesn't need `PATH` unless the caller names it.
- **Stopping:** `kill_tree()` kills the child and everything it started. Asking a child to stop gracefully is a
  protocol matter (for runners, `run/cancel`), not a signal, because Windows has no `SIGTERM`.

## Defaults

Every limit has its default in `troupe.core.defaults`, and each can be overridden by the caller.

| Setting | Default |
|---|---|
| `LOCK_TIMEOUT_SECONDS` | 30 |
| `LOCK_ANNOUNCE_AFTER_SECONDS` | 1 |
| `REPLACE_TIMEOUT_SECONDS` | 10 |
| `REPLACE_ANNOUNCE_AFTER_SECONDS` | 1 |

## Paths

Paths in messages are absolute, with the home directory shown as `~`, and never `.` or relative. Matching the
home directory ignores case on Windows and macOS, whose file systems are case-insensitive by default. On a
case-sensitive macOS volume, a path that differs from the home directory only in case is still shown as being
under `~`.

## Known limitations

- **A grandchild that starts its own session** (`setsid`) on Linux or macOS leaves the process group, so killing
  the tree misses it. Runners are first-party or reviewed, and containerised actors are stopped by container.
- **Windows job assignment** happens just after the child starts. A child that started a process within that
  instant would leave it outside the job. Runners start nothing before they read their first message.
- **Network file systems:** `flock` over NFS and SMB is unreliable. A theatre on a network share is not
  supported.
- **Windows permission bits:** Windows keeps only the read-only flag. That flag is preserved; other POSIX bits
  have no Windows equivalent.
