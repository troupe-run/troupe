# Tasks

## 1. The review step in the config's context (#185, design D1)

- [x] 1.1 Add D1's item as the last entry of the Working list in `openspec/config.yaml`'s `context`, after "Commit in
  small steps with messages that say why." Verify by a scratchpad script that the new item, whitespace collapsed,
  equals infrastructure's current item (fetched with `gh api repos/troupe-run/infrastructure/contents/openspec/config.yaml`)
  with only `docs/development-workflow.md` replaced by `troupe-run/infrastructure docs/development-workflow.md`, and
  that `git diff openspec/config.yaml` adds exactly those lines and removes none.
- [x] 1.2 Verify `openspec instructions tasks --change merge-queue-and-review-docs --json` shows the item in its
  `context`, and `openspec validate --all --strict` passes. Commit as
  `docs(openspec): plan for acting on Claude's review before archiving`, with `uv run scripts/check.py` passing first
  (only the OpenSpec part runs: the path is in `skip`).

## 2. The review and merge steps in CLAUDE.md (#184, #185, design D2 and D3)

- [ ] 2.1 In CLAUDE.md's "How work happens here", insert D3's step 5, renumber the archive step to 6 with D2's merge
  text, and renumber the after-merge step to 7. Verify `git diff CLAUDE.md` touches only that list, steps 1 to 4 are
  byte-identical, and the steps read 1 to 7 in order.
- [ ] 2.2 Check the facts the text states against their sources: the ruleset's required checks are exactly `check`,
  `DCO` and `guard (workflow rules)` and its `merge_queue` rule merges by `REBASE`
  (`gh api repos/troupe-run/troupe/rules/branches/main`); `.github/workflows/claude-review.yml`'s `name` is
  `claude review`; `gh pr merge --help` still says a queued branch needs no strategy and `--admin` bypasses the queue;
  infrastructure's `docs/development-workflow.md` has a `## Claude's review` heading, so the `#claudes-review` anchor
  resolves. Verify each by its command's output; if one has changed, stop and update design before the text.
- [ ] 2.3 Verify nothing else cites CLAUDE.md's old step numbers: `git grep -n -i -E "step (5|6)" -- ':!openspec/changes/archive'`
  finds no reference to CLAUDE.md's list (design D3). Commit as
  `docs: say pull requests land through the merge queue, after acting on Claude's review`, with
  `uv run scripts/check.py` passing first (the full check: CLAUDE.md is in no scope).

## 3. The pull request

- [ ] 3.1 Open the pull request with `Closes #184` and `Closes #185` on their own lines, and a link to
  troupe-run/infrastructure#194 and #197. Verify every required check (`check`, `guard (workflow rules)`, `DCO`)
  passes, and `gh pr view --json closingIssuesReferences` lists both #184 and #185.
- [ ] 3.2 Comment on troupe-run/infrastructure#194 with the pull request's link (#185's "Done when"). Verify the
  comment appears with `gh issue view 194 -R troupe-run/infrastructure --comments`.

## Workflow follow-up

- Act on Claude's review of the last push, as the new step says, then run `/opsx:archive` on the branch. The change
  sets `skip_specs: true`, so archiving moves it without touching `openspec/specs/`.
- Merge through the queue (`gh pr merge <n>`), which is this change's own first use of the step it writes down.
- After the merge: check #184 and #185 are closed and their cards on the troupe roadmap board say Done, and comment
  on each with the PR and the archived change.
