# Design: tests that tolerate a slow runner

## Context

See proposal.md for why. What reading the twelve tests showed:

| Issue | Test | What bounds it today | Cause |
|---|---|---|---|
| #357 | `test_run_workspaces.py::test_a_worktree_made_that_cant_be_recorded_…` | topics `== ["Run.Started", "Run.Ended"]`, versions `== [1, 2]` | Confirmed by reading: `WORKSPACE_ANNOUNCE_AFTER_SECONDS` is 2.0, so a worktree step over 2 s raises `workspace.waiting`, which #336 records as `Run.Noticed`. Lines 258 and 311 of the same file have the same shape. |
| #358 | `test_flake_campaign.py::test_an_interrupted_campaign_…` | `process.wait(60)` after the interrupt | Partly confirmed. The 60 s is the wait *after* the interrupt, not the setup, which is allowed 300 s. It equals the campaign's own `STOP_WAIT_SECONDS` (60.0), so whenever the hunt took longer than 60 s to stop, the test gave up at the moment the campaign itself would have. Why the hunt took that long on that runner isn't known. |
| #364 | `test_flake_hunt.py::test_an_interrupt_stops_…` | `hunt.wait(10)` and `stopped_in < 5` after the interrupt | Confirmed: on giving up, `finally: hunt.kill()` kills only the hunt. Load runs as `Tree`s in their own sessions on POSIX, so a killed hunt leaves `while True: pass` running. The hunt's own stop bound is `STOP_TIMEOUT_SECONDS` (30.0). |
| #350 | `test_flake_hunt.py::test_a_test_stuck_past_the_stall_limit_…` | `--stall 2 --round-timeout 8` | Not reproduced. The likely cause is the child pytest's start eating the 8 s. |
| #359 | `test_openai_runner.py`, the two stop tests | `time.sleep(0.3)` then `len(fake.requests) == 1` | Confirmed by reading: a fixed sleep. |
| #352 | `test_openai_fake_endpoint.py::test_a_pause_delays_…` | `monotonic() - started >= 0.3` | Confirmed: the fake's `Pause` is a `time.sleep`, measured with `time.monotonic()`, which ticks every 15.625 ms on Windows with Python 3.12. A 0.3 s sleep reads as 0.296875 s (D4). |
| #354 | `test_ollama_runner.py::test_both_preflight_requests_share_one_deadline` | `took < PREFLIGHT_TIMEOUT_SECONDS + MARGIN`, timed from before `session.start` | Likely: the 5 s margin covers starting the runner too. |
| #301, #353 | `test_ollama_runner.py::test_cancel_while_an_answer_streams_…` | `fake.closed_by_client.wait(5)` | Confirmed (D6): the test cancelled on the runner's `sent` record of its request, which comes before the request is made. A cancel landing in between leaves no connection to close. |
| #335 | `test_claude_code_runner.py::test_claude_runs_in_the_workspace_…` | `not any("hi" in arg …)` | Confirmed by reading: the `mkdtemp` suffix and temp roots can hold `hi`. |
| #351 | `test_git_worktrees.py::test_a_file_committed_in_a_form_git_would_normalise_…` | precondition `differing_from_head() == ("crlf.txt",)` | Likely: racy git. Whether git re-hashes the file depends on the index's timestamp tick. |
| #355 | `test_perform_claude_code.py::test_a_claude_code_actor_succeeds_…` | the harness's `LIMITS`: `start_timeout=10.0`, `run_timeout=20.0` | Not reproduced. A start or run limit firing under load is the likely cause. |

Constraints that shape this: every limit is a named setting with its default in one place (`openspec/config.yaml`).
There's no per-test timeout, so a test that can block must bound itself. Plugins stay self-contained, so a plugin's
tests can't import helpers from `packages/troupe/tests`.

## Goals / Non-Goals

**Goals:**

- Each of the twelve tests passes on a slow or loaded runner and still fails, at a named limit, when the thing it
  checks doesn't happen.
- The three causes not yet shown (#301/#353, #350, #355) are reproduced under load before they're fixed, and the
  failing assertion goes on the issue. #354 is reproduced too, as its done-when asks.
- No test that gives up on a hunt or campaign leaves a process behind.

**Non-Goals:**

- A suite-wide time scale factor (an environment variable that multiplies every limit). Each limit is sized for what
  it bounds instead. A scale factor would hide a limit that's wrong in kind, as #358's was.
- Sweeping every `time.sleep` in the suite. This change fixes the twelve tests, plus the siblings that share their
  exact shape in the same files: the other exact topic lists, the other lower-bound clock asserts, and the Ollama
  end-of-input close wait. Others are left for flake hunts to find.
- A round's tree outliving a *killed* hunt on POSIX. The spec promises that only on Windows. The test-side tree stop
  (D7) covers the tests. The hunt doesn't change its rounds.

## Decisions

### D1. A named limit says what it bounds, and the wait names what it waited for

Each limit is a module constant with a docstring, as `STOPPED_WITHIN` in `test_openai_runner.py` already is. The
docstring says what event the limit bounds and why it's that size. Where the tool under test has its own limit, the
test's limit is that one plus a named margin, read from the tool (`flake_campaign.STOP_WAIT_SECONDS`), never a copy
of its number. On timeout, a wait fails with a message naming the event, not a bare `assert False`.

*Alternative:* one shared `SLOW_RUNNER_SECONDS` for all of them. Rejected: the waits bound different things (a
request, a process stop, a round start), and one number would be wrong for most.

### D2. Exact event lists drop notices and keep everything else (#357)

`test_run_workspaces.py` gets `topics_besides_notices(made, run_id)`, which returns the run's topics without
`Run.Noticed`, and `assert_no_gap(made, run_id)`, which checks that the versions are `1..n` with no gap. That's what
`== [1, 2]` meant: the end was built on the reloaded run, not on the version that counted the unrecorded event. Any
other topic still shows up in the list and fails the exact comparison. This is the same loosening `ab6107b` and
`640bda1` gave the timed notice tests. Lines 258, 289 and 311 use it. `test_cli_runs.py:256` uses it only if its
actor makes a worktree or can record a silence (task 2.3 checks). Otherwise it can't see a notice and is left alone.

### D3. The OpenAI fake can be waited on for its *n*th request (#359)

`FakeEndpoint.wait_for_requests(count, timeout) -> bool` waits on a `threading.Condition` that `_State` signals as
it records each request. The two stop tests call it with a named `REQUEST_WITHIN`, replacing `time.sleep(0.3)`, and
then check that exactly one request arrived, as they do now. A runner that never sends the request still fails, at
that limit.

### D4. A fake's pause lasts its length on the clock the test measures with (#352)

The OpenAI fake's `Pause` slept with `time.sleep`, which uses a precise timer, while the test measured it with
`time.monotonic()`. On Windows with Python 3.12 that clock ticks every 15.625 ms (`GetTickCount64`), so a 0.3 s sleep
read as 19 ticks: 0.296875 s, the "0.297" #352 saw. The pause now waits until a `time.monotonic()` deadline, as the
Ollama fake's hold already does. Then it lasts at least its length on that clock, however coarse the clock is. A test
replaces `time.monotonic` with a 15.625 ms clock and times the fake's pause alone. main's pause fails it in most
runs, and the new one can't fail it. That gives the evidence on every OS, not only on the Windows 3.12 leg.

The other lower-bound asserts (`test_ollama_fake.py:52`, `test_platform_watching.py:132, 292`,
`test_run_queries.py:382`, `test_claude_code_processes.py:72`) are left as they are. Each times a wait that ends at a
`time.monotonic()` deadline (the Ollama fake's `_hold`, `DirectoryWatch.wait`, `Popen.wait`) and measures it with that
same clock, so it can't come out short. `DirectoryWatch` promises to return after its timeout on every platform, and
slack would weaken the test of that promise.

*Alternatives:* allow one tick of `time.monotonic()`'s resolution in every lower-bound assert, as first planned.
Rejected, because it weakens the asserts that are exact. Measuring with `time.perf_counter()`, as the issue suggests,
leaves the fake's sleep and the measurement on different clocks.

### D5. The preflight deadline is timed from the first preflight request (#354)

`fake_ollama.Request` gets an `at: float` (monotonic) stamped when the fake receives it. The test measures from the
first preflight request's `at` to when it reads the refusal, and allows a named `AFTER_DEADLINE` margin for the
runner to notice the deadline and the test to read the error. One shared deadline refuses at about 10 s and two
would refuse at about 18 s, so the margin must stay under 8 s to tell them apart. It's set to 6 s, with that reason
in its docstring. Starting the runner no longer counts.

### D6. The cancel test waits until the answer streams (#301, #353)

**The cause.** The runner records its first request's body as a `sent` transcript record before it makes the
request (`conversation.py:311–313`). The test cancelled on the first `run/transcript` it saw, which is that record,
not a line of the streamed answer. When the cancel landed between the two, the runner rightly made no request, so the
fake had no connection to see closed. That's #301's failure exactly: the runner answers the cancel and exits at once,
then `closed_by_client.wait(5)` runs out (the CI call took 5.10 s). Shown by widening that window with a 0.5 s sleep
after the record: main's test then fails every time with the same assertion, and the fixed test passes. Tracing the
fake under load matched it too: in all 540 rounds the test cancelled before the fake had sent line 0. On a fast
machine the request had simply gone out first.

**The fix, in the test:** wait for a transcript record of kind `received` (the answer's first line), then check the
fake has the chat request, then cancel. The runner is right, so it doesn't change, and no `ollama-runner` spec delta
is needed. The 5 s close waits, here and in the end-of-input test, become `CLOSE_SEEN_WITHIN`, at the same size.

**Found on the way, and fixed though it wasn't the cause:**

- Both fakes waited on a socket with `select.select`, which raises `ValueError` for a descriptor numbered 1024
  (`FD_SETSIZE`) or higher on Linux and macOS. They now use `selectors.DefaultSelector`. With 1100 descriptors held
  open, main's fake died on the first hold. A probe of a full local run found no worker above descriptor 18, so
  that's not what failed on CI. The fakes just don't depend on it any more.
- The Ollama fake's `handle_error` swallowed every exception, so a handler that died looked like a fake that saw
  nothing. It still swallows a `ConnectionError`, as its docstring says it should. Any other error is kept, and
  `stop()` raises the first one. No test in either plugin's suite was hiding such an error.
- Each fake's tests gain a POSIX-only regression test: a held reply still sees the client's close on a descriptor
  past 1024. With main's `select.select` both fail, and the Ollama one names the error.

#353 is the same test and the same assertion, so it's closed as a duplicate of #301.

### D7. A test that gives up on a hunt or campaign stops the whole tree (#364)

`scripts/tests/conftest.py` gets `stop_tree(process)`, which tests already reach through `from conftest import …`.
It takes a snapshot of the tree before killing anything, because once the root dies its descendants are re-parented
and can't be found:

- **POSIX:** read `ps -A -o pid=,ppid=,pgid=`, collect the root's descendants, `killpg` each distinct process group
  among them (rounds and load are each their own session), then `SIGKILL` any pid left, and reap the root.
- **Windows:** `taskkill /F /T /PID <root>`, which follows parent links. The hunt's rounds and load are also in
  jobs that die with the hunt.

Every test that starts a hunt or campaign uses it on giving up. `Popen` tests call it in their `finally` instead of
`process.kill()`. `run_hunt` becomes a `Popen` with a bounded wait, calling `stop_tree` on timeout and then failing
with the output so far.

*Alternative:* start the child with troupe's `ChildProcess` (jobs or process groups). Rejected: it's asyncio-based,
and a POSIX group kill doesn't reach rounds and load, which run in sessions of their own.

### D8. Load processes end with the hunt on POSIX (#364, spec)

`LOAD_PROGRAM` records `os.getppid()` at start, then spins. Between short pure-Python bursts, at most every named
`LOAD_CHECK_SECONDS` (0.2 s), it checks whether its parent has changed, and exits if so: a killed hunt's load is
re-parented to init or a subreaper. On Windows the same check never fires, because `getppid` doesn't change there.
The job already ends the load when the hunt dies. A new test kills the hunt with `SIGKILL` (or `TerminateProcess`)
while `--load 2` runs, and checks that both load pids are gone within a named limit.

*Alternatives:* `prctl(PR_SET_PDEATHSIG)` is Linux-only. A lifeline pipe through a supervisor process per `Tree`
would also cover rounds, but it adds a process layer and exit-code pass-through for a promise the spec doesn't make
(see Non-Goals).

### D9. A stop is bounded by the tool's own stop limit, and the slow path is checked from the output (#358, #364)

- **Campaign test:** wait `flake_campaign.STOP_WAIT_SECONDS + STOP_MARGIN`. A hunt that doesn't stop is killed by
  the campaign at its own limit and leaves no summary, so `summary is not None` still fails, now with the campaign's
  output to read.
- **Hunt interrupt test:** wait `flake_hunt.STOP_TIMEOUT_SECONDS + STOP_MARGIN` for the exit, and read the rest of
  the output to its end within the same limit. `stopped_in < 5` is replaced by checking that the output doesn't hold
  `workers still running after`, the line the hunt prints when it gives up on rounds it couldn't stop. A hunt that
  stops its rounds still passes however slow the machine is. One that doesn't still fails.
- **Startup waits** (`w0r0 passed`, the pid file) get a named `HUNT_START_WITHIN`, at their current size.

Before choosing the margin, the campaign test is run under load with the hunt's output kept, to see why its stop
took over 60 s on CI. If the hunt's own stop is slow in a way it shouldn't be, that's a hunt defect, and it's fixed
in this change rather than hidden by the margin.

### D10. The stall test's round timeout allows for a round starting under load (#350)

First reproduce it with `flake_hunt.py --load` on the test itself, and record the assertion on #350. The round has
to time out to be reported `hung`, so the test can't end on the dump alone. `--round-timeout` becomes
`STALL + ROUND_START_ALLOWANCE`, a named allowance for starting a child pytest on a loaded machine. Its docstring
gives that reason, and the test fails with the record's status and output tail. If the reproduction shows a
different assertion fails, the decision is revisited from what it shows.

### D11. The direction carries a marker no path can hold (#335)

The direction becomes `f'say "{marker}"\nthen stop'`, with `marker = f"direction-{uuid4().hex}"`. The test checks
the marker isn't in any argument and that stdin is the whole direction. A fresh UUID can't occur in a path the host
made by chance, and putting the direction on the command line still fails the test.

### D12. The CRLF test makes the file's stat disagree with the index (#351)

After `git checkout -- crlf.txt`, set the file's mtime 2 s earlier (`os.utime`). When the stat doesn't match the
index entry, git always compares the content, whatever the timestamp ticks were. The content differs from HEAD once
normalised, so git lists the file as modified every time. The fill and capture assertions are unchanged, so the test
still fails if either stops treating the file as unchanged.

### D13. The Claude Code perform test is bounded by its run, not by the harness's start limit (#355)

Reproduce it under load first and record the assertion. If a run limit fires (`start_timeout` 10 s or `run_timeout`
20 s), give the perform tests that start a real runner process limits from a named `runtesting.REAL_RUNNER_LIMITS`.
Those are sized to catch a hang, not to require speed, since these tests check what's recorded, not how fast.
Tests of the limits themselves keep their own. If the reproduction shows another cause, it's fixed there.

## Risks / Trade-offs

- **Reproducing under load takes the owner's machine.** It needs `flake_hunt.py --load` loops for #301, #350, #354
  and #355. → Announce each one before starting, and run them one at a time.
- **A cause doesn't reproduce.** → Fix on the evidence there is, write in the test what isn't known, and say so on
  the issue rather than claim a cause. Don't close the issue on a guess: leave it open with the fix linked, and ask
  the owner.
- **D4's slack hides a real early wake-up of up to one tick.** → It's one tick of the clock the code uses, which is
  that code's own precision. A larger shortfall still fails.
- **The stall test gets longer** by its start allowance, wall time, in one xdist worker. → Accepted. The allowance
  is the smallest the reproduction supports.
- **`ps` output differs between macOS and Linux.** → `-A -o pid=,ppid=,pgid=` is POSIX. The helper is tested on
  both in CI through the hunt tests that use it.
- **Windows evidence for D4 comes only from CI**, on the Windows 3.12 leg, which runs these tests on every full
  check. → The PR cites that leg's run.

## Migration Plan

None. Tests and test tooling only, apart from `flake_hunt.py`'s load program, which has no stored state.
