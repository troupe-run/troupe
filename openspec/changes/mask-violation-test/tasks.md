# Tasks

## 1. The violation branch

- [x] 1.1 Check the phrase with the credential put back, and that the masked sentence holds the credential only inside
  markers; pin #459's example. Verify the test passes, and the whole `test_run_host.py` (114 passed)
- [x] 1.2 Verify the old assertion fails on the pinned example, and that the new one fails when the host stops masking
  the sentence (a scratch edit of `host.py`, reverted)

## 2. Integration

- [ ] 2.1 `uv run scripts/check.py` passes

## Workflow follow-up

- Draft PR closing #459; act on the review; archive on the branch before merge.
