# Proposal

Issue: troupe-run/troupe#54, with the scope the owner added on 2026-10-13 (comment 6138260158) and the framing from
the owner's discussion the same day (comment 6138502371). It lands before #72 (strict-schemas), which
is then rebased onto it and re-checked. Builds on the event store (#35, design D10) and the platform seam
(`troupe.platform`, where job objects are already reached through ctypes).

## Why

Consumers subscribe to the event store's stream, not to files. `logs --follow`, the house's live projections and
future reactions all wait on the store port's subscription, and it should deliver every new event, whoever wrote it,
as it's recorded, and say so when it can only poll. Files exist only inside the text-store adapter. Watching them is
how that adapter learns of other writers' appends; a hosted store would learn another way, such as server push.

Today the guarantee isn't met. Anything that waits for new events finds them by polling. The store's subscription
rescans every `SUBSCRIBE_POLL_SECONDS` (1 s), and `troupe logs --follow` runs its own loop every
`LOGS_FOLLOW_POLL_SECONDS` (0.1 s). Polling costs a stat of every segment per look and per follower, so it doesn't
scale to the house (#5), to theatres with many segments, or to pushed live updates (#14).

It has also made a test flaky. In #72's CI on macOS, Python 3.12,
`test_following_shows_each_event_within_a_few_tenths_of_a_second_of_its_recording` measured a median of 0.412 s
against a 0.4 s bound (`[0.368, 0.412, 0.426]`), then passed on a rerun. The delay it measures is up to 0.1 s of
follow polling plus about 60 ms of the writer's own recording after the event's `at` is stamped, about 90% of which
is two `git` subprocesses run for lineage. So the test charges recording cost to following, and a slow runner
pushes it over the bound. The flake is a symptom of not having the guarantee, so the owner chose to provide it now
rather than patch the test, before #72 lands on top of it.

The house (#63) doesn't make this a workaround. It is another subscriber, and still has to learn of writes it didn't
make: `perform` writes directly from the CLI (#14), git `pull`, `merge` and `checkout` move segments underneath troupe,
and the house is optional (#5). With the house running, CLI followers get the same messages over its socket, because
the client protocol is transport-free. Only follow-specific machinery would be thrown away, and this change has none.

## What Changes

- **The store port's subscription carries the guarantee.** It delivers every new event, from this process, another
  process or git, within a bound and without a timer. When a store can only poll, it says so with the new notice
  `events.subscription-polling`. The port gains `listen` and `unlisten`: the text store's recorder already has them for
  the library's subscription, and `troupe.core` can now reach them without importing an adapter.
- **The text store meets it with OS notification** (the rest of this list up to `logs --follow` is that adapter's
  mechanism, invisible outside it).
- **A directory-watching primitive in `troupe.platform`** that wakes a waiter when a file in a directory is created,
  grows, is replaced or is removed. It uses one OS handle per directory, however many segments the directory holds:
  inotify on Linux, FSEvents on macOS and `ReadDirectoryChangesW` on Windows. It is reached through ctypes inside
  `platform` only, the way job objects are. **Decided by the owner (2026-10-13), in the text store's design
  (D1):** ctypes rather than `watchdog`, so troupe takes no second runtime dependency. It doesn't touch the port.
- **The text store's subscription wakes on a notification.** `listen` watches the store's `events/` directory
  instead of rescanning on a timer. When the directory can't be watched (the OS refuses the watch or runs out of
  watches, or FSEvents won't start), the subscription falls back to polling every `SUBSCRIBE_POLL_SECONDS`. That is
  announced with `events.subscription-polling` (reason `watch-refused`), naming the directory, the platform's reason
  and the fix. It is never silent.
- **A watch that is accepted but never delivers is caught.** Some file systems (container bind mounts, network
  shares) accept a watch and then don't report other machines' or the host's writes, and that can't be detected when
  the watch is set up. So every `SUBSCRIBE_CHECK_SECONDS` (new, 30 s) a listened-to store looks for itself. If it
  finds a write its watch didn't report, it falls back and gives the same notice, with the reason
  `watch-missed-write`. The check stats segments twice a minute, not ten times a second.
- **`logs --follow` subscribes through the port** (`listen`/`unlisten`) instead of running its own loop.
  `LOGS_FOLLOW_POLL_SECONDS` is removed (**BREAKING** for anyone overriding it; it is pre-alpha and only `troupe`'s
  own code reads it). The fallback notice reaches a follower as a `notice` update when it happens, not only in the
  result.
- **A run that stops without recording an end is still noticed while following.** Nothing is written when `perform`
  dies, so no notification arrives. The follower checks the run's lease every `LOGS_LEASE_CHECK_SECONDS` (new, 1 s),
  which is one non-blocking try of a lock and stats no segments. Today the 0.1 s loop catches this as a side effect;
  without the loop it needs its own named bound, or following would wait forever.
- **The flaky latency test is replaced** by tests that a write by another process wakes the waiter within a bound,
  measured from when the writer's append returned, not from the event's `at`. Each runs with the fallback poll set
  far above the bound, so only a notification can pass it. They run at four levels: the platform primitive, the
  port, the text store's subscription and `logs --follow`, on Linux, macOS and Windows.

Not in scope:
- **The per-event `git` cost on the writing side** (`EventStore.lineage()` running `branch` and `head` through
  `vcs_state` for every record). It is the same whether anyone follows, so it belongs to a Feature of its own: cache
  them behind `branch_token`, as the text store already caches the branch.
- Watching hand-edited config files (#5), and the house and run server themselves (#5, #14), including the house's
  delivery to CLI followers over its socket (#63).
- Retitling and rewording #54 at the port ("Event-store subscriptions deliver other writers' events as they're
  recorded, without polling"), as the framing comment proposes. That is the owner's call and still open; this change
  is written to that framing either way.
- Waking on a branch switch that changes no file in `events/`. That isn't a new recording; the next read or
  notification sees it (design D4).

## Capabilities

### New Capabilities
None.

### Modified Capabilities
- `platform`: a new requirement for watching a directory for changes on all three platforms, failing clearly when it
  can't, with bounded resources however many files the directory holds. The capability's purpose already names file
  watching as to come.
- `event-store`: the port's subscription delivers every writer's events as they're recorded, and says so when it can
  only poll. The text store meets that with notification, and polls (announced) when its directory can't be watched
  or its watch is found to miss a write. The store's limits now include the
  check and fallback intervals, and the new notice `events.subscription-polling` is defined.
- `runs`: following subscribes through the port instead of polling, so "within `LOGS_FOLLOW_POLL_SECONDS` of being
  recorded" becomes a bound timed from the write. It also gains a bound for noticing a run that stopped without
  recording an end.

## Impact

- **Code:** new `troupe.platform.watching` (Linux, macOS, Windows backends) and its errors in
  `troupe.platform.errors`; `troupe_store_text.store` (the watcher thread, the fallback and the notice);
  `troupe.core.events.port` (`listen`, `unlisten`); `troupe.core.runs.queries.logs` (waiting on the subscription and
  the lease check); `troupe.core.defaults` (`LOGS_FOLLOW_POLL_SECONDS` removed, `LOGS_LEASE_CHECK_SECONDS` and
  `SUBSCRIBE_CHECK_SECONDS` added, `SUBSCRIBE_POLL_SECONDS` redefined as the fallback's interval).
- **Dependencies:** none added (D1: ctypes, not `watchdog`).
- **Tests:** `test_run_queries.py` loses the latency test and gains the write-wakes-the-follower and
  perform-dies-while-following tests; `test_platform_watching.py` is new; `troupe-store-text`'s `test_processes.py`
  gains wake-within-bound and fallback tests; a new port-level test loads the installed store by name and checks the
  guarantee there.
- **Docs:** `docs/platform.md` (a watching row, defaults and limitations), `docs/event-store.md` (subscription,
  notice, defaults) and `docs/runs.md` (following and its defaults). The doc-against-defaults tests check them.
- **Protocol:** no schema change. `events.subscription-polling` is an ordinary notice, sent as an existing `notice`
  update.
- **#72:** rebased onto this change after it merges, and re-checked.
