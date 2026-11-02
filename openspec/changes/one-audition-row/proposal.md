# Proposal

## Why

The glossary on `main` has two audition rows (troupe-run/troupe#264). #260 (for #233) and #261 (for #257) each added
one, at different places in the table, so both merged on 2026-11-02 without a conflict. The `user-docs` spec already
says the glossary holds "one table row per term", but the docs check (`test_user_docs_vocabulary.py`) only checks that
each required term has a row, not that a term has only one, so neither pull request was stopped. Without a check, the
next pair of parallel pull requests can do it again.

## What Changes

- Remove the audition row after "performance" (#260's) from `docs/prompt-book/glossary.md`, and keep the one after
  "rehearsal" (#261's: "What troupe init --audition writes: a working example actor, Claude Code by default, ready
  to perform or edit. Not a rehearsal, which is a dry run (--rehearse)"). This is the owner's decision on #264
  (2026-11-02).
- The docs check refuses a glossary with more than one row for the same term, naming the term and how many rows it
  has. It checks every term, not only the required ones.
- A test shows a glossary with a duplicate term failing the check, naming the term.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `user-docs`: the requirement "The glossary is the single source of troupe's vocabulary" gains a scenario for a
  duplicate term. Its text ("one table row per term") is unchanged, and the check now enforces it. The spec's Purpose
  is unchanged, so `oob/troupe-spec-purposes.json` in troupe-run/infrastructure needs no update.

## Impact

- `docs/prompt-book/glossary.md`: one row removed.
- `packages/troupe/tests/test_user_docs_vocabulary.py`: `glossary_problems` reports duplicate terms; new tests.
- `openspec/specs/user-docs/spec.md`: one scenario added, at archive.
- Out of scope: the website's own checks of the brand guide against the glossary (troupe-run/website). They read the
  same glossary, which will have one audition row once this merges, so they need no change here.
