# Design

## Context

See proposal.md, Why. Both tests reach real OS notification: FSEvents on macOS, where both failed. FSEvents events
pass through `fseventsd`, a separate daemon, before the stream's callback runs on a dispatch queue. The machine was
loaded by other sessions' test suites, which also do a lot of file I/O. Workers may not generate load to reproduce
(owner's load rule), so each cause is found by reading the code and forcing the slow interleavings directly.

## Goals / Non-Goals

**Goals:**
- Each test still fails for the defect it was written for: a wait that blocks on a pending change (#446), and a store
  that doesn't deliver, or only polls (#448).
- Neither can fail from load alone, short of a slow stretch past the 60 s budget the watched-delivery tests share.

**Non-Goals:**
- #450 (order log duplicates), found on the way and owned by its own change.

At first this change left the three watch-only tests in `test_processes.py` alone, as none had failed. Then this
branch's own commit check, at a load of about 38, failed all three on one worker, each with no delivery within 10 s
while only the watch could deliver: #448's mechanism. They're in (D5).

## Decisions

### D1. #446: nothing in troupe blocks a pending report; the 0.25 s timing measured load

`_FSEvents.wait` returns at once when the callback has already set `_changed`; inotify's `poll` and Windows'
`WaitForMultipleObjects` return at once on a ready handle. `DirectoryWatch.wait` adds one `is_dir()` call. So the
0.32 s was either the OS delivering the change more than 0.5 s after it was made (the test's sleep only assumed
delivery), or the test's thread not running for most of a third of a second. Load causes both. Neither is something
the bound was meant to catch.

### D2. #446: check "at once" with a zero timeout, not with a clock

"The next wait returns at once" means the wait doesn't block when a change is pending. A wait with a timeout of zero
checks exactly that, and no scheduling delay can make it fail: a stall during the quiet half second only gives the OS
longer to deliver. What load can still do is delay the delivery past the half second. Then the zero-timeout wait says
nothing changed; the test asserts a normal wait reports the change (it's never lost), and tries again, until one
zero-timeout wait reports its change or the 60 s slow-stretch budget (`SLOW_STRETCH_SECONDS`) runs out.

A backend that blocks on a pending change, or only notices changes while someone waits, fails every attempt, so it
still fails once the budget is spent. On a quiet machine the first attempt passes.

Alternatives: the fastest of several wall-clock timings (`watched_delays`, as the append test does). Rejected: with a
backend that polls only while waiting, every sample is a random phase of its interval, so the fastest of five is under
0.25 s most of the time and such a backend can pass. Raising `BOUND`: rejected, it's the same measurement with less
power.

### D3. #448: no lost wake-up in the subscription; the 10 s wait was shorter than the store's backstop

Read through, every wake of the subscription's watch is followed by a delivery (`_run`), a delivery compares the
order's length, not the index, and the test thread's own reads can't consume a wake. The only path that consumes a
report without a delivery, `_reports_late`, runs at a check after 30 s with no report, which the test never reaches.
The remaining case, a report the OS drops, is already tested:
`test_a_watch_that_never_reports_is_caught_by_the_check_then_the_store_polls` (`test_processes.py`) shows the check
delivers an event the watch never reported.

So 10 s without a delivery means the OS reported late or not at all (FSEvents can coalesce or lag under load), or the
writer or reader didn't run for that long. The store's design already allows a dropped report: the check every
`SUBSCRIBE_CHECK_SECONDS` delivers it (watch-event-segments D5), with no notice while the watch is reporting other
writes. The port test uses the port's defaults, so a delivery can lawfully take up to that check.

The wait for each delivery becomes `SUBSCRIBE_CHECK_SECONDS + STALL_SECONDS` (35 s), named in the test with that
reasoning. What it proves is unchanged: `min(delays) < BOUND` still fails a store that only polls or only checks, and
the wait still fails a store that never delivers.

Alternatives: make the store fall back to polling whenever a check finds an event the watch didn't report, even
amid other reports. Rejected: on a loaded Mac one late report would switch the subscription to 1 s polling for good,
a real regression to fix a test. Keeping 10 s: it fails the port's own guarantee under load.

Proven without load: with FSEvents' callbacks for one write dropped (a scratch patch), the new test passes in 30.6 s,
the check having delivered the event, and the old one fails at `heard.wait(10)`, as #448 did.

How long it can take: `watched_delays` starts measurements until 60 s have passed, and each now waits up to 35 s, so a
run passes or fails within about 95 s. Before, it was about 70 s. A quiet run is unchanged, at about 2 s.

It still proves "the fastest under the bound", not only "eventually": `min(delays) < BOUND` is unchanged, and a
delivery the check makes, at a random point in its 30 s cycle, is almost never under 0.25 s. The longer wait only
changes what a single late delivery does: it is measured, as a slow sample, instead of failing the test.

### D4. The port test's "a store that only polls can't pass" is made true

The test asserted `SUBSCRIBE_POLL_SECONDS >= 4 * BOUND` and called that "polling alone can't pass". Nothing in the test
could falsify that. A poller's delay is the time to its next look, so it depends on when the writer records. Checked
with a store whose watch is refused (a scratch patch), each record lands about 0.1 s after the poll that delivered the
last one, every delay is about 0.9 s, and the test fails. But with a writer that pauses 0.85 s before recording, as a
loaded machine can, the delays fall to 0.12–0.15 s, and the old test passed against a store that only polls.

A store that only polls notifies at most once per `SUBSCRIBE_POLL_SECONDS`: its next look begins a full interval after
the look that last notified. The listener (`Notified`) keeps the time of each notification. A delivery counts towards
the bound only if its event was recorded less than `SUBSCRIBE_POLL_SECONDS - BOUND` (0.75 s) after the last
notification; a poller's delay for it is then more than `BOUND`, whatever the scheduling. Deliveries that don't count
are still measured for the median, and `watched_delays` keeps sampling while no counted delay is under the bound. On a
working store nearly every delivery counts, as each record follows the last notification by the writer's 0.1 s pause.

Checked by mutation: against the polling-only store, the new test fails both with and without the writer's 0.85 s
pause; the old one passes with it.

Alternatives: a count of deliveries under the bound large enough that a poller passes with negligible probability.
Rejected: a poller's delays aren't independent random phases but locked to the writer's timing, so no count bounds the
chance; and under the slow-stretch loop a poller gets many tries. Rewording the comment: rejected while a cheap way to
make it true exists.

### D5. The watch-only tests in `test_processes.py` wait longer, with the poll and check out of reach

Three tests set the poll and check to 60 s so that only the watch can deliver, and wait 10 s for each delivery:
`test_another_processs_write_wakes_this_processs_subscription`,
`test_another_processs_events_each_reach_a_listener_the_fastest_under_the_bound` and
`test_the_first_event_reaches_a_listener_that_subscribed_before_events_existed`. A 10 s FSEvents stall fails them.

Each wait becomes `HEARD_WITHIN` (`WITHIN`, 30 s, the repository's wait for a condition), and the poll and check
`WATCH_ONLY_SECONDS`: the slow-stretch budget plus twice `HEARD_WITHIN` (120 s). Measurements start within the 60 s
budget and each waits at most 30 s, so with 30 s to spare the store's first poll or check comes after the test, and
"every delivery was the watch's" now holds for the whole test. With 60 s it didn't for a run past 60 s. How fast the
watch delivers is still `BOUND`'s to check. The event-store spec's scenario says 120 s.

### D6. #452: a quiet test allows a read that follows a watch report

`test_following_a_quiet_run_reads_no_segment_while_it_waits` and its text-store sibling wait for 1.5 s without a read
(`settle`, #194), then require none for 2 s. Following reads only when the store notifies it; its lease check every
`LOGS_LEASE_CHECK_SECONDS` tries a lock and reads no segment. The store reads only on a watch report (its check is
60 s off). So any read in the window came from a report, and a report there is FSEvents reporting an earlier change
more than 1.5 s late. A full check's file I/O keeps `fseventsd` busy, which is why it failed at a 1-minute load as low
as 8 (two of four full checks on this branch). Forced with every FSEvents callback delivered 2 s late (a scratch
patch), both tests fail as #452 did; at 1 s late they pass.

The watch may report spuriously by design ("A spurious True is allowed"), so a read on a report isn't what the tests
are for. They're for "no timer": `watch_reports` records each report, and `unprompted` names any read in the window
with no report after the read before it. Checked by mutation: with reports 2 s late both now pass; with the store also
reading on a timer, every 0.5 s or every 1.8 s (slow enough to get past `settle`), both fail, the 1.8 s one on
`unprompted`.

Alternatives: a longer `settle`. Rejected: no settle outlasts an OS that reports arbitrarily late, and the test would
still be timing the OS.

## Risks / Trade-offs

- [The cause of #448 isn't observed directly] → It can't be without load. D3's reading and the existing check test rule out troupe;
  the test's failure message now names the wait it gave up after, so a failure past 35 s would point at the store.
- [A failing #448 run now takes up to 35 s per delivery] → Only when a delivery is late; a passing run is unchanged.
