# Proposal

## Why

Stopping a text-store subscription doesn't stop its thread (#97). `_Subscription.stop()` sets `_stopped` and closes
the watch, then returns without waiting. The thread's start-up `store._deliver()` doesn't check `_stopped` either. A
thread that hadn't reached it yet still runs it after `stop()` has returned, and that delivery can rebuild the order
projection, which writes a file under `.troupe/local/order/`. On PR #93's macOS 3.13 run this raced
`TemporaryDirectory.cleanup()`: rmtree failed with `Errno 66 Directory not empty`, and the thread failed on a temp
file rmtree had deleted.

The test only shows the symptom. The underlying problem is that once a subscriber has stopped listening, nothing
guarantees the store is quiet, for example before a theatre is deleted or moved, or before the process exits. The
event-store spec says when a subscription delivers but says nothing about when it stops.

## What Changes

- **After `unlisten` returns, the subscription doesn't read or write the store.** The thread checks `_stopped`
  before every store action, under the store's lock, including the start-up delivery. `stop()` sets `_stopped` with
  that lock held, so a delivery is either finished before `stop()` can run, or sees the flag and does nothing.
  That's an exact guarantee, not just a smaller window (design D1).
- **After `unlisten` returns, the subscription's thread has ended**, and with it the watch handles it opened. The
  store waits for the thread after releasing its lock, so the wait can't deadlock against a delivery (design D2).
- **The wait is bounded and announced.** Once it has lasted the store's lock-announce interval, the wait is reported
  through the store's `on_wait`. If it reaches `SUBSCRIBE_STOP_TIMEOUT_SECONDS` (a new named setting, default 5 s),
  `unlisten` fails with a new error, `events.subscription-not-stopped`, which names the events directory and how
  long it waited. It never returns quietly while the thread may still be running (design D3).
- A test reproduces #97 deterministically: the thread is held before its first delivery, the subscription is
  stopped, and the test checks that the thread has ended when `unlisten` returns and that nothing under `local/`
  changes afterwards. It fails on `main`.
- `docs/event-store.md`, `troupe.core.defaults`, the error registry and `protocol/schemas/error.schema.json` gain the
  new setting and error.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `event-store`: a new requirement that a stopped subscription leaves the store alone and its thread has ended, with
  a bounded, announced wait. "Store limits are named settings" now lists the stop wait among the store's limits.

## Impact

- `packages/troupe-store-text/src/troupe_store_text/store.py`: `_Subscription` (the stop check on every store action,
  `join`) and `TextStore.unlisten` (the wait after the lock is released, its announcement and its error). `TextStore`
  and `shared_store` take a `stop_timeout` that defaults to the new setting.
- `packages/troupe/src/troupe/core/defaults.py`, `packages/troupe/src/troupe/core/errors.py`,
  `protocol/schemas/error.schema.json`, `docs/event-store.md`.
- `packages/troupe-store-text/tests/`: new tests for the stop guarantee and the bound.
- The store port and the eventsourcing subscription API are unchanged. `unlisten` can now block, for milliseconds in
  practice and never longer than the bound, and can raise the new error.
- Closes #97. Not related to #96.
