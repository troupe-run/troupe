# Proposal

Issue: #28

## Why

The `pr-closes-issue` rule exists to enforce this repository's workflow: every PR into troupe delivers an issue and
closes it. Today it refuses any `gh pr create` from a session whose description closes no issue, whichever
repository the PR is opened in. During #26 the PRs that updated links in the website and org-profile repos
(troupe-run/troupe-run.github.io#2, troupe-run/.github#1) were refused. Each was correctly *part of* #26, not a
closer of it, and those repos don't follow this workflow. Each went through only on an owner override. A routine
cross-repo step shouldn't need one, and every unneeded override weakens the override log as a signal.

## What Changes

- **The rule covers PRs into this repository only.** A `gh pr create` whose target is a different repository goes
  ahead without the closing-keyword check.
- **The target is read from the command, in `gh`'s order of precedence:** `--repo`/`-R` (including `--repo=...`),
  then `GH_REPO` (set for the command or in the environment). With neither, the PR is treated as into this
  repository. A named target is compared with every remote of this clone (`origin`, and `upstream` in a fork's
  clone), ignoring case, a trailing `.git` and the URL form (SSH or HTTPS).
- **When the target can't be worked out, the rule still applies:** for example, an unparseable `--repo` value, or no
  remote to compare with. A PR into this repo that slips through is worse than an extra refusal, and the refusal's
  fix still works.
- **Docs:** the rule's row in `docs/development-workflow.md` says it covers PRs into this repository.

Not in scope: requiring cross-repo PRs to *reference* a troupe issue (e.g. "part of troupe-run/troupe#26"). The org's
other repos have their own conventions; if they want such a rule, it belongs in those repos.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `development-workflow`: the requirement "Pull requests close an issue" is narrowed to pull requests into this
  repository, with scenarios for a PR into another repository and for a target that can't be determined.

## Impact

- `scripts/guard.py`: `pr_closes_issue` resolves the PR's target repository and this clone's remotes before checking
  the body.
- `scripts/tests/test_guard_claude.py`: tests for each way of naming the target, and for the undetermined case.
- `docs/development-workflow.md`: the `pr-closes-issue` row.
- No change to the git hooks, the pre-push check or the GitHub `guard` check. None of them look at PR descriptions.
