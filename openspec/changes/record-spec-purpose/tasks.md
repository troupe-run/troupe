# Tasks

## 1. Write the note

- [ ] 1.1 Add design D1's bullet to the Working list in `openspec/config.yaml`'s context, directly after the
  `Capability:` line rule, wrapped at 120 characters like its neighbours. Verify `git diff --stat` lists only
  `openspec/config.yaml`, with no line removed; `openspec instructions proposal --change record-spec-purpose --json`
  shows the bullet in its `context`; and `openspec validate --all --strict` passes.
- [ ] 1.2 Check the note's pointers against infrastructure's `main`: `oob/troupe-spec-purposes.json` and
  `oob/README.md` exist (`gh api repos/troupe-run/infrastructure/contents/oob`), and `scripts/oob.py` still reports a
  missing record, a changed Purpose and a record with no spec (design, Context). Verify each by its message in
  `stale_descriptions`. Commit as `docs(openspec): say a spec's Purpose is recorded in infrastructure`, with
  `uv run scripts/check.py` passing first.

## 2. Ready the pull request

- [ ] 2.1 Rebase onto `main` and open the pull request with `Closes #199`, linking troupe-run/infrastructure#224 and
  saying the note widens #199 to edited Purposes and removed specs (design D2). Verify every CI job passes.

## Workflow follow-up

- Act on Claude's review of the last push, then run `/opsx:archive` on the branch before merging. The change sets
  `skip_specs: true`, so archiving moves it without touching `openspec/specs/`.
- After the merge: check #199 is closed and its card says Done, and comment on it with the PR and the archived change.
