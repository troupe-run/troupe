# Tasks

## 1. Baseline, before any code changes

- [x] 1.1 Make a detached baseline worktree at this change's base commit, outside the repository (in the scratchpad), and run `uv sync` there. Verify with `git -C <baseline> rev-parse HEAD` matching the base.
- [x] 1.2 Install the spike's spawn counter and a `_current()` reason logger (design D3) as an opt-in `.pth` in each worktree's `.venv`, active only while a flag file exists, and check none of it is tracked: `git status --short` shows nothing new.
- [x] 1.3 Tell the owner the timing runs are starting. Then, with load under 20, run the baseline suite (`-n 3`, fresh `--basetemp`, `--durations=0`) with both loggers on, and save the git process counts by command and the miss reasons (with `same`/`moved`) to the scratchpad. Verify the run passes and the totals for the three branch and HEAD commands are close to the spike's 8716.
- [x] 1.4 Run a real `troupe perform` with the scripted runner in a fresh theatre (as in `docs/opening-night/first-performance.md`) with the reason logger on, and save its counts: reads, reasons, `same`/`moved`, adapters made. Verify the perform completed.
- [x] 1.5 Write the counts from 1.3 and 1.4 into design.md's D5, decide which of D5's cuts they justify, and record the decision there. A cut that touches #75's racy rule or the watched files goes to the owner, with the counts, before any code depends on it. Verify `openspec validate git-call-latency --strict` passes, and commit.

## 2. `run_to_completion` returns when the command ends (#360)

- [x] 2.1 Write the tests first (design D2), in `packages/troupe/tests/test_platform_processes.py`: the deterministic test (no `time.sleep`, every wait bounded by the next deadline), the measured test (`git --version`, 20 interleaved runs, median difference under 10 ms), overflow acted on long before the announce time, and a drain thread held between setting the event and returning still not delaying the result. Verify each new test fails on today's loop, and that the existing run-to-completion tests pass.
- [x] 2.2 Rewrite `run_to_completion`'s wait as design D1 (per-stream ended flags set before a shared event, `process.wait` bounded by the next deadline, no `time.sleep`). Verify the whole of `test_platform_processes.py`, `test_commands` and `test_git_adapter.py` pass locally, and `mypy --strict` and `ruff` are clean.
- [x] 2.3 Update `contributing/platform.md`'s "Short commands" paragraph to say it returns as soon as the command ends and wakes only for the output ending, overflow, the announcement and the timeout. Verify the paragraph matches the platform delta spec, and commit with `uv run scripts/check.py` passing.

## 3. One git process per re-read of the branch and HEAD (#361)

- [x] 3.1 Write the differential property test first (design D4) in `packages/troupe-vcs-git/tests/test_git_state_cache.py`: generated sequences of commits, switches, detaches, orphan branches, tags and remote refs named after the branch (including `refs/remotes/<name>`), branches named `heads/…` and `tags/…`, and a file named `HEAD`, with both ref storages, comparing the adapter with git's own `symbolic-ref --quiet --short HEAD` and `rev-parse --verify --quiet HEAD` after each step. Verify it passes on today's three-command read.
- [x] 3.2 Write the command-count tests from the vcs delta spec: a re-read on a branch and on a detached HEAD runs one command; an unborn HEAD reports its branch and no commit; a repository git refuses to read raises vcs.failed naming the command. Verify the one-command tests fail on today's read and the others pass.
- [x] 3.3 Change `GitAdapter._current()` to read with `git rev-parse HEAD --symbolic-full-name HEAD --abbrev-ref=loose HEAD --`, falling back to today's three commands when it fails (design D4), keeping stat-then-read. Verify 3.1, 3.2 and every existing test in `packages/troupe-vcs-git/tests` pass, including all four `TestMoves…` layouts.
- [x] 3.4 Make the cuts recorded in 1.5, if any, each with a test that fails without it and passes with it. Verify the test results, or, when 1.5 recorded no further cut, that design.md says why.
- [x] 3.5 Update the module docstring and `contributing/platform.md`'s cache paragraph to say a re-read runs one command once HEAD has a commit, and update the vcs spec citation in the docstring if it changes. Verify the docs match the vcs delta spec, and commit with `uv run scripts/check.py` passing.

## 4. Measure after and record

- [x] 4.1 With load under 20, run the suite on the change and on the baseline, interleaved (baseline, change, baseline, change at least), each with `-n 3`, a fresh `--basetemp` and `--durations=0`, and with the spawn counter on for one run of each. Verify every run passes, and save wall time, worker time and git process counts.
- [x] 4.2 Measure one call's cost: `git rev-parse HEAD` 200 times through `subprocess.run`, the baseline's `run_to_completion` and the change's. Re-run 1.4's `troupe perform` on the change and count its git processes. Verify the numbers are saved.
- [x] 4.3 Write a "Measured" section in design.md with 4.1 and 4.2's numbers, the before and after counts of the three branch and HEAD commands, and perform's counts. Verify `openspec validate git-call-latency --strict` passes, and commit.
- [x] 4.4 Remove the `.pth` loggers from both `.venv`s and the baseline worktree (it isn't in use by any session: check with `lsof +D` first). Verify `git worktree list` no longer shows it.

## 5. Pull request and CI

- [x] 5.1 Open a draft pull request that closes #360 and #361 (`Closes #360`, `Closes #361`), with the Measured numbers in its body. Verify `gh pr view` shows both closing references.
- [ ] 5.2 Act on Claude's review of the last push per CLAUDE.md, then mark the PR ready. Verify the Linux, macOS and Windows legs all pass on the head, including `test_platform_processes.py` on Windows, and record each leg's pytest time from the job logs against the last `main` run in the PR and in design.md's Measured section.

## Workflow follow-up

- Run `/opsx:archive` on the branch before the merge, so the PR lands code, tests and specs together.
- Ask the owner to merge through the merge queue once every check passes and every conversation is resolved.
- After the merge, check #360 and #361 are closed and their cards say Done, and comment on each with the PR and the archived change.
