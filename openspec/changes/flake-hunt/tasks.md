# Tasks

The hunt's tests run real pytest processes on small test files they write into `tmp_path`, not hand-written reports,
so each fixture is the shape pytest actually produces. None of these tasks runs a load loop without asking first.

## 1. The hunt runs rounds and reports them (spec: flake-hunt; design D1, D2, D3, D5, D7, D10)

- [x] 1.1 Add `scripts/flake_hunt.py` with its options (`--workers`, `--rounds`, `--load`, `--round-timeout`,
  `--out`, `-k`, test paths) and their validation: a value that isn't a whole number, is below its minimum, or (for
  `--load`) exceeds the CPUs the hunt may use (`os.process_cpu_count()`, else the affinity, else `os.cpu_count()`)
  is refused before anything runs, naming the option, the value and what's allowed. Verify with tests for each
  refusal, including 0 rounds and too much load, that nothing ran and the exit is non-zero
- [x] 1.2 Run the rounds: a thread per worker, each running its rounds back to back as
  `sys.executable -m pytest -p no:cacheprovider --basetemp=<short dir> --junitxml=<file>` from the repository root,
  with the round's environment the hunt's own plus `HYPOTHESIS_STORAGE_DIRECTORY` (a new directory per round), and
  the basetemp under `<tmp>/fh-<6 characters>/w<n>r<n>` with its parent created first. Print each round as it ends.
  Verify with a test that 2 workers × 2 rounds over a written file of one passing test runs 4 rounds, that a `-k` and
  a path select exactly what pytest selects, that a `tmp_path` test passes in every round (the scratch run's basetemp
  bug), and that the round's environment has no variable the hunt's lacks other than the hypothesis directory
- [x] 1.3 Read each round's JUnit report into failures (test id, message, traceback), and report a round with no
  report as a failed round with the end of its output, decoded as UTF-8 with `errors="backslashreplace"`. Keep each
  round's output as bytes in its log, unchanged. Verify with tests over real pytest runs of a failing test, an
  erroring fixture, a file that crashes pytest (`os._exit(3)` at import), and a crash whose output holds bytes that
  aren't UTF-8
- [x] 1.4 Write `results.jsonl` (one record per round, appended as each ends), `summary.json` (both UTF-8) and each
  round's output and report to `--out`, defaulting to `<tmp>/flake-hunt/<UTC timestamp>`. Print the path at the
  start and the end, then the summary: platform, the interpreter's path and version, workers, rounds, load (from
  `os.getloadavg()`, or "not available" where it doesn't exist), and per failing test its runs, failures, and the
  first failure's message and traceback. Exit 0 only when no round failed. Verify with tests: a test that fails only
  in alternate rounds (it counts its runs in a file) is summarised with its run and failure counts, and a clean hunt
  says none failed and exits 0
- [x] 1.5 Reconfigure the hunt's standard output and error with `errors="backslashreplace"`, so the summary prints
  on a console whose encoding can't show a failure's text. Verify with a test that runs the hunt with
  `PYTHONIOENCODING=cp1252` over a written test that fails with `assert "ünïcødé ✓" == ""`: the summary prints, the
  check mark is escaped in it, and `summary.json` holds the text unchanged
- [x] 1.6 Verify each round's hypothesis database is private: with a written hypothesis test that always fails,
  every round reports it, the falsifying example is in the summary's traceback, and the repository's `.hypothesis/`
  is unchanged (compare its file list before and after)

## 2. Load, timeouts and stopping (spec: flake-hunt; design D4, D5, D6, D10)

- [x] 2.1 Start each round and load process so its whole tree can be stopped: on POSIX a new session, stopped with
  `SIGKILL` to the group; on Windows a kill-on-close job, the process started with `CREATE_SUSPENDED | CREATE_NO_WINDOW`
  (a console of its own; not a new process group, which turns Ctrl-C off in everything the round starts), assigned
  to the job and then resumed (`NtResumeProcess`), stopped by terminating the
  job. If the job can't be created or assigned, refuse to start, naming the Windows error. Verify with a test whose
  written test starts a child that starts a sleeping grandchild, records the grandchild's pid, and exits: after the
  round is stopped, the grandchild is gone (on Windows, too, where its parent has already exited)
- [x] 2.2 Kill a round past `--round-timeout` and report it as hung, with its output so far. Verify with a written test
  that sleeps past a 5 s timeout: the round is reported hung within a few seconds of the timeout, the next round
  still runs, and nothing the hung round started is left running
- [x] 2.3 Start `--load N` busy processes before the first round and stop them in a `finally`. Verify with a test that
  the N processes run during the rounds and are gone when the hunt returns, both after a normal end and after a stop
- [x] 2.4 Stop on Ctrl-C, and on Windows on Ctrl-Break: set the stop flag, kill the running rounds and the load, join
  the workers in waits of at most 0.5 s (bounded overall, and announced if slow), and print the summary of the
  finished rounds. Verify with a test that interrupts a hunt part-way (`SIGINT` on POSIX; on Windows,
  `CTRL_BREAK_EVENT` to a hunt started in its own process group) and checks that it stops within 5 s, the finished
  rounds are summarised and no process the hunt started is left
- [x] 2.5 Windows only: verify that killing the hunt's own process (`TerminateProcess`, so no `finally` runs) while a
  round runs ends the round's tree, because the job's last handle closes. Mark the test to skip elsewhere, with the
  reason
- [x] 2.6 Run `uv run scripts/check.py`, push the branch and open a draft PR (`Closes #100`), so the hunt's tests run
  on the Windows CI jobs. Verify every job passes on Linux, macOS and Windows, both Pythons, and record the run id

  Recorded: PR #103. The first run (38709557921) failed on five jobs and found two hunt bugs: hypothesis's CI
  profile (fixed seeds, no database) replayed the same examples every round, and a round the stop killed could be
  recorded as crashed. Both were fixed in 62148fc, and run 38711141945 passed on all six jobs. On Windows, 2.5's test
  ran (not skipped).

## 3. Running it on each platform (spec: flake-hunt "The hunt runs on every platform"; design D8, D10)

- [x] 3.1 Add `scripts/flake_hunt.Dockerfile` (uv on a current Debian, git, a non-root user, the repository copied in
  from `git archive HEAD`, `uv sync --locked` for a `PY` build argument). Verify by building it for 3.12 and 3.13 and
  checking, inside the container, that the user isn't root and that `git rev-parse --local-env-vars` lists nothing
  the git adapter's list lacks
- [x] 3.2 Write `docs/flake-hunt.md`: what the hunt is for and what it reports; how to read the summary; what to put
  on #100 for a finding; the narrowed selection used on #100; and per platform:
  - macOS and Linux: the commands, each Python version in its own environment (`UV_PROJECT_ENVIRONMENT=.venv-3.13
    uv run --python 3.13 ...`);
  - Linux in Docker: building the image per Python, and `docker run --init` as the image's user, with why;
  - Windows: PowerShell commands (`$env:UV_PROJECT_ENVIRONMENT = ".venv-3.13"`), Git for Windows on the PATH, Windows
    Terminal rather than a console window with QuickEdit (a click pauses its output), Ctrl-C or Ctrl-Break to stop,
    and recording whether Defender real-time protection is on.

  Link it from the README's docs list. Verify each macOS and Docker command runs as written with 1 worker and 1
  round, and that running the 3.13 command leaves `.venv`'s Python at 3.12
- [x] 3.3 Record in a comment on #100 that the hunt is ready on the branch, with the Windows commands from the docs and
  the draft PR's green Windows run, so the owner can run it on the Windows PC

## 4. The scripted runner reads messages only where a step waits (spec: scripted-runner; design D9)

- [x] 4.1 Reproduce the race without a delay: a scripted-runner test that queues `initialize`, `run/start` (script:
  `init`, ok `result`, `exit 3`) and `shutdown` on the runner's input before it plays anything, then checks it exits
  3 with `init` and `result` sent and `shutdown` unanswered. Run it on the current runner and verify it fails (exit 0)
- [x] 4.2 Stop `serve()` and a replay without delays from draining between steps, so messages are answered at a
  `wait`, during replay delays, at a `hang` and after the last step. Verify 4.1 passes, and add a test that a
  `run/cancel` queued during instant steps followed by a `hang` is answered at the `hang`, after every instant step
  played
- [x] 4.3 Verify the run host's tests that depended on the race now hold under the delay that reproduced it on #100:
  with a temporary `time.sleep(0.2)` in the runner's step loop, `test_an_ok_result_followed_by_an_unclean_exit_fails_as_uncertain`,
  `test_a_late_event_after_the_result_crashes_the_run_whether_the_runner_answers_shutdown_first` and
  `test_a_cancelled_run_keeps_every_transcript_record_received` all pass. Revert the sleep and show it reverted
  (`git diff --stat`)
- [x] 4.4 Run every scripted-runner and run-host test, and `openspec validate flake-hunt --strict`. Verify they pass

## 5. The agreed campaign, from one command (spec: flake-hunt, the campaign requirements; design D11)

- [x] 5.1 Add `scripts/flake_campaign.py`: the plan (CI's Python versions from `ci.yml`, refused naming the file when
  missing; loads 0 and 2; 3 workers × 10 rounds; direct, then Docker with `--docker`), the selection patterns and
  `--all`, the refusal of uncommitted changes with `--docker`, running each hunt in turn, and the report
  (`report.md`, `campaign.json`) written after every hunt. Verify with tests: the plan's versions equal the real
  `ci.yml`'s; a workflow with no matrix line is refused naming it; each selection pattern matches a file; the direct
  and Docker command lines are what D11 says; a dirty tree with `--docker` is refused naming the files; a report built
  from real hunt summaries names each hunt, its failing tests with runs and failures, and the commit; and one direct
  campaign of 1 worker × 1 round on the running Python, over one test file, runs end to end into a report, with its
  environment outside `.venv`
- [x] 5.2 Stop on Ctrl-C (Ctrl-Break on Windows): the running hunt stops itself, the campaign waits for it (bounded),
  runs no more hunts, marks it stopped, and writes the report. Verify with a test that interrupts a campaign during
  its first hunt and checks the report and the exit code (130)
- [x] 5.3 Document the campaign in `docs/flake-hunt.md` (the command on each platform, with and without `--docker`,
  how long it takes, and what to post on #100), and verify the documented command runs on macOS with `--rounds 1`
- [ ] 5.4 Agree the campaign on #100 as the bar for "done" (`--workers auto` × 10 rounds, load 0 and 2, the supported Pythons,
  direct and Docker). Run it on macOS with `--docker`, and post its report on #100. Each failure found becomes a task
  appended here and a line on #100, fixed by its kind
- [ ] 5.5 The owner runs the same campaign on the Windows PC, direct and with `--docker` (Docker Desktop's Linux
  containers), and posts its report on #100. Each failure found becomes a task here, as in 5.4
- [ ] 5.6 Rebase the branch onto `main`, run `uv run scripts/check.py`, mark the PR ready for review, and verify all CI
  jobs pass on Linux, macOS and Windows

## 6. Flakes the hunts found, each fixed by its kind (#100)

The owner's first Windows hunts (2026-10-15, Surface Pro 8, 10 workers, Python 3.15.0 then 3.12) and #100's earlier
list. Rates are from the 3.12 run's 65 rounds. Each fix is its own commit, with a test that fails before it, and a
spec scenario where behaviour changes.

- [x] 6.1 The hunt: a round that hung for 20 minutes left an empty log, because a round's output is buffered and a
  killed round loses it. Each round now passes pytest's `faulthandler_timeout` (`--stall`, 300 s), so a stuck test's
  stack reaches the log, and the summary keeps the dump from its start. Verified by
  `test_a_test_stuck_past_the_stall_limit_has_its_stack_in_the_hung_rounds_output`
- [ ] 6.2 **Windows: removing a watched directory during a wait reads as unwatchable, not missing** (platform
  behaviour; 11 of 65 rounds). A directory deleted while a handle is open stays visible, pending deletion, so
  re-issuing `ReadDirectoryChangesW` fails with `ERROR_ACCESS_DENIED` (WinError 5), and `wait` raises
  `WatchUnavailableError`. Fix it in `troupe.platform.watching`: a refusal on a directory that is pending deletion is
  `WatchDirectoryMissingError`. Pin it with a Windows test that holds the race open, rather than relying on timing
- [ ] 6.3 **Windows and Linux: a watch wait can return before its timeout** (platform behaviour; #100, CI run
  38568514789). One deadline loop in `DirectoryWatch.wait`, on `time.monotonic()`, for every backend, including
  Linux's `poll` reporting ready with nothing to read. Pin it with a test of a backend that returns early
- [ ] 6.4 **`test_concurrent_no_conflicts` (eventsourcing's suite): reader threads outlive the test** (threads that
  outlive the test, #97's family; 1 of 65). Its reader threads are never joined, and one still holds
  `.troupe/local` while `TemporaryDirectory.cleanup` runs: WinError 145, "the directory is not empty". Make the
  library suite's tear-down wait (bounded) for every thread the test started, not only `troupe-subscription`
- [ ] 6.5 **`test_a_hung_git_times_out_and_its_whole_tree_is_stopped`: the pid file isn't there yet** (a missing
  precondition; 4 of 65). On Windows the 1 s timeout has to cover `git.cmd`, `cmd.exe`, the venv launcher, the
  interpreter and its child before the child writes its pid. The test then reads a file that doesn't exist. The fake
  git's child confirms it has started before the timeout can matter, and the test asserts the file exists before
  reading it
- [x] 6.6 **`test_appends_are_kept_byte_for_byte_with_line_feeds_untranslated`: hypothesis's 200 ms deadline** (the
  hypothesis deadline on a loaded machine; 2 of 65; one example took 564 ms). CI's `ci` profile has no deadline, but
  local runs and the commit hook do. Decide on #100 (owner) between `deadline=None` on every I/O-bound hypothesis test
  and one project profile in `conftest.py` that drops the deadline but keeps CI's fixed seeds, then apply it

  Decided (owner, 2026-10-15): one profile. `packages/troupe/tests/hypothesis_profiles.py`, loaded for every test path
  through `addopts`, re-registers hypothesis's `default` profile with no deadline; `ci` keeps its fixed seeds and no
  database. `test_hypothesis_profiles.py` checks both profiles, and runs a 300 ms example that fails on the deadline
  under a bare configuration and passes under the project's
- [x] 6.7 **`test_waiting_for_a_lock_held_by_another_process_is_announced_then_times_out`: a wall-clock upper bound**
  (1 of 65; 10.8 s against `< 5.0`, at 10 workers on 8 logical CPUs). Check the mechanism (announced once, then
  `LockTimeoutError` after the timeout), and keep at most a loose upper bound with one named allowance

  Done, and it found a product gap: a stall past both the announce time and the timeout gave up without announcing,
  in the lock wait and in the file replace and read waits ("never silent", platform spec). All three now announce
  before any timeout, pinned by fake-clock tests that failed before the fix on every platform. The lock test checks
  one announcement, not before `announce_after`, no later than the timeout, and an upper bound of the timeout plus
  `STALL_ALLOWANCE` (30 s)
- [ ] 6.8 **A round hung for 20 minutes, test unknown** (1 of 65). Run the campaign with 6.1's stall dump to name the
  test, then add its own task here
- [ ] 6.9 **Store: another process's events can miss the listener's median bound** (a wall-clock bound; #100, release
  PR #89). The same treatment #91 got: check the interval and the next look, and keep a loose median bound

- [x] 6.10 The campaign follows python-version-bounds (#104, merged first): its versions are
  `python_versions.supported()`, its environments `.venvs/<version>` as `scripts/on.py` uses, and the docs run other
  versions through `on.py`. Workers default to `auto` (three quarters of the usable CPUs, less the load; owner, 2026-10-15). Verified
  by the campaign's and the hunt's tests, including
  `test_workers_auto_is_three_quarters_of_the_usable_cpus_less_the_load_and_at_least_one`

## Workflow follow-up

- Run `/opsx:archive` on the branch before merging, so the PR lands the script, the runner change and the synced
  specs together.
- After the merge, comment on #100 with the PR and the archived change, and close it.
