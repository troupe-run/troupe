# Design

## Context

See proposal.md, Why. The text on `main` before this change:

`CLAUDE.md` steps 5 and 6:

> 5. **Claude's review is acted on**, after the review of the last push: fix or answer each finding, resolve only
>    nits, and raise decisions and disputed must-fixes with the owner. The review resolves its own must-fixes once
>    they're addressed, judging a reply to one when it's posted; if that run fails, re-run it (`gh run rerun <id>`).
>    Once the review of the last push leaves no must-fix or decision open, **mark it ready** (`gh pr ready <n>`): CI
>    runs on Linux, macOS and Windows, and every job must pass. Marking ready starts no review. A merge needs every
>    conversation resolved ([development-workflow.md, "Claude's review"](…)).
> 6. **`/opsx:archive`** runs on the branch before merging, so the PR lands code, tests and specs together. **The
>    owner merges** by rebase, through the merge queue, which lands the pull request once `check`,
>    `guard (workflow rules)` and `DCO` pass on the commit it tested. Once every check passes and every conversation
>    is resolved, ask the owner to merge it. The guard refuses `gh pr merge` from an agent (`owner-only`), with or
>    without `--admin`.

`openspec/config.yaml`'s context, the last "Working" bullet:

> Before archiving, wait for Claude's review of the last push and act on each finding by its tier: fix or answer every
> must-fix and nit, resolve only nits, and raise decisions and disputed must-fixes with the owner. The review resolves
> its own must-fixes (troupe-run/infrastructure docs/development-workflow.md, "Claude's review"); after answering a
> must-fix without a push, re-run the last `claude review` run (`gh run rerun <id>`) so the review judges the reply.

infrastructure, as of 2026-11-02 (`main`):

- `CLAUDE.md` step 5: "… and raise decisions and disputed must-fixes with the owner. A must-fix fixed by a push gets
  no "fixed" reply; reply only when it needs a discussion, and then before pushing. The review resolves its own
  must-fixes once they're addressed, judging a reply to one when it's posted, and its nits once a push has fixed them,
  so a nit fixed by a push needs no reply or resolve; if that run fails, re-run it (`gh run rerun <id>`). Once the
  review of the last push has completed (the required `claude review completed` check passed; if it failed, re-run
  the run it names) and leaves no must-fix or decision open, **mark it ready** (`gh pr ready <n>`): …"
- `CLAUDE.md` step 6: "**`/opsx:archive`** runs on the branch before merging. The owner merges by rebase, through the
  merge queue." It names no checks.
- `openspec/config.yaml`: "… The review resolves its own must-fixes (docs/development-workflow.md, "Claude's review"),
  and judges a reply to one when it's posted; if that run fails, re-run it (`gh run rerun <id>`). It also resolves its
  own nits once a push has fixed them, so a nit fixed by a push needn't be resolved by hand."
- `docs/development-workflow.md`: `claude review completed` passes when a push's review and its resolving job
  succeeded, fails naming the `gh run rerun <id>` when they were cancelled or failed, and is skipped on a merge group.
- `openspec/specs/development-workflow/spec.md`, "The workflow says the review resolves a nit a push has fixed".

troupe's ruleset on `main` requires `check`, `DCO`, `guard (workflow rules)` and `claude review completed`
(`gh api repos/troupe-run/troupe/rules/branches/main`).

## Goals / Non-Goals

**Goals:**

- Both files say everything infrastructure's say about acting on Claude's review since infrastructure#208, #242 and
  #246, in infrastructure's words (#238 and #256's "Done when").
- Step 6's list of what a merge waits for matches `main`'s ruleset.
- troupe's own parts of steps 5 and 6 (the three-OS CI, "Marking ready starts no review", the queue's checks, asking
  the owner to merge) stay.

**Non-Goals:**

- Infrastructure-only parts of its step 5 (the plan posted as evidence once the owner approves the run): troupe has no
  plan.
- Changing step 6 to infrastructure's shorter wording: troupe's names what the queue waits for and what the agent
  does, which infrastructure's doesn't (`owner-merges`, design D1).

## Decisions

### D1. `CLAUDE.md` step 5

Infrastructure's step 5 sentence for sentence, with troupe's CI sentence and link kept:

> 5. **Claude's review is acted on**, after the review of the last push: fix or answer each finding, resolve only
>    nits, and raise decisions and disputed must-fixes with the owner. A must-fix fixed by a push gets no "fixed"
>    reply; reply only when it needs a discussion, and then before pushing. The review resolves its own must-fixes
>    once they're addressed, judging a reply to one when it's posted, and its nits once a push has fixed them, so a
>    nit fixed by a push needs no reply or resolve; if that run fails, re-run it (`gh run rerun <id>`). Once the
>    review of the last push has completed (the required `claude review completed` check passed; if it failed, re-run
>    the run it names) and leaves no must-fix or decision open, **mark it ready** (`gh pr ready <n>`): CI runs on
>    Linux, macOS and Windows, and every job must pass. Marking ready starts no review. A merge needs every
>    conversation resolved ([development-workflow.md, "Claude's review"](…)).

Wrapped at 120 columns, as the file is.

*Alternative:* keep troupe's wording and add the rules in its own words. Rejected: matching infrastructure's makes a
later comparison a plain diff, which is how these gaps were found.

### D2. `CLAUDE.md` step 6

> … **The owner merges** by rebase, through the merge queue, which lands the pull request once `check`,
> `guard (workflow rules)` and `DCO` pass on the commit it tested; `claude review completed`, also required, has to
> have passed on the pull request's head before it's queued. …

The rest of the step is unchanged.

*Alternative:* add `claude review completed` to the list of checks that "pass on the commit it tested". Rejected: on
a merge group the check is skipped (infrastructure's merge-queue design D5), so it doesn't pass on the commit the queue
tested; what it gates is entry to the queue.

### D3. `openspec/config.yaml`'s context

The last "Working" bullet becomes:

> Before archiving, wait for Claude's review of the last push to complete (the required `claude review completed`
> check passed; if it failed, re-run the run it names), and act on each finding by its tier: fix or answer every
> must-fix and nit, resolve only nits, and raise decisions and disputed must-fixes with the owner. A must-fix fixed
> by a push gets no "fixed" reply; reply only when it needs a discussion, and then before pushing. The review
> resolves its own must-fixes (troupe-run/infrastructure docs/development-workflow.md, "Claude's review"), and judges
> a reply to one when it's posted; if that run fails, re-run it (`gh run rerun <id>`). It also resolves its own nits
> once a push has fixed them, so a nit fixed by a push needn't be resolved by hand.

- The third and last sentences are infrastructure's context's, with troupe's repository-qualified link.
- The `claude review completed` clause and the no-"fixed"-reply sentence are infrastructure's step 5's. Its context
  doesn't carry them, but #256 asks this context to, so a session planning or applying a change from the context
  alone gets them too.

## Risks / Trade-offs

- [Infrastructure's wording moves again before this merges] → task 3.1 re-reads infrastructure's files and stops to
  update D1 to D3 if any has changed.
- [The context says more than infrastructure's] → the extra sentences are infrastructure's step 5's, word for word, so
  they can't disagree with it; if infrastructure later adds them to its context, the two converge.
- [The guidance tells a session it needn't act, and the review then leaves a fixed nit open] → the conversation stays
  unresolved, which blocks the merge, so it can't go unnoticed; infrastructure's requirement covers what the session
  does then.

## Migration Plan

Docs only. Rollback: revert the commits.
