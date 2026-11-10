# Proposal: tests that tolerate a slow runner

## Why

Twelve tests fail now and then for timing alone, when a CI runner or a local machine is slow or loaded, not because the
code they check is wrong. Each failure drops a pull request from the merge queue, and rounds 3 and 4 (#328, #325) are
paused until they stop. They're tracked as troupe-run/troupe#357, #358, #359, #364, #350, #335, #351 and #301, and,
added by the owner so every known flaky test is cleared in one pass, #352, #353, #354 and #355. They share one shape:
a test bounds what it checks by a fixed sleep, a margin that load uses up, an exact list of events, or a string that a
random path can hold. So they're fixed together, with one rule.

## What Changes

The rule for every test this change touches: **a test waits for the thing it checks** (an event, a request, a process,
a line of output) **with a bounded wait whose limit is a named setting** saying what it bounds, rather than a fixed
sleep, a wall-clock margin measured from before the work starts, or an exact list of events. **Each test still fails
when the thing it checks doesn't happen**, at that limit, with a message naming what it waited for.

- **Exact event lists allow timing notices** (#357). The worktree tests in `test_run_workspaces.py`, and the CLI
  perform test in `test_cli_runs.py` that also makes a worktree, check the topics the run must record in order. Any
  `Run.Noticed` between them is allowed, and nothing else is. A slow worktree step on a loaded runner raises
  `workspace.waiting`, which #336 now keeps in the run's history. Version checks become "no gap" rather than `[1, 2]`.
- **A fixed sleep becomes a wait for the request** (#359). The OpenAI fake endpoint gets a bounded wait for its *n*th
  request. The two stop tests wait for the first request instead of sleeping 0.3 s.
- **The OpenAI fake's pause lasts its length on the clock the test measures with** (#352). It waits until a
  `time.monotonic()` deadline rather than sleeping, as the Ollama fake already does. On Windows with Python 3.12 that
  clock ticks every 15.6 ms, so a 0.3 s sleep read as 0.297 s. A test with a clock that coarse shows it on every OS.
  The other lower-bound timing asserts already measure a monotonic-deadline wait with the same clock, so they stay
  exact (design D4).
- **The Ollama preflight deadline is measured from the first preflight request** (#354), which the fake timestamps,
  not from before the runner starts. One shared deadline (about 10 s) is still told apart from two (about 18 s).
- **The Ollama cancel-while-streaming close is diagnosed, then fixed at its cause** (#301, #353). Both issues are the
  same test and assertion. The fake is instrumented and the test looped under load to show why the close isn't seen
  within 5 s. The fix goes in the fake if it misses the close, or in the runner if the runner leaves the connection
  open. The wait becomes a named limit. #353 is closed as a duplicate of #301 if the cause is the same.
- **The flake-hunt and flake-campaign tests bound the stop by the tool's own stop limit** (#358, #364). They don't use
  a shorter fixed one. The campaign test waits for `flake_campaign.STOP_WAIT_SECONDS` plus a named margin, where it
  used to wait exactly the same 60 s. The hunt interrupt test waits for `flake_hunt.STOP_TIMEOUT_SECONDS` plus a
  margin. Both still catch a hunt that doesn't stop its rounds: they check the output says the hunt didn't give up
  on its workers, and that the hunt wrote its summary.
- **A test that gives up on a hunt or campaign stops its whole process tree** (#364): rounds, load processes and the
  campaign's hunt. A shared helper in `scripts/tests` takes a snapshot of the tree, then kills it: `taskkill /T` on
  Windows, and a walk of descendants and their process groups on POSIX.
- **A hunt's load processes end when the hunt does, however it ends** (#364). On POSIX the load program exits once
  its parent is gone, as a Windows job already makes it. Today a killed hunt on macOS or Linux leaves
  `while True: pass` spinning at 100% CPU.
- **The stall-limit hunt test's round timeout covers starting a round under load** (#350). The failure is first
  reproduced under load and its assertion recorded on the issue. The timeout becomes the stall limit plus a named
  start allowance, with the reason in the test.
- **The Claude Code argv test checks for a marker only the direction holds** (#335): a fresh unique token in the
  direction, compared against each argument, so `hi` in a random temp path can't fail it.
- **The git CRLF test makes git compare the file's content** (#351). It changes the checked-out file's mtime so its
  stat no longer matches the index, rather than depending on whether the index was written in a later timestamp
  tick ("racily clean").
- **The Claude Code perform test is reproduced under load, then bounded by what it waits on** (#355). Its likely
  cause is the harness's 10 s start limit. That isn't confirmed until the run shows it.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `flake-hunt`: "The hunt can load the machine" gains a scenario. The load ends when the hunt is killed, on every
  platform, not only when it stops itself. The requirement already says "however it ends", which a killed hunt on
  POSIX breaks today.

## Impact

- **Tests only, apart from two tools.** `scripts/flake_hunt.py` changes its load program on POSIX. The Ollama runner
  changes only if #301's diagnosis shows the runner leaves the connection open; if it does, the change adds an
  `ollama-runner` spec delta for it.
- **Test helpers:** `plugins/runner-openai/tests/fake_endpoint.py` gains a request wait.
  `plugins/runner-ollama/tests/fake_ollama.py` gains request timestamps, and possibly a fix for missing a close.
  `scripts/tests` gains a process-tree stop. `packages/troupe/tests` gains a topics-allowing-notices helper.
- **Suite time:** the stall-limit hunt test runs longer, by its start allowance. The other changes remove fixed
  sleeps or keep the same bounds.
- **Load-heavy local runs:** reproducing #350, #354, #355 and #301 under load needs `scripts/flake_hunt.py --load`
  loops. Each one is announced to the owner before it starts.
- **Issues:** the PR closes all twelve. #353 is closed as a duplicate of #301 if the diagnosis shows one cause.
