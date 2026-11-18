# Tasks

## 1. Failing tests first

- [ ] 1.1 In `packages/troupe-store-text/tests/test_shared_theatre.py`, add probe A (pull 1..2 under E1, another
  store rebuilds to E2, record `Tracking("f", 2)`, the next read from 3 gives every event of E2) and probe B (a live
  `TextApplicationRecorder` subscription given 1..3, a rebuild, a new event: it is given every event of E2, then the
  new one). Verify both fail on this branch before any code change, and commit them only together with the fix.

## 2. The order starts after the highest id issued

- [ ] 2.1 `OrderLog`: epoch line `{"epoch", "after"}` (required, n ≥ 0), ids from `after + 1`, sequence and repeat
  checks offset by `after`, `_still_there` on the whole first line (design D2). Verify the existing order-log tests,
  the conflict and repair tests, and a test that an epoch line without `"after"` is `events.malformed-record`.
- [ ] 2.2 The issued mark `issued/<branch-key>.json` (`{"issued": n}`, atomic replace), raised by
  `defaults.ORDER_ID_RESERVE` before an append passes it, and read when an order is started or rebuilt; every new
  order's `after` is the largest of the mark, the old order's last id and the last id seen (design D3). Verify with
  tests: a rebuilt order never reuses an id, deleting the order file renumbers after the old ids, deleting the issued
  file alone loses nothing, and the mark is never below the order's last id.
- [ ] 2.3 A malformed issued file is `events.malformed-record` naming the file, with the fix in design D4; the order
  file's fix says the rebuilt order numbers after the mark. Verify with a test of each message's fix text.
- [ ] 2.4 `TextStore.notifications` from `max(low, after + 1)` and `max_notification_id` as `after + len(ids)` or
  none (design D2). Verify probes A and B now pass, and `test_library_suite.py` passes unchanged.
- [ ] 2.5 Update the `write_order` helper and every test that writes or reads an order file by hand to the new epoch
  line; extend the ordering state machine (`test_ordering_state_machine.py`) with an invariant that no id is ever
  given to a second event across rebuilds. Verify the store package's tests pass:
  `uv run pytest packages/troupe-store-text`.

## 3. Docs

- [ ] 3.1 `contributing/event-store.md`: Ordering says ids are dense until a rebuild and never reused, the local
  files list gains `issued/`, and what deleting local files does (design D4). `local.py`'s module docstring too.
  Verify by reading the rendered sections against design D2 to D4.

## 4. Integration

- [ ] 4.1 `openspec validate follower-position-epoch --strict` passes.
- [ ] 4.2 Ask the orchestrator, then run the full check (`uv run scripts/check.py`, output kept in a scratch file);
  it passes.

## Workflow follow-up

- Rebase onto main once troupe-run/troupe#457 merges; open the PR as a draft saying it's stacked until then.
- Archive the change on the branch before the merge.
