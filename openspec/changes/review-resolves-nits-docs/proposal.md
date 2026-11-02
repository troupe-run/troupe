# Proposal

Issue: #238.

## Why

troupe-run/infrastructure#246 (change `review-resolves-fixed-nits`, archived 2026-11-01) lets Claude's review resolve
its own nits once a push has fixed them. Its new development-workflow requirement, "The workflow says the review
resolves a nit a push has fixed", asks each governed repository's `openspec/config.yaml` context to say so.
infrastructure's `CLAUDE.md` step 5 says it too. This repository's `CLAUDE.md` step 5 and `openspec/config.yaml` still
say only that the review resolves its must-fixes, so a session reading them resolves a fixed nit by hand. That's still
allowed, but the wording is incomplete, and these two files can only change here, through a pull request.

## What Changes

- **`CLAUDE.md` step 5** adds that the review resolves its nits once a push has fixed them, so a nit fixed by a push
  needs no reply or resolve. The words are infrastructure's `CLAUDE.md` step 5's (design D1).
- **`openspec/config.yaml`'s context**, in the "Working" bullet about Claude's review, adds the sentence
  infrastructure's context uses: "It also resolves its own nits once a push has fixed them, so a nit fixed by a push
  needn't be resolved by hand." (design D2).
- **"Resolve only nits" stays** in both files: it's still true of the author.

Out of scope:

- **Other differences between the two repositories' step 5 and context.** infrastructure's step 5 also says a
  must-fix fixed by a push gets no "fixed" reply, and that "ready" waits for the required `claude review completed`
  check; troupe's context still tells a session to re-run the review after answering a must-fix, where
  infrastructure's says the review judges a reply when it's posted. None of these is #238's, and each came from its
  own infrastructure change. They're #256, and listed in design (Non-Goals).
- **The guard's session-start summary** (`scripts/guard.py`), which already says the review resolves "the nits a push
  fixed". It's delivered from infrastructure, not edited here.
- **Archived changes**, which record what was planned then.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. `CLAUDE.md` and `openspec/config.yaml`'s context are contributor guidance, which no troupe spec describes; the
requirement that asks for the wording is infrastructure's development-workflow spec, already archived there. A search
outside the archive (`git grep -n -i -E "resolve only nits|resolves its own"`) finds the text only in these two files
and in `scripts/guard.py`. The change sets `skip_specs: true`.

## Impact

- Changed: `CLAUDE.md` step 5 and `openspec/config.yaml`'s `context`. No code, tests or specs.
- `openspec/config.yaml`'s context is given to every OpenSpec artifact and workflow, so later changes see the new
  sentence.
- Checks: `CLAUDE.md` is in no `scripts/check-paths.toml` group, so the commit runs the full check.
- After the merge: comment on #238 with the pull request and the archived change, and check its card says Done.
  Rollback: revert.
