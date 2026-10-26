# Tasks

## 1. Name each spec's labels

- [x] 1.1 Add the `Capability:` line to each of the 25 specs in `openspec/specs/`, as the first line of its
  `## Purpose`, followed by a blank line and the Purpose's prose unchanged, with the labels from the proposal's table
  in the order it gives (design D2). Verify `git diff --stat` lists exactly the 25 `spec.md` files, each with 2 lines
  added and none removed.
- [x] 1.2 Check every line by script against #169's mapping, written out in the script from the proposal's table:
  each spec's first non-blank Purpose line is exactly ``Capability: `cap:a`[, `cap:b`]`` with the expected labels,
  every spec in `openspec/specs/` has an entry, and the mapping names no spec that doesn't exist. Keep the script in
  the scratchpad, not the repository. Verify it reports 25 matches and nothing else.
- [x] 1.3 Verify `openspec validate --specs --strict` passes (25 passed, 0 failed), and that
  `git diff --name-only main -- openspec/changes/archive/` prints nothing. Commit as
  `docs(openspec): name each spec's capability labels under its Purpose`, with `uv run scripts/check.py` passing first.

## 2. Write the convention down

- [ ] 2.1 Add the note to the Working list in `openspec/config.yaml`'s context (design D3): a new spec's Purpose
  starts with the `Capability:` line naming each label it belongs to; a new spec's delta puts the line at the top of
  its `## Purpose`, which OpenSpec carries over; and a label that doesn't exist yet is added through
  troupe-run/infrastructure#152. Verify `openspec instructions proposal --change spec-capability-labels --json`
  shows the note in its `context`, and `openspec validate --all --strict` passes. Commit as
  `docs(openspec): say a new spec names its capability labels under its Purpose`, with `uv run scripts/check.py`
  passing first.

## 3. Ready the pull request

- [ ] 3.1 Rebase onto `main` and re-run task 1.2's script, so a spec added on `main` meanwhile can't go without its
  line (design, Risks). Verify it still reports one match per spec in `openspec/specs/`. If a new spec appeared, ask
  the owner which labels it names unless #169's "its own label" rule clearly applies.
- [ ] 3.2 Open the pull request with `Closes #170`, the drift job's expected 25 "Purpose has changed" findings and
  why (design D4), and links to troupe-run/infrastructure#151 and #153. Verify every CI job passes.

## Workflow follow-up

- Run `/opsx:archive` on the branch before merging. The change sets `skip_specs: true`, so archiving moves it without
  touching `openspec/specs/`.
- After the merge: check #170 is closed and its card says Done, and comment on it with the PR and the archived
  change. Tell troupe-run/infrastructure#151 that the lines are on troupe's `main`.
