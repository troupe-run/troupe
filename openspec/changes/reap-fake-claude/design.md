# Design

## Context

See proposal.md, "Why". Here's what the fix has to work with:

- troupe's platform starts every child with `start_new_session=True` on POSIX, or in a job of its own on Windows.
  `ChildProcess.kill_tree()` then kills the group with `os.killpg(pid, SIGKILL)`, or terminates the job
  (`packages/troupe/src/troupe/platform/processes.py`). The runner keeps Claude Code in its own process group on
  POSIX, so troupe's kill reaches it. On Windows the runner gives Claude Code a job nested in its own, created with
  `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (`plugins/runner-claude-code/src/troupe_runner_claude_code/processes.py`).
- The plugin's harness (`tests/claude_harness.py`, `Session`) starts the runner with a plain `Popen`, so it stays in
  pytest's process group. `Session.kill()` calls `process.kill()` on the runner's pid alone. The `sessions` fixture
  calls `kill()` on every session at teardown.
- The plugin's tests import nothing from troupe. Core's tests load `fake_claude.py` by path
  (`packages/troupe/tests/claude_stand_in.py`) and start the stand-in through troupe's real host, which already
  kills the group.
- The runner's environment in these tests is minimal: `PATH` holding only the stand-in, plus `FAKE_CLAUDE_*`. perform
  chooses its own. Only the shim, which `install()` writes, runs every time a stand-in starts.
- `scripts/check_paths_reach.py` works out statically which suites reach which package. A module loaded for every
  suite that names `plugins/runner-claude-code` would make every suite reach that plugin.

## Goals / Non-Goals

**Goals:**

- The harness ends a runner as troupe does, so a test that ends mid-run leaves nothing behind.
- Any test, in the plugin or in core, that leaves a stand-in running fails, and the stand-in is stopped.

**Non-Goals:**

- Changing the runner or core. Their teardown is already right. This change only makes the tests match it.
- The scripted runner's harness. It has the same `kill()`, but the scripted runner starts no process, so it has
  nothing to leak.
- Stand-ins left by earlier runs on a developer's machine. Those can be cleared once by hand. The check only covers
  stand-ins started in the run it's part of.

## Decisions

### D1. The harness starts and kills the runner as troupe's platform does

On POSIX, `Session` starts the runner with `start_new_session=True`, and `kill()` sends `SIGKILL` to the group
(`os.killpg`), ignoring `ProcessLookupError`, before it waits for the runner. This is what `kill_tree` does. It
runs even when the runner has already exited, because the group outlives its leader while a member is still
running. That case would be a contract break (the runner never exits while Claude Code runs), and the check (D3)
would report it.

On Windows the harness keeps killing the runner's process. When the runner ends, its handle to Claude Code's job
closes, and `KILL_ON_JOB_CLOSE` ends the stand-in. troupe's own job reaches the same result.

**Alternative: give the harness a Windows job of its own.** That would mean about forty lines of ctypes, a copy of
what's in core and the plugin. It's left out because the runner's nested job already covers it. The check (D3)
runs on Windows CI, so if the job doesn't cover it, the check fails there. One case isn't covered: the runner's job
can't be created (the fallback in `processes.start`). troupe's own job would still hold the stand-in, but the
harness has no job. If CI shows that happening, the harness gains a job.

**Alternative: stop the stand-in in the test** (cancel the run before the test ends). That fixes one test, not the
cause. The issue asks for the teardown to work the way a real one does.

### D2. Each stand-in records itself in a ledger, holding a lock while it runs

When `FAKE_CLAUDE_LEDGER` is set, the stand-in's first step is to create `<ledger>/<pid>.lock` and take an exclusive
lock on it (`fcntl.flock` on POSIX, `msvcrt.locking` on Windows). It holds the lock until it ends. Then it writes
`<pid>.json` with its pid, working directory and argv, replacing the file whole as `_write_record` does. The OS
releases the lock when the process ends, however it ends, `SIGKILL` included. So a lock still held means that
stand-in is still running, and the pid still belongs to it, since a pid isn't reused while its process exists.

`install()` writes `FAKE_CLAUDE_LEDGER`, when it's set in the installing process, into the shim (`export` on POSIX,
`@set` in `claude.cmd`), so it reaches the stand-in whatever environment the runner or perform passes on. When it
isn't set (the stand-in run by hand, or the capture tool), there's no ledger, which is the old behaviour.

The ledger and lock code is in `fake_claude.py`, written with the standard library only: the stand-in's side
(register) and the reader's side (list entries, see whether a lock is still held, stop a pid). It's the one place
that branches on the OS for this.

**Alternative: check `alive(pid)` against the pid in the record.** It's simpler, but if the pid is reused while the
check waits, the check would report another process as a leak, and could stop it. The lock makes "this pid is still
the stand-in" something the OS answers. Stopping an unrelated process is the one result this check can never risk.

### D3. A pytest check per suite, in conftest, checks around each test

`plugins/runner-claude-code/tests/stand_in_guard.py` (pytest plus the standard library) holds the check:

- At configure, it sets `FAKE_CLAUDE_LEDGER` to `<tempdir>/troupe-stand-ins-<pid of this pytest process>` and
  creates the directory. The path is worked out from the pid, so two copies of the module in one process (the
  plugin's and core's) agree on it. Under xdist each worker has its own process, so it gets its own ledger, and
  overwrites the controller's value it inherited. At unconfigure it removes the directory, ignoring errors.
- `pytest_runtest_setup` (a wrapper) records which `.lock` entries exist before the test. A `pytest_runtest_teardown`
  wrapper, after every fixture's teardown has run, takes the entries added since. For each, it waits up to
  `STAND_IN_END_SECONDS` (5.0, a named constant with its reason) for the lock to be released. If the lock is still
  held after that, it stops the pid (`SIGKILL`, or `TerminateProcess` through `os.kill` on Windows), waits the same
  bound again, and fails the teardown. The failure names each stand-in's pid, its working directory (from the
  `.json`, or "not recorded yet") and whether stopping it worked. If the stop doesn't work within the bound, the
  failure says so. It never waits silently or without a bound.
- It's loaded by a `conftest.py` in each suite that uses the stand-in. The plugin's `tests/conftest.py` imports the
  hooks from `stand_in_guard`. Core's new `packages/troupe/tests/conftest.py` loads `stand_in_guard.py` by path (as
  `claude_stand_in.py` does) and binds the same hook functions. conftest hooks only apply to tests in their own
  directory, so each test is checked once, and no other suite loads the check. Core's suite already reaches the
  plugin through `claude_stand_in.py`, so `check_paths_reach.py` sees no new reach.

**Alternative: a `-p stand_in_guard` plugin in `addopts`, as `protocol_guard` is.** That's a single place, but it
loads for every suite. Its path into `plugins/runner-claude-code` would make every suite reach the plugin, so every
plugin change would run the scripts' and the other packages' suites.

**Alternative: a check once at session end.** That's cheaper, but it fails the session rather than the test that
leaked, and under xdist a worker's session-end failure doesn't reach the controller's exit status as a named test.

### D4. Test the check before fixing the harness

The check goes in first, with the harness unchanged, and has to fail `test_a_second_run_start_is_refused` on macOS,
naming its stand-in. That run is the evidence the check catches the leak #276 describes. Then D1 goes in and the
same test has to pass. The check's own tests run a child pytest in `tmp_path` (with `--confcutdir`, so the
repository's conftests don't load into it). They cover a test that leaks a hanging stand-in (it fails, naming it,
and afterwards it isn't running) and a test whose stand-in ended (it passes). The pid-reuse scenario is tested
directly on the reader's side: a `.lock` entry with no holder, whose pid now belongs to a live process the test
started, reads as ended and isn't signalled.

## Risks / Trade-offs

- [A stand-in that registers after its test's check has run, because the runner was killed between starting the
  shim and the stand-in's first step] → the next test in the same worker counts it as its own. The failure names the
  stand-in's working directory, which is under the test it came from, so it can still be traced. The window is the
  shim's start-up time.
- [`msvcrt.locking` releases a dead process's lock "after an unspecified time"] → the bounded wait covers it. If
  Windows CI shows false failures, the bound is the one place to change.
- [Two `conftest.py` files named the same in different suites, with the default import mode] → pytest imports
  conftests by path, and `scripts/tests/conftest.py` already lives alongside the others. A full `scripts/check.py`
  run confirms collection.
- [The check's per-test cost] → a directory listing before and after each test in two suites. It only waits when a
  stand-in started during the test.
- [The ledger directory is left behind after a crashed pytest] → it's under the temp directory, named by the pid,
  and empty apart from small files. The next run with the same pid reuses the directory, and its stale entries are
  in the setup snapshot, so they're never counted.
