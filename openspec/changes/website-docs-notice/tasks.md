# Tasks

## 1. The notice job (D1, D2, D3)

- [ ] 1.1 Add `notify-website` to `.github/workflows/release.yml` as D1 and D2 say. Verify: actionlint reports nothing
  for `release.yml`, and `uv run scripts/check.py` passes.

## 2. The house scenario (D4)

- [ ] 2.1 Check that `docs/the-company/the-house.md` says the house isn't built yet. Verify: `grep -n "isn't built"
  docs/the-company/the-house.md` finds it, and `openspec validate website-docs-notice --strict` passes.

## 3. Pull request

- [ ] 3.1 Open the pull request, citing troupe-run/website#23, and saying it merges after the website's pull request is
  deployed. Verify: every CI job passes.

## Workflow follow-up

- Archive the change on the branch, then merge by rebase after troupe-run/website#23's pull request has deployed.
- After the merge, check D3's first run: the job passed and the website's deploy ran as `workflow_dispatch`. Record
  it on troupe-run/website#23.
