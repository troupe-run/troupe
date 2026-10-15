# Tasks

The hunt's tests run real pytest processes on small test files they write into `tmp_path`, not hand-written reports,
so each fixture is the shape pytest actually produces. None of these tasks runs a load loop without asking first.

## 1. The hunt runs rounds and reports them (spec: flake-hunt; design D1, D2, D3, D5, D7, D10)

- [ ] 1.1 Add `scripts/flake_hunt.py` with its options (`--workers`, `--rounds`, `--load`, `--round-timeout`,
  `--out`, `-k`, test paths) and their validation: a value that isn't a whole number, is below its minimum, or (for
  `--load`) exceeds the CPUs the hunt may use (`os.process_cpu_count()`, else the affinity, else `os.cpu_count()`)
  is refused before anything runs, naming the option, the value and what's allowed. Verify with tests for each
  refusal, including 0 rounds and too much load, that nothing ran and the exit is non-zero
- [ ] 1.2 Run the rounds: a thread per worker, each running its rounds back to back as
  `sys.executable -m pytest -p no:cacheprovider --basetemp=<short dir> --junitxml=<file>` from the repository root,
  with the round's environment the hunt's own plus `HYPOTHESIS_STORAGE_DIRECTORY` (a new directory per round), and
  the basetemp under `<tmp>/fh-<6 characters>/w<n>r<n>` with its parent created first. Print each round as it ends.
  Verify with a test that 2 workers × 2 rounds over a written file of one passing test runs 4 rounds, that a `-k` and
  a path select exactly what pytest selects, that a `tmp_path` test passes in every round (the scratch run's basetemp
  bug), and that the round's environment has no variable the hunt's lacks other than the hypothesis directory
- [ ] 1.3 Read each round's JUnit report into failures (test id, message, traceback), and report a round with no
  report as a failed round with the end of its output, decoded as UTF-8 with `errors="backslashreplace"`. Keep each
  round's output as bytes in its log, unchanged. Verify with tests over real pytest runs of a failing test, an
  erroring fixture, a file that crashes pytest (`os._exit(3)` at import), and a crash whose output holds bytes that
  aren't UTF-8
- [ ] 1.4 Write `results.jsonl` (one record per round, appended as each ends), `summary.json` (both UTF-8) and each
  round's output and report to `--out`, defaulting to `<tmp>/flake-hunt/<UTC timestamp>`. Print the path at the
  start and the end, then the summary: platform, the interpreter's path and version, workers, rounds, load (from
  `os.getloadavg()`, or "not available" where it doesn't exist), and per failing test its runs, failures, and the
  first failure's message and traceback. Exit 0 only when no round failed. Verify with tests: a test that fails only
  in alternate rounds (it counts its runs in a file) is summarised with its run and failure counts, and a clean hunt
  says none failed and exits 0
- [ ] 1.5 Reconfigure the hunt's standard output and error with `errors="backslashreplace"`, so the summary prints
  on a console whose encoding can't show a failure's text. Verify with a test that runs the hunt with
  `PYTHONIOENCODING=cp1252` over a written test that fails with `assert "ünïcødé ✓" == ""`: the summary prints, the
  check mark is escaped in it, and `summary.json` holds the text unchanged
- [ ] 1.6 Verify each round's hypothesis database is private: with a written hypothesis test that always fails,
  every round reports it, the falsifying example is in the summary's traceback, and the repository's `.hypothesis/`
  is unchanged (compare its file list before and after)

## 2. Load, timeouts and stopping (spec: flake-hunt; design D4, D5, D6, D10)

- [ ] 2.1 Start each round and load process so its whole tree can be stopped: on POSIX a new session, stopped with
  `SIGKILL` to the group; on Windows a kill-on-close job, the process started with `CREATE_SUSPENDED |
  CREATE_NEW_PROCESS_GROUP`, assigned to the job and then resumed (`NtResumeProcess`), stopped by terminating the
  job. If the job can't be created or assigned, refuse to start, naming the Windows error. Verify with a test whose
  written test starts a child that starts a sleeping grandchild, records the grandchild's pid, and exits: after the
  round is stopped, the grandchild is gone (on Windows, too, where its parent has already exited)
- [ ] 2.2 Kill a round past `--round-timeout` and report it as hung, with its output so far. Verify with a written test
  that sleeps past a 5 s timeout: the round is reported hung within a few seconds of the timeout, the next round
  still runs, and nothing the hung round started is left running
- [ ] 2.3 Start `--load N` busy processes before the first round and stop them in a `finally`. Verify with a test that
  the N processes run during the rounds and are gone when the hunt returns, both after a normal end and after a stop
- [ ] 2.4 Stop on Ctrl-C, and on Windows on Ctrl-Break: set the stop flag, kill the running rounds and the load, join
  the workers in waits of at most 0.5 s (bounded overall, and announced if slow), and print the summary of the
  finished rounds. Verify with a test that interrupts a hunt part-way (`SIGINT` on POSIX; on Windows,
  `CTRL_BREAK_EVENT` to a hunt started in its own process group) and checks that it stops within 5 s, the finished
  rounds are summarised and no process the hunt started is left
- [ ] 2.5 Windows only: verify that killing the hunt's own process (`TerminateProcess`, so no `finally` runs) while a
  round runs ends the round's tree, because the job's last handle closes. Mark the test to skip elsewhere, with the
  reason
- [ ] 2.6 Run `uv run scripts/check.py`, push the branch and open a draft PR (`Closes #100`), so the hunt's tests run
  on the Windows CI jobs. Verify every job passes on Linux, macOS and Windows, both Pythons, and record the run id

## 3. Running it on each platform (spec: flake-hunt "The hunt runs on every platform"; design D8, D10)

- [ ] 3.1 Add `scripts/flake_hunt.Dockerfile` (uv on a current Debian, git, a non-root user, the repository copied in
  from `git archive HEAD`, `uv sync --locked` for a `PY` build argument). Verify by building it for 3.12 and 3.13 and
  checking, inside the container, that the user isn't root and that `git rev-parse --local-env-vars` lists nothing
  the git adapter's list lacks
- [ ] 3.2 Write `docs/flake-hunt.md`: what the hunt is for and what it reports; how to read the summary; what to put
  on #100 for a finding; the narrowed selection used on #100; and per platform:
  - macOS and Linux: the commands, each Python version in its own environment (`UV_PROJECT_ENVIRONMENT=.venv-3.13
    uv run --python 3.13 ...`);
  - Linux in Docker: building the image per Python, and `docker run --init` as the image's user, with why;
  - Windows: PowerShell commands (`$env:UV_PROJECT_ENVIRONMENT = ".venv-3.13"`), Git for Windows on the PATH, Windows
    Terminal rather than a console window with QuickEdit (a click pauses its output), Ctrl-C or Ctrl-Break to stop,
    and recording whether Defender real-time protection is on.

  Link it from the README's docs list. Verify each macOS and Docker command runs as written with 1 worker and 1
  round, and that running the 3.13 command leaves `.venv`'s Python at 3.12
- [ ] 3.3 Record in a comment on #100 that the hunt is ready on the branch, with the Windows commands from the docs and
  the draft PR's green Windows run, so the owner can run it on the Windows PC

## 4. The scripted runner reads messages only where a step waits (spec: scripted-runner; design D9)

- [ ] 4.1 Reproduce the race without a delay: a scripted-runner test that queues `initialize`, `run/start` (script:
  `init`, ok `result`, `exit 3`) and `shutdown` on the runner's input before it plays anything, then checks it exits
  3 with `init` and `result` sent and `shutdown` unanswered. Run it on the current runner and verify it fails (exit 0)
- [ ] 4.2 Stop `serve()` and a replay without delays from draining between steps, so messages are answered at a
  `wait`, during replay delays, at a `hang` and after the last step. Verify 4.1 passes, and add a test that a
  `run/cancel` queued during instant steps followed by a `hang` is answered at the `hang`, after every instant step
  played
- [ ] 4.3 Verify the run host's tests that depended on the race now hold under the delay that reproduced it on #100:
  with a temporary `time.sleep(0.2)` in the runner's step loop, `test_an_ok_result_followed_by_an_unclean_exit_fails_as_uncertain`,
  `test_a_late_event_after_the_result_crashes_the_run_whether_the_runner_answers_shutdown_first` and
  `test_a_cancelled_run_keeps_every_transcript_record_received` all pass. Revert the sleep and show it reverted
  (`git diff --stat`)
- [ ] 4.4 Run every scripted-runner and run-host test, and `openspec validate flake-hunt --strict`. Verify they pass

## 5. The hunt, on every platform

- [ ] 5.1 Agree on #100 the number of rounds and the load for "done". Then run that hunt on macOS and in Docker
  (3.12 and 3.13), with and without load, and record each summary on #100. Each failure found becomes a task appended
  here and a line on #100, fixed by its kind
- [ ] 5.2 The owner runs the same hunt on the Windows PC (3.12 and 3.13) and records the summaries on #100. Each
  failure found becomes a task here, as in 5.1
- [ ] 5.3 Run `uv run scripts/check.py`, mark the PR ready for review, and verify all CI jobs pass on Linux, macOS and
  Windows

## Workflow follow-up

- Run `/opsx:archive` on the branch before merging, so the PR lands the script, the runner change and the synced
  specs together.
- After the merge, comment on #100 with the PR and the archived change, and close it.
