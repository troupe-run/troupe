# Development workflow guardrails

This repository enforces its own workflow (spec: `openspec/specs/development-workflow`). The path every change takes
is in the org's [contributing guide](https://github.com/troupe-run/.github/blob/main/CONTRIBUTING.md). This page
lists what the guardrails refuse and how an override works.

Two layers enforce the rules. Both call the same rules in `scripts/guard.py`:

- **Git hooks** (`.githooks/`) apply to everyone, human or agent. Turn them on once per clone with
  `git config core.hooksPath .githooks`. Claude Code sessions do this automatically at start-up.
- **Claude Code hooks** (`.claude/settings.json`) apply to agent sessions, before a tool runs.

Every refusal names its rule and its fix:

```
guard: commit-on-main: commits aren't made on main; work reaches main through a pull request.
  fix: Create a branch named after the OpenSpec change: git switch -c <change-name>
```

## Rules

| Rule | Layer | Refuses | Fix |
|---|---|---|---|
| `commit-on-main` | git | a commit with `main` checked out | create a branch named after the change |
| `commit-branch-change` | git | a commit on a branch with no matching OpenSpec change (active, or archived on that branch), or on a detached HEAD | propose the change, or switch to its branch |
| `commit-message` | git | a first line that isn't a Conventional Commit (`type(scope)!: subject`); `fixup!`, `squash!` and `amend!` are accepted | use one of `feat fix docs build ci test refactor perf style chore revert` |
| `commit-checks` | git | a commit while tracked files have unstaged changes, or while `scripts/check.py` fails | stage or stash the changes; fix what the check reports |
| `archive-incomplete` | git | a commit that adds an archived change with an unticked task | finish and tick every task first |
| `edit-branch-change` | Claude | an Edit, Write, MultiEdit or NotebookEdit to a repository file when the branch has no matching change | switch to, or create, the change's branch |
| `pr-closes-issue` | Claude | `gh pr create` whose `--body` or `--body-file` doesn't close an issue, or that uses `--fill` or stdin | add `Closes #<issue>` |
| `skip-hooks` | Claude | `--no-verify`, `git commit -n`, and setting, unsetting or overriding `core.hooksPath` | fix what the hook reports |
| `command-unparseable` | Claude | a `git` or `gh` command that can't be parsed (for example, unbalanced quotes) | simplify the command |
| `guard-tamper` | Claude | running the override command, naming a path in the override directory, or editing under `.git/`. **No override unlocks this rule.** | ask the owner |

The pre-commit check runs the full `scripts/check.py`, which takes 10–15 seconds at present. It's the same check CI
runs, so a commit that passes locally passes CI.

## Overrides

Only a person can grant an override, from their own terminal, never through an agent's tool calls:

```console
uv run scripts/guard.py override commit-on-main --reason "hotfix while CI is down"
```

- **One action:** the override applies to the next refusal of that rule, and is then used up.
- **Recorded:** it's stored under `.git/troupe-guard/`, which is local and never committed, with the reason, your
  git `user.email` and the time.
- **Logged:** each use appends a line to `.git/troupe-guard/overrides.jsonl`: the rule, the reason, who granted
  it, when it was granted and used, and what it let through.
- **Not for `guard-tamper`:** that rule can't be overridden.

## Known gaps

- **These hooks aren't a security boundary.** They stop honest shortcuts. A Bash command that writes a file isn't
  seen by the edit hook, though the git hooks catch it at commit time. A determined bypass is still possible.
  GitHub's rulesets and required checks (#19) are the hard backstop.
- **Pull requests opened through `gh api`** aren't checked for a closing reference. #19's required checks cover
  that.
- **Bash parsing is heuristic.** When a `git` or `gh` command can't be parsed, it's refused rather than guessed at.
- **Permission modes:** whether a Claude Code hook's deny applies in `bypassPermissions` mode is recorded here once
  verified (task 6.3 of `workflow-guardrails`). The git hooks apply in every mode.
