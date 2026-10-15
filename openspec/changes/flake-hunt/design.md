# Design

## Context

See proposal.md for why, and the two specs for what. What exists today:

- **A scratch version ran on #100**, from outside the repository: a thread per worker, each running
  `python -m pytest --junitxml` round after round, with `HYPOTHESIS_STORAGE_DIRECTORY` per round and a short
  `--basetemp`. Its first run failed every `tmp_path` test because the basetemp's parent didn't exist, and it called
  `os.getloadavg()`, which Windows doesn't have. Both are design inputs below.
- **`scripts/`** holds standalone tools run with `uv run` (`check.py`, `benchmark_event_store.py`,
  `release_config.py`), typed and linted like the packages, with tests in `scripts/tests/`.
- **The scripted runner** (`plugins/runner-scripted/.../runner.py`): a reader thread queues troupe's messages, and
  `serve()` calls `_drain()` (answer everything queued, without waiting) before every step. A replay without delays
  drains before every record. `wait` steps, replay delays and `hang` answer messages while they wait, and so does the
  loop after the last step. `shutdown` answers and exits 0.

## Goals / Non-Goals

**Goals:**
- One script, the same options and output on Linux, macOS and Windows, using only the standard library and the
  workspace's pytest.
- The hunt keeps working when the code it hunts in is broken: it doesn't import `troupe`.
- Never waits silently or without limit: every round is announced as it ends, and a hung round is killed and
  reported.
- Nothing the hunt starts outlives it, on any platform: not when a round ends, not on Ctrl-C, and on Windows not
  even when the hunt itself is killed.
- A script's steps play the same way whenever troupe's messages arrive.

**Non-Goals:**
- Running hunts in PR CI, or on a self-hosted runner. The hunt's own tests do run in CI, on all three platforms.
- Retrying or quarantining flaky tests. The hunt finds them; each is fixed by its kind (#100).
- Fixing the other suspects #100 lists from reading. They join this change as tasks when the hunt shows them fail.

## Decisions

### D1: The default selection is the whole suite, not a list of OS-sensitive tests

With no paths and no `-k`, a round runs whatever the repository's pytest configuration collects. Paths and `-k`
narrow it, and the docs give the narrowed command used on #100 (the platform, run host, CLI-runs, store, git adapter
and scripted runner tests).

- **Alternative: a list of "time-sensitive" files inside the script.** It's a hand-maintained coverage list with no
  trigger to update it, so it would quietly stop covering a new test file. The full suite costs about 3.5 minutes a
  round. A short hunt narrows it on the command line, where the choice is visible in the evidence.
- **Alternative: a pytest marker on each sensitive test.** Same drift, spread over every test file.

### D2: Each round is a separate pytest process, reporting through JUnit XML

A round runs `sys.executable -m pytest -p no:cacheprovider --basetemp=<dir> --junitxml=<file> <selection>` from the
repository root. Failures are read from the XML report (the standard library parses it), and the round's whole
output is kept beside it. A process per round means a crash, a leaked thread or a hung test costs one round, not the
hunt. JUnit XML is pytest's own stable report format, so no plugin is needed.

- `--basetemp` is short and under the system temporary directory (`<tmp>/flake-hunt/<run>/w<worker>r<round>`), with
  its parent created first. A long base path changes behaviour: on macOS a Unix socket path is limited to 104 bytes,
  and on Windows paths over 260 characters fail without the long-path prefix.
- The cache provider is off, so rounds don't share `--lf` state and don't write `.pytest_cache`.
- Each round also passes `-o faulthandler_timeout=<--stall>` (300 s by default), pytest's own option. A test that
  runs past it has every thread's stack written straight to the round's output, unbuffered. A round's output goes to
  a file, so pytest's own output is block-buffered, and a round killed at its timeout loses it. The owner's Windows
  hunt had a round hang for 20 minutes and leave an empty log. The summary keeps a stall dump from its start, where
  the stuck test is named, instead of the output's last 4,000 characters.
- **Alternative: pytest-xdist or pytest-repeat.** New dependencies (#83 is the separate question of parallel
  tests), and both run many tests in one process, so one crash ends the round's other tests and one leaked thread
  reaches the next test.

### D3: Each round gets a private, empty hypothesis database

A round runs with `HYPOTHESIS_STORAGE_DIRECTORY` set to a new directory in the hunt's output, which hypothesis reads
for its example database. Seeds stay random (hypothesis' default, with no `--hypothesis-seed`), so every round explores
new examples and none replays one saved earlier. The repository's `.hypothesis/` is never read or written: a saved
failure there would replay in every later local commit. A hypothesis failure's falsifying example is in its
traceback, which the summary keeps.

Each round also passes `--hypothesis-profile=default`. Hypothesis loads its own `ci` profile (fixed seeds, no
database) whenever it sees `CI` set, as on GitHub Actions or in a shell that exports it, and the rounds would then
replay the same examples every time. The option is pytest's own, so the rounds' environment stays the hunt's (D10).
Found on the draft PR's first CI run, where the database test failed on every platform.

### D4: The hunt starts and stops its own processes, without `troupe.platform`

Each round and each load process is started so that it and everything it starts can be killed together:

- **Linux and macOS:** a new session, so the process leads its own group, killed with `SIGKILL` to the group.
- **Windows:** a job object created with kill-on-close. The process is started with `CREATE_SUSPENDED`, assigned to
  the job, then resumed (`NtResumeProcess`, through ctypes), so nothing it
  starts can run before it is in the job. Stopping it terminates the job. If the hunt itself dies, its job handles
  close and the trees die with it. The suspended start matters on Windows in particular: `sys.executable` in a uv
  virtual environment is a launcher that starts the real interpreter as its child (#90's trap), and a test's
  grandchild can outlive its parent. A job holds both.

A round past `--round-timeout` (default 20 minutes, the CI job's limit) is killed and reported as hung, with its
output so far.

- **Alternative on Windows: `taskkill /T /F /PID`.** It walks the tree by parent pid, so it misses a process whose
  parent has already exited, and it can't take back a tree when the hunt is killed.
- **Alternative on Windows: assign the job after the process starts.** That's the gap #100 found in
  `troupe.platform.processes`: a child started before the assignment escapes the job.
- **Alternative: `troupe.platform.processes`.** `run_to_completion` can't be cancelled from another thread, which is
  how Ctrl-C reaches the workers. The hunt shouldn't depend on the seam it is hunting flakes in either: if that seam
  breaks, the hunt should still run and report it. The two kinds of tree kill are about 60 lines of the script.

### D5: Workers are threads, and the main thread owns stopping

Each worker is a thread that runs its rounds in turn and appends each result to the results file as the round ends.
The main thread waits on the workers, and on Ctrl-C (`KeyboardInterrupt`) it sets a stop flag, kills every running
round's tree and the load, joins the workers (bounded, and announced if slow), then prints the summary of the rounds
that finished. Load processes start before the first round, and stop in a `finally`, however the hunt ends.

- The main thread waits in joins of at most 0.5 s at a time, never one join with no timeout. On Windows a blocking
  `join()` can't be interrupted, so Ctrl-C would wait for the whole hunt.
- On Windows, Ctrl-Break (`SIGBREAK`) stops the hunt the same way. A process in its own console process group gets
  only Ctrl-Break, and the hunt's own test sends it that way.
- On Windows each round gets a console of its own, with no window (`CREATE_NO_WINDOW`), so a Ctrl-C typed at the
  hunt reaches only the hunt, which then stops the rounds itself. Two alternatives failed:
  - **A new process group** turns Ctrl-C off in the round and in everything it starts. The owner's first Windows
    hunt showed it: `test_a_real_ctrl_c_on_windows_calls_back_too` failed in every round, because its child never
    got the Ctrl-C it sent itself.
  - **The hunt's own console and group** let the person's Ctrl-C reach a round's pytest too. pytest exits at once,
    before the hunt's main thread has seen the interrupt, so the round was recorded as a crash. The interrupt
    test caught that on Windows CI.

### D6: Load is busy interpreter processes, bounded by the CPU count

`--load N` starts N processes of `sys.executable -c "while True: pass"`. N above the CPUs the hunt may use is refused
(see spec), because past that the hunt measures the scheduler rather than the tests, and the person asked not to
saturate the machine. The CPUs it may use come from `os.process_cpu_count()` where it exists (Python 3.13, which
honours affinity and a container's CPU limit), and `len(os.sched_getaffinity(0))` or `os.cpu_count()` otherwise.
Load is reported with the platform: `os.getloadavg()` where it exists, and "not available" on Windows, never a
made-up number.

### D7: Output goes to a directory outside the repository by default

`--out` names the directory. By default it is `<tmp>/flake-hunt/<UTC timestamp>`, so a hunt never leaves files in
the working tree. It holds `results.jsonl` (one record per round, appended as each ends, so an interrupted hunt keeps
its evidence), `summary.json`, and each round's output and XML report. The hunt prints the path at the start and the
end.

### D8: Linux runs from a Dockerfile in `scripts/`, as an ordinary user, with `--init`

`scripts/flake_hunt.Dockerfile` builds from the uv image on a current Debian, with git installed. It creates a
non-root user, copies the repository in (from `git archive HEAD`, so the container's files are its own and nothing
is bind-mounted), and runs `uv sync --locked` for the Python version given as a build argument. The docs run it with
`docker run --init`.

- **Non-root**, because CI runs as an ordinary user, and root changes what `chmod` and `kill(pid, 0)` do.
- **`--init`**, because without a PID 1 that reaps orphans, the kill-the-tree tests read leftover zombies as running
  and fail for a reason no CI runner has (#100).
- **A copy, not a bind mount**, because file locking and watching on a mount from the host behave unlike a local
  Linux file system.
- Two tests fail in a container for container reasons (#100): the PID 1 test, because PID 1 is the hunt's own user,
  and the git variable test, on a git older than the adapter's list. The image uses a git current enough for the
  second. The first, and the git gap itself, get their own issues rather than being hidden by the image.

### D9: The scripted runner reads messages only where a step waits

`serve()` stops calling `_drain()` before every step, and a replay without delays stops draining before each record.
Messages are answered at a `wait`, during replay delays, at a `hang`, and after the last step. Those were the places
where waiting was already part of the step. The instant steps between them (events, transcript records, standard
error, raw output, file writes, exit) play back to back.

- That makes the scripts in `test_run_host` deterministic: "ok, then exit 3" always exits 3, the late event is always
  sent, and in `test_a_cancelled_run_keeps_every_transcript_record_received` both records always come before the
  cancel is answered at the `hang`.
- **Alternative: keep draining, and change the tests.** A test can't order the host's `shutdown` against the runner's
  next step. Only the runner can, so a test-side fix would mean sleeps.
- **Alternative: a per-step "don't drain before this" flag.** It adds a schema field every script author must
  remember, to get what should be the default: a script plays as written.
- **What changes for scripts:** a cancel or shutdown sent while instant steps play is answered a little later, at
  the next waiting step or the end. Every scripted outcome is still reachable. "A cancel that is honoured" and "a
  cancel that is ignored" are both built on `hang` or `wait`, and those still answer at once.

### D10: Windows is a first-class platform for the hunt, not a port

The Windows PC is where most of the flakes are (#100: 9 of 11 in CI), so these are part of the design, each with a
test that runs in the Windows CI job (the hunt's tests run in `check.py` on all three platforms):

- **Output is bytes until it's printed.** A round's output is kept as bytes and written to its log file unchanged.
  It's decoded as UTF-8 with `errors="backslashreplace"` only to read the end of a crashed round. The hunt
  reconfigures its own standard output and error the same way, so a traceback holding text the console's code page
  can't show (the suite has `ünïcødé` tests, and a Windows console is often cp1252) still prints, instead of
  crashing the summary. The JSON files are written as UTF-8 whatever the console is.
- **The rounds' environment is the hunt's, unchanged.** Setting `PYTHONUTF8` or `PYTHONIOENCODING` for the rounds
  would make them unlike a CI run, which is the thing being reproduced.
- **Paths stay short.** The run directory under `%TEMP%` is named `fh-<6 characters>`, and each round's basetemp is
  `w<n>r<n>` under it. pytest's own nesting then stays well under 260 characters from a default `%TEMP%`.
- **One environment per Python version.** `uv run --python 3.13` re-syncs the project's `.venv` to 3.13, replacing
  the environment the person develops in. The docs run other versions through `scripts/on.py` (python-version-bounds,
  #104), which gives each its own `.venvs/<version>`, on every platform. The summary names the interpreter it ran.
- **The docs cover what only Windows has:** PowerShell commands; Git for Windows on the PATH (the git adapter's tests
  need it); QuickEdit mode, where a click in a console window pauses everything that writes to it, so use Windows
  Terminal or don't click in the window during a hunt; and recording whether Microsoft Defender real-time
  protection is on, because it slows file operations and is part of the evidence.

### D11: The agreed campaign is a script of its own, that runs the hunt as a subprocess

`scripts/flake_campaign.py` runs the matrix #100 agreed (`--workers auto` × 10 rounds; load 0 and 2; every supported
Python; direct, then Docker with `--docker`, or only Docker with `--docker-only`), one hunt after another, never two at once. Two hunts at once would load
each other, and an unattended run that fans out is what this project avoids. Each hunt is `flake_hunt.py` itself:

- **Direct:** `uv sync --locked --python <version>` into `.venvs/<version>`, the environment `scripts/on.py` uses,
  then that environment's interpreter runs `flake_hunt.py` itself. Not `on.py` and `uv run`: a Ctrl-C has to reach
  the hunt with no uv process in between that might end before the hunt has written its summary. `.venv` is never
  touched, whatever Python it holds.
- **Docker:** the image for each version is built once per campaign from `git archive HEAD`, then each hunt is
  `docker run --init` in a container named for the campaign and the hunt. Its results are copied out with
  `docker cp`, and the container is removed. Docker hunts the commit while direct hunts hunt the working tree, so
  uncommitted changes refuse the campaign when `--docker` or `--docker-only` is given. `--docker-only` hunts only
  Linux, for a machine whose direct hunts have already run, or to hunt Linux from Windows or macOS (owner,
  2026-10-16).
- **The Python versions are the supported range**, from `python_versions.supported()` (python-version-bounds), the
  one place they're decided. Its check keeps them equal to CI's matrix, so when #104's Part 2 widens both, the
  campaign widens with them. A malformed bound refuses the campaign, naming the problem.
- **Workers are `auto`**: three quarters of the CPUs the hunt may use, rounded down, less the load, and at least 1
  (owner, 2026-10-15). Counting the load inside the share keeps a with-load hunt from oversubscribing the machine:
  on 8 CPUs, 6 workers alone, or 4 workers and 2 busy CPUs. The first Windows hunts used 10 workers on 8 logical CPUs, which loads the machine well past what a
  person's own runs do. Each hunt resolves `auto` itself, so a container counts its own CPUs.
- **The selection** (spec: "The campaign's selection is the OS-sensitive tests, named in one place") is a tuple of
  glob patterns in the campaign script: `test_platform_*.py`, the run host, CLI runs, the store, the git adapter and
  the scripted runner. That's the selection #100's hunts used, and it's what the owner typed by hand on Windows.
  Patterns, not a file list, so a new platform test file joins without an edit. A test checks each pattern still
  matches. `--all` hunts the whole suite instead. This differs from D1 only for the campaign: a full-suite campaign
  is most of a day on Windows, while a single hunt's default stays the whole suite.
- **The report** reads each hunt's `summary.json` and writes `report.md` (for #100) and `campaign.json`, with the
  commit (`git rev-parse HEAD`, and whether the tree was clean), the machine and the options. It's written after every
  hunt, so a stopped or crashed campaign still leaves the report of what ran.
- **Ctrl-C** reaches the running hunt as it would anyway (it's in the same console or process group, and `docker run`
  forwards it), so the hunt stops itself and writes its summary. The campaign waits for it, bounded, runs nothing
  more, and writes the report.

## Risks / Trade-offs

- [A clean hunt on macOS and Linux finds little, as on #100] → It's a tool for the Windows PC too, and the per-test
  summary makes the Windows rounds as cheap to read as the others. The number of rounds for "done" is agreed on #100.
- [The Windows job and suspended start are ctypes code in a script, outside the seam's tests] → Its tests run on the
  Windows CI job: a round's grandchild that outlives its parent is gone once the round is stopped, and so is the tree
  of a round that is still running when the hunt is killed.
- [A nested job is refused] → Windows 8 and later allow nested jobs, and CI's Windows runners already run the hunt's
  tests inside the runner's own job. If assignment is refused, the hunt names the error and doesn't start, rather than
  running rounds it can't stop.
- [A round's grandchild escapes its group on POSIX] → It's a test that started its own session. The hunt reports the
  round normally. A leaked process like that is itself a finding for #100, and the docs say to look for one after a
  hunt.
- [Changing when the runner answers delays a cancel during a long run of instant steps] → Instant steps take
  microseconds, and any script that runs long has a `wait` or `hang`, which answers at once.
