# Design

## Context

See proposal.md for why. What exists today:

- **The text store's subscription** (`troupe_store_text/store.py`, event-store design D10). `listen` adds a
  `threading.Event` and starts a daemon thread, `_poll`, which every `poll_seconds` (`SUBSCRIBE_POLL_SECONDS`, 1 s)
  calls `max_notification_id()`. That refreshes (a `scandir` and stat of every segment, then reads of new bytes) and
  orders, and the thread sets every listener when the id has grown. Writes in the same process set listeners
  directly (`_notify`). The thread exits once nobody listens. `TextApplicationRecorder.listen`/`unlisten` forward to
  it, and `TextSubscription` (the library's `ListenNotifySubscription`) uses them.
- **`logs --follow`** (`troupe/core/runs/queries.py`) doesn't use the subscription. It loops: send new events; stop
  if ended, cancelled or no longer `running` (a non-blocking try of the lease lock); otherwise
  `wait_for(cancel.wait(), LOGS_FOLLOW_POLL_SECONDS)` and re-read the run's history. So the 0.1 s loop is also what
  notices a `perform` that died.
- **The event-store port** (`troupe/core/events/port.py`, `EventRecorder`) has no `listen`/`unlisten`, so core can't
  reach the subscription without importing an adapter, which an import contract forbids.
- **The platform seam** already reaches Windows job objects through ctypes in `platform/processes.py`. An import
  contract allows `ctypes` (and `fcntl`, `msvcrt`, `signal`...) only in `troupe.platform`. Platform functions raise
  small exceptions from `platform/errors.py`, and core turns them into structured errors and notices with defaults
  from `troupe.core.defaults`.
- **Segments** are `events/<ULID>.jsonl` files directly in one directory (or `local/purposes/<p>/events/` for other
  purposes). They are created by a session's first write and then only appended to, each append with one handle that
  is opened, written, fsynced and closed (`platform/files.py`). git creates, replaces and deletes them on checkout,
  merge and pull. Reads create nothing, so `events/` may not exist yet.

## Goals / Non-Goals

**Goals:**
- One primitive: "wake me when something in this directory changed", with the same behaviour on all three platforms
  and a fixed number of OS handles, whatever the segment count.
- Waking costs nothing until something changes. A wake costs one refresh, which is already incremental.
- Every case where notification isn't working is announced: refused at setup, or found to miss a write later.
- Tests that can only pass if notification works, timed from the write, not from the event's `at`.

**Non-Goals:**
- Telling a waiter *what* changed. The store rescans incrementally anyway, so the primitive reports only that
  something did. That keeps every backend small: no event records are decoded.
- Recursive watching, or watching anything but the store's own segments directory.
- Reducing the writer's cost (the per-event `git` calls), which is out of scope (proposal).
- The house's delivery to CLI followers over its socket (#63). The house is another subscriber of the port. The
  client protocol is transport-free (#14), so `logs --follow` keeps the same messages when the house serves them.

## Decisions

### D0. Layers: the guarantee is the port's, the files are the text store's

From the owner's framing on #54 (2026-10-13):

| Layer | What it is | Who sees it |
|---|---|---|
| The store port's subscription (`troupe.core.events.port`) | Delivers every new event, whoever wrote it, within a bound; announces with `events.subscription-polling` when it can only poll | Everyone: `logs --follow`, the house, reactions |
| The text store's mechanism (`troupe-store-text` and `troupe.platform.watching`) | Notices appends to its segments and segments git brings in: OS notification, or a slow, announced poll as the fallback | Nothing outside the adapter |

- **Consumers name no mechanism.** Core code (`logs`) uses only `listen`, `unlisten` and `notices()` on the port. The
  notice's code doesn't name files or watching; the text store's reasons (`watch-refused`, `watch-missed-write`) go in
  `details.reason`, and another store would have its own.
- **The guarantee is tested at the port** too: a test in `packages/troupe/tests` loads the installed store by name, as
  core does, and checks that another writer's event reaches a subscriber within the bound (D7).
- **D1 to D5 are the text store's design.** A hosted store would meet the same guarantee another way (server push, for
  example) and none of them would apply to it.

The rest of the decisions are labelled by layer: D1 to D5 the text store's (with the platform primitive it uses), D6
core's, D7 the tests at every layer.

### D1. The text store's mechanism: ctypes behind `troupe.platform`, not `watchdog`

**Decided by the owner (2026-10-13): our own ctypes bindings, in `troupe.platform.watching`:** inotify on Linux, FSEvents on macOS and
`ReadDirectoryChangesW` on Windows.

What was checked (PyPI, 2026-10-13):
- `watchdog`'s latest release is **6.0.0, from 2024-11-01**. Its Linux and Windows wheels are `py3-none`: pure Python
  calling inotify and `ReadDirectoryChangesW` **through ctypes**, which is what we would write. Only its macOS wheels
  are compiled, for the FSEvents extension, and they stop at CPython 3.13 (`cp39` to `cp313`). troupe declares
  `requires-python >=3.12`, and 3.14 is already out. So on macOS with Python 3.14, installing troupe would build that
  extension from source, which needs Xcode's command-line tools.
- If the extension can't be imported, `watchdog` falls back to its kqueue observer. As far as I can tell from its
  source, that opens one descriptor per watched file, and macOS's default open-file limit is 256, against the
  benchmark's 10,000 segments. I haven't run this, so it needs confirming if `watchdog` is chosen.
- We need much less than `watchdog` offers. Its API is an observer thread per `Observer`, handlers and typed events,
  and we would discard all of it to reach "something changed". It also falls back without saying so, and our own
  announcement (D5) would still have to be written.

What ctypes costs: three small backends, and FSEvents is the largest. It needs CoreFoundation strings and arrays, a
stream, a dispatch queue and a callback. Its risk is a wrong signature crashing the process rather than raising an
error. The mitigations: every foreign function gets `argtypes` and `restype`, the platform suite runs on all three
platforms in CI, and the backends follow the job-object precedent.

Alternatives considered:
- **`watchdog` 6.0.0.** Mature and maintained, and covers all three platforms. It would be troupe's second runtime
  dependency after `eventsourcing`, with a compiled part on macOS only, for the reasons above. If the owner prefers it,
  only `troupe.platform.watching`'s backends change: D2's interface, the text store, the port, `logs` and every test
  stay the same.
- **kqueue through the standard library's `select.kqueue` on macOS (no ctypes).** A directory's `NOTE_WRITE` reports
  entries added or removed, not a file growing, so seeing appends needs a descriptor per segment. Rejected because of
  the 10,000 segments.
- **Keep polling, with a faster interval.** The cost of a look grows with the segment count and the number of
  followers (#54's "where it stands"). Rejected.

### D2. The text store's primitive: `troupe.platform.watching`

```python
def watch(directory: Path) -> DirectoryWatch:
    """Raises WatchDirectoryMissingError or WatchUnavailableError."""


class DirectoryWatch:  # also a context manager
    def wait(self, timeout: float | None) -> bool:
        """True: something changed since the last wait returned."""

    def close(self) -> None:
        """Releases the handles, and wakes a wait in another thread."""
```

- **Level-triggered.** Changes are buffered by the OS between waits, so a change made while nobody waits makes the
  next `wait` return `True` at once. A spurious `True` is allowed; a missed change isn't. When the OS reports that its
  buffer overflowed, that counts as a change.
- **What counts:** a file directly in the directory created, grown (written), renamed in or out, replaced or removed,
  and the directory itself removed. FSEvents is inherently recursive, which is a superset and harmless, because
  `events/` has no subdirectories.
- **Errors** (in `platform/errors.py`): `WatchDirectoryMissingError(directory)` and
  `WatchUnavailableError(directory, reason)`, where `reason` is the OS's wording plus what it means. For example:
  `inotify_add_watch: ENOSPC`, the user's inotify watch limit (`fs.inotify.max_user_watches`) is reached.
- **Thread safety:** one waiter at a time; `close` may be called from any thread.

Backends:

| Platform | Set-up | Wait | Close |
|---|---|---|---|
| Linux | `inotify_init1(IN_NONBLOCK \| IN_CLOEXEC)`, `inotify_add_watch(dir, IN_CREATE \| IN_MODIFY \| IN_CLOSE_WRITE \| IN_MOVED_TO \| IN_MOVED_FROM \| IN_DELETE \| IN_DELETE_SELF \| IN_ONLYDIR)` through libc | `select.poll` on the inotify fd and a self-pipe; drain the fd with `os.read` | write to the self-pipe, close both |
| macOS | `FSEventStreamCreate` on the directory's real path with `kFSEventStreamCreateFlagFileEvents \| kFSEventStreamCreateFlagNoDefer \| kFSEventStreamCreateFlagWatchRoot` and latency 0, scheduled on a private serial dispatch queue (`FSEventStreamSetDispatchQueue`), then `FSEventStreamStart` | The callback, on the queue's thread, sets a flag under a `threading.Condition`; `wait` waits on the condition | `FSEventStreamStop`, `Invalidate`, `Release`; notify the condition |
| Windows | `CreateFileW(dir, FILE_LIST_DIRECTORY, share all, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS \| FILE_FLAG_OVERLAPPED)`, then an overlapped `ReadDirectoryChangesW` (`FILE_NAME \| SIZE \| LAST_WRITE`, not recursive), kept outstanding | `WaitForMultipleObjects` on the read's event and a close event; on completion, re-issue the read | `CancelIoEx`, close the handle, set the close event |

Each backend holds a fixed number of handles: one fd and a pipe, one stream and one queue, or one directory handle
and two events. The callback that FSEvents calls is kept referenced by the watch, so it can't be collected while the
stream lives.

Latency is 0 with no-defer, so there's no coalescing delay to name as a setting. The one delay a caller chooses is
the wait's timeout.

### D3. The text store waits on a watch, not a timer

`TextStore` gains a `watcher: Callable[[Path], DirectoryWatch]` (default `troupe.platform.watching.watch`), so tests
can supply a refusing or silent one. `shared_store` passes it through. Its subscription thread becomes:

1. **`listen` sets up the watch synchronously** for the first listener, so a refusal is known (and its notice
   recorded) before `listen` returns. That's what lets `logs` send the notice as soon as following starts (D6). The
   thread is then started with the watch.
2. **Loop:** `watch.wait(timeout=SUBSCRIBE_CHECK_SECONDS)`.
   - `True`: refresh through `max_notification_id()`. If the id grew, set every listener, as `_poll` does today.
   - `False` (the check, D5): refresh. If the id grew although the watch reported nothing in the interval, switch to
     the fallback and announce it.
3. **Missing directory:** if `events/` doesn't exist yet, watch the nearest existing ancestor inside the theatre
   (`events/`'s parent, then `.troupe`, then the theatre). When that reports a change, try `events/` again. Waking
   listeners still depends only on the id growing.
4. **Stopping:** when the last listener unlistens, `unlisten` closes the watch, which wakes the thread, and the thread
   exits. A later `listen` starts again from step 1.
5. **Fallback:** today's `_poll` loop at `poll_seconds` (`SUBSCRIBE_POLL_SECONDS`), unchanged. While it runs, the
   store keeps one `events.subscription-polling` notice.

The store's own writes still set listeners directly. The watch also sees them, which causes one extra refresh and
no extra notification, because the id hasn't grown since the direct notify.

### D4. What the text store watches, and what doesn't wake it

Only the store's `events/` directory. These do wake a listener: another process's append or new segment, and git
creating, replacing or deleting segments (checkout, merge, pull). Deletion matters because it can rebuild the order.

A branch switch that changes no file in `events/` doesn't wake one, although it can change which uncommitted
segments are visible. Nothing new was recorded, so a subscription has nothing to deliver, and the next wake or read
sees the new branch. Watching the VCS's own files (`.git/HEAD`) would couple the store to an adapter's internals.
That's left to a later change if a consumer needs it.

### D5. The text store's announced fallback, and catching a watch that doesn't deliver

There are two ways notification fails, and both give `events.subscription-polling` (one code, with
`details.reason` saying which):

| `details.reason` | When | Fix |
|---|---|---|
| `watch-refused` | `watch()` raised `WatchUnavailableError`; `details.detail` carries the platform's reason | Depends on the reason. For the inotify limit: raise `fs.inotify.max_user_watches`. Otherwise: keep the theatre on a local disk. Events still arrive, up to `SUBSCRIBE_POLL_SECONDS` late. |
| `watch-missed-write` | The check found a write that the watch didn't report in the last `SUBSCRIBE_CHECK_SECONDS` | Keep the theatre on a local file system, not a container bind mount or network share. Events still arrive, up to `SUBSCRIBE_POLL_SECONDS` late. |

- **A condition notice, not a one-off:** `notices()` includes it for as long as the fallback lasts, like
  `events.other-branch`. It isn't consumed the way `events.order-rebuilt` is.
- **Why the check exists:** a file system can accept a watch and then never deliver other writers' changes, as with
  some container bind mounts. Nothing at set-up time tells us. The check is the only way to keep the issue's "never
  silent", and at 30 s it stats segments 120 times an hour instead of 36,000 (0.1 s).
- **When the check counts a write as missed:** only when the id grew, the watch reported nothing at all since the
  previous check, and it still reports nothing within a one-second grace (`_REPORT_GRACE_SECONDS`, internal to the
  text store). An event recorded just before a check can be read before its notification arrives; the grace keeps
  that from counting as a miss.
- **Nothing recorded during set-up is lost or miscounted:** the subscription delivers once as soon as its watch is
  set up, so an event recorded between the first read and the watch reaches listeners at once, rather than at the
  next check, where it would have looked like a miss.
- **No probe write at set-up:** reads create nothing (event-store spec), so we don't write a test file into `events/`
  to see whether it's reported.

Alternatives considered:
- A code naming the mechanism (`events.watch-unavailable`, this change's first draft). Rejected by D0: the notice is
  the port's, and a store that doesn't watch files would have to give a code that describes another adapter.
- A separate code per reason (`events.watch-refused`, `events.watch-missed`). One code keeps polling a single condition
  for surfaces to show; `details.reason` still tells the cases apart.

### D6. Core: `logs --follow` subscribes through the port and checks the lease

- **The port** gains `listen(event: threading.Event)` and `unlisten(event)` on `EventRecorder`. The text recorder
  already has both.
- **Bridging to asyncio:** `queries.logs` passes a small `threading.Event` subclass whose `set()` also calls
  `loop.call_soon_threadsafe(wake.set)` on an `asyncio.Event`. The store's thread then wakes the coroutine without a
  thread blocked in `to_thread`.
- **The loop:**
  1. `listen`, then read the store's notices once. Any `events.subscription-polling` is sent as a `notice` update at
     once.
  2. Send unsent events. Stop if ended or cancelled. If the run is no longer `running`, do one last read and stop,
     as today.
  3. Wait for the wake, cancel, or `LOGS_LEASE_CHECK_SECONDS`, whichever comes first. Clear the wake *before*
     re-reading, so a write during the read isn't lost. Re-read the run's history only if woken. A timeout only
     re-checks the lease (step 2), which tries one lock and stats no segment.
  4. `unlisten` in a `finally`.
- **The result's notices** are those read at the start, the store's notices at the end and the run's own notice,
  each given once (by code and path). `events.order-rebuilt` is consumed when read, so it is kept from the first read
  rather than lost.
- **`LOGS_LEASE_CHECK_SECONDS = 1.0`:** a `perform` that dies writes nothing, so no notification can say so. Today
  the 0.1 s loop notices within 0.1 s; now it takes up to 1 s. Saying "interrupted" a second late is fine for a
  person, and checks are 10 times fewer. Alternative: 0.1 s, keeping today's latency at ten lock tries a second per
  follower.
- **`LOGS_FOLLOW_POLL_SECONDS` is removed.** In the fallback, following inherits the store's poll
  (`SUBSCRIBE_POLL_SECONDS`, 1 s), so events can be up to 1 s late there instead of 0.1 s. That case is announced,
  and the interval can be overridden.

### D7. Tests that only notification can pass, timed from the write

- **Timing from the write:** the writer is a child process. Right after the store's segment append returns, a
  test-only wrapper around `troupe_store_text.store.append_bytes`, installed by the test's child helper, writes
  `time.time()` to a side file outside the theatre. The waiter records `time.time()` when it wakes. Both use the wall
  clock, because `time.monotonic()`'s reference point is undefined across processes. So the delay leaves out the
  writer's lineage and `git` cost, which the old test counted. Nothing in troupe's own code changes for this.
- **Falsifiable:** each wake test sets `SUBSCRIBE_POLL_SECONDS` and `SUBSCRIBE_CHECK_SECONDS` to 60 s, so a pass
  within the bound can only come from a notification.
- **Bounds and medians:** the primitive and the store take the median of five writes, under 0.25 s, a quarter of the
  old 1 s subscription interval. `logs --follow` takes the median of three run events, under 0.5 s, because each wake
  also reads and folds the run's history. Medians absorb one slow CI sample, the failure #72 hit.
- **Refusal on each platform:** each backend's error mapping is tested by making its OS call fail (`inotify_add_watch`
  returning `ENOSPC`, `FSEventStreamStart` returning false, `ReadDirectoryChangesW` failing with
  `ERROR_INVALID_FUNCTION`). Those tests are named "a refused … (simulated at the OS call)", because they don't
  exhaust a real limit.
- **At the port:** `packages/troupe/tests/test_event_subscription.py` loads the installed store by name through
  `troupe.core.events.port` with its defaults, subscribes, and checks that five of a child process's events reach it
  with a median delay under 0.25 s, timed from when the child's call to record returned (the port has no "append" to
  time from; the record call returns after the write, so this only shortens the measured delay). A store polling every
  second gives a median near 0.5 s, so this fails for one
  that only polls. The test knows nothing of files or watching, so it holds any store to the guarantee.
- **A silent watch:** the store is given a watcher whose `wait` never reports, to exercise the `watch-missed-write`
  path.
- **Bounded handles:** 10,000 files in the watched directory, one of them appended to. On macOS (limit 256) and
  Linux (limit 1024), a descriptor-per-file design fails this test.
- **Replaced test:** `test_following_shows_each_event_within_a_few_tenths_of_a_second_of_its_recording` is deleted,
  not renamed. Its replacement is named for what it checks: following wakes on another process's write, timed from
  the append.

## Risks / Trade-offs

- [A wrong ctypes signature crashes the process instead of raising] → declare `argtypes` and `restype` for every
  call, run the platform suite on all three platforms, and keep each backend small (D2).
- [FSEvents delays or coalesces events] → latency 0 with no-defer; the CI bound is a median, not a single sample.
- [Windows reports a size change late for a file held open] → troupe's appends close their handle each time, and git
  closes the files it writes. `LAST_WRITE` is watched too. The `SUBSCRIBE_CHECK_SECONDS` check catches what's left.
- [`ReadDirectoryChangesW` or inotify overflow their buffers under a burst] → overflow counts as a change, and the
  store rescans anyway.
- [The inotify watch limit is reached by other programs (editors, IDEs)] → `watch-refused`, with a fix naming
  `fs.inotify.max_user_watches`.
- [A file system that accepts watches but doesn't deliver them] → noticed within `SUBSCRIBE_CHECK_SECONDS` of the
  first missed write, then the announced fallback (D5).
- [A branch switch that changes no event file doesn't wake listeners] → documented (D4); nothing was recorded.
- [Interruption is noticed up to 1 s late instead of 0.1 s] → a named setting; the alternative is in D6.

## Migration Plan

No data or format changes. `LOGS_FOLLOW_POLL_SECONDS` is removed. Only troupe's own code reads it, and the
doc-against-defaults tests catch any reference left behind. #72 is rebased onto this change once it merges and
re-checked on all three platforms. Rollback is reverting the merge: the store's poll and the follow loop come back
unchanged.

## Open Questions

None. D1 was the one open decision, settled by the owner on 2026-10-13 (ctypes).
