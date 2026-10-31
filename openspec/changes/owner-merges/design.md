# Design

## Context

CLAUDE.md's step 6 today (see proposal.md, Why):

> **`/opsx:archive`** runs on the branch before merging, so the PR lands code, tests and specs together. The pull
> request then goes into the merge queue, which merges it by rebase once `check`, `guard (workflow rules)` and `DCO`
> pass on the commit it tested: `gh pr merge <n>`, or "Merge when ready", queues it. `gh pr merge <n> --rebase
> --admin` skips the queue, and is only for emergencies, such as clearing a stuck queue.

infrastructure's CLAUDE.md step 6: "**`/opsx:archive`** runs on the branch before merging. The owner merges by rebase,
through the merge queue." Its `docs/development-workflow.md` lists `owner-only`, which refuses an agent's
`gh pr merge` (with or without `--admin`, and the API and GraphQL routes to the same), and says the owner merges only
once every conversation is resolved.

## Goals / Non-Goals

**Goals:**

- Step 6 says who merges, and what the agent does at that point, so no session reaches for `gh pr merge`.
- It stays consistent with infrastructure's step 6 and with website#79's fix.

**Non-Goals:**

- Writing down how the owner merges (the commands, the emergency route). That's the owner's, and the workflow doc
  covers the queue.

## Decisions

### D1. The new step 6

> 6. **`/opsx:archive`** runs on the branch before merging, so the PR lands code, tests and specs together. **The
>    owner merges** by rebase, through the merge queue, which lands the pull request once `check`,
>    `guard (workflow rules)` and `DCO` pass on the commit it tested. Once every check passes and every conversation
>    is resolved, ask the owner to merge it. The guard refuses `gh pr merge` from an agent (`owner-only`), with or
>    without `--admin`.

- Keeps step 6's first sentence and the queue's required checks, which are troupe-specific and still true.
- "The owner merges by rebase, through the merge queue" is infrastructure's wording, so the two repositories read the
  same.
- "Every check passes and every conversation is resolved" is when the pull request can merge: the ruleset needs both
  (step 5 already says "A merge needs every conversation resolved"). Asking earlier would hand the owner a pull
  request that can't merge yet.
- Naming `owner-only` tells a session the refusal is expected, and what to look up, rather than leaving it to find
  out by trying.

Alternative: copy infrastructure's two sentences only. Rejected: it drops the queue's checks, which tell the agent
what "every check passes" means here, and says nothing about what the agent does.

### D2. The `--admin` emergency route goes

The old text told the reader `gh pr merge <n> --rebase --admin` skips the queue in emergencies. That's the owner's
decision and the owner's command; written in an agent's instructions, it reads as a route the agent may take. The
guard refuses it anyway. infrastructure's step 6 doesn't mention it either.

Alternative: keep it, marked "the owner's only". Rejected: the step is read by agents, and the owner doesn't need
CLAUDE.md to know the route exists.

## Risks / Trade-offs

- [The wording drifts from website#79's] → at apply, if website#79's pull request exists, compare its step with D1
  and note any difference in the pull request. A difference in wording is cosmetic as long as both say the owner
  merges and the agent asks.
- [The guard's rule changes later] → the step names the rule by its id (`owner-only`), which the workflow doc keys
  its table by, so a change there is easy to find from here.
