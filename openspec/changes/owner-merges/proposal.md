# Proposal

## Why

CLAUDE.md's step 6 reads as if the agent queues its own pull request: "`gh pr merge <n>`, or "Merge when ready",
queues it", with `gh pr merge <n> --rebase --admin` for emergencies. The guard refuses every `gh pr merge` from an
agent as `owner-only`, `--admin` or not (infrastructure `docs/development-workflow.md`, the `owner-only` rule): only
the owner merges a pull request, queues it or turns on its auto-merge. An agent following website's same wording hit
that refusal on troupe-run/website#78 (2026-10-31). The step should say who merges and what the agent does instead
(#207).

## What Changes

- **CLAUDE.md's step 6 says the owner merges**, by rebase, through the merge queue, as infrastructure's CLAUDE.md has
  it ("The owner merges by rebase, through the merge queue"). It keeps what the queue waits for (`check`,
  `guard (workflow rules)` and `DCO` passing on the commit it tested).
- **The step says what the agent does instead:** once every check passes and every conversation is resolved, it asks
  the owner to merge. It names the guard's `owner-only` refusal, so a session that reads the step doesn't try
  `gh pr merge` first.
- **The `gh pr merge` and `--admin` instructions go.** Both are the owner's, and the `--admin` emergency route is the
  owner's call, as infrastructure's step 6 leaves it (design D2).

Out of scope:

- **The guard rule itself, and the ruleset.** They're infrastructure's, and already say this.
- **website's CLAUDE.md.** troupe-run/website#79 is the same fix there, made in that repository.
- **Archived changes.** `2026-10-28-merge-queue-and-review-docs` mentions `gh pr merge <n>` in its tasks' follow-up;
  an archive is a record of what was planned then, and isn't rewritten.
- **Steps 1 to 5 and 7, and the Guardrails section.** They stay as they are.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. No requirement changes: CLAUDE.md is contributor guidance, which no spec describes. A search of
`openspec/specs/` and `openspec/config.yaml` finds no text that repeats step 6 (`gh pr merge`, "Merge when ready",
`--admin`, or who merges), so #207's "any spec that repeats it" has nothing to change. The change sets
`skip_specs: true`.

## Impact

- Changed: `CLAUDE.md`, step 6 only. No code, tests or specs.
- Checks: `CLAUDE.md` is in no `check-paths.toml` group, so its commit runs the full check.
- Follow-ups: after the merge, comment on #207 with the pull request and the archived change. This change's own
  pull request is the first to follow the new step: the agent asks the owner to merge it. Rollback: revert.
