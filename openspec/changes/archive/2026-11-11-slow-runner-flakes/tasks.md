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

- [x] 2.1 Find why the campaign test's stop took over 60 s on CI. The failing job's log shows the hunt stopped at
  once and printed its summary, and the *campaign* then didn't exit within 60 s. Under load (`--workers 2 --load 4`,
  16 rounds) it didn't reproduce, and the cause isn't known: say so on #358. Make the next failure show it. The test
  sends the campaign's group `SIGABRT` with `PYTHONFAULTHANDLER=1` before giving up, so every thread's stack is
  dumped (checked with a campaign made to hang after its hunt: the dump names the line). The campaign flushes its
  closing lines. Whether the PR closes #358 is the owner's call.
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
- [x] 2.4 Reproduce #350 and record the failing assertion on #350. Under load (`--workers 2 --load 4`, 30 rounds,
  load average 16–50) it didn't fail. #350 failed at about 224, so it was reproduced deterministically instead: a
  stuck test whose module sleeps 7 s while collected makes main's test fail every time with
  `assert 'Timeout (0:00:02)!' in ''`. The round's 8 s ran out before the stuck test ran. Set `--round-timeout` to
  `STALL + ROUND_START_ALLOWANCE` (2 + 20 s), with the reason in its docstring, and make the assertions print the
  record's status and output tail (D10). Verify it passes with the 7 s start and without it.

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
  (3 of 3 local runs, 0.296875 s each time), and the new pause passes. A second test checks that a `Pause` sent
  through `FakeEndpoint` calls `pause()`: with the stream back on `time.sleep`, it fails. Check the other lower-bound asserts each time a
  monotonic-deadline wait with that same clock, and leave them unchanged. Found with
  `grep -rnE "monotonic\(\) - \w+ >=" packages plugins scripts` and a search for `elapsed >=`.

## 5. Ollama: the preflight deadline and the close (#354, #301, #353)

- [x] 5.1 Reproduce #354 and record the failing assertion on #354. With the runner's start delayed 6 s, main's
  test fails every time with `assert 16.13 < (10.0 + 5.0)`, the timing check.
- [x] 5.2 Stamp `fake_ollama.Request` with its arrival time. In
  `test_both_preflight_requests_share_one_deadline`, measure from the first preflight request to the refusal, with
  `AFTER_DEADLINE` (6 s, its docstring saying why it must stay under 8 s) (D5). Verify the fixed test passes with the
  same 6 s slow start, and under `--workers 2 --load 4` (12 rounds). Then check that two separate deadlines fail it:
  with the runner giving the model request its own deadline, it fails with `refused 18.0s after preflight`. Reverted.
- [x] 5.3 Instrument the fake's `_hold` and `_stream` (D6), and loop
  `test_cancel_while_an_answer_streams_closes_it_and_nothing_follows_the_answer` under load on macOS. 540 rounds
  (Python 3.12 and 3.15, `--workers 2 --load 4`) passed, and every close was seen within 14 ms. The traces showed
  the test cancelling before the fake sent line 0, which led to the cause: the runner's `sent` record comes before
  its request (`conversation.py:311`). Shown by sleeping 0.5 s there: main's test then fails every time with #301's
  assertion. A first hypothesis, `select.select` dying on a descriptor past 1024, reproduced the same assertion
  with 1100 descriptors held. A probe of a full local run then refuted it as CI's cause: no worker went above
  descriptor 18. Record both on #301. The instrumentation is removed.
- [x] 5.4 Fix the cause: the test waits for a `received` transcript record and checks the fake has the chat request
  before it cancels (D6). No runner change, so no spec delta. Name `CLOSE_SEEN_WITHIN` at both close waits. Verify
  the fixed test passes with the 0.5 s window, and the runner suite passes. Also fix what the diagnosis found in the
  fakes: `selectors` instead of `select.select` in both, and the Ollama fake's `handle_error` stops hiding
  non-connection errors. Each fake gets a regression test with descriptors past 1024, which fails with main's
  `select.select`. The error handling gets two tests. A handler failing with something other than a reset makes
  `stop()` raise, naming it, and fails when `handle_error` swallows everything again. A client resetting its
  connection leaves `stop()` quiet, and fails when resets are kept too. Verify both plugins' suites pass (605).
- [x] 5.5 #353 is the same test, assertion and cause. Comment on #353 that it's a duplicate of #301, fixed by this
  change, for the PR to close.

## 6. Claude Code: the direction marker and the perform test (#335, #355)

- [x] 6.1 In `test_claude_runs_in_the_workspace_with_the_fixed_flags_and_the_direction_on_stdin`, use a direction
  holding a fresh `direction-<uuid4 hex>` marker, and check that no argument holds it (D11). Verify it passes, and
  that a local change appending the direction to argv fails it, then revert.
- [x] 6.2 Reproduce #355. Under load (`--workers 2 --load 4`, 20 rounds) it didn't fail. With the runner's start
  delayed 11 s, main's test fails every time with `assert 'could-not-start' == 'succeeded'`: the harness's 10 s start
  limit. #355's own assertion wasn't kept, so record on #355 that this is the mechanism shown, not certainly the
  one that fired.
- [x] 6.3 Add `REAL_RUNNER_LIMITS` to `packages/troupe/tests/runtesting.py`, with a docstring saying it bounds a
  hang, not speed, and use it in `test_perform_claude_code.py`, that file's only test (D13). Verify it passes with
  the 11 s slow start and without it.

## 7. Git: compare the CRLF file's content every time (#351)

- [x] 7.1 In `test_a_file_committed_in_a_form_git_would_normalise_neither_stops_the_fill_nor_is_in_the_diff`, set
  `crlf.txt`'s mtime 2 s earlier after the checkout, with a comment on why (D12). Verified by forcing the racy case
  rather than with a 200-round hunt: with `.git/index` made newer than the file after the checkout (the later tick),
  main's test fails every time with #351's `assert () == ('crlf.txt',)`, and the fixed test passes. Then the force
  was removed. The test still fails when the capture diffs against HEAD instead of the fill's baseline (a local patch,
  then reverted). Cloning the file instead of checking it out doesn't fail it, rightly: the capture diffs against the
  fill's own baseline.

## 8. Integration

- [x] 8.1 Run the twelve tests together under `flake_hunt.py --workers 2 --load 4`, 20 rounds. Every round
  reported failed, but from the repo's scope-reach guard, which flags every test at teardown when tests from several
  scopes share one pytest process (`check.py` never runs them that way). Under it, every test call passed in all 20
  rounds, except the new `test_a_killed_hunts_load_ends_with_it`. That one failed in the slowest round (137 s) on
  both workers: the inner hunt's round hadn't started its test within 60 s, and the test couldn't say why. It now
  fails at once with the hunt's output when the round ends early (checked with a round that crashes at
  collection), and with the output on timeout. The `scripts`-scope tests were then hunted on their own, so the
  guard has no cross-scope reads to flag: 10 rounds, load averages up to 82, none failed, nothing left running.
- [x] 8.2 Run `uv run scripts/check.py` locally, then CI on all twelve legs once the PR is ready. Verify every job
  passes, and cite the Windows 3.12 leg's run for #352. The local check passed on every commit and after the rebase
  onto `71c76ced`. CI on the last code commit, `2f2a5a71`, run 42919100829: all twelve legs passed. Windows 3.12
  is job 130189193958.
- [x] 8.3 `openspec validate slow-runner-flakes --strict` passes.

## Workflow follow-up

- Draft PR with `Closes` for each of #357, #358, #359, #364, #350, #335, #351, #301, #352, #354, #355, and #353 if
  5.5 found it a duplicate. Act on Claude's review, then mark it ready.
- `/opsx:archive` on the branch before the owner merges through the merge queue.
- After the merge: comment on each issue with the PR and the archived change, and check that each is closed and its
  card says Done.
- The flake-hunt spec's Purpose is unchanged, so infrastructure's `oob/troupe-spec-purposes.json` needs no update.
