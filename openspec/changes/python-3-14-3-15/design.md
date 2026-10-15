# Design

## Context

See proposal.md for why. Part 1 made the root `pyproject.toml`'s `requires-python` the single source of the
supported versions, and `scripts/python_versions.py` checks the CI matrix, every member's bound, `.python-version`
and the ruff and mypy targets against it.

To find out what breaks, a copy of `main` (ce644b1) was widened to `>=3.12,<3.16` with the matrix set to 3.12–3.15,
re-locked, and the full `scripts/check.py` run on 3.14.8 and 3.15.0 on macOS arm64. The copy's environments were
kept outside it: the copy has no `.git`, so ruff wouldn't apply `.gitignore` to `.venvs/`. The results:

- ruff, `mypy --strict` and the import contracts pass on both versions. 1702 tests pass on each.
- 1 test fails on both:
  `test_platform_processes.py::test_a_kill_sent_after_the_child_exited_but_before_asyncio_saw_it_did_not_end_it`,
  with "precondition not reached: the child did not exit within 30.0 s".
- 19 tests in `scripts/tests/` fail on any Python. They hard-code `>=3.12,<3.14`.
- 1 warning: `PendingDeprecationWarning: FileType is deprecated`, from `test_cli.py:613`.
- `uv lock` resolves. A wheel scan of `uv.lock`, which counts free-threaded `cp3Nt` wheels as not matching, finds one
  gap: `grimp` 3.17 has no `cp315` wheel for macOS arm64. `uv sync` on 3.15 built it from source.

Linux and Windows on 3.14 and 3.15 weren't run locally. CI is their first run (task 1.3).

PR #110's first CI run (38733866261) passed all 12 jobs, each on its own version:

| | 3.14 | 3.15 |
|---|---|---|
| Linux | 3.14.8: 1723 passed | 3.15.0: 1723 passed |
| macOS | 3.14.7: 1723 passed | 3.15.0: 1723 passed, `grimp` built from source |
| Windows | 3.14.8: 1721 passed | 3.15.0: 1721 passed |

Each had 4 skipped. Windows collects 1725 tests on every version, so 1721 there matches 3.12 and 3.13. None of the
3.14 or 3.15 jobs logged a warning. The macOS 3.15 job built `grimp` 3.17 with the runner's Rust toolchain and took
6m49s, against 5m6s for macOS 3.14 (D5).

## Goals / Non-Goals

**Goals:**

- Every PR checks 3.12–3.15 on all three platforms, and the bound says exactly that.
- The next version bump touches the bound, the matrix and `uv.lock`, and nothing in the tests.

**Non-Goals:**

- Free-threaded builds (`3.14t`). They're a separate interpreter, and troupe makes no claim about them.
- Making the new jobs required. That's troupe-run/infrastructure#43, after this merges.
- Replacing `argparse.FileType` handling in `parser.py`. troupe never uses `FileType`, and refusing one doesn't
  construct one, so nothing warns there.

## Decisions

### D1. The bound and the matrix move in one commit

Part 1's check fails if either moves alone, so they change together, with `uv lock` in the same commit. The lock
changes only by gaining the 3.14+ wheels and `resolution-markers` that Part 1 dropped.

### D2. The race test's exit watcher is chosen by `os.waitid`, not by platform

Since 3.14, asyncio's `_ThreadedChildWatcher` calls `os.waitid(pid, WEXITED | WNOWAIT)` in its thread, then reaps
with `waitpid` on the loop thread "so that reaping and notification are atomic". In 3.12 and 3.13 the thread reaped
directly. The test blocks the loop deliberately, so on 3.14 the exited child stays a zombie. The macOS helper polls
`kill(pid, 0)` until the pid disappears, and a zombie never disappears, so the helper times out.

The Linux helper already does the right thing on any POSIX system that has `os.waitid`. It polls
`waitid(P_PID, pid, WEXITED | WNOWAIT | WNOHANG)`. A status means the child exited and nothing has reaped it, the
3.14 case. `ChildProcessError` means a watcher thread reaped it, the macOS 3.13 case, which only an exit allows. So
the helper is chosen by `hasattr(os, "waitid")`:

| Platform and Python | `os.waitid` | Who reaps | Helper |
|---|---|---|---|
| Linux, any | yes | pidfd watcher, on the loop | `waitid` (unchanged) |
| macOS 3.12 | no | watcher thread | `kill(pid, 0)` (unchanged) |
| macOS 3.13 | yes | watcher thread | `waitid`: sees `ChildProcessError` |
| macOS 3.14, 3.15 | yes | the loop, after `waitid(WNOWAIT)` | `waitid`: sees the zombie's status |
| Windows | n/a | n/a | process handle (unchanged) |

Only the test helper changes. The seam's `is_running` is still documented as unable to see zombies
(`docs/platform.md`), and nothing in the seam relied on who reaps.

*Alternatives:* skipping the test on 3.14 and later (it would stop proving the race on the versions where the reap
moved), or a kqueue `NOTE_EXIT` watcher on macOS (more code, for what `waitid` already gives).

### D3. Part 1's script tests read the bound from the repository

`test_python_versions.py` and `test_on.py` assume `>=3.12,<3.14`, the list "3.12 and 3.13", and 3.15 as the
unsupported version. Instead:

- `BOUND = python_versions.bound(REPO)` and `SUPPORTED = python_versions.supported(REPO)`. Expected messages are
  built from them, and from fixed strings for the parts that aren't the bound.
- The unsupported version is one past the highest supported. The "widen together" test widens to two past.
- The matrix line to replace is built from `SUPPORTED`.

Tests that need a specific malformed value still name it literally (`~=3.12`, `"3.13.1"`). The hypothesis tests
don't depend on the bound.

*Alternative:* edit the literals to 3.16 now. That's the same breakage at the next bump, and the bump is exactly
what Part 1 meant to make mechanical.

### D4. The `FileType` test expects the warning from 3.14 on

`test_declared_refuses_an_argument_the_checks_cannot_read[file-type]` constructs `argparse.FileType("r")` to prove
`parser.py` refuses it. On 3.14 and later the construction is wrapped in `pytest.warns(PendingDeprecationWarning)`.
That asserts the deprecation instead of hiding it, so the test notices if the warning changes kind or `FileType` is
removed. On 3.12 and 3.13 it's constructed as today.

### D5. `grimp` builds from source on the macOS 3.15 jobs

GitHub's macOS images include a Rust toolchain, and `uv` builds the sdist once per cache key, with setup-uv's cache
enabled. If the build fails in CI, the options are: pin a `grimp` with a 3.15 macOS wheel if one exists by then,
install Rust in that job, or ask the owner. 3.15 isn't quietly dropped from macOS (#104).

## Risks / Trade-offs

- **Linux and Windows on 3.14 and 3.15 are untested until CI runs.** → Task 1.3 is a full CI run. Any failure there
  is investigated before the PR is ready, and recorded here.
- **12 jobs double CI time per PR.** → Accepted. #104 asks for every PR to run on all four versions on all three
  platforms.
- **The macOS 3.15 job is slower** while `grimp` builds from source, until a wheel ships or the cache is warm.
- **The first release will publish the cap `<3.16`.** Supporting 3.16 then needs a release that raises it, and
  Part 1's check keeps that from being forgotten.

## Migration Plan

Merge. Then infrastructure#43 adds the six new job names to `tofu/required-checks.json`. Nothing to roll back
beyond reverting the commit.
