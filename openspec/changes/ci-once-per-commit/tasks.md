# Tasks

## 1. Check what the change relies on

- [x] 1.1 Confirm D3's reading of the check-runs API on a real troupe commit: for a recent pull request head, compare
  `gh api "repos/troupe-run/troupe/commits/<sha>/check-runs?check_name=check&app_id=15368&filter=all"` with the
  default `filter=latest`, and record here whether every run carries `started_at` and `conclusion`, including a
  skipped one (find a run with the legs skipped, such as an archive push). If `started_at` can be null on a completed
  run, say so in design D3 before task 3.1.
  Done 2026-10-31. troupe's last six merged heads each have one `check` (one suite), the same under both filters.
  efa5105 on `main` has two, from its merge-group and push suites (111252847691, 111256534054), and `filter=latest`
  returns **both**, newest first: it dedupes within a suite only, as D3 assumed. A skipped `check` (infrastructure's
  draft head d936713, run 124088533146) is `completed`/`skipped` with `started_at` set, and its `completed_at` a
  second *before* its `started_at`, so ordering by `completed_at` would be wrong and D3's `started_at` is the key.
  Every run seen carries `started_at`; the no-start-time rule stays as a safe default.
- [x] 1.2 Confirm the guard allows the pull request steps in this repository: run the guard's Claude Code hook on a
  `gh pr create --draft --body-file <file with Closes #204>` and a `gh pr ready 1` tool call, as
  `scripts/tests/test_guard_*.py` do, and record the decisions here. If either is refused, stop and raise it with the
  owner (it's infrastructure's rule, delivered).
  Done 2026-10-31 by piping a PreToolUse Bash payload into `uv run --no-project python scripts/guard.py
  claude-pre-tool-use` (troupe holds no guard tests; they're infrastructure's). `gh pr create --draft … --body-file
  <Closes #204>`: exit 0, no decision, so Claude Code's own check applies. `gh pr ready 1`: allowed and granted
  ("on the guard's allow-list"). The same create with a body that closes nothing is denied by `pr-closes-issue`, so
  the hook is deciding. No rule change needed.

## 2. A push to `main` asks the merge queue (design D1)

- [x] 2.1 Add `scripts/queue_passed.py`, adapted from troupe-run/infrastructure's (its header names the source): given
  `--repository` and `--sha`, read CI's `merge_group` runs on that commit with `gh run list`, print `scope=none` and
  `check-args=` when one completed with success, and `scope=full` and `check-args=` otherwise. Poll a waiting run
  every 10 s for up to 2 minutes. Answer `full` with a `::warning::` naming why on a failed read, unparseable output
  or an unknown status, and always exit 0. Standard library only, with an injected `gh` callable. Add it to
  `scopes.scripts` in `scripts/check-paths.toml`.
- [x] 2.2 Add `scripts/tests/test_queue_passed.py`, each test named for what it checks: a successful queue run skips;
  no queue run, or a failed or cancelled one, runs everything; a run that completes during the wait is waited for;
  one still running at the limit runs everything; a failed read, unparseable output and an unknown status run
  everything with a warning and exit 0; only `--event merge_group` runs of `ci.yml` on the given sha are asked for;
  stdout holds only `name=value` lines. Verify `uv run scripts/check.py --scope scripts` passes.
- [x] 2.3 Run it against GitHub: `python3 scripts/queue_passed.py --repository troupe-run/troupe --sha <sha>` for
  efa5105's full sha (merged through the queue) answers `scope=none`, and for 2588054's (a guard delivery) answers
  `scope=full`. Record both outputs here.
  Done 2026-10-31. efa5105: `scope=none`, `check-args=` ("the merge queue passed efa5105…, so its legs aren't run
  again"). 2588054: `scope=full`, `check-args=` ("no merge-queue run of CI tested 2588054…"). A repository that
  doesn't exist: `scope=full` with a `::warning::` naming the 404. Each exited 0.

## 3. D1 judges only the latest `check`, and accepts `ready_for_review` (design D2, D3)

- [x] 3.1 Before changing `scripts/check_range.py`, list in `scripts/tests/test_check_range.py` the behaviours that
  must stay the same (a passing previous head narrows a `synchronize`; anything else, `opened` and `reopened` take
  the whole diff; malformed shas and unknown actions are refused, naming them) and confirm they pass on the current
  code.
  Done 2026-10-31: the file already holds each one (narrowing, the whole diff for every other conclusion and for
  `opened`/`reopened`, malformed shas, unknown actions, the exit codes and argument count). All 26 pass on
  `check_range.py` as of 281ed5a, before 3.2 changes it. 3.2 keeps every case, moving each conclusion into the
  check-runs JSON it now reads.
- [x] 3.2 Change `check_range.py`'s fifth argument from a conclusion to the path of the check-runs JSON (empty when
  nothing was looked up). It picks the run that started last, counting one with no start time as the latest, and
  narrows only when that run's conclusion is `success`. JSON that isn't the check-runs shape is refused, naming the
  file and what's wrong. Add `ready_for_review` to the actions, handled as `opened`. Rewrite the tests from 3.1 on the
  new argument, and add: the latest decides; an older success behind a later failure, `skipped` or unfinished run
  doesn't narrow; a run with no start time decides; a draft's `skipped` run followed by a ready run in progress
  doesn't narrow; `ready_for_review` takes the whole diff; malformed JSON is refused. Verify
  `uv run scripts/check.py --scope scripts` passes.
- [x] 3.3 Change `scripts/check_result.py`'s message for skipped legs so it's true for a push to `main` as well as for
  skipped paths (design D2), and update `scripts/tests/test_check_result.py`. Verify it passes.

## 4. The workflow (design D1 to D4)

- [x] 4.1 In `.github/workflows/ci.yml`: write out `pull_request`'s types with `ready_for_review`. Run `changes` on
  `github.event_name != 'merge_group'`, with `actions: read`. Give it three exclusive answering steps: a draft
  (`scope=none`, `check-args=`, `draft=true`, and a notice that the legs run once it's marked ready), a push
  (checkout, then `queue_passed.py` with `github.sha`), and a ready pull request (the existing paths step, its lookup
  using `filter=all` and writing the JSON to a file for `check_range.py`). Take each output from whichever step
  answered, and add the `draft` output. Give `check` the condition `always() && needs.changes.outputs.draft !=
  'true'`. Rewrite the header comment: a draft runs nothing until ready, a push to `main` skips a commit the queue
  passed, and why a draft's `check` is skipped (D3). Verify `actionlint`, if installed, or a YAML parse of the file.
  Done 2026-10-31: `actionlint` isn't installed; the file parses with PyYAML, and 4.2's tests read its structure.
- [x] 4.2 Update `scripts/tests/test_ci_workflow.py` (design D4): the `changes` condition becomes
  `github.event_name != 'merge_group'`, and pins are added for the `pull_request` types, the draft step's answers,
  the push step's script and sha, `check`'s draft condition and the lookup's `filter=all`. Add a broken copy for
  each, and keep the existing ones, updated to the new condition. Update the module docstring. Verify the file passes
  and that each broken copy is named.

## 5. The docs (design D5)

- [x] 5.1 Update `CLAUDE.md`'s "How work happens here", steps 4 and 5: open a draft (`gh pr create --draft`); Claude
  reviews it while CI's legs wait; once the review of the last push leaves no must-fix or decision open,
  `gh pr ready <n>` runs the legs and starts no review; the review judges a reply when it's posted, and a failed
  review run is re-run with `gh run rerun <id>`. Compare it with infrastructure's `docs/development-workflow.md`
  ("A pull request opens as a draft…") and its CLAUDE.md, and verify the docs checks in `uv run scripts/check.py`
  pass.

## 6. Whole-change checks

- [ ] 6.1 Run `uv run scripts/check.py` (full) and `openspec validate ci-once-per-commit --strict`; both pass.
- [ ] 6.2 Open the pull request as a draft (`gh pr create --draft`, `Closes #204`). Verify its CI run: `changes`
  answers draft, no leg runs, `check` is skipped, and the run succeeds. Record the run link here.
- [ ] 6.3 Act on Claude's review of the last push by tier. Once nothing is left to fix, `gh pr ready <n>`. Verify every
  leg runs the full check and no review run starts. Record the run link here.
- [ ] 6.4 Straight after 6.3, before the ready run's `check` reports, push an `openspec/`-only commit (this task's
  tick). Verify `changes` reports diffing the whole pull request and every leg runs the full check, not a skip
  (design D3, Migration Plan step 3). Record the run link here.

## Workflow follow-up

- Archive the change on the branch (`/opsx:archive`), then queue the pull request (`gh pr merge <n>`).
- After the merge, verify CI's push run on `main` skips the legs, `check` passes and the run succeeds (design
  Migration Plan step 4). Record it in the issue comment.
- Comment on #204 with the PR, the archived change and that run, check it's closed, and check its card on the
  roadmap board says Done.
