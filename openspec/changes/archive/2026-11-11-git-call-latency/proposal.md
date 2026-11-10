# Proposal

## Why

Every git call troupe makes costs about twice what git itself takes, and most of the calls ask the same three
questions again. A timing spike on 2026-11-10/11 (branch `spike-test-time`, d55029d0, macOS) found two causes:

- `run_to_completion` checks on its child every 20 ms, so a 16 ms `git rev-parse HEAD` costs 34 ms (#360).
  Waiting on an event instead brought the suite from 426 / 408 s to 367 / 370 s wall time.
- The git adapter's branch and HEAD reads are 8716 of the suite's 22,459 git processes, three per re-read (#361).
  Nobody has counted why the cache from #75 misses that often.

Both costs land on real commands as well as on the tests: every `troupe` command that records an event reads the
branch and HEAD.

## What Changes

- `run_to_completion` returns as soon as the command has ended, instead of on the next 20 ms tick. It wakes when
  the child's output ends, on overflow, at the timeout and at the announcement, and at no other time. The timeout,
  the output limit, the single announcement and the rule that a command whose grandchild still holds its output open
  is still running are all unchanged. Overflow is now acted on at once rather than at the next tick.
- Before the git adapter's reads change, the reasons they miss the cache are counted: no state yet (a new adapter),
  the previous read was racy, a watched file changed (which one), the branch's ref changed, and whether the re-read
  then found anything different. They're counted across the whole suite and in a real `troupe perform`, and the
  counts are recorded in the design.
- A re-read of the branch and HEAD runs one git process instead of three whenever HEAD has a commit, on a branch or
  detached. An unborn HEAD keeps today's reads. The short branch name stays `symbolic-ref --short`'s answer, so what
  lineage records doesn't change (cache-vcs-state design D2).
- If the counts show re-reads that #75's rule doesn't need, those are cut too. #75's rule stays: a cached value is
  used only while the token says nothing has moved. Any change to the racy window or the watched files is a design
  decision, raised with the owner before code depends on it.
- The suite is timed before and after on macOS (3 xdist workers, a fresh `--basetemp`, runs interleaved with a
  baseline), along with the per-call cost and the git process counts, and the numbers are recorded in the design and
  on the pull request. CI's three legs give the Linux and Windows times.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `platform`: running a command to completion returns once the command has ended, with no fixed polling delay, and
  acts on overflow at once.
- `vcs`: when the git adapter has to read the branch and HEAD again, it uses one git command once HEAD has a commit.

## Impact

- `packages/troupe/src/troupe/platform/processes.py`: `run_to_completion` and `_Output`. `ChildProcess.wait`'s
  20 ms is an `asyncio.wait` timeout that returns as soon as the child exits, so it's left alone.
- `packages/troupe-vcs-git/src/troupe_vcs_git/__init__.py`: `GitAdapter._current()` and `_read_head()`, plus whatever
  the counts justify.
- Tests: `packages/troupe/tests/test_platform_processes.py` (on Linux, macOS and Windows) and
  `packages/troupe-vcs-git/tests/test_git_state_cache.py`, `test_git_adapter.py`.
- No new settings, no protocol, config or event changes, and no change to what lineage records. Spec Purposes are
  unchanged, so `oob/troupe-spec-purposes.json` in troupe-run/infrastructure needs no update.
- Closes troupe-run/troupe#360 and troupe-run/troupe#361 in one pull request.
