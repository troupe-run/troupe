# Tasks

Each load-heavy local run below (`flake_hunt.py --load`, or a loop of a test under load) is announced to the owner
before it starts and run one at a time. Every reproduction records its assertion on its issue.

## 1. Hunt load ends with the hunt, and a test stops a whole tree (#364)

- [x] 1.1 Write the spec scenario's test first: in `scripts/tests/test_flake_hunt.py`, start a hunt with `--load 2`
  over a hanging root, wait for `load.json`, kill only the hunt's own process (`SIGKILL`; `TerminateProcess` on
  Windows), and check both load pids are gone within a named `LOAD_GONE_WITHIN`. Verify it **fails on main on macOS**
  (the load keeps spinning). Clean up the leaked load by hand when it does.
- [x] 1.2 In `scripts/flake_hunt.py`, make `LOAD_PROGRAM` exit when its parent changes, checked at least every named
  `LOAD_CHECK_SECONDS` between pure-Python bursts (D8). Verify that 1.1 passes, and that
  `test_the_load_runs_during_the_rounds_and_is_gone_when_the_hunt_returns` and the interrupt test still pass.
- [x] 1.3 Add `stop_tree(process)` to `scripts/tests/conftest.py`: take a snapshot of the descendants, then kill each
  process group and pid on POSIX (`ps -A -o pid=,ppid=,pgid=`), or run `taskkill /F /T` on Windows (D7). Verify with a
  test in `scripts/tests` that starts a child, which starts a grandchild in a new session and then a spinning load
  process, calls `stop_tree` on the child, and finds none of the three running within a named limit.
- [x] 1.4 Use `stop_tree` wherever a test in `scripts/tests` gives up on a hunt or campaign: `run_hunt` becomes a
  `Popen` with a bounded wait that stops the tree on timeout and fails with the output so far, and every
  `finally: process.kill()` / `hunt.kill()` becomes `stop_tree`. Verify with `grep -n "\.kill()"` in
  `scripts/tests/test_flake_hunt.py` and `scripts/tests/workspace/test_flake_campaign.py`, which should find none left
  for a hunt or campaign process, and with `uv run pytest scripts/tests -k "flake"`, which should pass.
- [x] 1.5 Update `contributing/flake-hunt.md`: a killed hunt's load ends with it on every platform. Add a short
  section, "Tests that tolerate a slow runner", stating the rule this change applies (proposal "What Changes"),
  including stopping a whole tree on giving up. Verify the docs tests pass.

## 2. Hunt and campaign stop bounds, and the stall test (#358, #364, #350)

- [ ] 2.1 Run `test_an_interrupted_campaign_stops_its_hunt_runs_no_more_and_reports` under load (announced), keeping
  the campaign's and the hunt's output, to see why its stop can take over 60 s. Record the finding on #358. If the
  hunt's stop is slow in a way it shouldn't be, fix that in `flake_hunt.py` or `flake_campaign.py`, with a test that
  fails before the fix.
- [x] 2.2 In the campaign test, wait `flake_campaign.STOP_WAIT_SECONDS + STOP_MARGIN` after the interrupt, and name
  the 300 s start wait (D9). Verify it passes, and that it still fails when the hunt ignores the interrupt: patch the
  hunt's interrupt handler locally to do nothing, check `summary is not None` fails, then revert.
- [x] 2.3 In the hunt interrupt test, wait `flake_hunt.STOP_TIMEOUT_SECONDS + STOP_MARGIN` for the exit and the rest
  of the output. Replace `stopped_in < 5` with a check that the output doesn't hold `workers still running after`.
  Name the 60 s start waits `HUNT_START_WITHIN` (D9). Verify it passes, and that it fails when the hunt doesn't stop
  its rounds. Done with every `running.stop_all()` and the round's own stop check patched out locally: the test fails
  on its last assert, because the round's grandchild is still running. Then reverted. Patching out only the interrupt
  path's `stop_all()`, as first planned, doesn't fail it: the interrupted `join` leaves the worker looking finished, so
  the hunt doesn't wait, and `finally`'s `stop_all()` stops the round. The test's comment says what each check covers.
- [ ] 2.4 Reproduce #350 with `flake_hunt.py --load` on
  `test_a_test_stuck_past_the_stall_limit_has_its_stack_in_the_hung_rounds_output` (announced), and record the
  failing assertion on #350. If it's the round's start that runs out the timeout, set `--round-timeout` to
  `STALL + ROUND_START_ALLOWANCE`, with the reason in its docstring, and make the assertions print the record's
  status and output tail (D10). Otherwise revisit D10 from what the run showed. Verify the same load run then passes
  every round.

## 3. Run topics allow timing notices (#357)

- [x] 3.1 Add `topics_besides_notices` and `assert_no_gap` to `packages/troupe/tests/test_run_workspaces.py` (D2).
  Use them at lines 258, 289 and 311. Verify with a test there that wraps the VCS, as
  `test_a_slow_worktree_operation_is_announced_naming_it` does, so a worktree step raises `workspace.waiting` in the
  #357 test's scenario. It passes, and the recorded history holds a `Run.Noticed`, so the test can't pass
  without one being there.
- [x] 3.2 Check that the helpers still fail on a non-notice topic. Done with the shared-state test, whose run
  records `Run.WorktreeMade`, compared locally against `["Run.Started", "Run.Ended"]`: it fails. Also checked that
  main's exact assertion fails the slow variant from 3.1, which reproduces #357. Both local changes were reverted.
- [x] 3.3 Check whether `test_cli_runs.py:256`'s run can record a notice: its actor's workspace, and the CLI's default
  silence limit against a slow start. If it can, give it the same allowance. If it can't, say why in a comment on
  #357. Verify `uv run pytest packages/troupe/tests/test_cli_runs.py packages/troupe/tests/test_run_workspaces.py`
  passes.

## 4. OpenAI fake: wait for the request; clock-tick slack (#359, #352)

- [x] 4.1 Add `FakeEndpoint.wait_for_requests(count, timeout)` to `plugins/runner-openai/tests/fake_endpoint.py`,
  signalled as each request is recorded (D3). Test it in `test_openai_fake_endpoint.py`: it returns true once the
  *n*th request arrives, and false at its timeout when none does.
- [x] 4.2 In the two stop tests in `test_openai_runner.py`, replace `time.sleep(0.3)` with
  `assert fake.wait_for_requests(1, REQUEST_WITHIN)`, with a message, keeping `len(fake.requests) == 1`. Verify they
  pass, and that a local run with the first request delayed past `REQUEST_WITHIN` fails with the message.
- [x] 4.3 Make the OpenAI fake's `Pause` wait until a `time.monotonic()` deadline (D4). Verify with a test that
  replaces `time.monotonic` with a 15.625 ms clock and times the fake's pause alone: main's `time.sleep` pause fails it
  (3 of 3 local runs, 0.296875 s each time), and the new pause passes. Check the other lower-bound asserts each time a
  monotonic-deadline wait with that same clock, and leave them unchanged. Found with
  `grep -rnE "monotonic\(\) - \w+ >=" packages plugins scripts` and a search for `elapsed >=`.

## 5. Ollama: the preflight deadline and the close (#354, #301, #353)

- [ ] 5.1 Reproduce #354 under load (announced) and record the failing assertion on #354.
- [ ] 5.2 Stamp `fake_ollama.Request` with its arrival time. In
  `test_both_preflight_requests_share_one_deadline`, measure from the first preflight request to the refusal, with
  `AFTER_DEADLINE` (6 s, its docstring saying why it must stay under 8 s) (D5). Verify the same load run passes. Then
  check locally that two separate deadlines fail it: make the runner restart the deadline for the second request,
  check the test fails, then revert.
- [ ] 5.3 Instrument the fake's `_hold` and `_stream` (D6, step 1). Loop
  `test_cancel_while_an_answer_streams_closes_it_and_nothing_follows_the_answer` under load on macOS (announced)
  until it fails, and record on #301 which of D6's cases happened, with the log. Remove the instrumentation.
- [ ] 5.4 Fix the cause 5.3 showed, in the fake or in the runner. A runner fix comes with an `ollama-runner` spec
  delta scenario and a test that fails before it. Name `CLOSE_SEEN_WITHIN` and use it at both
  `closed_by_client.wait(5)` sites (lines 381 and 396). Verify the 5.3 loop passes every round.
- [ ] 5.5 Decide #353 from 5.3. If it's the same cause, comment on #353 that it's a duplicate of #301 fixed by this
  change, for the PR to close. If it isn't, it stays in scope with its own fix and verification.

## 6. Claude Code: the direction marker and the perform test (#335, #355)

- [ ] 6.1 In `test_claude_runs_in_the_workspace_with_the_fixed_flags_and_the_direction_on_stdin`, use a direction
  holding a fresh `direction-<uuid4 hex>` marker, and check that no argument holds it (D11). Verify it passes, and
  that a local change appending the direction to argv fails it, then revert.
- [ ] 6.2 Reproduce #355 under load (announced) and record the failing assertion on #355.
- [ ] 6.3 If 6.2 shows a run limit firing, add `REAL_RUNNER_LIMITS` to `packages/troupe/tests/runtesting.py`, with a
  docstring saying it bounds a hang, not speed. Use it in the perform tests that start a real runner process and
  aren't testing limits (D13). Otherwise fix the cause 6.2 showed. Verify the same load run passes.

## 7. Git: compare the CRLF file's content every time (#351)

- [ ] 7.1 In `test_a_file_committed_in_a_form_git_would_normalise_neither_stops_the_fill_nor_is_in_the_diff`, set
  `crlf.txt`'s mtime 2 s earlier after the checkout, with a comment on why (D12). Verify the precondition holds over
  a 200-round local hunt of the test. Also verify the test still fails when the fill copies the file in its
  normalised form: patch it locally, check, then revert.

## 8. Integration

- [ ] 8.1 Run the twelve tests together under `flake_hunt.py --load` (announced), at least 20 rounds, and record the
  summary in the PR. Verify no round fails.
- [ ] 8.2 Run `uv run scripts/check.py` locally, then CI on all twelve legs once the PR is ready. Verify every job
  passes, and cite the Windows 3.12 leg's run for #352.
- [ ] 8.3 `openspec validate slow-runner-flakes --strict` passes.

## Workflow follow-up

- Draft PR with `Closes` for each of #357, #358, #359, #364, #350, #335, #351, #301, #352, #354, #355, and #353 if
  5.5 found it a duplicate. Act on Claude's review, then mark it ready.
- `/opsx:archive` on the branch before the owner merges through the merge queue.
- After the merge: comment on each issue with the PR and the archived change, and check that each is closed and its
  card says Done.
- The flake-hunt spec's Purpose is unchanged, so infrastructure's `oob/troupe-spec-purposes.json` needs no update.
