# Design: CI runs the matrix once for each version of the code that matters

## Context

See proposal.md for why. What the change works with:

- `.github/workflows/ci.yml` (ci-check-scope design, ci-on-merge-queue design):
  - `changes` runs only on `pull_request` (`if: github.event_name == 'pull_request'`). It looks up the previous
    head's `check`, asks `scripts/check_range.py` what to diff, and answers `scope` and `check-args` through `guard.py
    check-scope`.
  - `check-legs` runs unless `scope == 'none'`. With no answer (a push to `main`, a merge group, a failed `changes`),
    it runs the full check.
  - `check`, `if: always()`, runs `scripts/check_result.py "$LEGS" "$CHANGES" "$SCOPE"`. That passes when the legs
    passed, or when they were skipped because `changes` succeeded and answered `none`.
  - The `pull_request` trigger has no `types`, so it runs on GitHub's defaults: opened, synchronize, reopened.
- **D1's lookup.** `changes` reads `repos/<repo>/commits/<before>/check-runs?check_name=check&app_id=15368` and takes
  `.check_runs[0].conclusion`. That's the default `filter=latest`, which drops older runs of a check *within* a check
  suite (a rerun). Each workflow run is its own suite, though. Once a head has been checked as a draft and again
  after `ready_for_review`, it carries two `check` runs from two suites, and `[0]` is whichever the API lists first.
- `scripts/tests/test_ci_workflow.py` pins that `changes`' `if` is exactly the pull-request condition, and that no
  other job's `if` reads `github.event_name`, so nothing can skip or narrow a merge group.
- troupe-run/infrastructure#232 (its `ci-once-per-commit` design) built the same two things for infrastructure:
  `scripts/queue_passed.py` answers a push to `main`, and a three-step `changes` answers drafts and pushes through
  its existing outputs. Its CI on a draft runs `check` and has it pass (`scope=none`). Infrastructure's `changes`
  doesn't narrow by the previous head, so a passing draft `check` is harmless there. In troupe it isn't (D3).
- The delivered `claude-review.yml` already reviews drafts and no longer runs on `ready_for_review` (2588054). The
  guard allows `gh pr create --draft` and grants `gh pr ready` (infrastructure's task 1.1, same guard).
- Nothing in troupe follows CI's run on `main`. `release.yml` and the website dispatch run on the push itself, not on
  CI's result. A green run still matters for anyone reading `main`'s history.

## Goals / Non-Goals

**Goals:**
- One full matrix per commit that lands through the queue, and none on a draft.
- A draft's `check` can never let a later push be narrowed, whatever a future edit makes the draft path report.
- Every way of not knowing runs more, never less, as in ci-check-scope.

**Non-Goals:**
- Required checks, the guard, `claude-review.yml` or any other delivered file.
- A guard rule refusing `gh pr ready` while findings are open (rejected in infrastructure#227).
- infrastructure's and website's CI (#232, done; website#77).

## Decisions

### D1. A push to `main` asks for CI's merge-queue run on the commit

`changes` runs on a push and runs `scripts/queue_passed.py --repository <repo> --sha <github.sha>`. That's
infrastructure's script, adapted to troupe's outputs. It reads `gh run list --workflow ci.yml --commit <sha> --event
merge_group --json status,conclusion`. If any run completed with `success`, it prints `scope=none` and
`check-args=`, so the legs skip and `check` passes through `check_result.py`'s existing skip row. Otherwise it prints
`scope=full`. A run that's still waiting is polled every 10 seconds for up to 2 minutes, because the queue can land a
commit before its run has closed.

The issue says "a successful `check` from GitHub Actions on `github.sha`". This asks for the merge-queue *run*
instead, for infrastructure's reason (its D1). A `check` on the same sha could come from a pull request's run,
scoped or skipped, and only the queue's run always ran everything. A commit that reaches `main` outside the queue,
such as a guard delivery, has no such run and runs everything.

**It always exits 0.** A read that fails, output it can't parse, or a status it doesn't know answers `scope=full`, with
a `::warning::` naming why. A red `changes` on `main` would also run everything (D2 of ci-check-scope), but it would
leave a red job in a run whose tests passed. The script has an injected `gh` callable, so every branch has a test
without the network.

`changes` gets `actions: read` for `gh run list`, alongside `contents: read` and `checks: read`. The script goes in
`scopes.scripts` in `scripts/check-paths.toml`, beside `check_range.py`.

*Alternative:* skip `push` to `main` from the workflow's triggers. Rejected: a guard delivery would then never be
checked, and CI on `main` would stop reporting at all.

### D2. `changes` decides every event, through three exclusive steps

`changes`' condition becomes `github.event_name != 'merge_group'`, so it answers pull requests and pushes. Exactly one
answering step runs:

| Event | Step | Answer |
| --- | --- | --- |
| merge group | (no `changes`) | no answer: everything runs, as today (ci-on-merge-queue D1) |
| push to `main` | `queue_passed.py` (D1) | `scope=none`, or `scope=full` |
| pull request, draft | the draft step | `scope=none`, `check-args=`, `draft=true`, and a notice saying the legs run once it's marked ready |
| pull request, ready | D1's paths step, unchanged apart from D3 | the changed paths' answer |

The draft is read from `github.event.pull_request.draft` in the step's `if`. The job's outputs take whichever step
answered (`steps.draft.outputs.scope || steps.main.outputs.scope || steps.paths.outputs.scope`), as infrastructure's
do. `pull_request` gets `types: [opened, synchronize, reopened, ready_for_review]`. Naming any type replaces GitHub's
defaults, so the defaults are written out. A `ready_for_review` payload has `draft: false` and no `before`, so the
ready run diffs the whole pull request from its base, which is what the issue's done-when asks for.

`check_range.py` adds `ready_for_review` to the actions it accepts. It's treated like `opened`: the whole diff.

The legs' condition is unchanged. `check_result.py`'s message for a skip changes from "no changed path needs the
check" to one that's true for a push to `main` too: `changes` answered that nothing needs checking (its log says
why).

*Alternative:* conditions on each job reading the draft and the event. Rejected for the reason infrastructure gave
(its D2): several places to keep in step, and `test_ci_workflow.py` exists to stop jobs other than `changes` reading
the event.

### D3. A draft's `check` doesn't run, and D1 judges only the latest `check`

The caveat from infrastructure#227: if a draft's `check` read as passed, the first push after marking ready could be
narrowed to that push alone, though nothing ran the legs on the code before it. It happens like this:

1. A push to the draft makes head H. The draft run reports `check` on H.
2. The pull request is marked ready. The ready run on H starts. Its `check` job reports only after the legs, minutes
   later.
3. A push makes H2 before then. D1 looks up `check` on H.

Two guards make that lookup answer "not passed", each on its own:

- **On a draft, `check` is skipped.** Its condition becomes `always() && needs.changes.outputs.draft != 'true'`. A
  skipped job's check run concludes `skipped`, set by GitHub, not by troupe's code, and `check_range.py` trusts only
  `success`. On a draft that's harmless: a draft can't merge or join the queue, and the ready run reports `check`.
  If `changes` fails on a draft, `draft` is empty, so `check` runs and judges legs that ran in full.
- **D1 takes the latest `check` on the previous head, by start time.** The lookup asks for `filter=all` and passes
  the check runs' JSON to `check_range.py`. That picks the run that started last. A run with no start time counts as
  the latest. Only that one's `conclusion == "success"` lets the push be
  narrowed. So in step 3 above, H's latest `check` is the ready run's, still in progress, or the draft's `skipped` if
  the ready run's hasn't started. Either way, the whole diff decides. Once the ready run's `check` has passed, it's
  the latest, and a later push is narrowed as before.

The choice of run moves from `jq` into `check_range.py`, so it has tests: the latest decides; an older success
behind a later failure, skip or unfinished run doesn't count; a run with no start time decides; and JSON that isn't
the check-runs shape is refused, naming it. The script's fifth argument becomes the path of that JSON, or empty when
nothing was looked up. A refusal fails `changes`, and the legs run the full check, as a malformed sha does today.

`test_ci_workflow.py` pins both guards: `check`'s condition reads the draft answer, the draft step answers
`draft=true` and `scope=none`, and D1's lookup asks for every check run. A broken copy of each is named, as the
existing cases are.

*Alternatives:*
- `check` runs and passes on a draft, as in infrastructure. Rejected: it's exactly the state the caveat warns about,
  and it would leave D1 depending on the order the API lists two suites in.
- `check` fails on a draft. Rejected: a red required check on every draft reads as broken.
- Rename the draft's result job so no `check` exists on a draft. Rejected: the required check would sit at "Expected"
  on every draft, and D1 would still read an unordered list after ready.
- Ask the previous head's workflow run whether it was a draft. Rejected: the run doesn't record it, and finding out
  through its jobs and steps is several more reads, each a way to fail.

### D4. `test_ci_workflow.py` keeps the merge group whole

The test's pull-request-only condition becomes `github.event_name != 'merge_group'`. The rule stays the same: only
`changes` reads the event, and its condition must keep merge groups out. New pins, each with a broken copy:

| Pin | Fails when |
| --- | --- |
| `pull_request` types | `ready_for_review` or any default type is missing |
| `changes`' condition | it lets a merge group in, or confines `changes` to pull requests again |
| the draft step | it's missing, or doesn't answer `scope=none` and `draft=true` |
| the push step | it doesn't run `queue_passed.py` with `github.sha` |
| `check`'s condition | it doesn't skip on `changes`' draft answer |
| D1's lookup | it doesn't ask for `filter=all` |

### D5. CLAUDE.md says what infrastructure's workflow doc says

Steps 4 and 5 of "How work happens here" take infrastructure's shape: a **draft** pull request closes the issue
(`gh pr create --draft`), and Claude reviews it while CI's legs wait. Once the review of the last push leaves no
must-fix or decision open, mark it ready with `gh pr ready <n>`, which runs the legs and starts no review. Step 5's
note about re-running the review is brought in line too: the review now judges a reply when it's posted
(review-judge-reply-on-post, delivered), so the re-run is for a review run that failed.

## Risks / Trade-offs

- [A flake the duplicate run on `main` used to catch by accident goes unseen] → Accepted in infrastructure#227. #201's
  `main` run caught #159's Windows flake that way. Flake hunting is done on purpose, under #168.
- [The queue's commit isn't the one that lands, if GitHub's merge method changes] → No merge-queue run exists on the
  landed sha, so `main` runs everything. It costs time, never a skipped test.
- [An agent marks ready before the review is clean] → It costs a run of the legs. A draft can't merge, and the
  ruleset refuses a merge with an open conversation.
- [The first push after marking ready runs the whole diff, though it could have been narrowed] → Only when it arrives
  before the ready run's `check` reports. Running more is the safe side of D3.
- [The ready run starts a few minutes after a clean first review] → Accepted in infrastructure#227. It saves the most
  when the review has findings, which has been most pull requests.
- [`queue_passed.py` is a copy of infrastructure's] → It isn't delivered, because its outputs differ per repository
  (troupe has no `guard` answer). Its header names the source, so a fix there can be carried here.
- [`changes` now runs on every push to `main`] → About 20 seconds, and up to 2 minutes when the queue's run is still
  closing. A full matrix it saves takes 10 to 15 minutes.

## Migration Plan

This pull request shows each case on its own runs. A pull request runs its own `ci.yml`:

1. Open it as a draft. CI: `changes` answers draft, no leg runs, `check` is skipped, and the run succeeds.
2. Act on the review. Once it's clean, `gh pr ready <n>`: every leg runs the full check, because `ci.yml` changed.
3. Straight after marking ready, push an `openspec/`-only commit (a task tick) before the ready run's `check`
   reports. It must run the full check, not skip: that's D3 working. With D3 broken, it would narrow to `openspec/`
   and skip every leg.
4. After the queue merges it, CI's run on `main` skips the legs, `check` passes, and the run succeeds.

Step 4 can only be seen after the merge, so it's in the issue comment, not a task.

Rollback is a revert through the same path. Without `changes` on a push, `main` runs everything again. Without the
draft step, a draft runs as any pull request does.
