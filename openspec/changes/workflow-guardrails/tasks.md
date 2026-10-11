# Tasks

## 1. Guard module foundation

- [ ] 1.1 Create `scripts/guard.py` with the decision type (allow, or refuse with rule id, problem and fix), the rule-id list (design D7), the fact-gathering helpers (current branch including during a rebase, matching change per design D3, repo root), and a CLI dispatching to the entry points; add `scripts/tests/` to pytest `testpaths`; verify `uv run scripts/check.py` passes and `uv run --no-sync python scripts/guard.py --help` lists the entry points
- [ ] 1.2 Implement and test the matching-change helper: active change, archived-on-branch change (`archive/<date>-<branch>`), no change, `main`, and a branch read during a rebase; verify each case with a test in a temporary git repository

## 2. Git-level rules (git hooks)

- [ ] 2.1 Implement `commit-message` (design D5) with tests: accepted types with and without scope and `!`, autosquash prefixes, unknown type, missing type, `Revert "…"`, merge message; add a hypothesis test that any generated `type(scope): subject` from the accepted set is accepted and any first line without `: ` is refused
- [ ] 2.2 Implement `commit-on-main`, `commit-branch-change` and `archive-incomplete` with tests, including an archived change with one unticked task (the message names the change and the task)
- [ ] 2.3 Implement `commit-checks` (design D4): refuse when a tracked file has unstaged changes, otherwise run `scripts/check.py` and refuse naming the failing gate; test both paths with a stub check script in a temporary repository
- [ ] 2.4 Add `.githooks/pre-commit` and `.githooks/commit-msg` shims (design D1) and test them end to end in a temporary git repository with `core.hooksPath` set: a commit on `main` is refused, a non-conventional message is refused, a commit on a matching branch with a conventional message and a passing stub check is made, and each refusal leaves no commit
- [ ] 2.5 Document the git hooks and the one-time `git config core.hooksPath .githooks` in the README's Development section; verify the documented command activates them in a fresh clone

## 3. Claude Code rules (PreToolUse)

- [ ] 3.1 Implement the Bash command splitter (design D6) with tests for `&&`, `||`, `;`, `|`, newlines, quoting, and the refuse-when-unparseable path
- [ ] 3.2 Implement `skip-hooks` (`--no-verify`, `git commit -n`, `core.hooksPath` changes via `git config` and `git -c`) with tests
- [ ] 3.3 Implement `pr-closes-issue` for `gh pr create` with `--body`, `--body-file`, `--fill` and no body, with tests for each closing keyword, a missing keyword, and a body file that does and doesn't close an issue
- [ ] 3.4 Implement `edit-branch-change` for `Edit|Write|MultiEdit|NotebookEdit` (paths inside the repository only; paths outside it are allowed), with tests for `main`, a non-matching branch, a matching branch, an archived-on-branch change and an outside path
- [ ] 3.5 Implement the `claude-pre-tool-use` entry point: read the hook JSON from stdin, apply the rules, print the documented `permissionDecision: "deny"` JSON on refusal; test it by piping real-shaped PreToolUse JSON for Edit, Write and Bash and asserting the output
- [ ] 3.6 Add `.claude/settings.json` with the PreToolUse hooks (matchers `Edit|Write|MultiEdit|NotebookEdit` and `Bash|PowerShell`, `${CLAUDE_PROJECT_DIR}` paths, `onFailure: "block"`) and the SessionStart hook; verify in a live session that an edit on a non-matching branch is refused with the rule's message

## 4. Overrides

- [ ] 4.1 Implement `guard.py override <rule> --reason …` (design D7): validate the rule id, write `.git/troupe-guard/override.json` with who and when; test that an unknown rule is refused and a valid one is written
- [ ] 4.2 Make every refusal consume a matching override and append to `.git/troupe-guard/overrides.jsonl`; test grant → one action allowed → logged → next action refused, for a git-hook rule and a Claude rule
- [ ] 4.3 Refuse agent attempts to grant overrides (Bash running `guard.py override` or mentioning `troupe-guard`; edits under `.git/`), with tests

## 5. Session start and CLAUDE.md

- [ ] 5.1 Implement `claude-session-start` (design D8): set `core.hooksPath` when it isn't `.githooks` and say so, then return the workflow and branch/change status as `additionalContext`; test with a temporary repository in both states
- [ ] 5.2 Write the project `CLAUDE.md` (design D9); verify a new session in this repository loads it, and receives the session-start context on its first turn

## 6. Integration

- [ ] 6.1 Run the full check on Linux, macOS and Windows in CI; verify every job passes, including the guard tests that make real commits in temporary repositories on Windows
- [ ] 6.2 Run the guard tests on the owner's Windows machine, in a Claude Code session there, and confirm a refused edit and a refused `--no-verify` behave as on macOS
- [ ] 6.3 Verify whether a PreToolUse deny applies in `bypassPermissions` mode by attempting a refused edit in that mode; record the result in `docs/development-workflow.md` and in the design's open question
- [ ] 6.4 Write `docs/development-workflow.md`: every rule (id, what it refuses, fix), how to grant an override and read the log, and the known gaps (not a security boundary, `gh api` PRs, the bypass-mode result); verify every rule id in it matches the guard module's list with a test

## Workflow follow-up

- Open the PR with "Closes #22"; archive the change on the branch before merging (all tasks ticked — the new `archive-incomplete` rule will check that); after the merge, comment on #22 with the PR and the archived change.
