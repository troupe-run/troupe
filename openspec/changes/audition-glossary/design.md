# Design

## Context

The glossary is a two-column table (`docs/prompt-book/glossary.md`, `prerelease: false`) that defines words rather
than behaviour, so it already has rows for things not built yet (gate, cue). `test_user_docs_vocabulary.py` checks it:
every term is plain text, `REQUIRED_TERMS` (stage, rehearsal, system, cue) each have a row, and cue says it's
provisional. The check of the brand guide's §6 against the glossary lives in troupe-run/website, which reads the
glossary as synced from `main` here.

`troupe init --audition` isn't on `main` yet: #233 builds it in pull request #260, for 0.2.0.

## Goals / Non-Goals

**Goals:**

- An audition row whose meaning agrees with the brand guide's status for the word (proposal, What Changes).
- A docs check that keeps the row there.

**Non-Goals:**

- The flag itself, its `cli.md` entry, or anything in `packages/troupe/src` (#233).
- Checking the row's wording against the brand guide. That cross-check is the website's.

## Decisions

### D1. audition joins `REQUIRED_TERMS`

The issue asks only for the row. But troupe.run's check fails whenever the brand guide has a term the glossary
doesn't, so a later edit that drops the row would pass here and break the website on its next sync. Requiring it
here makes the failure land on the pull request that causes it, the same reason rehearsal and system are required.
The spec requirement names audition beside them.

- *Alternative: add the row only.* Meets the issue's done-when, but leaves the dependency unguarded. Rejected.
- *Alternative: require every term the brand guide lists.* The guide lives in another repository, and the website
  already owns that check (the vocabulary test's docstring). Rejected.

### D2. The row's wording and place

The row goes straight after rehearsal, so "not a rehearsal" is read beside the rehearsal row it points to:

> | audition | What troupe init --audition writes: a working example actor, Claude Code by default, ready to perform or
> edit. Not a rehearsal, which is a dry run (--rehearse) |

- It leads with the command, as the brand guide's status does, and names the default runner, as the issue asks.
- The command and flag are written plainly, as the rehearsal row already writes `--rehearse`, and as the brand guide's
  status quotes them.
- It names no version. No other row does, and "from 0.2.0" would go stale once 0.2.0 ships; the brand guide carries
  the date and version. The glossary defining a word before its behaviour is on `main` follows gate and cue.
- The term is plain text, so the code-font rule passes.

## Risks / Trade-offs

- [#260 changes the flag or its default runner before it merges] → The row would then disagree with the CLI. #260's
  owner, and the brand guide's status, are the places that change first; the row is one line to follow them, and
  #260's pull request should check it.
- [Website#85's check reads the row's wording, not just its presence] → The wording follows the guide's status
  closely (D2). If the website's check still fails after the re-sync, its failure names what differs, and the fix is
  a follow-up here or there.
