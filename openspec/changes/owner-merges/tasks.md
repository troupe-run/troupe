# Tasks

## 1. Step 6 in CLAUDE.md (#207, design D1 and D2)

- [x] 1.1 Check the facts D1 states against their sources before writing them: `main`'s ruleset still requires
  exactly `check`, `DCO` and `guard (workflow rules)` and its `merge_queue` rule merges by `REBASE`
  (`gh api repos/troupe-run/troupe/rules/branches/main`); infrastructure's `docs/development-workflow.md` still lists
  `owner-only` as refusing `gh pr merge` with or without `--admin`; infrastructure's CLAUDE.md step 6 still reads "The
  owner merges by rebase, through the merge queue." Verify each by its command's output; if one has changed, stop and
  update design before the text.
- [x] 1.2 Replace CLAUDE.md's step 6 with D1's text. Verify `git diff CLAUDE.md` touches only step 6, steps 1 to 5 and
  7 and the rest of the file are byte-identical, and the list still reads 1 to 7 in order.
- [x] 1.3 Verify nothing outside the archive still tells an agent to merge: `git grep -n -i -E "gh pr merge|merge when
  ready|--admin" -- ':!openspec/changes/archive' ':!scripts' ':!.github'` finds only step 6's `owner-only` sentence
  and this change's own files. (`scripts/` and `.github/` are the guard and CI, which describe the refusal, not the
  workflow.)
- [x] 1.4 If website#79 has a pull request, compare its step with D1 and note any difference for the pull request's
  description (design, Risks). Verify by `gh pr list -R troupe-run/website --search "79 in:body"`'s output.
- [x] 1.5 Commit as `docs: say the owner merges a pull request, and the agent asks`, with `uv run scripts/check.py`
  passing first (the full check: CLAUDE.md is in no `scripts/check-paths.toml` group).

## 2. The pull request

- [x] 2.1 Open a draft pull request with `Closes #207` on its own line and a link to troupe-run/website#79. Verify
  `gh pr view --json closingIssuesReferences` lists #207.

## Workflow follow-up

- Act on Claude's review of the last push, mark the pull request ready once it's clean, and run `/opsx:archive` on
  the branch. The change sets `skip_specs: true`, so archiving moves it without touching `openspec/specs/`.
- Once every check passes and every conversation is resolved, ask the owner to merge: this change's own first use of
  the step it writes down.
- After the merge: check #207 is closed and its card on the troupe roadmap board says Done, and comment on it with
  the PR and the archived change.
