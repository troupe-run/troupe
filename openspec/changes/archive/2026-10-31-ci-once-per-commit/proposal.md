# Proposal: CI runs the matrix once for each version of the code that matters

## Why

troupe's 12-leg matrix (3 OSes × 4 Pythons, about 10 to 15 minutes) runs twice on code that doesn't need it. On a
push to `main` it reruns the exact commit the merge queue has just passed: #198, #200 and #201 each did, measured
2026-10-30. On each push to a pull request, it runs alongside Claude's review, so when the review finds something,
the legs ran on code that is about to change. The Free plan's concurrent-job limit, macOS above all, makes parallel
sessions wait on each other's runners for these repeats.

troupe-run/infrastructure#227 decided both fixes (owner, 2026-10-30), for troupe, infrastructure and website. This is
troupe's part, #204. Infrastructure's own part, #232, has landed: its `ci.yml` and `docs/development-workflow.md`
already work this way, and the delivered `claude-review.yml` no longer reviews on `ready_for_review`.

## What Changes

- **A push to `main` skips the legs when the merge queue passed that commit.** `changes` runs on a push too, asks
  whether CI's `merge_group` run on `github.sha` succeeded, and answers `scope=none` if so. `check` then passes and the
  run is green. A commit that reaches `main` any other way, such as the App's guard deliveries, runs everything, as
  today, and so does a lookup that fails. This replaces ci-check-scope design D5 ("main runs everything after every
  merge"), whose reason predates the queue.
- **A draft pull request runs no legs.** `changes` answers `scope=none` on a draft, and `ready_for_review` joins the
  `pull_request` types, so marking a pull request ready runs what its paths need.
- **A draft's `check` can never count as passed.** `changes` narrows a push to what changed since the previous head
  when that head passed `check` (ci-check-scope D1). If a draft's `check` read as passed, the first run after ready
  could be narrowed to a single push. So on a draft the `check` job doesn't run at all, and D1 picks the latest `check`
  on the previous head explicitly, by when it started, instead of trusting the API's order.
- **`changes`' condition widens from pull requests to everything but a merge group.** `scripts/tests/test_ci_workflow.py`
  keeps a merge group running the full check, unskippable and unnarrowed (ci-on-merge-queue D1), and pins the new
  draft and push answers.
- **CLAUDE.md's pull request steps** say what infrastructure's `docs/development-workflow.md` now says: open a pull
  request as a draft, act on the review, and `gh pr ready <n>` once the review of the last push is clean.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `quality-check`: a push to `main` the merge queue passed skips the legs; a draft runs no legs and reports no `check`;
  marking ready runs what the whole pull request needs; a draft's `check` never narrows a later push; `check`
  reports on every ready pull request, merge group and push to `main`.

## Impact

- `.github/workflows/ci.yml`: the `pull_request` types, `changes`' condition, permissions and three answering steps,
  `check`'s condition, and the header comment.
- New `scripts/queue_passed.py` and `scripts/tests/test_queue_passed.py`, adapted from troupe-run/infrastructure's,
  listed in `scopes.scripts` in `scripts/check-paths.toml`.
- `scripts/check_range.py` (the `ready_for_review` action, and choosing the latest `check` on the previous head),
  `scripts/check_result.py`'s wording for a skip, and their tests. `scripts/tests/test_ci_workflow.py`.
- `CLAUDE.md`, steps 4 and 5.
- No change to troupe's required checks, the guard, or any delivered file. The Purpose of `quality-check` is
  unchanged, so infrastructure's `oob/troupe-spec-purposes.json` needs no update.
