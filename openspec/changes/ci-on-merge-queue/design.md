# Design: CI's check runs on merge queue commits

## Context

See proposal.md for why. What exists today:

- `.github/workflows/ci.yml` runs on `pull_request` and on `push` to `main`. Three jobs (ci-check-scope design):
  - `changes` has `if: github.event_name == 'pull_request'`, and answers which check the changed paths need.
  - `check-legs`, the 3 × 4 matrix, has `needs: changes` and `if: ${{ !cancelled() && needs.changes.outputs.scope
    != 'none' }}`. With `changes` skipped, the scope is empty, so the legs run, and their `check-args` is empty, so
    each runs the full check. That's how a push to `main` runs everything (D5 there).
  - `check`, `if: always()`, runs `scripts/check_result.py "$LEGS" "$CHANGES" "$SCOPE"`, which passes when the legs'
    result is `success`.
- The workflow's concurrency group is `ci-${{ github.ref }}`, with `cancel-in-progress: true`.
- No test reads `ci.yml`'s triggers or job conditions. `scripts/python_versions.py` reads its `python: [...]` line
  with a regular expression.
- `pyyaml` is in `uv.lock`, but only as a dependency of `datamodel-code-generator`. No troupe code or test imports
  it, and `types-PyYAML` isn't installed.
- troupe-run/infrastructure#169 (change `merge-queue`) will declare a queue in troupe's ruleset once `check` reports
  on merge groups. Its probe showed the guard and DCO already do.

What GitHub does on a merge group, from its docs: the queue pushes a `gh-readonly-queue/main/pr-<n>-<sha>` branch and
sends `merge_group` (activity type `checks_requested`) with `github.ref` set to that branch and `github.sha` to its
commit. `actions/checkout` checks out `github.sha` by default. A `merge_group` trigger takes no `branches` or `paths`
filter, and a `pull_request` path filter doesn't apply to it.

## Goals / Non-Goals

**Goals:**

- `check` reports on every merge group commit, with the full check on every leg behind it.
- Something that fails when a later edit would skip or narrow the check on the queue.

**Non-Goals:**

- Turning the queue on, or changing which checks are required. Both are troupe-run/infrastructure's.
- Changing what a pull request or a push to `main` runs.
- Saving the push-to-`main` run that follows a queue merge. The queue tested that exact commit, but whether to drop
  the run is a separate question with its own trade-off (a manual merge that bypasses the queue).

## Decisions

### D1: A merge group runs exactly what a push to `main` runs

Add `merge_group:` to `on`, with no `types` (GitHub's only type is `checks_requested`). Change no job. On a merge
group, `changes` is skipped by its `if`, so the legs run the full check and `check` judges them with the same script,
exactly the path a push to `main` already takes. `check_result.judge("success", "skipped", "")` already passes, and
`judge("skipped", "skipped", "")` already fails, so a merge group can't pass on skipped legs.

The concurrency group keeps working: each merge group has its own `github.ref`, so groups don't cancel each other, and
a pull request's own runs (on `refs/pull/<n>/merge`) don't cancel the queue's.

Alternative: run the scoped check on a merge group by diffing it against `main`. Rejected: a merge group is a
combination no single pull request tested, which is the reason `main` runs everything (ci-check-scope D5), and
running the full check is what makes `main` hold only combinations that passed it.

### D2: A test reads the workflow, with `pyyaml` declared

`scripts/tests/test_ci_workflow.py` parses `ci.yml` and checks the three things that, if they changed, would skip or
narrow a required check on the queue:

| Test | Fails when |
|---|---|
| CI runs on merge groups | `merge_group` isn't a trigger |
| No trigger filters by path | any trigger has `paths` or `paths-ignore` |
| Only the job that works out changed paths reads the event, and only on pull requests | `changes`' `if` isn't `github.event_name == 'pull_request'`, or any other job's `if` mentions `github.event_name` |

The third is strict on purpose: widening `changes` to merge groups, or adding an event condition to the legs or to
`check`, is exactly the edit this test exists to stop, and whoever makes it should have to come here and say why.

The tests parse YAML rather than match lines, because what they check is structure (a key under `on`, a job's `if`)
and a regular expression over YAML would pass on a commented-out line. PyYAML reads the bare key `on` as the boolean
`true` (YAML 1.1), so the test looks the triggers up under `True`, and says so in a comment.

`pyyaml` and `types-PyYAML` go into the root `dev` group, so the test doesn't depend on another package's dependency
and mypy `--strict` has the stubs. Alternative: a regular expression, like `python_versions.py`'s matrix line.
Rejected for the reason above: a single line is a fair thing to match, a job's condition isn't.

The test file is under `scripts/tests/**`, so a change to it alone runs `--scope scripts`. A change to `ci.yml` is in
no scope and runs the full check, which includes this test.

### D3: The workflow's header comment says why

The header gains a paragraph: a merge group runs everything, like `main`, because the queue lands only a commit its
required checks reported on and that commit is a combination no pull request tested; nothing may filter or narrow it,
and `scripts/tests/test_ci_workflow.py` fails if something does.

## Risks / Trade-offs

- **The trigger can't be exercised here before the queue is on.** Nothing sends `merge_group` to troupe until
  troupe-run/infrastructure declares the queue, and that waits on this change. → The test pins the workflow's shape,
  D1 reuses the path `main` already runs, and infrastructure's probe ran the same shape on a merge group. The first
  pull request through troupe's queue is the end-to-end check, and #169's change verifies it.
- **Each queue entry costs a full 12-leg run**, on top of the pull request's own run. → Accepted in #169: it's the
  price of `main` only holding tested combinations.
- **The third test is brittle by design.** A harmless rewording of `changes`' condition fails it. → That's the point;
  the failure message names the condition to keep and why.

## Migration Plan

Merge this, then comment on troupe-run/infrastructure#169 that `check` reports on merge groups, so troupe's queue can
be declared. Rollback is reverting the trigger; with no queue declared, nothing depends on it.
