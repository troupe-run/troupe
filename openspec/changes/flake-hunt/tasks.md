# Tasks

The hunt's tests run real pytest processes on small test files they write into `tmp_path`, not hand-written reports,
so each fixture is the shape pytest actually produces. None of these tasks runs a load loop without asking first.

## 1. The hunt runs rounds and reports them (spec: flake-hunt; design D1, D2, D3, D5, D7)

- [ ] 1.1 Add `scripts/flake_hunt.py` with its options (`--workers`, `--rounds`, `--load`, `--round-timeout`,
  `--out`, `-k`, test paths) and their validation: a value that isn't a whole number, is below its minimum, or (for
  `--load`) exceeds `os.cpu_count()` is refused before anything runs, naming the option, the value and what's
  allowed. Verify with tests for each refusal, including 0 rounds and too much load, that nothing ran and the exit is
  non-zero
- [ ] 1.2 Run the rounds: a thread per worker, each running its rounds back to back as
  `sys.executable -m pytest -p no:cacheprovider --basetemp=<short dir> --junitxml=<file>` from the repository root,
  with the basetemp's parent created first and `HYPOTHESIS_STORAGE_DIRECTORY` set to a new directory per round. Print
  each round as it ends. Verify with a test that 2 workers × 2 rounds over a written file of one passing test runs 4
  rounds, that a `-k` and a path select exactly what pytest selects, and that a `tmp_path` test passes in every round
  (the scratch run's basetemp bug)
- [ ] 1.3 Read each round's JUnit report into failures (test id, message, traceback), and report a round with no
  report as a failed round with the end of its output. Verify with tests over real pytest runs of a failing test, an
  erroring fixture, and a file that crashes pytest (for example, `os._exit(3)` at import)
- [ ] 1.4 Write `results.jsonl` (one record per round, appended as each ends), `summary.json` and each round's output
  and report to `--out`, defaulting to `<tmp>/flake-hunt/<UTC timestamp>`. Print the path at the start and the end,
  then the summary: platform, Python, workers, rounds, load (from `os.getloadavg()`, or "not available" where it
  doesn't exist), and per failing test its runs, failures, and the first failure's message and traceback. Exit 0 only
  when no round failed. Verify with tests: a test that fails only in alternate rounds (it counts its runs in a file)
  is summarised with its run and failure counts, and a clean hunt says none failed and exits 0
- [ ] 1.5 Verify each round's hypothesis database is private: with a written hypothesis test that always fails,
  every round reports it, the falsifying example is in the summary's traceback, and the repository's `.hypothesis/`
  is unchanged (compare its file list before and after)

## 2. Load, timeouts and stopping (spec: flake-hunt; design D4, D5, D6)

- [ ] 2.1 Start each round and load process in its own process group (a new session on POSIX,
  `CREATE_NEW_PROCESS_GROUP` on Windows), and stop one by killing the group (`SIGKILL`) or with `taskkill /T /F /PID`
  resolved from `SYSTEMROOT`. If `taskkill` isn't found, refuse to start and name it. Verify with a test whose written
  test file starts a child that sleeps, and records the child's pid: after the round is stopped, the child is gone
- [ ] 2.2 Kill a round past `--round-timeout` and report it as hung, with its output so far. Verify with a written test
  that sleeps past a 5 s timeout: the round is reported hung within a few seconds of the timeout, and nothing it
  started is left running
- [ ] 2.3 Start `--load N` busy processes before the first round and stop them in a `finally`. Verify with a test that
  the N processes run during the rounds and are gone when the hunt returns, both after a normal end and after a stop
- [ ] 2.4 Stop on Ctrl-C: set the stop flag, kill the running rounds and the load, join the workers (bounded, and
  announced if slow), and print the summary of the finished rounds. Verify with a test that interrupts a hunt part-way
  (`SIGINT` on POSIX; `CTRL_BREAK_EVENT` to a hunt started in its own group on Windows) and checks that the finished
  rounds are summarised and no process the hunt started is left

## 3. Running it on each platform (spec: flake-hunt "The hunt runs on every platform"; design D8)

- [ ] 3.1 Add `scripts/flake_hunt.Dockerfile` (uv on a current Debian, git, a non-root user, the repository copied in
  from `git archive HEAD`, `uv sync --locked` for a `PY` build argument). Verify by building it for 3.12 and 3.13 and
  checking, inside the container, that the user isn't root and that `git rev-parse --local-env-vars` lists nothing
  the git adapter's list lacks
- [ ] 3.2 Write `docs/flake-hunt.md`: what the hunt is for and what it reports; the commands for macOS, Linux in
  Docker (`docker run --init`, and why) and Windows (PowerShell, Python 3.12 and 3.13 through `uv run --python`); the
  narrowed selection used on #100; how to read the summary; and what to put on #100 for a finding. Link it from the
  README's docs list. Verify each documented command runs as written on macOS and in Docker, with 1 worker and 1 round
- [ ] 3.3 Record in a comment on #100 that the hunt is ready on the branch, with the Windows commands, so the owner
  can run it on the Windows PC

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
- [ ] 5.3 Run `uv run scripts/check.py`. Open the PR (`Closes #100`) and verify all CI jobs pass on Linux, macOS and
  Windows

## Workflow follow-up

- Run `/opsx:archive` on the branch before merging, so the PR lands the script, the runner change and the synced
  specs together.
- After the merge, comment on #100 with the PR and the archived change, and close it.
