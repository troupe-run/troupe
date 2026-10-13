# Tasks

Group 2 builds the ctypes backends the owner chose for design D1 (2026-10-13).

## 1. The watching primitive's interface

- [x] 1.1 Add `WatchDirectoryMissingError(directory)` and `WatchUnavailableError(directory, reason)` to
  `troupe/platform/errors.py`, and `troupe/platform/watching.py` with `watch(directory)` and `DirectoryWatch`
  (`wait(timeout) -> bool`, `close()`, context manager) as in design D2, choosing the backend by platform. Verify
  `uv run scripts/check.py` passes (mypy strict, ruff, import contracts: `ctypes` stays inside `troupe.platform`)
- [x] 1.2 Write `packages/troupe/tests/test_platform_watching.py` against the interface, for every scenario in the
  platform delta: another process's append (median of five under 0.25 s, timed from when the child's append returned,
  by wall clock, design D7), another process's create, a removal, a change between waits returning at once, a timeout
  with nothing changed, 10,000 files with one appended to, `close` waking a waiting thread, a missing directory. Verify
  the tests are collected and fail only for want of a backend (record the output for the PR)
- [x] 1.3 Add the watching row, its errors and its limitations (a file system that accepts watches but doesn't
  deliver them; FSEvents being recursive) to `docs/platform.md`, and update the platform spec's Purpose so it no longer
  lists file watching as later. Verify `test_platform_docs.py` passes, including the row-per-module test

## 2. The backends (design D1 and D2)

- [x] 2.1 Linux: inotify through libc via ctypes (`inotify_init1`, `inotify_add_watch` with the D2 mask), waiting with
  `select.poll` on the fd and a self-pipe, mapping `ENOSPC`, `EMFILE` and `ENOENT` to the D2 errors. Verify
  `test_platform_watching.py` passes on Linux, plus a test that a refused watch (simulated at the OS call:
  `inotify_add_watch` returning `ENOSPC`) fails naming the directory and `fs.inotify.max_user_watches`
- [x] 2.2 macOS: FSEvents through CoreServices and CoreFoundation via ctypes (`argtypes` and `restype` on every call),
  scheduled on a private serial dispatch queue with file events, no-defer and watch-root, latency 0. The callback is
  kept referenced by the watch. Verify `test_platform_watching.py` passes on macOS, plus a test that a refused watch
  (simulated at the OS call: `FSEventStreamStart` returning false) fails naming the directory and the reason
- [x] 2.3 Windows: `CreateFileW` with backup semantics and overlapped I/O, an outstanding `ReadDirectoryChangesW`
  (`FILE_NAME | SIZE | LAST_WRITE`), and `WaitForMultipleObjects` on its event and a close event. A zero-byte
  completion (overflow) counts as a change, and the read is re-issued after each completion. Verify
  `test_platform_watching.py` passes on Windows, plus a test that a refused watch (simulated at the OS call:
  `ReadDirectoryChangesW` failing with `ERROR_INVALID_FUNCTION`) fails naming the directory and the reason
- [x] 2.4 Push the branch and verify the platform suite passes on Linux, macOS and Windows in CI, with no watching test
  skipped on any platform (record the run for the PR)

## 3. The port's guarantee, met by the text store (design D0, D3 to D5)

- [x] 3.1 Add `SUBSCRIBE_CHECK_SECONDS = 30.0` to `troupe.core.defaults`, and redefine `SUBSCRIBE_POLL_SECONDS`'s
  docstring as the fallback's interval. Add `listen` and `unlisten` to `EventRecorder` in
  `troupe/core/events/port.py`. Verify `uv run scripts/check.py` passes, which shows the text recorder still satisfies
  the protocol
- [x] 3.2 Give `TextStore` and `shared_store` a `watcher` (default `watching.watch`) and a `check_seconds`. Replace
  `_poll` with the D3 loop: the watch set up synchronously in the first `listen`, refresh on a wake, notify when the
  id grew, the nearest existing ancestor watched until `events/` exists, and the watch closed by the last `unlisten`.
  Verify `test_library_suite.py` (including the opt-in subscription case) and `test_processes.py` pass
- [x] 3.3 Add the fallback and the check (D5): `events.subscription-polling` with `details.reason` `watch-refused` or
  `watch-missed-write`, kept in `notices()` while the fallback lasts. Verify `test_notices.py` validates the new notice
  against `notice.schema.json`
- [x] 3.4 Add store tests to `packages/troupe-store-text/tests/test_processes.py`, one per event-store delta scenario:
  another process's five writes wake the listener (median under 0.25 s from the append, poll and check at 60 s); the
  first write, which creates `events/`, wakes a listener; no segment is read in 2 s of quiet (counting `scandir`
  calls); a refusing watcher falls back, gives the notice on every read, and still wakes within
  `SUBSCRIBE_POLL_SECONDS`; a silent watcher is caught within the check interval (set small) and then falls back.
  Replace `test_another_processs_write_wakes_this_processs_subscription`'s `poll_seconds=0.05`, so it no longer passes
  by polling. Verify they pass, and that the wake test fails with a watcher that never reports (record the output)
- [x] 3.5 Add `packages/troupe/tests/test_event_subscription.py` (design D0, D7): load the installed store by name
  through `troupe.core.events.port` with its defaults, subscribe, and have a child process record five events.
  Verify the median delay from the child's record call returning is under 0.25 s, that the test imports nothing from
  `troupe_store_text` or `troupe.platform`, and that it fails against the store with a watcher that never reports
  (record the output)
- [x] 3.6 Update `docs/event-store.md`: the ordering section's subscription sentence, the notices table
  (`events.subscription-polling`), the defaults table (`SUBSCRIBE_CHECK_SECONDS`, `SUBSCRIBE_POLL_SECONDS` as the
  fallback), what doesn't wake it (D4), and the layering (D0): subscribers see the port's guarantee, and watching is
  how the text store meets it. Verify `test_event_store_doc.py` and `test_platform_docs.py`'s defaults test pass

## 4. `logs --follow` waits on the subscription (design D6)

- [ ] 4.1 Remove `LOGS_FOLLOW_POLL_SECONDS` and add `LOGS_LEASE_CHECK_SECONDS = 1.0` to `troupe.core.defaults`.
  Rewrite the follow loop in `troupe/core/runs/queries.py` as D6 describes: listen through the port with an
  asyncio-bridging event, send `events.subscription-polling` as a `notice` update at the start, clear the wake before
  re-reading, re-read only when woken, check the lease on timeout, unlisten in `finally`, give each result notice once.
  Update the docstring. Verify `test_run_queries.py`'s existing follow, interrupted and cancel tests pass
- [ ] 4.2 Delete `test_following_shows_each_event_within_a_few_tenths_of_a_second_of_its_recording`. Add tests named
  for what they check: following wakes on another process's write (three events, median under 0.5 s from when the
  child's append returned, poll and check at 60 s, timed by a wrapper installed in the child helper, D7); no segment
  is read in 2 s of a quiet followed run; an unwatchable store sends `events.subscription-polling` as an update when
  following starts, includes it in the result, and still delivers each event; killing `perform` mid-follow stops
  following within `LOGS_LEASE_CHECK_SECONDS` plus the read, as `interrupted` with `run.interrupted`. Verify they pass
- [ ] 4.3 Update `docs/runs.md`: how `--follow` waits (it subscribes through the port, any polling is announced,
  the lease check) and its defaults table (`LOGS_LEASE_CHECK_SECONDS`, no `LOGS_FOLLOW_POLL_SECONDS`). Verify
  `test_runs_doc.py` and the defaults test pass, and `grep -r LOGS_FOLLOW_POLL_SECONDS packages docs` finds nothing

## 5. Integration

- [ ] 5.1 Run `uv run scripts/check.py` and the full suite locally. Verify both pass, and record the output
- [ ] 5.2 Open the PR closing #54 and verify every CI job passes on Linux, macOS and Windows for Python 3.12 and 3.13.
  Rerun the wake tests five times on each platform (a matrix rerun or a loop), so a flake like #72's shows up before
  merging. Record the delays
- [ ] 5.3 Verify `openspec validate watch-event-segments --strict` passes

## Workflow follow-up

- Run `/opsx:archive` on the branch before merging, so the PR lands code, tests and specs together.
- After the merge, comment on #54 with the PR and the archived change, and close it.
- Rebase #72 (strict-schemas) onto `main` and re-check it on all three platforms.
- The owner decides whether to retitle and reword #54 at the port, as its 2026-10-13 framing comment proposes.
- In troupe-run/infrastructure, record the platform spec's new Purpose in `oob/troupe-spec-purposes.json` and
  check `cap:platform`'s description still fits (`scripts/oob.py` reports the change once this is on `main`).
- File the Feature for the writer's per-event `git` cost (cache the branch and HEAD behind `branch_token`), as #54's
  comment set out.
