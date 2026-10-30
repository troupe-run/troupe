# Design

## Context

See proposal.md, Why. Three facts shape the note:

- `openspec/config.yaml`'s `context` reaches every proposal through `openspec instructions … --json`, and its Working
  list already holds the `Capability:` line rule and the #152 rule for a new label.
- troupe-run/infrastructure's `scripts/oob.py` (`stale_descriptions`) reports three things about troupe's specs
  against `oob/troupe-spec-purposes.json`: a spec with no record ("Purpose isn't recorded"), a spec whose Purpose,
  without its `Capability:` line and with whitespace collapsed, differs from its record ("Purpose has changed"), and a
  record with no spec ("remove it"). A change to the `Capability:` line alone isn't reported.
- infrastructure's `oob/README.md` already says how a record is written: by the spec's folder name, without the
  `Capability:` line, whitespace collapsed, with the named labels' descriptions reviewed against it.

## Goals / Non-Goals

**Goals:**
- Someone proposing a troupe change that adds, removes or re-words a spec's Purpose learns, while proposing it, that
  infrastructure needs a matching pull request.

**Non-Goals:**
- Checking it. No troupe test may read `openspec/**` (`scripts/check-paths.toml`), and the drift job in
  infrastructure already catches a miss after the merge.
- Changing anything in infrastructure. Its README already describes the record (infrastructure design D3 rejected a
  second copy there).

## Decisions

**D1. One bullet in the Working list, right after the `Capability:` line rule, that points to `oob/README.md` for the
details.** The text:

```
  - Every spec's Purpose, without its `Capability:` line, is recorded in troupe-run/infrastructure's
    `oob/troupe-spec-purposes.json`, and the descriptions of the labels it names are checked against it. A change
    that adds or removes a spec, or edits a Purpose, updates the record in an infrastructure pull request merged
    alongside it; otherwise infrastructure's drift job fails. Its `oob/README.md` says how.
```

It sits next to the #152 rule, which is where #199 asks for it and where a proposer already reads about
infrastructure. How the record is written stays in `oob/README.md`, its one named place, so the two can't drift.
Rejected: appending it to the `Capability:` bullet, which would mix two rules in one item. Rejected: spelling out the
record's format (folder name, whitespace collapsed), which is a second copy of `oob/README.md`.

**D2. Cover a new spec, a removed spec and an edited Purpose.** `oob.py` fails the drift job for all three, so a note
that names only a new spec leaves the other two to be found after the merge, as `installation` was. Owner,
2026-10-30, widening #199's "every new spec".

**D3. Don't say which pull request merges first.** Two repositories can't merge in one pull request, so the drift job
is red between the two merges whichever goes first. The owner accepted a short red window over an ordering rule
(2026-10-30): "merged alongside" is enough. Rejected: "with or before" (#199's wording), which suggests an order that
doesn't avoid the failure. Rejected: "right after troupe's merge", which would make the job's message in the gap say
"record it" rather than "remove it", but adds a rule for a window of minutes.

## Risks / Trade-offs

- [The note is guidance, not a check, so it can still be missed] → infrastructure's drift job still fails after the
  merge, naming the spec and the fix, as it did for `installation`.
- [infrastructure renames the file or changes `oob.py`'s check] → the note names the file and the README, so a rename
  shows up as a broken pointer; whoever changes it there updates troupe's note through a troupe issue.
