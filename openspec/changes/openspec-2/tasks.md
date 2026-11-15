# Tasks

## 1. Regenerate the OpenSpec files

- [x] 1.1 Verify `openspec --version` prints `2.0.0` (design D1). Run `openspec update --dry-run` and save its list
  of 25 changes, then verify it lists no locally edited file to keep.
- [x] 1.2 Run `openspec update` from the repository root. Verify `git status --short` matches the dry run's list
  exactly: `.agents/skills/.openspec-target` and six `.agents/skills/openspec-*/SKILL.md` added, six
  `.claude/commands/opsx/*.md` deleted, six `.claude/skills/openspec-*` now links to `.agents/skills/` (relative
  targets, inside the repository). Verify `openspec/config.yaml` and `.claude/settings.json` are unchanged. Revert
  and report any other file.
- [x] 1.3 Verify each `.agents/skills/openspec-*/SKILL.md` says `generatedBy: "2.0.0"`, and that
  `cat .claude/skills/openspec-propose/SKILL.md` reads the `.agents` copy through the link.
- [x] 1.4 Run `openspec update` a second time and verify nothing changes.

## 2. Replace the `/opsx:*` names

- [x] 2.1 In `CLAUDE.md`, replace `/opsx:propose`, `/opsx:apply` and `/opsx:archive` with `/openspec-propose`,
  `/openspec-apply-change` and `/openspec-archive-change` (design D3). Verify with
  `git grep -n 'opsx' -- ':!openspec/changes/archive' ':!scripts/guard.py' ':!.github/workflows/guard.yml'`
  that only the generated skills' own trigger phrases remain ("opsx apply" in a description is OpenSpec's text,
  not a command name; no `/opsx:` remains).
- [x] 2.2 Run `openspec validate --all --strict` with 2.0.0, and with 1.14.3
  (`npx -y @fission-ai/openspec@1.14.3 validate --all --strict`, the version CI still pins), and verify both pass.

## 3. Verify and commit

- [x] 3.1 Run `uv run scripts/check.py` (load under ~40) and verify it passes. Commit, signed off, as
  `chore(openspec): upgrade to OpenSpec 2.0.0` with `openspec validate openspec-2 --strict` passing first.

## Workflow follow-up

- Tell the orchestrator the final skill names, for the owner's /orchestrator and /worker skills.
- Open a draft pull request that says `Closes #423`, mentions troupe-run/infrastructure#308 without a closing
  keyword, and act on Claude's review.
- Archive the change on the branch before merging (no specs to sync).
- After the merge, check #423 is closed and its card says Done.
