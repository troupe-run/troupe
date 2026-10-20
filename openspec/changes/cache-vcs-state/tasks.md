# Tasks

## 1. Pin today's behaviour and reproduce the token's misses (design D7)

- [x] 1.1 Add `packages/troupe-vcs-git/tests/test_git_state_cache.py` with the helpers the later tests share: a
  repository fixture parametrised over ref storage (files, reftable) × reflogs (on, off), and the reftable rule from
  D7 test 5 (skip with "reftable needs git ≥ 2.45" when the installed git can't `init --ref-format=reftable`, fail
  when `CI` is set). Verify by running it with `uv run pytest packages/troupe-vcs-git/tests/test_git_state_cache.py`
  and seeing the matrix collected on this machine
- [x] 1.2 Add the D7 test 1 token scenarios (commit, empty commit, same-tree switch, detach, commit while detached,
  `reset --soft/--mixed/--hard`, merge, `update-ref` from a linked worktree, `pack-refs --all` then a commit). Each
  asserts that the token changed and that `branch()`/`head()` equal a fresh adapter's. Verify that on the unchanged
  adapter the token assertions **fail** exactly in the cells the design's probe table marks "no", and pass elsewhere.
  Commit them marked `xfail(strict=True, reason="#75")` in those cells, with the failure output quoted in the message,
  so `scripts/check.py` passes

## 2. The wider token and the cached state (design D1, D2, D3, D5, D6)

- [x] 2.1 In `GitAdapter`, resolve the watched paths once with the single `rev-parse --git-common-dir --git-path …`
  command from D3, and make the stat helper treat `NotADirectoryError` as missing. Add the snapshot and the private
  fresh-snapshot method from D1, with the stat-before-read order, and route `branch()`, `head()` and `branch_token()`
  through it. The branch stays `--short`'s answer (D2). Verify by removing the 1.2 xfails: every cell passes
- [x] 2.2 Update the port's docstrings in `packages/troupe/src/troupe/core/vcs.py` (`branch_token`, `branch`, `head`)
  to D5's contract, and the git adapter's module docstring to name the cache. Verify by re-reading them against the
  spec delta's three requirements, and with `uv run mypy --strict` clean
- [x] 2.3 Rename `test_the_branch_token_costs_one_git_command_per_adapter_and_none_after` to say what it now checks
  (the first token reads the state, then nothing runs while nothing moves) and re-count it per D7 test 3. Add the
  "repeated reads cost nothing" test for `branch()` and `head()`. Verify `uv run pytest packages/troupe-vcs-git` passes
- [x] 2.4 Add D7 test 2, the stateful hypothesis differential test (random sequences of the 1.2 operations plus
  `branch -m`, cached adapter against a fresh one after each step), over the whole matrix, once with a non-racy clock
  and once with the real clock and default window. Use the project's hypothesis profiles. Verify it passes, and that
  it **fails** when 2.1's ref-file stat is temporarily removed (shows it can catch a regression; revert before commit)

## 3. Racy timestamps (design D4)

- [x] 3.1 Add `GIT_RACY_WINDOW_SECONDS = 0.1` and `GIT_COARSE_RACY_WINDOW_SECONDS = 2.0` with their docstrings to
  `troupe_vcs_git/defaults.py`, matching `racy_window`/`coarse_racy_window` parameters and an injected `now` on
  `GitAdapter`, and the racy mark on the snapshot, with the window chosen from the watched files' timestamps (design
  D4). Add both settings to the git adapter's table in `contributing/platform.md`. Verify
  `uv run pytest packages/troupe/tests/test_platform_docs.py` passes, and that
  `test_following_from_another_process_sees_each_event_and_stops_at_the_end` passes again (it failed with a 2 s window
  everywhere)
- [x] 3.2 Add D7 test 4: within the window the second read runs git again; past it, no command runs; with whole-second
  timestamps (set with `os.utime`), a read past the short window but within the coarse one runs git again. Verify all
  pass, and that the first fails with the racy check disabled (revert before commit)

## 4. Recording events: cost and lineage (spec: event-store; design D7 tests 6–8)

- [x] 4.1 In `packages/troupe/tests/test_event_service.py`, add D7 test 6: recording 5 and then 50 events with the
  actor given costs the same `commands_run` delta with git (non-racy clock), and runs no subprocess at all with the
  files adapter. Verify it passes, and that on `main`'s adapter (checked out into a scratch worktree) the git case
  fails with a delta that grows with N
- [x] 4.2 Add D7 test 7: lineage after a commit, a switch, a merge and a reset within one session, with the real
  clock and default window. Verify it passes
- [x] 4.3 Add D7 test 8: a child process holding one `EventStore` records an event per stdin line while the test
  process commits, switches, merges and resets between lines, with bounded waits on the child. Every event's lineage
  matches `git rev-parse HEAD` and `git symbolic-ref --short HEAD` at that step. Verify it passes, and run it 20 times
  in a loop (`pytest --count` or a shell loop) without a failure

- [x] 4.4 In `packages/troupe-store-text/tests/test_store_git.py`, add the read-side regression for a reftable
  theatre: a store records an event on a branch, HEAD is detached, and the same store records again. The second event
  goes to a new segment whose header has no branch, as "Branch changes mid-session" requires. Verify it **fails** on
  `main`'s adapter (checked out into a scratch worktree) and passes here

## 5. Integration

- [x] 5.1 Measure what recording an event costs before and after, the way #54 measured it (the time per event over
  100 events in a git theatre, nothing moving). Quote both numbers in the PR description, and say there that the
  wider token also fixes the reftable read-side bug, with 4.4's test as evidence
  - 2026-10-20, macOS, 100 events after a warm-up, nothing moving, median of 3 runs: `main` 62.5 ms per event
    (62.5, 61.4, 64.7); this branch 3.8 ms (4.3, 3.7, 3.8). Git commands to record 5 and 50 events: `main` 12 and
    102; this branch equal (4.1's test).
- [x] 5.2 Run `uv run scripts/check.py` and verify it passes. Open the PR with `Closes #75`, and verify every CI job
  passes on Linux, macOS and Windows, including the reftable cells (not skipped) on each runner
  - 2026-10-20, PR #134: every job passed on Linux, macOS and Windows, Python 3.12-3.15. git 2.55 (Ubuntu), 2.56
    (macOS, Windows). No log mentions the reftable skip, and the reftable machines appear among the slowest tests on
    each OS. Full suite on each: 2084 passed (Linux, macOS), 2085 (Windows).

## Workflow follow-up

- Run `/opsx:archive` on the branch before merging, so the PR lands code, tests and specs together.
- After the merge, comment on #75 with the PR and the archived change, check it is closed, and check its card on the
  troupe roadmap board says Done.
