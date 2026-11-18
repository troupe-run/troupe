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
- The other watched-delivery tests' 10 s waits. In `test_processes.py` they are set up with a 60 s check so that "every
  delivery inside the 10 s waits was the watch's", which is their property. None has failed this way yet.
- #450 (order log duplicates), found on the way and owned by its own change.

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
The new test in D4 forces the remaining case, a report the OS drops, and shows the store recovers at its check.

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

### D4. A store-level test of the backstop

`test_processes.py` gets a backend wrapping a `Manual` one that drops exactly one report after the watch has reported
others. With a short check (0.5 s), the dropped event must reach the listener by the check, and the store must not say
it's polling. This is the path #448's wait now covers, tested without load or timing luck.

## Risks / Trade-offs

- [The cause of #448 isn't observed directly] → It can't be without load. D3's reading and D4's test rule out troupe;
  the test's failure message now names the wait it gave up after, so a failure past 35 s would point at the store.
- [A failing #448 run now takes up to 35 s per delivery] → Only when a delivery is late; a passing run is unchanged.
