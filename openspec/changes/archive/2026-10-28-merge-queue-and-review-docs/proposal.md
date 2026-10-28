# Proposal

## Why

Two org-level workflow changes have landed in troupe-run/infrastructure, and troupe's own files don't say either yet.

- **#184.** troupe-run/infrastructure#197 turned on troupe's merge queue: `main`'s ruleset now has a `merge_queue`
  rule (rebase, all-green grouping) requiring `check`, `guard (workflow rules)` and `DCO`. Step 5 of CLAUDE.md's
  "How work happens here" says the change is archived "before merging" but not how a pull request is merged, so a
  session has nothing telling it that `gh pr merge` now queues, or when skipping the queue is allowed.
- **#185.** troupe-run/infrastructure#194 makes each finding of Claude's review a conversation tiered **must-fix**,
  **nit** or **decision**, and `main`'s ruleset needs every conversation resolved before a merge
  (`required_review_thread_resolution`). `/opsx:propose` writes each change's tasks from `openspec/config.yaml`'s
  `context`, which is troupe's own file, so infrastructure can't add the step there. Without it, no troupe change
  plans for the review, and a pull request reaches the queue with unresolved conversations.

Both are contributor-workflow text, in two files, from the same pair of infrastructure changes, so one change and one
pull request closes both (owner, 2026-10-28).

## What Changes

- **`openspec/config.yaml`'s context gains the review step** (#185), as the last item of its Working list: before
  archiving, wait for Claude's review of the last push and act on each finding by its tier. The line is
  infrastructure's current one, with its document reference qualified to troupe-run/infrastructure (design D1).
- **CLAUDE.md's "How work happens here" gains the same step** (#185, owner, 2026-10-28), as a new step 5 between the
  pull request and the archive, as infrastructure's CLAUDE.md has it. The archive and after-merge steps become 6
  and 7 (design D3).
- **CLAUDE.md's archive step says how a pull request lands** (#184): once archived, it's added to the merge queue,
  which merges it by rebase once `check`, `guard (workflow rules)` and `DCO` pass on the commit the queue tested.
  `gh pr merge <n>`, or "Merge when ready", queues it. `gh pr merge <n> --rebase --admin` skips the queue and is for
  emergencies only, such as clearing a stuck queue (design D2).

Out of scope:

- **The ruleset, the queue and the review workflow themselves.** They're infrastructure's, and already applied:
  `claude-review.yml` is delivered (5f37b3a) and the queue rule is live on `main`.
- **Rewording the rest of "How work happens here".** Steps 1 to 4 and the Guardrails section stay as they are.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. No requirement changes: CLAUDE.md and the config's context are contributor guidance, which no spec describes.
`quality-check` already requires CI to run on merge groups (ci-on-merge-queue); that's unchanged. The change sets
`skip_specs: true`.

## Impact

- Changed: `CLAUDE.md` (a new step 5, the archive step's merge text), `openspec/config.yaml` (one Working item). No code, tests or specs.
- Checks: `openspec/config.yaml` is in `check-paths.toml`'s `skip` group, so its commit needs only the OpenSpec
  part of the check. `CLAUDE.md` is in no group, so its commit runs the full check.
- Every change proposed after this merges gets a task to act on Claude's review before archiving.
- Follow-ups: comment on troupe-run/infrastructure#194 with the pull request (#185's "Done when"). Rollback: revert.
