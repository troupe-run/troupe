# Tasks

## 1. Remove troupe's own templates

- [ ] 1.1 Confirm the org defaults are in place before deleting anything: `gh api repos/troupe-run/.github/contents/.github/ISSUE_TEMPLATE --jq '.[].name'` lists `bug.yml`, `config.yml`, `decision.yml` and `feature.yml`, and `gh api repos/troupe-run/.github/contents/.github/PULL_REQUEST_TEMPLATE.md` succeeds and its archive step reads "Archive the change on this branch before merging"
- [ ] 1.2 `git rm -r .github/ISSUE_TEMPLATE .github/PULL_REQUEST_TEMPLATE.md`; verify `git ls-files .github` lists only `guard-delivery.json` and `workflows/`, and `git grep -n "ISSUE_TEMPLATE\|PULL_REQUEST_TEMPLATE" -- . ':!openspec/changes'` returns nothing

## 2. Check

- [ ] 2.1 Run `uv run scripts/check.py`, and verify all gates pass

## Workflow follow-up

- Open the PR with `Closes #48`, referencing troupe-run/infrastructure#15 (already closed). GitHub reads templates from the default branch, so this PR can't show the org's template yet; that's checked after the merge. CI must pass on Linux, macOS and Windows.
- Archive the change on the branch (`/opsx:archive`) before merging. There are no delta specs to sync.
- After the merge, verify #48's "done when": `https://github.com/troupe-run/troupe/issues/new/choose` lists the org's Bug, Feature and Decision forms, and a new PR's description starts from the org's template. Then comment on #48 (and on troupe-run/infrastructure#15) with the PR and the archived change.
