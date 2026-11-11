# Proposal

## Why

`test_a_notice_raised_before_the_start_is_recorded_straight_after_it` failed four times on Windows in the merge
queue (#380). It asserts a run's first three topics exactly: started, one notice, worktree made. On a slow runner,
looking for uncommitted changes or making the worktree can outlast `WORKSPACE_ANNOUNCE_AFTER_SECONDS` (2 s), so
troupe rightly records a second notice, `workspace.waiting`, before the worktree, and the test fails. The assertion
compares topics, so a failure doesn't say which notice arrived.

## What Changes

- The test checks the run's shape (topics with each notice's code) instead of its bare topics, so a failure names
  every notice it saw.
- It drops `workspace.waiting` notices before checking the order, as `apart_from_silences` drops a slow runner's
  `run.silent` (640bda12). The notice the test is about, `workspace.uncommitted-unseen`, must still come straight
  after the start and before the worktree.
- The test also runs with the worktree announcement due at once, so `workspace.waiting` is always recorded before
  the worktree, as on #380's slow runners. That case fails today and passes with the change.

No product behaviour changes, so no spec changes (`skip_specs: true`).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None.

## Impact

- `packages/troupe/tests/test_run_notices.py` only.
- Closes troupe-run/troupe#380. Whether #367 (git-call-latency) added to the runner's load is answered there: #367
  cut its new property tests to the size of the existing ones.
