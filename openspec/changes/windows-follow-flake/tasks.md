# Tasks

## 1. Reproduce #227 on demand

- [ ] 1.1 Make design D6's slow-stretch edit (temporary): in `logs`' follow loop in `packages/troupe/src/troupe/core/runs/queries.py`, sleep 1 s before each re-read after a wake, for the first 8 s of following. Verify: on the unchanged test, `uv run pytest packages/troupe/tests/test_run_queries.py -k timed_from_when_the_append_returned` fails on `delays[1] < 0.5` with every delay about 1 s or more, as CI did. Record the output here, and keep the edit for 3.2

## 2. A bound for the sampling helper

- [ ] 2.1 Add design D3's case to `packages/troupe/tests/test_storetesting.py`: with `bound=1.0`, deliveries of 0.5 s stop sampling at five. Verify: `uv run pytest packages/troupe/tests/test_storetesting.py` fails, because `watched_delays` takes no `bound` yet
- [ ] 2.2 Give `watched_delays` in `packages/troupe/tests/storetesting.py` a `bound: float = BOUND` and use it in the loop; add `FOLLOW_BOUND = 0.5` beside `BOUND`, with the docstring design D2 describes (the store's 0.25 s plus following's own hops, the bound the spec already promised, and #227's 0.17 s and 0.18 s first deliveries). Verify: `uv run pytest packages/troupe/tests/test_storetesting.py packages/troupe/tests/test_event_subscription.py packages/troupe/tests/test_platform_watching.py packages/troupe-store-text/tests/test_processes.py` passes

## 3. The handshake and the test

- [ ] 3.1 In `packages/troupe/tests/perform_child.py`, read `TROUPE_TEST_SHOWN` (design D5). When it's set, `Announcing.send` waits after each event update, polling the file every 10 ms until it lists the update's seq or says `stop`. After `stop`, it never waits again. If `WITHIN` passes first, it prints `UNSHOWN <seq>` and never waits again. The child raises its run's `run_timeout` to `SLOW_STRETCH_SECONDS + 2 * WITHIN` plus the default. Update the module docstring. Give `Child` in `test_run_queries.py` a `shown: Path | None` that sets the variable, merged with `TROUPE_TEST_STOP` when both are given. Verify: `uv run pytest packages/troupe/tests/test_run_queries.py` still passes (no test sets it yet), and ruff and `mypy --strict` are clean on both files
- [ ] 3.2 Rewrite and rename the test as `test_following_shows_each_event_before_another_process_records_the_next_the_fastest_under_the_bound` (design D1, D2, D4, D7). The script is `INIT`, then `5 + ceil(SLOW_STRETCH_SECONDS / FOLLOW_BOUND) + 1` turns, then `OK`, with no waits. `monkeypatch` `defaults.LOGS_LEASE_CHECK_SECONDS` to 60. Follow with `QUIET` in a background thread (`follow_in_background`), with `send` queueing each event's seq and receive time. Show seq 0, then sample with `watched_delays(measure, bound=FOLLOW_BOUND)`, then write `stop`, join the follower and finish the child (writing `stop` and killing the child in a `finally`). Assert:
  - the child ended `succeeded` and printed no `UNSHOWN`;
  - the followed seqs are every seq in order;
  - each measured event was received before the child appended the next;
  - the fastest delay is under `FOLLOW_BOUND`, and the median of the first five is under `FOLLOW_BOUND + STALL_SECONDS`.

  Every delay goes in the messages. Verify: `uv run pytest packages/troupe/tests/test_run_queries.py -k before_another_process_records_the_next` passes 10 times in a row (a shell loop), each in under 5 s on a quiet machine, measuring five. Then, with 1.1's edit still in place, it passes, measuring more than five (shown by a temporary print); record the count here, and revert the edit
- [ ] 3.3 Run design D6's edits 2 to 4 (temporary), one at a time, against the new test. Verify, recording each result here: (2) a held event: fails naming seq 1; (3) a timer-driven follower: fails naming seq 1, and passes with D4's patch removed; (4) a steady 2 s delay: fails on the fastest delay after about 60 s, listing every delay. Then revert every edit, and `git status` shows changes only in `test_run_queries.py`, `perform_child.py`, `storetesting.py`, `test_storetesting.py` and `openspec/`
- [ ] 3.4 Check nothing still names the old test or its 0.5 s median: `grep -rn "timed_from_when_the_append_returned" packages openspec/specs`. Verify: no match outside `openspec/changes/archive`

## 4. Verify

- [ ] 4.1 Run `uv run scripts/check.py`. Verify: every gate passes; record the counts here
- [ ] 4.2 Push and let CI run on Linux, macOS and Windows (#227's done-when). Verify: every leg of the run on the last code commit passes; record the run here. If the owner wants more confidence than one CI run, ask before any load run (a Windows flake hunt needs the owner's machine, as for #159)

## Workflow follow-up

- Open the PR as a draft with `Closes #227`; mark it ready once the review of the last push is clean, so CI runs on all three platforms.
- Act on Claude's review of the last push, then archive the change on the branch (`/opsx:archive`) before merging. The `runs` delta syncs at archive; no Purpose changes, so no `oob/troupe-spec-purposes.json` update.
- After the merge, comment on #227 with the PR and the archived change, check it's closed, and check its card on the roadmap board says Done.
