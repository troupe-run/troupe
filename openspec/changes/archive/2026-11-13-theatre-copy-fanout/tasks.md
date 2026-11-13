# Tasks

## 1. Start

- [x] 1.1 Set troupe#408's card to In Progress on the troupe roadmap board, and verify with
  `gh issue view 408 -R troupe-run/troupe --json projectItems`

## 2. The test that fails first (design D2)

- [x] 2.1 In `test_theatres.py`, add the test that two fresh builds of `committed()` with commit times 1700000030 and
  1700000000 (fixed through `gitrepo.AUTHOR`) look the same to `_observed()`, after asserting its premise: different
  fan-out directory counts, the same loose object count. Run it on today's `_observed()` and verify the premise holds
  and the equality fails on the fan-out directory count (record the output)

## 3. The comparison (design D1, D3)

- [x] 3.1 Change `_observed()` to count loose objects and empty fan-out directories, not fan-out directories. Verify
  2.1 now passes, and so do the three `test_a_copy_shows_git_what_a_fresh_build_of_its_shape_shows` cases
- [x] 3.2 Add the strictness tests (D3): a copy with a fixed blob's loose object removed, with `refs/heads/main`
  removed, and with an empty `objects/00` made, each compares unequal to a fresh build. Verify each fails when its
  alteration is taken out (so each one checks what its name says), then passes with it
- [x] 3.3 Run `test_theatres.py` in full, then `uv run scripts/check.py`, keeping the full log in the scratchpad
- [x] 3.4 Check the load (`uptime`, 1-minute under ~40), then run `scripts/flake_hunt.py` on `test_theatres.py` with
  `--load 2` at most, and record rounds and failures for the pull request

## Workflow follow-up

- Draft pull request closing #408; act on Claude's review; mark ready; archive on the branch; the owner merges.
- After the merge: #408 closed and its card Done.
