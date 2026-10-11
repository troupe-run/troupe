# Tasks

## 1. Reproduce the bug

- [ ] 1.1 Add failing tests to `scripts/tests/test_guard_claude.py` for the new scenarios, run against a temporary repository (`make_repo`) whose `origin` is `git@github.com:troupe-run/troupe.git`. Each uses a description that closes no issue:
  - `--repo troupe-run/.github`, `-R troupe-run/troupe-run.github.io`, `--repo=troupe-run/.github` and `GH_REPO=troupe-run/.github gh pr create ...`: allowed;
  - `--repo troupe-run/troupe`, `--repo TROUPE-RUN/Troupe`, `--repo github.com/troupe-run/troupe` and `--repo https://github.com/troupe-run/troupe.git`: refused with `pr-closes-issue`;
  - an unrecognisable `--repo` value, and a repository with no remotes: refused.
  Verify the "allowed" cases fail and the "refused" cases pass before any fix (the bug reproduced).

## 2. Scope the rule to this repository

- [ ] 2.1 Implement repository-name normalisation (design decision 3) with a test per accepted form: `OWNER/REPO`, `HOST/OWNER/REPO`, `https://` with and without `.git`, `git@HOST:OWNER/REPO.git`, `ssh://git@HOST/OWNER/REPO.git`, and a few rejected values. Add a hypothesis test that any generated owner/name, in each form, normalises to the same triple. Verify with `uv run pytest scripts/tests/test_guard_claude.py`
- [ ] 2.2 Resolve the PR's target in `pr_closes_issue` (design decisions 1, 2 and 4): `-R`/`--repo`/`--repo=`, then a leading `GH_REPO=`, then the environment's `GH_REPO`, comparing against every remote of the repository from `cwd`. Pass the remotes in rather than reading them per word. Verify the section 1 tests and the existing `pr-closes-issue` tests all pass, including a test that `GH_REPO` in the environment is honoured (via `monkeypatch`) and that `--repo` beats `GH_REPO`
- [ ] 2.3 Add a test of the Claude hook entry point: real-shaped PreToolUse JSON for `gh pr create --repo troupe-run/.github --title t --body 'Updates a link.'` from a repository whose `origin` is troupe produces no deny, and the same command without `--repo` produces the `pr-closes-issue` deny. Verify it passes
- [ ] 2.4 Update the `pr-closes-issue` row in `docs/development-workflow.md` to say it covers PRs into this repository, named by `--repo`/`-R` or `GH_REPO` or by default, and that an unrecognised target counts as this one. Verify `uv run pytest scripts/tests/test_guard_docs.py` passes and the row reads correctly in the rendered table

## 3. Integration

- [ ] 3.1 Run `uv run scripts/check.py`, and verify all gates pass
- [ ] 3.2 In a live session on this branch, run `gh pr create --repo troupe-run/.github --head no-such-branch --title t --body 'x'` and verify the hook doesn't refuse it. `gh` itself then fails on the missing branch, which creates nothing. Then run the same command without `--repo`, and verify it is refused with `pr-closes-issue`. Record both outputs in the task's commit message

## Workflow follow-up

- Open the PR with `Closes #28`; CI must pass on Linux, macOS and Windows.
- Archive the change on the branch (`/opsx:archive`), which syncs the modified requirement into `openspec/specs/development-workflow/spec.md`.
- After the merge, comment on #28 with the PR and the archived change.
