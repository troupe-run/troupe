# Proposal

## Why

`test_following_wakes_on_another_processs_write_timed_from_when_the_append_returned` has failed three times on Windows
CI (#227): on #225 (Python 3.15, delays 1.79 s, 2.83 s and 4.97 s), on #230's merge-queue run (3.14, median 0.54 s),
and on #231 (3.14, median 0.59 s). None of those pull requests touched the runs code, the other 11 legs passed each
time, and the failure took #230 out of the merge queue. The test requires the median of three deliveries to be under
0.5 s, with the child's appends 700 ms apart. That bound rests on the runner not being loaded. Following takes more
thread hops per event than the store's own subscription (the store's thread, the event loop and a worker thread that
re-reads the run), and each hop costs a scheduling slice on a loaded two-core runner. #159 had the same shape one
layer down.

The issue's done-when: the bound is set by what following has to promise, not by an assumption that the runner isn't
loaded (or the test says why its bound holds under load), and CI passes on all three platforms.

## What Changes

- **Order, checked exactly.** The child process records each event only once following has shown the one before it
  (a handshake through a file outside the theatre). With the store's poll and check, and following's lease check, all
  at 60 s, nothing but the store's subscription can wake following inside the test, and the next write hasn't happened
  yet. So each event being shown proves that following woke on that event's own write and showed it, without waiting
  for a later event or a timer. Load can slow that down, but can't make it false.
- **Speed, sampled until a quiet moment.** As #159 did for the store, the test measures five deliveries. While none is
  under 0.5 s, it measures one more at a time, until one is or the 60 s slow-stretch budget (`SLOW_STRETCH_SECONDS`)
  runs out. It asserts the fastest is under 0.5 s, the bound the spec promises today. Then it tells the child to stop
  waiting, and the run ends. A follower that is slow every time, say a steady 2 s delay, still fails, once the budget
  is spent. A loaded runner fails only if its slow stretch outlasts the budget. A quiet machine measures five.
- **The median stays as a loose guard.** The median of the first five must be within 0.5 s plus `STALL_SECONDS`, the
  allowance the event store's tests already give a loaded machine.
- **One sampling helper.** The test reuses `watched_delays` from `storetesting.py`, which gains a `bound` argument. The
  helper's own tests cover that argument. Following's 0.5 s bound becomes a named constant beside the store's 0.25 s.
- **Failures name what they waited for.** A follower that never shows an event fails within `WITHIN` (30 s), naming
  the event, instead of hanging or timing out the run.
- **Name and spec match the body.** The test is renamed to say what its body checks, and the runs spec scenario
  "Following shows events as they are recorded" says the same.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `runs`: in "Logs read a run's events in order", the scenario "Following shows events as they are recorded" changes
  from "the median delay of three events is under 0.5 s" to:
  - each event is shown before the run's next one is recorded, with nothing but the store's subscription able to
    wake following;
  - the fastest delay is under 0.5 s, among the first five or among more recorded until one is or a 60 s slow-stretch
    budget runs out;
  - the median of the first five is within 0.5 s plus an allowance for a loaded machine.

## Impact

- Tests only: `packages/troupe/tests/test_run_queries.py` (the test), `packages/troupe/tests/perform_child.py` (the
  child's side of the handshake), `packages/troupe/tests/storetesting.py` (`watched_delays`' bound and the follow
  bound), and `packages/troupe/tests/test_storetesting.py` (the helper's tests).
- No change to following, the subscription, their defaults or notices.
- A follower that is slow every time now takes about 60 s to fail, and one that never shows an event about 30 s,
  instead of about 3 s. A passing run on a quiet machine gets faster: five events with no 700 ms gaps.
- No spec is added or removed, and no Purpose changes, so troupe-run/infrastructure's `oob/troupe-spec-purposes.json`
  needs no update.
