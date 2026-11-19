# Tasks

## 1. The helper and its deterministic test

- [x] 1.1 Add the deterministic test (design D2) to `packages/troupe/tests/test_theatres.py`, leaving the helper as it
  is, and verify it fails at the helper's `00` assertion: `uv run pytest packages/troupe/tests/test_theatres.py -k
  "fan_out"`. Keep the failing output.
- [x] 1.2 Change `_make_an_empty_fan_out` to pick the first free prefix (design D1). Verify the new test and the three
  parametrised cases pass with the same command, and the whole of `test_theatres.py` passes.
- [x] 1.3 Commit as `test(theatres): make an empty fan-out under a prefix no object uses`, signed and signed off
  (`git commit -S -s`), with `uv run scripts/check.py` passing (asked of the orchestrator first; full output to a
  scratch file).

## 2. Pull request

- [ ] 2.1 Push the branch and open a draft pull request that closes #442 (`gh pr create --draft --body-file <literal
  path>`), with the before/after runs from 1.1 and 1.2. Act on Claude's review of the last push, and mark it ready
  once the review is clean. Verify every CI leg passes on Linux, macOS and Windows.

## Workflow follow-up

- Run `/openspec-archive-change` on the branch before the merge.
- Ask the owner to merge, through the orchestrating session "troupe" ("#442 ready to queue: …").
- After the merge: check #442 is closed and its card says Done, and comment on it with the pull request and the
  archived change.
