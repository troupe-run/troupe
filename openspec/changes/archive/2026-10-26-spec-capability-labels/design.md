# Design

## Context

See proposal.md, Why. #169's closing comment (owner, 2026-10-26) fixed the mapping and where the line goes: one line
directly under `## Purpose`, naming one or more labels, which passes `openspec validate --strict`. It was tested on a
copy of `run-workspaces`, and tested again for this design on a scratch copy of all 25 specs.

Three facts shape how the line gets there:

- OpenSpec merges deltas by requirement. When it archives a delta for a spec that already exists, it ignores the
  delta's Purpose and warns that the spec already has one (`specs-apply.js` in OpenSpec 1.14.3).
- `scripts/check-paths.toml` puts `openspec/**` in `skip`: no test may read a file there, and `guard_pytest` fails
  one that does. So no troupe test can check the line.
- One thing outside OpenSpec reads a troupe spec's Purpose: troupe-run/infrastructure's `scripts/oob.py`
  (`stale_descriptions`). It compares each spec's whole Purpose, whitespace collapsed, with the text recorded in
  `oob/troupe-spec-purposes.json`.

## Goals / Non-Goals

**Goals:**
- Every current spec names its labels in one line whose shape a program can read without guessing, because
  troupe-run/infrastructure#151 and #153 will read it.
- A new spec's proposer learns the convention when they propose it, not when a check refuses it later.

**Non-Goals:**
- Checking that a named label exists. The label list lives in troupe-run/infrastructure (`tofu/labels/troupe.json`),
  and #151's drift check and #153's guard check it there.
- Changing any requirement, or the Purpose's prose.
- Updating `oob/troupe-spec-purposes.json` in infrastructure. #151 reconsiders the Purpose check as a whole.

## Decisions

**D1. Edit the 25 main specs directly, with `skip_specs: true`.** No requirement changes, so there's no delta to
write. A delta couldn't carry the line anyway: OpenSpec ignores a delta's Purpose for an existing spec, so 25 deltas
would archive and leave every spec without its line. Rejected: inventing a requirement in each spec so a delta
exists, which the schema forbids and which puts metadata into the requirements. Rejected: syncing the specs by hand
from a delta at archive, which is the same direct edit with an extra step that looks like a merge but isn't one.

**D2. The line's exact shape.** The first non-blank line of `## Purpose`, then a blank line, then the Purpose's prose
as it is today:

```markdown
## Purpose

Capability: `cap:stages`, `cap:vcs`

Defines where a run works, ...
```

- It starts `Capability: ` and is followed by one or more labels, each in backticks, separated by `, `, with nothing
  after the last one. This is #169's example, word for word.
- The word is `Capability:` whether there's one label or two, as in #169's examples. One fixed word gives a reader
  one thing to match.
- The labels are in the order #169's table gives them, with the spec's main capability first (`cap:actor-runners`
  before `cap:protocol`). Nothing depends on the order. It just makes the line read the same way everywhere.
- It's the first line, rather than the last, so a reader stops at the first non-blank line and never has to tell the
  line apart from prose that happens to start with "Capability:".

Rejected: a front-matter block or an HTML comment. OpenSpec's parser doesn't know either, and #169 chose a line a
person reads in the rendered spec.

**D3. The convention goes in `openspec/config.yaml`'s context, under Working.** It's where troupe writes the
conventions every artifact follows, and OpenSpec puts it in front of every proposal, which is where a new spec is
named. That's as early as the labels can be known (troupe-run/infrastructure#153). The note says: a new spec's
Purpose starts with the `Capability:` line, naming each label it belongs to from troupe's label list, and a spec that
needs a label that doesn't exist yet gets it through troupe-run/infrastructure#152's process. It also has to say
how: OpenSpec ignores a delta's Purpose only for a spec that *already* exists. For a new spec it carries the delta's
Purpose over, so the proposer writes the line at the top of the delta's `## Purpose`. Rejected: a contributing doc.
`contributing/` covers the code's subsystems, not OpenSpec, and an agent proposing a change reads the config's context
anyway.

The carry-over was checked for this design on a scratch copy: archiving a change whose delta adds a new spec, with
the line at the top of its `## Purpose`, writes a main spec that starts with the line. OpenSpec drops the blank line
between the heading and the line, which is why D2 says "first non-blank line" rather than "the line after the
heading".

**D4. Accept the drift job's 25 findings until #151 lands, rather than sequencing around them.** Adding the line
changes every Purpose, so after this merges the drift job's `troupe labels` check reports each spec's Purpose as
changed. #151 is blocked by this change and already plans to reconsider that check, so the findings last only between
the two. Rejected: updating `oob/troupe-spec-purposes.json` first, in infrastructure. #151 may drop the file, and the
update would be work done only to be thrown away. Rejected: holding this change until #151 is ready, which #151's own
blocking order rules out.

## Risks / Trade-offs

- [A typo in a label, such as `cap:stage`] → Nothing in troupe catches it, because no test may read `openspec/**`.
  Mitigation: task 1.2 compares every spec's line with #169's table by script, and #151's check refuses an undeclared
  label once it lands.
- [A spec added on another branch before this merges has no line] → Task 3.1 re-lists `openspec/specs/` against
  `main` before the PR, and any new spec gets its line from #169's rule (its own label, or the owner says which).
- [The drift job is red for a while] → Expected and named in the PR (D4). The findings say "Purpose has changed",
  which is true and points at #151.

## Migration Plan

One commit for the 25 lines and one for the config note. Rollback: revert them. The archives aren't touched, so
there's nothing else to undo.
