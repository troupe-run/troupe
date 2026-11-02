# Design

## Context

See proposal.md for why. What exists today:

- **The test** (`packages/troupe/tests/test_run_queries.py`,
  `test_following_wakes_on_another_processs_write_timed_from_when_the_append_returned`). A child process
  (`perform_child.py`) performs a scripted run: `INIT`, then 700 ms, `turn a`, 700 ms, `turn b`, 700 ms, `OK`. The
  child notes the wall-clock time each segment append returned, and the seqs that append wrote, in a file outside the
  theatre (watch-event-segments design D7). The test follows the run in process with `QUIET` (the store's poll and
  check at 60 s), records `time.time()` as each event update is sent, and asserts the median of the three delays
  (seq 1 to 3) is under 0.5 s.
- **What following does** (`troupe.core.runs.queries.logs`). It listens to the store's subscription before its first
  read. On each wake it clears the wake, then re-reads the whole run in a worker thread (`_log`) and sends what's new.
  Its only timer is `defaults.LOGS_LEASE_CHECK_SECONDS` (1 s), which checks the run's lease. A timeout doesn't re-read.
  So a delivery takes: the OS signal, the store's subscription thread waking and reading, `_Wakeup.set` scheduling the
  event loop with `call_soon_threadsafe`, the loop waking, a `to_thread` hop for `_log`, and the send. That's three
  or four thread handoffs past the store's own delivery.
- **The failures** (#227). Delays of 1.79 s, 2.83 s and 4.97 s on one run, so all three were slow. On the other two,
  the first delay was quick (0.17 s, 0.18 s) and the median missed by 0.04 s and 0.09 s. Both shapes are load. Nothing
  here suggests a missed wake: a missed wake on a 60 s poll would mean an event that never arrives.
- **Where the child can wait.** perform records an event (`_record`, under the store's thread and write locks), then
  calls `send` with the event's update once the record has returned. `perform_child.Announcing.send` already hooks
  that point to print `STARTED` at seq 0. Blocking there holds no store lock, so the follower's reads aren't blocked.
  perform's event loop is blocked, so the runner's later events wait in its pipe and nothing else is recorded.
- **Shared timing and sampling** (`packages/troupe/tests/storetesting.py`, from listener-bound-on-windows). It holds:
  - `BOUND` (0.25 s), the store's bound;
  - `STALL_SECONDS` (5 s, with its CI evidence);
  - `SLOW_STRETCH_SECONDS` (60 s, with #159's evidence);
  - `WITHIN` (30 s);
  - `watched_delays(measure, *, clock, slow_stretch)`, which measures five, then one at a time while none is under
    `BOUND`, until the budget has passed. Its own tests (`test_storetesting.py`) drive it with scripted delays and a
    fake clock. Three store and watch tests use it, and it has held on Windows CI since #159.

## Goals / Non-Goals

**Goals:**
- A slow stretch can't fail the test while it is shorter than `SLOW_STRETCH_SECONDS` overall and shorter than `WITHIN`
  on any one event.
- The test still fails a follower that:
  - only shows an event once a later one is written (a lost or late wake);
  - shows events from a timer rather than the subscription;
  - never wakes;
  - is slow every time, such as a steady 2 s delay in following's own hops (the gap a median-only check leaves).
- A quiet machine measures five events.
- The test's name, its body and the spec scenario all claim the same thing.

**Non-Goals:**
- Changing following, the subscription, their defaults or notices.
- The other following tests in the file. They have no latency bound and haven't flaked.

## Decisions

### D1: Check order exactly, with a handshake

The old test checked a race: the median delay against 0.5 s, with 700 ms between writes. Part of what that stood in
for is order: following shows event *n* because event *n* was written, not because event *n+1* was, and not because a
timer fired. Under load the race fails while the order still holds.

So the writer waits for following. After perform sends each event's update, the child waits until the test has written
that seq to a "shown" file outside the theatre. Only then does it go on and record the next event. With the store's
poll and check at 60 s (`QUIET`), and following's lease check at 60 s (D4), only the subscription can wake following
within the test. Event *n+1* hasn't been written while the child waits on *n*. So each event shown proves following
woke on that event's own write and showed it.

Seq 0 takes part too. The child prints `STARTED` at seq 0, then waits for it to be shown, so seq 1's write comes after
following's first read and can only arrive through a wake. Today the 700 ms gap only makes that likely.

### D2: Sample speed until a quiet moment, reusing `watched_delays`

Order says nothing about speed. A follower with a steady 2 s delay in its own hops would pass D1 alone, and a median
with a load allowance (5 s or more) would let it through too. The fastest-of-many check is right in kind: a follower
that is slow by design is slow every time, while load is uneven over time. listener-bound-on-windows made it
load-proof by measuring until one is fast or a budget runs out. The handshake makes each event a measurement the test
can ask for, so the same sampling applies here.

- **Each measurement.** `measure()` waits (up to `WITHIN`) for following to send the next event. It reads that seq's
  append time from the appends file, polling briefly, since the child writes that line just after its append returns
  and following may get there first. It writes the seq to the shown file, so the child records the next event, and
  returns the delay.
- **The sampling.** `watched_delays(measure, bound=FOLLOW_BOUND)` measures five, then more while none is under the
  bound, until `SLOW_STRETCH_SECONDS` has passed. Then the test writes `stop` to the shown file. The child stops
  waiting and plays the rest of its script at once, so the run ends and following stops.
- **The assertions.** The fastest delay is under `FOLLOW_BOUND`. The median of the first five is under
  `FOLLOW_BOUND + STALL_SECONDS`, the event store's tests' allowance for a loaded median. Each event was received
  before the child appended the next. Every delay goes in each message.

**The script.** `INIT`, then enough turns for the longest possible sampling, then `OK`, with no waits. Every
measurement after the fifth is at least `FOLLOW_BOUND`, or sampling would have stopped. So at most
`5 + ceil(SLOW_STRETCH_SECONDS / FOLLOW_BOUND) + 1` turns are measured, 126 today. The test derives the count from
the two constants, so changing either can't leave the script short. The turns after `stop` record in a burst. That's
a few hundred milliseconds of the child's writes, and the test's following just catches up.

**The bound.** `FOLLOW_BOUND = 0.5` joins `storetesting.py` beside `BOUND`. Its docstring says it's the store's
0.25 s plus following's own hops (the loop's wake and a re-read of the run), and that 0.5 s is the bound the spec
already promised. #227's runs show it holds in a quiet moment: two of the three failures had a first delivery of
0.17 s and 0.18 s.

*Alternative: order plus a loose median only* (the first draft of this design). It leaves a steady delay of a few
seconds uncaught. Rejected at the owner's review.

*Alternative: keep the 700 ms gaps and sample adaptively without a handshake.* Order would rest on timing again, and
a follower that holds each event until the next write would give about 0.7 s delays, so only the bound would catch
it. Rejected: the handshake makes that case exact.

*Alternative: a looser bound with the gaps kept.* Gaps would have to exceed the bound (6 s or more) for a held event
to fail, which makes the test take 18 s or more and still rest on an assumption about load. Rejected.

### D3: `watched_delays` takes a bound

`watched_delays` gains `bound: float = BOUND`, used in place of `BOUND` in its loop. Existing callers are unchanged.
`test_storetesting.py` gains one case: with a bound of 1 s, a 0.5 s delivery that would be "slow" against `BOUND` but
is fast against 1 s stops sampling at five. Its docstrings stop saying "under BOUND" where they mean the bound passed
in.

### D4: Turn following's lease check up to 60 s in this test

A timeout of following's lease check doesn't re-read today. But a regression where it did (a follower driven by its
timer) would show each event within one interval, which passes the handshake. With
`monkeypatch.setattr(defaults, "LOGS_LEASE_CHECK_SECONDS", 60)` in this test, only the subscription can wake
following inside the test, so such a follower fails on order, naming the event, whatever its interval.

Without the patch, the bound would catch only a timer slower than `FOLLOW_BOUND`. The handshake writes each event just
after a re-read, so a timer-driven follower's delay is always about one full interval. That covers today's 1 s, but
not an interval under 0.5 s (found in 3.3). The run ends by recording its end, which wakes following, so the long check never holds
the test up. The follower runs in the test's process and reads the setting through `defaults` on each wait, so the
patch reaches it.

### D5: The child's side of the handshake, bounded

`perform_child.py` takes the shown file from the environment (`TROUPE_TEST_SHOWN`, alongside `TROUPE_TEST_STOP`), and
`Child` takes a `shown: Path | None`. In `Announcing.send`, after any `STARTED` print, for each event update the child
polls the file (every 10 ms) until it lists the update's seq or says `stop`. After `stop` it never waits again.

- If `WITHIN` passes first, it prints `UNSHOWN <seq>` and never waits again, so a broken follower fails in about 30 s
  at most. The test's own wait in `measure` fails first, naming the seq. The test also asserts the child printed no
  `UNSHOWN`.
- With the shown file set, the child raises its run's `run_timeout` to `SLOW_STRETCH_SECONDS + 2 * WITHIN` plus the
  default 20 s. That covers seq 0's wait, the budget, and the last measurement, so a slow follower fails in the test,
  never as a timed-out run.
- The shown file is written by the test and read by the child, outside the theatre, so its writes never wake the
  follower's watch.
- The test writes `stop` and kills the child in a `finally`, so a failed assertion leaves no process behind.

### D6: Show the test fails only for what it's named for

Temporary edits, each reverted, made in following's loop in `queries.py`:

1. **A slow stretch.** Sleep 1 s before each re-read after a wake, for the first 8 s of following, then none. The old
   test fails, with every delay about 1 s or more, which is #227 reproduced on demand. The new test passes, measuring
   more than five. This one edit, run against both tests, is the differential check.
2. **A held event.** After a wake, send all but the newest event unless the run has ended. The new test fails, naming
   seq 1.
3. **A timer-driven follower.** Stop listening to the subscription, and re-read on the lease check's timeout instead.
   Seq 0 still comes from the first read, and the new test fails, naming seq 1. With D4's patch taken out it fails on
   the bound instead, every delay about 1 s, since the handshake writes each event just after a re-read (D4).
4. **A steady delay.** Sleep 2 s before every re-read. The new test fails on the fastest delay once the 60 s budget
   has passed, listing every delay. This is the case the owner's review asked to catch.

### D7: Rename the test

`test_following_shows_another_processs_events_each_before_the_next_the_fastest_under_the_bound`, in the shape
of the store tests' names. Its body checks both claims.

## Risks / Trade-offs

- [A slow stretch longer than 60 s, or one event slower than 30 s, still fails] → Those are `SLOW_STRETCH_SECONDS` and
  `WITHIN`, shared with the store's tests. Each is one named constant.
- [A broken follower takes up to about 60 s to fail instead of about 3 s] → Only a failing run pays it, and the message
  lists every delay or names the event.
- [A follower that is fast only now and then passes on a loaded machine] → Accepted, as in #159. On a quiet machine it
  measures five and fails unless one of them is fast, and the median of the first five still bounds gross slowness.
- [Under load, many single deliveries miss 0.5 s] → Only the fastest of up to about 126 must meet it. #225's run had
  three slow events in about 10 s; here it would keep measuring for 60 s.
- [Blocking perform's event loop in `send` changes when perform's own timers fire] → Only in this test's child. Start
  is over before seq 0, the run timeout is raised (D5), and the silence announcement only sends a notice, which
  `Announcing.send` ignores.
- [The two processes compare `time.time()`] → The same machine and clock, as the test does today.

## Migration Plan

None: tests and spec text only. Rollback is reverting the commits.
