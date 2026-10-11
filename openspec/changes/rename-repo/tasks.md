# Tasks

## 1. References in this repo

- [x] 1.1 Point `BUG_REPORT_URL` (`packages/troupe/src/troupe/core/errors.py`) at `https://github.com/troupe-run/troupe/issues` and update `test_an_unexpected_exception_is_reported_as_a_structured_internal_error` in `packages/troupe/tests/test_cli.py` to expect `github.com/troupe-run/troupe/issues`; verify that test passes and fails against the old URL
- [x] 1.2 Set `Repository = "https://github.com/troupe-run/troupe"` in `packages/troupe/pyproject.toml`, leaving `Homepage` as `https://troupe.run`; verify `uv build --package troupe` succeeds and the built wheel's `METADATA` lists the new `Project-URL: Repository`
- [x] 1.3 Change the guard fixture in `test_a_pr_body_referring_to_another_repository_s_issue_is_allowed` (`scripts/tests/test_guard_claude.py`) to `Closes troupe-run/infrastructure#1` (design decision 2); verify the guard tests pass
- [x] 1.4 Update the repo links in `packages/troupe/README.md`, `plugins/README.md` (#16) and `protocol/README.md` (#7) to `github.com/troupe-run/troupe`, and retitle `CLAUDE.md` to `# troupe`; verify the links resolve once the repo is renamed (2.3)
- [x] 1.5 Verify nothing live still names the old repo: `git grep -n "troupe-run/troupe\.run\|troupe\.run\.git" -- ':!openspec/changes/archive' ':!openspec/changes/rename-repo'` returns nothing, and the remaining `troupe\.run` hits are only the domain (`https://troupe.run`); then `uv run scripts/check.py` passes and the work is committed

## 2. Rename on GitHub and open the PR

- [x] 2.1 With the owner's go-ahead, rename the repo: `gh repo rename troupe --repo troupe-run/troupe.run --yes`; verify `gh repo view troupe-run/troupe --json id` returns `R_kgDOVEZa3g`
- [x] 2.2 Set the clone's remote: `git remote set-url origin git@github.com:troupe-run/troupe.git`; verify `git remote -v` shows the new URL and `git ls-remote origin main` succeeds
- [x] 2.3 Verify the new URLs resolve directly, with no redirect: `curl -sI https://github.com/troupe-run/troupe` and `.../troupe/issues` both return `200`
- [x] 2.4 Push the branch and open the PR with `Closes #26`; verify every CI job passes on Linux, macOS and Windows
- [ ] 2.5 Confirm both Apps still cover the repo: `gh api user/installations/170159387/repositories` (DCO) and `.../170224209/repositories` (`troupe-run-infrastructure`) each list `troupe-run/troupe`, and the DCO check appears on the PR

## 3. The rest of the org

- [x] 3.1 In `troupe-run/troupe-run.github.io`, on a branch, change all 16 references to `github.com/troupe-run/troupe`: the copy (header, hero, closing), the two backstage docs pages, `tests/e2e/landing.spec.ts`, the `--skip` in `.github/workflows/links-weekly.yml`, `CONTRIBUTING.md`, and `docs/superpowers/` (design decision 3). Verify `git grep "troupe-run/troupe\.run"` returns nothing, the site's build and e2e tests pass, and the PR (citing #26) is open with checks green
- [x] 3.2 In `troupe-run/.github`, change `profile/README.md` to link `https://github.com/troupe-run/troupe` as the "troupe repository" (design decision 4); verify `git grep "troupe-run/troupe\.run"` returns nothing and the PR (citing #26) is open
- [x] 3.3 Edit the bodies of #19 and #25 to the new name; verify by scanning every open issue's body (`gh issue list --state open --json number,body` with a `troupe\.run` scan) that only #26 still mentions the old name. GitHub's search splits `troupe.run` into two words, so `--search "troupe.run in:body"` can't tell old names apart

## 4. The local workspace

These run from a terminal in `~/Projects/troupe/`, with no Claude Code session open in the clone (design decision 5).

- [ ] 4.1 Update the memory's text: in `~/.claude-troupe/projects/-Users-martin-Projects-troupe-troupe-run/memory/`, change `troupe-run/troupe.run` to `troupe-run/troupe` (and "troupe.run's open design questions" to "troupe's") in `MEMORY.md` and `troupe-decisions-live-in-github-issues.md`; verify `grep -rn "troupe\.run" memory/` returns nothing
- [ ] 4.2 Back up `~/.claude-troupe/.claude.json` and `~/.claude-troupe/history.jsonl`, then `mv ~/Projects/troupe/troupe.run ~/Projects/troupe/troupe` and `mv ~/.claude-troupe/projects/-Users-martin-Projects-troupe-troupe-run ~/.claude-troupe/projects/-Users-martin-Projects-troupe-troupe`; verify the old paths no longer exist and the new ones do
- [ ] 4.3 Rewrite the old folder path to the new one: the `projects` key in `.claude.json`, and the `project` field of each `history.jsonl` entry; verify both files still parse as JSON/JSONL, `.claude.json` has a `projects["/Users/martin/Projects/troupe/troupe"]` entry with the old entry's `allowedTools` and `hasTrustDialogAccepted`, and no entry or line names the old path
- [ ] 4.4 Rebuild the virtual environment in the new folder (`rm -rf .venv && uv sync`); verify `head -1 .venv/bin/troupe` names the new path and `uv run scripts/check.py` passes
- [ ] 4.5 Start Claude Code in `~/Projects/troupe/troupe` and verify: there's no trust prompt, the memory index loads (the decisions memory is in context), earlier sessions are listed in `/resume`, and `git remote -v` shows `troupe-run/troupe`

## Workflow follow-up

- Archive the change on the branch (`/opsx:archive`) from the session in the renamed folder, so the PR lands code and specs together.
- Merge the PR once checks pass, then merge the website and `.github` PRs.
- Comment on #26 with the PR, the archived change and the two org PRs, then close it.
- Delete the `.claude.json` and `history.jsonl` backups once the new session has worked for a day.
