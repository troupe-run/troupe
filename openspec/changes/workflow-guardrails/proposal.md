# Proposal

Issue: troupe-run/troupe.run#22

## Why

This repository's workflow was agreed and written down: an issue, then an OpenSpec change that cites it, then a PR
that closes it, with Conventional Commits, signed commits and every check passing. But nothing stops anyone, human
or agent, from skipping a step. In the methodology bake-off every method sometimes decided a design point and built
on it before saying so, and none wrote back to its tracker. The rules only hold if something refuses the shortcut.
Doing this now, before the second change (#23), means that change is the first one built under the rules rather than
from memory.

## What Changes

- **Git hooks in the repository** (versioned under `.githooks/`, activated with `core.hooksPath`) enforce the
  git-level rules for every contributor, human or agent:
  - no commits on `main`;
  - commit messages must be Conventional Commits;
  - `scripts/check.py` must pass before a commit.
- **Claude Code hooks** (in the committed `.claude/settings.json`) enforce the agent-workflow rules:
  - editing source needs an active OpenSpec change whose name matches the current branch;
  - a PR must close an issue;
  - git's own checks can't be skipped (`--no-verify`);
  - a change can't be archived with unticked tasks.
- **A session-start check** sets up the git hooks if they aren't active, and tells the session the workflow it is
  working under.
- **Refuse, with a logged override.** Every guardrail blocks the action and names the rule and the fix. An explicit
  override, carrying a reason, lets one action through and records the bypass in a local log, so a bypass is
  visible, never silent.
- **A project `CLAUDE.md`** states the workflow and points to the rules, so an agent reads them before it starts.
- **Portable:** the hooks are Python run through `uv`, so they work the same on Linux, macOS and Windows. Each rule
  has tests.

These guardrails belong to this repository's development tooling. They are not part of troupe the product, which
will grow its own gates later.

## Capabilities

### New Capabilities
- `development-workflow`: the rules this repository enforces on its own development — which actions are refused,
  how a refusal reads, and how an override is recorded — for both git and Claude Code sessions.

### Modified Capabilities
None.

## Impact

- New files: `.githooks/` (pre-commit, commit-msg), `.claude/settings.json`, `.claude/hooks/` (the hook scripts),
  `CLAUDE.md`, and tests for every rule.
- Developer setup: `core.hooksPath` is set automatically at the start of a Claude Code session. A human contributor
  runs one command (documented in the README). Checks then run before every commit, which takes about five
  seconds.
- No change to the `troupe` package or its specs.
- GitHub-side enforcement (rulesets and required checks) stays in #19. Release automation stays in #23.
