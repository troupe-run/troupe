# Design

## Context

See proposal.md, Why. The text today:

`CLAUDE.md` step 5 (its middle sentence):

> The review resolves its own must-fixes once they're addressed, judging a reply to one when it's posted; if that run
> fails, re-run it (`gh run rerun <id>`).

`openspec/config.yaml`'s context, the last "Working" bullet (its last sentence):

> The review resolves its own must-fixes (troupe-run/infrastructure docs/development-workflow.md, "Claude's review");
> after answering a must-fix without a push, re-run the last `claude review` run (`gh run rerun <id>`) so the review
> judges the reply.

infrastructure, as of 2026-11-02 (`main`):

- `CLAUDE.md` step 5: "The review resolves its own must-fixes once they're addressed, judging a reply to one when it's
  posted, and its nits once a push has fixed them, so a nit fixed by a push needs no reply or resolve; if that run
  fails, re-run it (`gh run rerun <id>`)."
- `openspec/config.yaml`: "… It also resolves its own nits once a push has fixed them, so a nit fixed by a push needn't
  be resolved by hand."
- `openspec/specs/development-workflow/spec.md`, "The workflow says the review resolves a nit a push has fixed": the
  session may leave a nit it fixed with a push for the review to resolve, and resolves it itself only if that review
  leaves it open and it still judges it fixed, replying with what it did.

## Goals / Non-Goals

**Goals:**

- Both files say the review resolves a nit a push has fixed, in infrastructure's words (#238's "Done when").
- Nothing else in either file changes.

**Non-Goals:**

- Bringing the rest of troupe's step 5 and context into line with infrastructure's. That's #256 (website's is
  troupe-run/website#101). The differences:
  - infrastructure's step 5 says a must-fix fixed by a push gets no "fixed" reply, and to reply only when it needs a
    discussion, before pushing.
  - infrastructure's step 5 says "ready" waits for the review of the last push to have completed (the required
    `claude review completed` check passed).
  - troupe's context tells a session to re-run the review after answering a must-fix without a push; infrastructure's
    says the review judges a reply when it's posted, and to re-run only if that run fails. troupe's own `CLAUDE.md`
    step 5 already says the latter, so the context is the stale one.

## Decisions

### D1. `CLAUDE.md` step 5

Replace the middle sentence with infrastructure's, word for word:

> The review resolves its own must-fixes once they're addressed, judging a reply to one when it's posted, and its nits
> once a push has fixed them, so a nit fixed by a push needs no reply or resolve; if that run fails, re-run it
> (`gh run rerun <id>`).

The step is rewrapped at 120 columns, as the file is; the sentences before and after it are unchanged.

*Alternative:* a separate sentence after the must-fix one. Rejected: infrastructure's step is the model #238 names,
and matching it word for word makes a later comparison a plain diff.

### D2. `openspec/config.yaml`'s context

Append infrastructure's sentence to the end of the last "Working" bullet, after "so the review judges the reply.":

> It also resolves its own nits once a push has fixed them, so a nit fixed by a push needn't be resolved by hand.

The bullet's existing sentences stay as they are (Non-Goals); "It" reads as "the review", the subject of the sentence
before, as it does in infrastructure's.

*Alternative:* also replace the must-fix sentence with infrastructure's. Rejected for this change: it isn't #238's,
and it changes what a session is told to do after answering a must-fix. Listed under Non-Goals instead.

## Risks / Trade-offs

- [Infrastructure's wording moves again before this merges] → task 1.1 re-reads both of infrastructure's files and
  stops to update D1 and D2 if either has changed.
- [The guidance tells a session it needn't act, and the review then leaves a fixed nit open] → the conversation stays
  unresolved, which blocks the merge, so it can't go unnoticed; infrastructure's requirement covers what the session
  does then. Not repeated here, as infrastructure's files don't.

## Migration Plan

Docs only. Rollback: revert the commit.
