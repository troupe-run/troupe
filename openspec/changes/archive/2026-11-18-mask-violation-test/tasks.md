# Tasks

## 1. The violation branch

- [x] 1.1 Check the phrase with the credential put back, and that the masked sentence holds the credential only inside
  markers; pin #459's example. Verify the test passes, and the whole `test_run_host.py` (114 passed)
- [x] 1.2 Verify the old assertion fails on the pinned example, and that the new one fails when the host stops masking
  the sentence (a scratch edit of `host.py`, reverted)

## 2. Integration

- [x] 2.1 `uv run scripts/check.py` fails on no test this change touches: the capped run (6 workers, 480 s) failed only
  on #452's test, and the commit's own check on three watch-timing tests fixed or recorded by #458. Committed under the
  owner's one-off override (2026-11-18); CI's matrix is the passing check before merge

## Workflow follow-up

- Draft PR closing #459; act on the review; archive on the branch before merge.
