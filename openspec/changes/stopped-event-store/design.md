# Design

## Context

See proposal.md, Why. What exists today, in `packages/troupe-store-text/src/troupe_store_text/store.py`:

- **`TextStore.listen` / `unlisten`** run with the store's `RLock` (`_lock`) held. `unlisten` calls
  `_Subscription.stop()` when the last listener goes, then drops the subscription. Nothing waits for its thread.
- **`_Subscription.stop()`** sets `_stopped` and closes the watch. `DirectoryWatch.close()` wakes a thread blocked in
  `wait` and releases the handles once that wait has returned (`troupe/platform/watching.py`).
- **`_Subscription._run`** first calls `store._deliver()` if there is a watch, **without checking `_stopped`**. It
  then loops while `_stopped` isn't set. Inside the loop it checks the flag after a watch wait returns, but not before
  the deliveries on the polling path or at a check. `_rearm` creates a replacement watch outside the lock and only then
  checks `_stopped` under the lock. `_fall_back` and the `finally` block take the lock.
- **`TextStore._deliver`** does all its work with `_lock` held: `max_notification_id()` → `ensure_ordered()`, which
  takes the theatre's write lock and can rebuild the order projection through `replace_file` under
  `.troupe/local/order/`. That's the write that raced rmtree in #97.
- The only caller of `unlisten` is `TextSubscription.stop()` (`recorders.py`), via the recorder. It doesn't hold the
  store's lock, and the subscription thread never calls it: the thread only sets the listeners' `threading.Event`s.

The issue suggested reproducing it with `time.sleep(0.5)` at the top of `_run`. That only works if the delayed
delivery has something to write, so the reproduction in D4 records an event from a second store object after
`listen` returns. The order then needs extending when the delayed delivery runs.

## Goals / Non-Goals

**Goals:**
- After `unlisten` returns, the subscription makes no read or write of the store and delivers nothing, whatever
  point the thread had reached. This must be guaranteed by the locking, not by timing.
- After `unlisten` returns, the thread has ended and its watch handles are released. On Windows an open directory
  handle can stop the directory being deleted, so a released flag isn't enough.
- The wait for the thread is bounded, announced and fails loudly. It is never silent or unbounded.
- The existing subscription guarantees (watch-event-segments) don't change: delivery delays, polling and its notice,
  and the missed-write check.

**Non-Goals:**
- Stopping subscriptions at interpreter exit when nobody calls `unlisten`. The thread stays a daemon. A store-level
  `close()` would be a separate change if one is needed.
- The eventsourcing library's `ListenNotifySubscription` threads. Those belong to the library.
- #96 (an interrupt test's child printing from a signal handler on macOS).

## Decisions

### D1: Every store action the thread takes checks `_stopped` under the store's lock

A `_Subscription._deliver()` wrapper takes `store._lock`, returns False if `_stopped` is set, and otherwise calls
`store._deliver()`. Every delivery in `_run` goes through it: the start-up one, the polling one, the one after a watch
wakes it and the one at a check. `_rearm` checks `_stopped` before it creates a replacement watch, as well as after
(as it does now). `_fall_back` already checks under the lock.

This is exact because of the lock. `stop()` sets `_stopped` while holding `_lock`, and every store read or write the
thread makes is inside `_lock`. So a delivery that holds the lock finishes before `unlisten` can even acquire it. A
delivery that acquires the lock after `stop()` sees the flag and does nothing. The issue's concern that a check only
narrows the window applies to a check made *outside* the lock. This one is made inside it.

*Alternative: check `_stopped` at the top of `_run` only.* That narrows the window but doesn't close it, as the issue
says. Rejected.

### D2: `unlisten` waits for the thread after releasing the lock

`unlisten` decides under the lock whether this is the last listener, and if so stops the subscription and detaches it
(`_subscription = None`, `_polling = None`), as it does now. It then **releases the lock** and joins the stopped
subscription's thread. If it joined while holding the lock, a thread waiting for the lock in D1's wrapper could never
finish, so the join would wait until the bound in D3 every time.

Once stopped, the thread has nothing slow left to do. Watch waits are woken by `close()` and polling waits by the
`_stopped` event. A pending delivery returns at once (D1). The only work left is closing a replacement watch `_rearm`
may have created. So the join normally takes milliseconds.

Because the subscription is detached before the join, a `listen` that runs during the join starts a new subscription
with its own thread. The two can't interfere: the old thread can no longer act on the store (D1).

### D3: The wait is bounded by `SUBSCRIBE_STOP_TIMEOUT_SECONDS`, announced, and fails with an error

- New setting `SUBSCRIBE_STOP_TIMEOUT_SECONDS = 5.0` in `troupe.core.defaults`. `TextStore` and `shared_store` take
  `stop_timeout`, defaulting to it, as they already do for the poll and check intervals. 5 s is far above the
  milliseconds the thread needs (D2). It's there to catch something stuck, not a slow machine.
- The join is made in steps. When it has lasted `lock_announce_after`, `on_wait(events_dir, waited)` is called once.
  That's the callback the store already uses to announce a lock wait, so a surface that shows lock waits shows this
  one too.
- If it reaches the bound, `unlisten` raises `TroupeError("events.subscription-not-stopped", ...)`. The problem names
  the events directory and the seconds waited. The fix says the subscription's thread is still running, that the
  store can't be treated as quiet, and to report it as a bug with the thread's stack. `details` carries
  `{"waitedSeconds": ..., "timeoutSeconds": ...}` and `path` is the events directory. The code is added to the error
  registry with `ExitCode.FAILURE`, to `protocol/schemas/error.schema.json` as a closed entry, and to
  `docs/event-store.md`.

**Recorded assumption, open for the owner to change:** at the bound this raises rather than returning with a notice.
Under D1 a thread that outlives the bound still can't touch the store, but it may still hold a watch handle. The
caller asked for the store to be quiet, and only the thread ending proves that. The project rule is to refuse rather
than guess, and the issue asks for "an announcement if it's exceeded", so a silent return isn't an option. The
alternative, a notice and no error, isn't read by anyone who has just stopped listening. The cost: a
`TextSubscription.stop()` called from a `with` block's exit would raise this error there. That only happens if the
thread is stuck, which is a bug worth surfacing.

### D4: Tests

All tests are in `packages/troupe-store-text/tests/` (a new `test_subscription_stop.py`), on a `files` theatre unless
stated otherwise.

1. **Stopped before its first delivery** (reproduces #97 and fails on `main`): wrap `_Subscription._run` so it sleeps
   0.5 s before running. `listen`. Record one event through a second `TextStore` over the same theatre (a separate
   object, so this store hasn't ordered it). `unlisten`. Assert that no thread named `troupe-subscription` started
   by this store is alive. Snapshot every path under the theatre with its size and `mtime_ns`, wait 1 s, and assert
   the snapshot hasn't changed. On `main`, `unlisten` returns at once, and 0.5 s later the thread extends the order
   under `local/`, so the snapshot changes.
2. **Stopped while it delivers**: wrap the store's `max_notification_id` so that on the subscription thread it sets
   `entered` and waits (bounded) for `proceed`. `listen` and wait for `entered`. Call `unlisten` on a helper thread,
   and assert it hasn't returned 0.2 s later. Set `proceed`. Assert `unlisten` returns within 2 s and the thread has
   ended. This checks that a delivery in progress ends before `stop` returns.
3. **The bound**: wrap `_run` so it waits on an event the test sets only in its cleanup. Use `stop_timeout=0.5` and
   `lock_announce_after=0.1`, with an `on_wait` that records its calls. `unlisten` raises
   `events.subscription-not-stopped`. The elapsed time is ≥ 0.5 s and < 0.5 s plus 2 s. `on_wait` was called exactly
   once, with the events directory. `check_error(error.to_data())` (`protocol_schemas`) passes. The suite's
   protocol guard also validates every `TroupeError` built during a test run, and `test_errors.py` checks that the
   registry and the schema list the same codes.
4. **The library suite**: `test_library_suite._Theatre.tearDown` asserts that no `troupe-subscription` thread is alive
   before the temporary directory is removed. That turns #97's cleanup race into a named failure rather than an
   intermittent `Errno 66`.
5. **Non-goals unchanged**: the existing subscription tests (`test_processes.py`: delivery delays, polling, missed
   write, first event) pass unchanged. They run on `main` before the change and after it. D1 only adds a check that
   is false while subscribed, so they can't change behaviour unless the change is wrong.

The wrappers in 1–3 are installed with `monkeypatch`, not by editing `store.py`. A sleep in the product code (as the
issue suggests) would have to be reverted, and a test that depends on a reverted edit doesn't stay in the suite.

## Risks / Trade-offs

- **`unlisten` can now block and raise.** It blocks for milliseconds in practice and never for more than 5 s. It
  raises only when the thread is stuck, which is a bug. See the recorded assumption in D3.
- **A deadlock if `unlisten` is ever called with the store's lock held** (for example from a future caller inside a
  `with store._lock:` block). The `RLock` would still be held during the join, so D1's wrapper couldn't get it. The
  bound turns that into `events.subscription-not-stopped` after 5 s rather than a hang, and the error's details point
  at the stop. No caller does this today (see Context).
- **Test 1 depends on timing**: a sleep of 0.5 s and an observation window of 1 s. On a loaded runner a slow thread
  only makes the `main` failure *more* likely to show, and the fixed code doesn't depend on the timing, because the
  join waits. So the test can't pass on a broken implementation by accident, but on `main` it could in principle miss
  the write if the runner stalls for over 1.5 s. That's acceptable for a reproduction. The guarantee itself is checked
  by tests 2 and 4.
