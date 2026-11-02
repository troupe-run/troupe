# Proposal

Issues: #238, #256.

## Why

Three infrastructure changes changed how Claude's review works, and each updated infrastructure's own `CLAUDE.md` and
`openspec/config.yaml` but not this repository's, which can only change here, through a pull request:

- troupe-run/infrastructure#246 (`review-resolves-fixed-nits`, archived 2026-11-01): the review resolves its own nits
  once a push has fixed them. Its development-workflow requirement, "The workflow says the review resolves a nit a
  push has fixed", asks each governed repository's `openspec/config.yaml` context to say so (#238).
- troupe-run/infrastructure#208 (PR #215, `review-judge-reply-on-post`): a reply to one of the review's open must-fixes
  starts a review that judges it. troupe's `CLAUDE.md` step 5 says this, but `openspec/config.yaml`'s context still
  tells a session to re-run the review by hand after answering a must-fix (#256).
- troupe-run/infrastructure#242 (PR #243, `review-completed-check`): `claude review completed` is a required check on
  `main`, so a pull request can't merge until the review of its head has completed. Because a reply's review cancels a
  push's running review and leaves that check failed, a must-fix fixed by a push gets no "fixed" reply, and a reply
  that needs a discussion goes before the push. Neither file says either, and step 6 lists only `check`,
  `guard (workflow rules)` and `DCO` as what a merge waits for (#256).

A session following troupe's files today re-runs a review that already ran, can reply "fixed" to a must-fix it pushed
a fix for and leave the required check failed, and doesn't know to wait for that check before marking a pull request
ready.

## What Changes

- **`CLAUDE.md` step 5** says, in infrastructure's step 5's words (design D1):
  - the review resolves its nits once a push has fixed them, so a nit fixed by a push needs no reply or resolve
    (done in the first commit);
  - a must-fix fixed by a push gets no "fixed" reply; reply only when it needs a discussion, and then before pushing;
  - "ready" waits for the review of the last push to have completed (the required `claude review completed` check
    passed; if it failed, re-run the run it names).
  troupe's own parts of the step stay: CI on Linux, macOS and Windows, "Marking ready starts no review", and the link.
- **`CLAUDE.md` step 6** names `claude review completed` among the required checks, as having passed on the pull
  request's head before it's queued (design D2).
- **`openspec/config.yaml`'s context**, in the "Working" bullet about Claude's review (design D3):
  - says the review judges a reply to a must-fix when it's posted, and to re-run only if that run fails, in
    infrastructure's context's words, replacing "after answering a must-fix without a push, re-run the last `claude
    review` run";
  - says the review resolves its nits once a push has fixed them (done in the first commit);
  - says the no-"fixed"-reply rule and to wait for `claude review completed`, in infrastructure's step 5's words.
- **"Resolve only nits" stays** in both files: it's still true of the author.

Out of scope:

- **The guard's session-start summary** (`scripts/guard.py`) and the review workflow (`.github/workflows/`). Both are
  delivered from infrastructure, not edited here.
- **website's files.** troupe-run/website#89 and #101 are the same fixes there.
- **Archived changes**, which record what was planned then.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. `CLAUDE.md` and `openspec/config.yaml`'s context are contributor guidance, which no troupe spec describes; the
requirements behind the wording are infrastructure's development-workflow spec. Outside the archive, `scripts/` and
`.github/`, a search for the review's wording and the queue's checks
(`git grep -n -i -E "gh run rerun|claude review|\"fixed\"|must-fix|guard \(workflow rules\)|merge queue"`) finds it
only in these two files, and nothing in `openspec/specs/`. The change sets `skip_specs: true`.

## Impact

- Changed: `CLAUDE.md` steps 5 and 6 and `openspec/config.yaml`'s `context`. No code, tests or specs.
- `openspec/config.yaml`'s context is given to every OpenSpec artifact and workflow, so later changes see it.
- Checks: `CLAUDE.md` is in no `scripts/check-paths.toml` group, so a commit touching it runs the full check.
- After the merge: comment on #238 and #256 with the pull request and the archived change, and check both cards say
  Done. Rollback: revert.
