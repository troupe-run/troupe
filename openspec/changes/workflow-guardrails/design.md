# Design

## Context

See proposal.md for why, and `specs/development-workflow` for the rules. Owner decisions (2026-10-11):
- **Refuse, with a logged override.**
- **Edits and commits need a change matching the branch.**
- **Enforcement is layered:** git hooks for every contributor, Claude Code hooks for agent sessions.

Facts about Claude Code hooks, checked against the hooks reference (code.claude.com/docs/en/hooks) on 2026-10-11:
- **Configuration:** `PreToolUse` hooks are set up in `.claude/settings.json` with a `matcher`. `Edit|Write|MultiEdit`
  is read as a list of exact tool names.
- **Input:** the hook receives JSON on stdin (`tool_name`, `tool_input`, `cwd`, …).
- **Refusing:** the hook prints `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
  "permissionDecisionReason": …}}`. A deny always wins over any other hook's answer.
- **Session start:** `SessionStart` hooks can add context through `additionalContext`. They can't block.
- **Windows:** hooks run under Git Bash, or PowerShell when Git Bash is absent. Shell-inspecting hooks should match
  `Bash|PowerShell`. `${CLAUDE_PROJECT_DIR}` is the form that expands under both shells.
- **Failures:** a hook that fails or times out does **not** block unless `onFailure` is `block`.
- **Unverified:** whether a deny applies in `bypassPermissions` and `dontAsk` modes.

**Claude Code hooks aren't a security boundary.** The Edit hook doesn't see a file written through Bash. These
guardrails exist to stop honest shortcuts, not to resist a determined bypass. That is why every rule that matters at
the repository level is also enforced by the git hooks, and later by GitHub's rulesets (#19).

## Goals / Non-Goals

**Goals:**
- One implementation of each rule, shared by the git hooks and the Claude Code hooks.
- Each rule refuses with its name and its fix, and can be overridden only by a person, with the override logged.
- The same behaviour, and passing tests, on Linux, macOS and Windows.

**Non-Goals:**
- Resisting deliberate circumvention by an agent. That needs GitHub rulesets (#19) and review.
- Checking commit scopes against the capability list. That is decided in #23 and can tighten the commit-message rule
  later.
- GitHub-side checks of any kind.

## Decisions

### D1. One guard module, many entry points

`scripts/guard.py` holds every rule as a pure function: facts in, a decision (allow, or refuse with rule, message
and fix) out. Thin entry points gather the facts and act on the decision:

| Entry point | Called by | What it does |
|---|---|---|
| `guard.py pre-commit` | `.githooks/pre-commit` | branch rules, the archived-change rule, then `scripts/check.py` |
| `guard.py commit-msg <file>` | `.githooks/commit-msg` | the Conventional Commits rule |
| `guard.py claude-pre-tool-use` | `.claude/settings.json` PreToolUse | edit rule, PR rule, skip-hooks rule, override protection |
| `guard.py claude-session-start` | `.claude/settings.json` SessionStart | activates the git hooks; adds the workflow as context |
| `guard.py override <rule> --reason …` | a person, in a terminal | grants one override |

It lives in `scripts/` rather than in the `troupe` package, because it is repository tooling, not product. Its tests
go in `scripts/tests/`, which is added to pytest's `testpaths`, so `scripts/check.py` and CI run them. The module
uses only the standard library, so it runs under `uv run --no-sync` without installing anything.

The git hooks are two-line POSIX `sh` shims (`exec uv run --no-sync python "<repo>/scripts/guard.py" <hook> "$@"`).
Git for Windows runs hooks with its own `sh`, so the same shim works there.

**Hook management: plain `core.hooksPath` (owner, 2026-10-11).** Every option needs a one-time activation per clone,
because git never runs hooks from a fresh clone. With plain `core.hooksPath` that step is a single `git config`, which
the session-start hook already runs (D8). The alternatives considered:

| Option | What it needs | Why not now |
|---|---|---|
| husky | Node and npm; installs through npm's `prepare` script | Brings Node into a Python repository just to run hooks |
| pre-commit (Python) | A dev dependency, plus `pre-commit install` per clone | Each hook runs in its own managed environment, so first runs are slower, and it adds a configuration language. Our rules are custom, so it would mostly run `guard.py`. It doesn't help the Claude Code side. |
| lefthook | One binary (also on PyPI), plus `lefthook install` per clone | Its strengths (parallel jobs, staged-file globs) pay off with many hooks; this change has two |
| **plain `core.hooksPath`** | Nothing but git | **Chosen:** no dependencies, no install step for agents, works wherever git does |

**When to revisit:** if the hooks multiply, for example per-file formatters on staged files only, lefthook is the first
candidate. Switching is cheap: the shims are two lines each, and `guard.py` doesn't care what calls it.

### D2. How each layer refuses

- **Git hooks:** exit 1, with the refusal printed to stderr as `guard: <rule>: <problem>` and then `  fix: <fix>`.
  Git aborts the commit, so nothing changes.
- **Claude Code hooks:** exit 0 with the documented `permissionDecision: "deny"` JSON. The reason is the same rule,
  problem and fix text. Every guard handler in `.claude/settings.json` sets `onFailure: "block"`, so a crash or
  timeout refuses instead of silently allowing.

### D2a. Nested git in hooks

While a hook runs, git sets repository-location variables (`GIT_DIR`, `GIT_INDEX_FILE` and others). The pre-commit
check runs the test suite, which makes commits in temporary repositories. If those inherited the variables, they
would act on the outer repository. So every git call the guard makes, and the check it runs, drops exactly those
variables, and keeps every other `GIT_*` setting, which belongs to the user. An early version stripped every
`GIT_*` variable; a test showed that also dropped `GIT_CONFIG_GLOBAL`.

### D3. What "a matching change" means

The branch is `git rev-parse --abbrev-ref HEAD`. During a rebase, HEAD is detached, so the branch name is read from
the rebase state (`.git/rebase-merge/head-name` or `.git/rebase-apply/head-name`). A change matches when either of
these exists:
- `openspec/changes/<branch>/`, an active change;
- `openspec/changes/archive/<YYYY-MM-DD>-<branch>/`, a change archived on that branch before merging.

`main` never matches.

### D4. Checks before commit: tracked files must match what's staged

`scripts/check.py` runs against the working tree, but the commit records the index. So that the check is about "the
work being committed", pre-commit refuses when a tracked file has unstaged changes. The fix it gives: stage them, or
stash them. Untracked files are ignored. Checking out the index into a temporary directory would be exact, but means
a fresh `uv sync` on every commit, which is too slow. Rejected.

**The check is announced, streamed and bounded.** Found on the owner's Windows machine: the first version captured
the check's output, so a first-time `uv` sync plus a minute-long Windows check sat silent and looked hung. That
breaks "never wait silently or indefinitely". The check is now:
- announced on stderr before it starts;
- streamed line by line as it runs;
- stopped, with its whole process tree, after `CHECK_TIMEOUT_SECONDS` (600, defined once in `guard.py`). A
  stopped check refuses the commit with a message naming the timeout.

### D5. Commit messages

First line:
`^(feat|fix|docs|build|ci|test|refactor|perf|style|chore|revert)(\([a-z0-9][a-z0-9-]*\))?!?: \S`

Lines starting `fixup! `, `squash! ` or `amend! ` are accepted, because git writes them for autosquash. A message git
writes for `git revert` (`Revert "…"`) is refused, with the fix "use `revert: …`". A merge commit message is refused
too, which suits a linear history. The scope is free text for now; #23 may restrict it to the capability list.

### D6. Reading Bash commands

The PreToolUse hook splits the command on shell operators (`&&`, `||`, `;`, `|`, newlines), and each part with
`shlex`. It refuses:
- a `git` command carrying `--no-verify`, or `-n` on `git commit`;
- any `core.hooksPath` setting other than `.githooks`, whether through `git config` or `git -c`;
- `gh pr create` unless its `--body` text, or the file named by `--body-file`, contains a closing keyword
  (`Closes`, `Fixes` or `Resolves`, then `#<n>` or a full issue reference);
- `gh pr create` with `--fill` or no body, since the body has to be given;
- any command that runs `guard.py override` or touches the override directory.

Parsing shell text is heuristic. When a command can't be parsed (for example, unbalanced quotes), the hook refuses
rather than guessing, with the fix "simplify the command". A pull request opened through `gh api` isn't detected;
that's a known gap, covered later by #19's required checks.

### D7. Overrides

- **Granting:** a person runs `uv run scripts/guard.py override <rule> --reason "<why>"` in their own terminal. That
  writes `.git/troupe-guard/override.json` (rule, reason, granted by — git `user.email` — and when). It lives under
  `.git/`, so it's never committed and is per-clone.
- **Using:** the next refusal of that rule consumes it. The action is allowed, and a line (rule, reason, granted by,
  granted at, used at, what was allowed) is appended to `.git/troupe-guard/overrides.jsonl`.
- **The agent can't grant one:** the PreToolUse hook refuses Bash commands that run the override command or mention
  `troupe-guard`, and refuses edits under `.git/`. (D1's caveat applies: this stops an honest agent, not a
  determined one.)

Rule ids, which are what an override names: `commit-on-main`, `commit-branch-change`, `commit-message`,
`commit-checks`, `archive-incomplete`, `edit-branch-change`, `pr-closes-issue`, `skip-hooks` and
`command-unparseable` (D6's refuse-when-unparseable path, given its own id while building).

`guard-tamper` is also a rule, but no override unlocks it, so an agent can never unlock the override machinery
itself. The tamper check reads the parsed words of a command, with heredoc bodies removed. That way a commit
message that only *mentions* the override command isn't taken for running it. That was found live, when this
change's own commit was refused.

### D8. Session start

`claude-session-start` reads `git config core.hooksPath`. If it isn't `.githooks`, it sets it (local repository
config only) and says so. It then returns, as `additionalContext`:
- a short statement of the workflow;
- the current branch, and whether a matching change exists.

That way an agent knows on its first turn whether it's in a position to edit.

### D9. CLAUDE.md

A short project `CLAUDE.md`:
- the workflow (issue → change → PR → archive → close);
- where things live;
- that the guardrails refuse shortcuts, and that an agent must not try to work around them but ask the owner.

It links to the org contributing guide instead of repeating it.

### D10. Tests

- **Each rule's pure function** is tested over its cases, including property tests for commit messages and command
  splitting.
- **Each entry point** is tested end to end:
  - the git hooks in a temporary git repository with `core.hooksPath` set, making real commits (with a stub
    `scripts/check.py` that passes or fails);
  - the Claude Code entry points by piping real-shaped PreToolUse and SessionStart JSON into the script and reading
    its output.
- **Overrides** are tested for grant, use once, log, and agent refusal.

### D11. Defaults on, and a server-side layer (owner, 2026-10-11)

The owner's requirements: the guardrails should be on by default outside Claude Code too; commit messages should be
enforced at push time on every branch, so history never needs a force-push to rewrite; and the other rules should
be re-checked on GitHub.

- **On by default:** `scripts/check.py`, which every contributor runs, turns the git hooks on when they aren't,
  the same way the session-start hook does. Git itself never runs hooks from a fresh clone, so the project's own
  tooling is the only place a default can live.
- **`pre-push` hook:** `guard.py pre-push` reads the refs git is about to push. For each, it checks every commit
  not yet on the remote (`<remote>..<local>`, or for a new branch, everything not on any remote branch) with the
  `commit-message` rule. Deleted refs are skipped.
- **Server-side push rejection isn't available on our plan.** A probe on 2026-10-11 used a scratch public repo in
  the free-plan `troupe-run` org. It created an active `commit_message_pattern` ruleset on all branches, which
  GitHub accepted ("bypass: never"), and then pushed non-conforming commits to a new branch, to an existing branch,
  and to `main`. **All three were accepted:** the rule is stored but not enforced. A second probe the same day, in
  the GitHub Team org `hpsgd`, repeated it on a private and a public repository: both accepted a non-conforming
  push to `main` and to a new branch, while a branch-deletion rule in the same private repository refused a
  deletion. So Team enforces rulesets but not metadata rules, and moving the project to a paid Team org wouldn't
  close the gap. GitHub Enterprise would be needed for metadata rules or pre-receive hooks. This is recorded so it
  isn't retried by accident.
- **`guard.py ci`** applies the same rule functions to a range of commits: every message; the branch-change match
  (skipped on `main`); and archived changes touched in the range. A `guard` workflow runs it on every push to every
  branch and on every pull request. A bad push then shows red within a minute, and #19 makes the check required, so
  nothing unchecked can merge.
  - **Range:** for a pull request, `merge-base(origin/main, HEAD)..HEAD`. For a push, `before..after`, or the
    merge-base with `origin/main` when the push creates the branch.
  - **Branch:** the pull request's head branch, or the pushed branch.
- **#23's commit linting** reuses this check instead of adding commitlint. #23 keeps the release tool and the
  PR-title check.

## Risks / Trade-offs

- [The pre-commit check adds 10–15 seconds to every commit (measured while building this; the guard tests
  make real commits in temporary repositories)] → It's the same `scripts/check.py` CI runs, so a
  commit that passes locally passes CI. The time is reported. An emergency skip goes through an override, which is
  logged.
- [Bash parsing misses an unusual command form] → Refuse when parsing fails. The git hooks and #19 are the backstop.
- [Unverified: a deny may not apply in bypass-permissions mode] → The git hooks still apply in every mode. To verify
  in task 6.x by running a refused edit in that mode, and to record the result.
- [The rules bind this change's own implementation part-way through] → Expected, and useful: the guardrails start
  working on the change that builds them.

## Migration Plan

- Existing clones activate the hooks once with `git config core.hooksPath .githooks`. The README says so, and Claude
  Code sessions do it automatically.
- Branches created before this change still work: each is named after its change.

## Open Questions

- Whether a PreToolUse deny applies in `bypassPermissions` and `dontAsk` modes is unverified. It doesn't change the
  design, because the git hooks are the backstop. Task 6.3 records the result.
