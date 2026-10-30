# Proposal

## Why

troupe-run/infrastructure's out-of-band drift job (`scripts/oob.py`) fails when a troupe spec's Purpose isn't recorded
in its `oob/troupe-spec-purposes.json`. #192 merged the `installation` spec on 2026-10-29 with existing labels, so
nothing sent anyone to infrastructure, and the job failed on every run until troupe-run/infrastructure#224 recorded
it. infrastructure's `oob/README.md` already says a new troupe spec's Purpose is recorded there, but nobody proposing a
troupe spec reads that file. They read troupe's project context, which mentions infrastructure only for a new label
(#199; the owner chose the project context, 2026-10-30, design D3 of infrastructure's `installation-spec-purpose`
change).

## What Changes

- **`openspec/config.yaml`'s context says a spec's Purpose is recorded in infrastructure.** Next to the rule that a
  new label is added through troupe-run/infrastructure#152 first, the Working list says that every spec's Purpose is
  recorded in troupe-run/infrastructure's `oob/troupe-spec-purposes.json`, and that the descriptions of the labels the
  spec names are checked against it, in an infrastructure pull request merged alongside the troupe change. It points
  to infrastructure's `oob/README.md` for how the record is written, rather than repeating it (design D1).
- **The note covers an edited Purpose and a removed spec too, not just a new spec.** `oob.py` reports a Purpose that
  differs from its record, and a record with no spec, just as it reports a missing record. So a change that adds or
  removes a spec, or edits a Purpose, needs the same pull request (design D2; owner, 2026-10-30, widening #199's
  wording).
- **The note doesn't say which pull request merges first** (design D3; owner, 2026-10-30).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. No requirement changes: the project context guides how changes are proposed, and no spec describes it. The
change sets `skip_specs: true`.

## Impact

- Changed: `openspec/config.yaml` only. No code, tests, specs or docs change.
- The commit needs only the OpenSpec part of the check: the changed path is under `openspec/**`.
- Every later proposal's `context` carries the note (`openspec instructions … --json`).
- Nothing changes in infrastructure: `oob/README.md` already describes the record, and #224 recorded `installation`.
- Rollback: revert the commit.
