# Tasks

## 1. Regenerate the OpenSpec files

- [x] 1.1 Run `npx -y @fission-ai/openspec@1.14.3 --version` and verify it prints `1.14.3` (design D1). Then run
  `npx -y @fission-ai/openspec@1.14.3 update` from the repository root.
- [x] 1.2 Verify `git status --short` lists exactly the 9 expected files: the six
  `.claude/skills/openspec-*/SKILL.md` and `.claude/commands/opsx/{explore,propose,update}.md`. Verify that
  `openspec/config.yaml` and `.claude/settings.json` are unchanged, and that `grep -r 'generatedBy' .claude` shows
  `1.14.3` six times and no other version. Revert and report any other file.
- [x] 1.3 Generate a preview with the same pinned version in a separate scratch repository holding a copy of
  `main`'s `.claude/` and `openspec/`. Verify every generated file in the repository is byte-identical to the
  preview's, and report any difference instead of editing (design D4).
- [x] 1.4 Run `npx -y @fission-ai/openspec@1.14.3 update` a second time and verify the diff is unchanged (the
  generator is stable).

## 2. Ignore the local settings file

- [x] 2.1 Add `.claude/settings.local.json` to `.gitignore` (design D3). Verify with
  `git -c core.excludesFile=/dev/null check-ignore -v .claude/settings.local.json` that the repository's own
  `.gitignore` matches it, independent of personal git config.

## 3. Verify and commit

- [x] 3.1 Run `uv run scripts/check.py` and verify it passes. Commit as
  `chore(openspec): regenerate the skills with OpenSpec 1.14.3, and ignore .claude/settings.local.json`, with
  `openspec validate openspec-1-14-2` passing first.

## Workflow follow-up

- Update #113's title and outcome to say 1.14.3, with a comment recording the owner's decision and that the website
  and troupe-run/infrastructure#58 still run 1.14.2.
- Open a pull request that says `Closes #113` and mentions troupe-run/infrastructure#58 without a closing keyword.
- Archive the change on the branch before merging (no specs to sync).
- After the merge, comment on #113 with the PR and the archived change. Check that the issue is closed and that its
  roadmap card says Done.
