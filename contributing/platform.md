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
| Durable append | `platform/files.py` | One handle opened for appending, all bytes written, then fsynced; a new file's directory is fsynced too. A crash leaves at most a prefix of the appended bytes. | The same, in binary mode, so line feeds are never turned into CRLF. A directory can't be fsynced (NTFS journals the creation). |
| Directory locks | `platform/locks.py` | `fcntl.flock` on `<directory>/.lock` | `msvcrt.locking` on the first byte of `<directory>/.lock` |
| Paths shown to people | `platform/paths.py` | `~/Projects/theatre` | `~\Projects\theatre` |
| Starting a child process | `platform/processes.py` | A new session, so the child leads its own process group. Only the caller's variables are passed. | A new process group, and the child is assigned at once to a new job object created with kill-on-close. `SYSTEMROOT` is always passed, because Python and sockets need it. |
| Killing a child and everything it started | `platform/processes.py` | `SIGKILL` to the process group | The job is terminated. If troupe itself dies, the job's last handle closes and the tree dies with it. |
| Reading a child's output | `platform/processes.py` | Line by line, with a caller-set maximum; a longer line is an error naming the maximum, never a hang | The same |
| Whether a process has ended | `platform/processes.py` | `kill(pid, 0)`: no such process (`ESRCH`) is ended; success or a refusal (`EPERM`) is running | `OpenProcess`, then whether the handle is signalled (`WaitForSingleObject`, zero timeout): no such process (`ERROR_INVALID_PARAMETER`) or signalled is ended; a refusal (`ERROR_ACCESS_DENIED`) or not signalled is running |
| Watching a directory for changes | `platform/watching.py` | inotify on Linux, one watch on the directory; FSEvents on macOS, one stream with file events, no defer and latency 0 | `ReadDirectoryChangesW` on the directory, kept outstanding with overlapped I/O |
| Catching Ctrl-C | `platform/interrupts.py` | `SIGINT`, through `signal.signal`, calls back instead of raising `KeyboardInterrupt` | `SIGINT` and `SIGBREAK` (Ctrl-Break: a process in its own console process group gets only that). The previous handlers come back when the block ends |

## Locks

- **Lock file:** a lock is an OS-level exclusive lock on an empty file, `.lock`, inside the directory it protects.
  The OS releases it when the holder exits, even after a crash, so there is no stale-lock clean-up. The file
  stays in place; it is never deleted, because deleting it would race with a process waiting on it.
- **Waits are never silent:** a waiting process says what it is waiting for after `LOCK_ANNOUNCE_AFTER_SECONDS`,
  and gives up with `lock.timeout` after `LOCK_TIMEOUT_SECONDS`.
- **No self-deadlock:** taking a lock the same process already holds fails immediately with
  `lock.already-held`.

## Child processes

- **Explicit environment:** a child gets exactly the environment its caller passes; nothing is inherited. The caller
  builds it with `build_environment(policy, explicit=...)`: `MINIMUM_ENVIRONMENT` (empty on Linux and macOS,
  `SYSTEMROOT` on Windows), plus the parent's variables the policy selects, plus explicit values.
- **Environment policies:** each port or adapter declares one `EnvironmentPolicy`, as a named default in one place.
  A policy selects variables by exact name (`names`) or by prefix (`prefixes`), and never passes `never` names or
  `never_prefixes`. An explicit value for a never-passed name is refused (`EnvironmentPolicyError`), not dropped.
  Names match case-insensitively on Windows. `policy.narrow(...)` keeps a subset and adds never-passed names; it
  refuses to select anything the policy doesn't already select, so a policy can be tightened but never loosened.
  Runners use `RUNNER_ENVIRONMENT`, which selects nothing.
- **Command lookup:** the command is resolved to an absolute path with the caller's search path before the child
  starts, so the child doesn't need `PATH` unless the caller names it.
- **Short commands:** `run_to_completion(argv, cwd=, env=, timeout=, max_output_bytes=, announce_after=)` runs a
  command such as git and returns its exit code and both outputs. It blocks and uses no event loop, so it works
  from anywhere; wrap it in `asyncio.to_thread` to keep a loop free. It never waits silently or without limit: it
  announces a long wait once through `on_wait`, and past `timeout` (`ProcessTimeoutError`, with the output so far)
  or past `max_output_bytes` of output (`OutputTooLargeError`) it kills the whole tree. A command that exits while a
  child still holds its output open counts as still running.
- **Stopping:** `kill_tree()` kills the child and everything it started. Asking a child to stop gracefully is a
  protocol matter (for runners, `run/cancel`), not a signal, because Windows has no `SIGTERM`.
- **Whether the kill ended it:** once `wait()` has returned the exit code, `ended_by_kill(exit_code)` says whether
  troupe's kill is what ended the child: `kill_tree()` was called and the exit status is the one a kill gives. A
  child that exited by itself before the kill landed keeps its own code, so it reads as having exited, however the
  timing fell. On Linux and macOS a kill is `SIGKILL`, exit status `-9`. On Windows, terminating a job sets an exit
  code the caller chooses, so troupe uses `KILLED_EXIT_CODE`, `0x74726B6C` (1953655660, "trkl" in ASCII). No
  program commonly exits with it and it isn't an NTSTATUS crash code. A program that exits with exactly that code
  while troupe's kill is in flight would be read as killed.
- **Whether a process has ended:** `is_running(pid)` answers that one question on every platform. A process the
  OS refuses access to exists, so it is running. It is ended only when the OS says there is no such process or that
  it has exited. Anything else raises `ProcessStateUnknownError`, naming the pid and the OS error, never a guess.
  Windows reads the exit from the process handle, not the exit code, because a process can exit with 259, the value
  `STILL_ACTIVE` uses. A value that can't name one process (`0`, a negative number, more than `PID_MAX`, a `bool`)
  is a `ValueError` before the OS is asked: on Linux and macOS `0` and negative pids address process groups.

## Watching

- **One question:** `watch(directory).wait(timeout)` says whether anything in the directory changed since the last
  wait returned: a file created, written, renamed, replaced or removed, or the directory itself removed. It never
  says what changed, because callers rescan anyway. It may report a change that wasn't one, never miss one.
- **Nothing is lost between waits:** the OS buffers changes, so a change made while nobody waits makes the next
  wait return at once.
- **Fixed resources:** a watch holds the same few handles however many files the directory has, so a directory of
  10,000 files is watched within a 256-file open limit.
- **It fails clearly or not at all:** a missing directory raises `WatchDirectoryMissingError`, and one the OS won't
  watch raises `WatchUnavailableError` with the OS's reason (on Linux, for example, the inotify watch limit
  `fs.inotify.max_user_watches`). A watch is never returned that wouldn't wake. If the directory is removed later,
  the next wait raises `WatchDirectoryMissingError`.
- **Closing wakes:** `close()` from another thread wakes a waiting thread at once, then releases the handles.

All three are reached through ctypes inside `troupe.platform`, with no compiled code and no dependency (decision on
#54, 2026-10-13).

## Defaults

Every limit has its default in `troupe.core.defaults`, and each can be overridden by the caller.

| Setting | Default |
|---|---|
| `LOCK_TIMEOUT_SECONDS` | 30 |
| `LOCK_ANNOUNCE_AFTER_SECONDS` | 1 |
| `REPLACE_TIMEOUT_SECONDS` | 10 |
| `REPLACE_ANNOUNCE_AFTER_SECONDS` | 1 |

## Adapters' commands

An adapter that runs commands calls `troupe.core.commands.run_command`, which builds the child's environment from the
adapter's own policy and turns platform failures into errors with a code, the problem and the fix:
`command.not-found`, `command.timeout`, `command.output-too-large` (each naming the command) and
`environment.policy-invalid` (a policy widened, or an explicit value it forbids). `narrow_policy` narrows a policy
under the same rule.

Each adapter declares its policy and limits in its own package, because `troupe.core` never imports an adapter.

### The git adapter (`troupe_vcs_git.defaults`)

`GIT_ENVIRONMENT` passes `HOME`, `USERPROFILE`, `APPDATA`, `XDG_CONFIG_HOME`, `PATH`, `SSH_AUTH_SOCK` and the user's
`GIT_*` variables, so git finds its config, credentials and SSH agent. It never passes the repository-location
variables a hook sets (exactly what `git rev-parse --local-env-vars` prints, plus `GIT_NAMESPACE`), so troupe always
reads the theatre's own repository. Nothing else of troupe's environment reaches git. The git adapter runs only
local commands, so git never starts a credential helper or `ssh`.

| Setting | Default |
|---|---|
| `GIT_TIMEOUT_SECONDS` | 10 |
| `GIT_ANNOUNCE_AFTER_SECONDS` | 1 |
| `GIT_MAX_OUTPUT_BYTES` | 16777216 |
| `GIT_RACY_WINDOW_SECONDS` | 0.1 |
| `GIT_COARSE_RACY_WINDOW_SECONDS` | 2 |

The adapter caches the branch and HEAD, and asks git again only when one of the files git changes on a move has
changed: `HEAD`, the index, `logs/HEAD`, `packed-refs`, the branch's own ref and the reftable table lists. An answer
read within `GIT_RACY_WINDOW_SECONDS` of such a change is used only once, because two git operations in one
timestamp tick can leave a file looking unchanged. Git treats its own index the same way. When every watched file's
timestamp is a whole second, as on FAT or HFS+, the window is `GIT_COARSE_RACY_WINDOW_SECONDS` instead.

## Paths

Paths in messages are absolute, with the home directory shown as `~`, and never `.` or relative. Matching the
home directory ignores case on Windows and macOS, whose file systems are case-insensitive by default. On a
case-sensitive macOS volume, a path that differs from the home directory only in case is still shown as being
under `~`.

## Known limitations

- **A grandchild that starts its own session** (`setsid`) on Linux or macOS leaves the process group, so killing
  the tree misses it. Runners are first-party or reviewed, and containerised actors are stopped by container.
- **An unreaped child reads as running** on Linux and macOS: `kill(pid, 0)` succeeds for a zombie, a process that
  has exited but whose parent hasn't waited for it yet. Telling the two apart needs `/proc` on Linux and a
  `sysctl` on macOS, two more platform paths for a case no caller hits: troupe waits for its own children, and a
  killed child's grandchildren are reparented to init, which reaps them. Windows has no zombies.
- **Windows job assignment** happens just after the child starts. A child that started a process within that
  instant would leave it outside the job. Runners start nothing before they read their first message.
- **Network file systems:** `flock` over NFS and SMB is unreliable. A theatre on a network share is not
  supported.
- **Watching on file systems that don't notify:** some (container bind mounts written from the host, network
  shares) accept a watch and then don't report other machines' writes. Nothing at set-up tells. The event store
  catches it with a periodic check and falls back to an announced poll ([contributing/event-store.md](event-store.md)).
- **FSEvents watches subdirectories too,** and reports changes made to a directory just before it was watched,
  for up to about half a second after the watch starts. Both are harmless: a reported change is only a cue to
  rescan.
- **Windows permission bits:** Windows keeps only the read-only flag. That flag is preserved; other POSIX bits
  have no Windows equivalent.
