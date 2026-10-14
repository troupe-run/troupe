# Tasks

## 1. Reproduce #97 first (design D4, tests 1 and 5)

- [x] 1.1 Run the existing subscription tests on the unchanged code and record the result:
  `uv run pytest packages/troupe-store-text/tests/test_processes.py packages/troupe-store-text/tests/test_library_suite.py`.
  Verify they pass. They're the non-goal baseline that D1 and D2 must not change
- [x] 1.2 Add `packages/troupe-store-text/tests/test_subscription_stop.py` with design D4 test 1 ("stopped before its
  first delivery": `_run` delayed 0.5 s by `monkeypatch`, an event recorded through a second `TextStore` after
  `listen`, then `unlisten`, then a check that the thread has ended and the theatre's snapshot doesn't change for 1 s).
  Verify it **fails** on the unchanged code, and commit it with the failure output quoted in the message, marked
  `xfail(strict=True)` with the reason "#97" so `scripts/check.py` passes

## 2. The thread does nothing to the store once stopped (design D1)

- [x] 2.1 Add `_Subscription._deliver()`, which takes the store's lock, returns False when `_stopped` is set, and
  otherwise calls `store._deliver()`. Route every delivery in `_run` through it: the start-up one, the polling one,
  the one after a wake and the one at a check. Make `_rearm` check `_stopped` before it creates a replacement watch.
  Verify with `grep` that `_run` and the methods it calls no longer call `store._deliver()` directly, and that 1.1's
  tests still pass

## 3. Stopping waits for the thread, bounded and announced (design D2, D3)

- [x] 3.1 Add `SUBSCRIBE_STOP_TIMEOUT_SECONDS = 5.0` with its docstring to `troupe.core.defaults`, a `stop_timeout`
  parameter defaulting to it on `TextStore` and `shared_store`, and the setting to the defaults table and paragraph
  in `docs/event-store.md`. Verify `test_platform_docs.py` and the event-store doc tests pass
- [x] 3.2 Add `events.subscription-not-stopped` to the error registry (`ExitCode.FAILURE`), to
  `protocol/schemas/error.schema.json` as a closed entry with the `waitedSeconds` and `limitSeconds` details, and to
  the errors table in `docs/event-store.md`. Verify `uv run pytest packages/troupe/tests/test_errors.py
  packages/troupe/tests/test_event_store_doc.py` passes
- [x] 3.3 Change `TextStore.unlisten` to stop and detach the subscription with the lock held, then release the lock and
  join the thread in steps: call `on_wait(events_dir, waited)` once at `lock_announce_after`, and raise
  `events.subscription-not-stopped` at `stop_timeout` (design D3's problem, fix, path and details). Remove 1.2's
  `xfail` marker. Verify test 1 now passes, and that 1.1's tests pass unchanged
- [x] 3.4 Add design D4 test 2 ("stopped while it delivers") and test 3 ("the bound", including `check_error` on the
  raised error and exactly one `on_wait` call naming the events directory). Verify both pass. Verify test 2 catches
  a broken implementation: temporarily join *inside* the lock and show test 2 failing with the error from the bound
  rather than hanging. Then do the same with the D1 check removed from the wrapper, and show test 1 failing. Revert
  both and show them reverted with `git diff --stat`

## 4. The library suite proves its cleanup (design D4, test 4)

- [x] 4.1 In `test_library_suite.py`, have `_Theatre.tearDown` assert that no `troupe-subscription` thread is alive
  before the temporary directory is removed, with a message naming #97. Verify the whole module passes, and that
  with D2's join temporarily removed `test_insert_subscribe` fails on that assertion. Revert and show it reverted
  with `git diff --stat`

## 5. Check and CI

- [x] 5.1 Run `uv run scripts/check.py`. Verify every gate passes, including mypy `--strict`, ruff and the full test
  suite
- [x] 5.2 Open the PR (`Closes #97`). Verify every CI job passes on Linux, macOS and Windows, Python 3.12 and 3.13,
  for the PR's final commit, and record the run id in the PR

## Workflow follow-up

- Run `/opsx:archive` on the branch before merging.
- After the merge, comment on #97 with the PR and the archived change, and close it.
