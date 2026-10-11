# The platform seam

`troupe.platform` is the one place where troupe's behaviour depends on the operating system. Everything else in
troupe calls it and sees one behaviour on Linux, macOS and Windows. An import contract keeps OS-specific modules
(`fcntl`, `msvcrt`, `termios`, `signal`) out of every other package.

`troupe.platform` raises its own small exceptions. `troupe.core` wraps each call, supplies the defaults from
`troupe.core.defaults`, and turns failures into structured errors with a code, the problem and the fix.

| What | Where | Linux and macOS | Windows |
|---|---|---|---|
| Atomic file replacement | `platform/files.py` | Temporary file in the same directory, fsynced, given the original's permission bits, renamed over the target. The directory is then fsynced. | The same, except a directory can't be fsynced (NTFS journals the rename). A read-only target stays read-only: the flag is lifted only for the rename. |
| A replacement target that is open elsewhere | `platform/files.py` | Never blocks: the rename succeeds and the other program keeps the old contents. | Windows refuses the rename while another program has the file open. troupe retries with backoff, says which file it is waiting for after `REPLACE_ANNOUNCE_AFTER_SECONDS`, and fails with `replace.in-use` after `REPLACE_TIMEOUT_SECONDS`. |
| Directory locks | `platform/locks.py` | `fcntl.flock` on `<directory>/.lock` | `msvcrt.locking` on the first byte of `<directory>/.lock` |
| Paths shown to people | `platform/paths.py` | `~/Projects/theatre` | `~\Projects\theatre` |

## Locks

- **Lock file:** a lock is an OS-level exclusive lock on an empty file, `.lock`, inside the directory it protects.
  The OS releases it when the holder exits, even after a crash, so there is no stale-lock clean-up. The file
  stays in place; it is never deleted, because deleting it would race with a process waiting on it.
- **Waits are never silent:** a waiting process says what it is waiting for after `LOCK_ANNOUNCE_AFTER_SECONDS`,
  and gives up with `lock.timeout` after `LOCK_TIMEOUT_SECONDS`.
- **No self-deadlock:** taking a lock the same process already holds fails immediately with
  `lock.already-held`.

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

- **Network file systems:** `flock` over NFS and SMB is unreliable. A theatre on a network share is not
  supported.
- **Windows permission bits:** Windows keeps only the read-only flag. That flag is preserved; other POSIX bits
  have no Windows equivalent.
