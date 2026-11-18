# Tasks

## 1. #446: a change between waits, checked with a zero timeout

- [ ] 1.1 Rewrite `test_a_change_made_while_nobody_waits_is_reported_by_the_next_wait_at_once` in
  `packages/troupe/tests/test_platform_watching.py` as design D2 says; verify it passes on its own
- [ ] 1.2 Verify it rides out late delivery: with the first two backend reports held back past the zero-timeout wait
  (a scratch patch, not committed), the new test passes and the old one fails
- [ ] 1.3 Verify it still catches a blocking wait: with every backend wait delayed 0.3 s before reporting (scratch
  patch), the new test fails once the budget is spent (budget shortened for the check)

## 2. #448: the port test waits as long as the store's backstop

- [ ] 2.1 Add the store-level test of design D4 to `packages/troupe-store-text/tests/test_processes.py`; verify it
  passes, and fails with the check disabled (check_seconds=60, scratch)
- [ ] 2.2 Replace `heard.wait(10)` in `test_event_subscription.py` with the named wait of design D3; verify the test
  passes on its own
- [ ] 2.3 Verify the port test now survives one dropped report: with the store's watch dropping one report (scratch
  watcher), the new wait passes and the old 10 s one fails

## 3. Integration

- [ ] 3.1 `uv run scripts/check.py` passes (run when the 1-minute load is under 40)

## Workflow follow-up

- Draft PR closing #446 and #448; act on the review; archive on the branch before merge.
