# Design

## Context

See proposal.md (Why) for the measurements. Each slow test waits on something different:

- **Conformance.** `check_runner` runs six checks, each against a fresh runner, then a whole run through
  `run_actor`. `_Driver.answer` waits up to `start_timeout` for each answer. `_Driver.exits`, the end-of-input check
  and `_with_runner`'s clean-up wait up to `cancel_grace`. The host's watchdog stops the whole run at `run_timeout`,
  then waits `cancel_grace` before killing. The `ignore-eof` fake runner answers `run/cancel` and then sleeps instead
  of exiting, so it pays `cancel_grace` in the cancel check, the end-of-input check and the whole run. Neither fake
  mode sends a result, so both pay the full `run_timeout` in the whole run.
- **State machine.** Almost all of its time is git subprocesses, through `gitrepo.Repo.git` and through `TextStore`'s
  refresh on every read. Profiled: the invariant takes 13.5 of 22.7 s, and its two
  `reader.notifications(1, 100_000, None, ())` calls take 7.9 s between them. `self.branch()` is called twice per
  invariant, once to read `issued` and once to write it, and that's about 1.9 s more.
- **Ctrl-C.** `troupe perform` runs as a real subprocess with `RunLimits()` defaults. The script ignores cancel, so the
  host waits `RUNNER_CANCEL_GRACE_SECONDS` (10 s) and then kills it. No setting reaches that limit from outside the
  process.

## Goals / Non-Goals

**Goals:**

- Cut each wait to what the test's assertion needs, while every test still checks what its name promises.
- Make durations visible in every check run's log.

**Non-Goals:**

- Changing any limit's default, or adding a setting for run limits. The owner chose not to add one for the Ctrl-C
  test (proposal).
- Changing the state machine's `max_examples` or `stateful_step_count`, or adding a separate scheduled profile with
  higher counts. That would be a coverage decision of its own, with its own reason.
- Making the conformance checker itself faster, for example by skipping the whole run after an earlier check fails.
  That's product behaviour (actor-runners), and a real runner needs every check reported.

## Decisions

### D1: A second, short set of limits for the conformance tests that expect a timeout

`test_runner_conformance.py` keeps `LIMITS` (start 10 s, cancel grace 3 s, run 10 s) for the tests that expect a
runner to pass or fail a check by its content, and adds `EXPIRING` with `start_timeout=10.0`, `cancel_grace=1.0` and
`run_timeout=1.0` for the two fake-runner tests. `_check` takes the limits as a parameter, defaulting to `LIMITS`.

Why this is safe: in both tests, the check they assert either fails on content or fails by timing out.

- `unknown option refused` fails because the fake accepts the option. That only needs answers within
  `start_timeout`, which stays 10 s.
- `exit on end of input` fails because the fake never exits. Any positive `cancel_grace` produces the same "didn't
  exit within …s of its input closing" problem, and a shorter one can't make the check pass. The test still asserts
  `"input closing"` in the problem.

The whole-run check, which is where the 1 s `run_timeout` applies, isn't asserted in either test.

**Why `cancel_grace=1.0` and not the issue's 0.5 s:** `_with_runner` also uses `cancel_grace` for waiting on a killed
child before `release()`, whose contract is "call once it has exited". A killed process on a loaded Windows worker
should go well inside 1 s. 0.5 s saves about 1.5 s more in one test and leaves less margin, so it isn't worth it.
Expected: the end-of-input test about 4 to 5 s instead of 19, and the unknown-option test about 1.5 s instead of 10.

**Alternatives:** one shared shorter `LIMITS`, which the side agent's note (2026-10-20) rules out, because the
scripted runner's passing test needs a real process to exit within the grace on Windows CI. Or limits per check
inside `check_runner`, a product change that buys nothing here.

### D2: The state machine's invariant reads each value once

`the_order_holds` takes `listed = list(reader.notifications(1, 100_000, None, ()))` once and derives `ids` and
`numbers` from it. It reads `branch = self.branch()` once and uses that for both `issued` lookups. `reader.notices()`
is still read after the notifications, so an `events.order-rebuilt` notice raised by that read is still seen. Every
assertion stays as it is. Expected saving: about 5 s of 23.

**Why not the counts:** the issue lists them as a coverage trade-off to change only with a stated reason. The repeated
reads aren't coverage. They read the same unchanged repository twice.

**Checking the rewrite:** per [[learned--differential-test-rewrites-against-the-old-behaviour]], the property that has
to hold is that the invariant fails on the same broken stores. A temporary local mutation (for example, the store
skipping a notification number) must fail both the old and the new invariant. Then the mutation is reverted. It
isn't committed.

### D3: The Ctrl-C test gets a comment, not a change

The comment goes above the test. It says the ~10 s is troupe's default `RUNNER_CANCEL_GRACE_SECONDS` in a real
`troupe perform` subprocess, needed because the second Ctrl-C has to land while the run is still cancelling. It says
that `test_run_host` covers kill-after-grace in-process with a short grace. And it says that shortening this test
needs a cancel-grace setting, which is out of scope for #84. That meets the issue's "or has a comment saying why it
can't be".

### D4: `--durations=25` in the tests gate's command

`gates()` builds the pytest command as `[pytest, *PARALLEL, "--durations=25", ...]`, before any `-m` scope, so the full
check and scoped checks both print it. It goes in `check.py`, not `addopts`. Like `PARALLEL`, it's how the check runs
the suite, and running `pytest` directly (one test, the flake hunt's rounds) stays unchanged.

pytest-xdist reports durations to the controller, so the table covers every worker. A test in
`scripts/tests/test_check_parallel.py` runs the gate's own command through pytester with 2 workers and checks for the
"slowest 25 durations" header, on a passing suite and on a failing one.

## Risks / Trade-offs

- [The short limits produce Windows-only noise in the clean-up, such as a still-running child at `release()`] → the 1
  s grace, not 0.5 s (D1). CI on all three platforms has to pass. Re-running CI is the check that #84 counts, not a
  harsher local stress loop.
- [The durations table makes every check's output longer] → 25 lines, printed before the short summary, so failures
  stay at the end where people look.
- [After this change the state machine is still the longest test (~18 s), so it still sets the parallel floor] →
  recorded in the PR with the measured times. Any change to its counts is a separate decision.
