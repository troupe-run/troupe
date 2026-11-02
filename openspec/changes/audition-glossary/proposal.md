# Proposal

## Why

#232 (owner, 2026-11-01) named the example-actor flag `troupe init --audition`, which makes "audition" a product
term, and #233 builds the flag for 0.2.0 (pull request #260). troupe-run/website#85 adds the word to the brand guide's
vocabulary, and troupe.run's vocabulary check fails while the guide has a term the glossary has no row for. The owner
chose to land the two together (2026-11-02), so website#85's pull request waits on an audition row reaching `main`
here (#257).

## What Changes

- **The glossary gets an audition row.** `docs/prompt-book/glossary.md` says what `troupe init --audition` writes (a
  working example actor, Claude Code by default) and that it isn't a rehearsal, which is a dry run (`--rehearse`). It
  agrees with the brand guide's status for the word: "In use, 2026-11-01: troupe init --audition, from 0.2.0, writes a
  working example actor. Not a rehearsal, which is a dry run (--rehearse)". The row sits after rehearsal, so the two
  are read together (design D2).
- **The docs check requires the row.** `REQUIRED_TERMS` in `packages/troupe/tests/test_user_docs_vocabulary.py` gains
  audition, so the row can't be dropped while the brand guide keeps the word and troupe.run's check depends on it
  (design D1).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `user-docs`: "The glossary is the single source of troupe's vocabulary" adds audition to the rows the glossary
  must have, with a scenario for a glossary that has no audition row. The rest of its text and its scenarios are
  unchanged. The spec's Purpose doesn't change, so infrastructure's `oob/troupe-spec-purposes.json` needs no update.

## Impact

- `docs/prompt-book/glossary.md`: one new row.
- `packages/troupe/tests/test_user_docs_vocabulary.py`: audition in `REQUIRED_TERMS` and in the sample
  `GLOSSARY_TABLE`, and a case naming a missing audition row.
- No code in `packages/` or `plugins/` changes. The flag itself is #233's (pull request #260); this change doesn't
  wait on it, since the glossary defines words ahead of behaviour, as it does for gate and cue.
- After this merges, website#85's pull request re-syncs the docs and its vocabulary check should pass. That check
  runs in troupe-run/website, not here.
