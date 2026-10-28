# Design

## Context

See proposal.md, Why. What's already in place, checked on 2026-10-28:

- `main`'s ruleset ("protect main") has a `merge_queue` rule (`merge_method: REBASE`, `ALLGREEN`), requires `check`,
  `DCO` and `guard (workflow rules)`, allows only rebase merges, and has `required_review_thread_resolution: true`.
- `.github/workflows/claude-review.yml` is delivered from infrastructure (5f37b3a); its workflow is named
  `claude review`.
- `gh pr merge --help` (gh's own text): on a branch with a merge queue, no merge strategy is needed; it enables
  auto-merge if required checks haven't passed yet, or adds the pull request to the queue if they have; `--admin`
  bypasses the queue.
- infrastructure's `openspec/config.yaml` Working list and its CLAUDE.md step 5 hold the wording this change follows.
  infrastructure's config line has grown a sentence since #185 quoted it (re-running the review after a must-fix
  answered without a push).
- No test reads `CLAUDE.md`, and `check-paths.toml` forbids any test reading `openspec/**`. So the checks here are
  by reading and by `openspec instructions`, not by a test (Risks).

## Goals / Non-Goals

**Goals:**
- A session reading troupe's CLAUDE.md, or proposing a change here, learns the same review and merge path as one in
  infrastructure, in the same words where the two repositories work the same way.

**Non-Goals:**
- Restating infrastructure's `docs/development-workflow.md`. CLAUDE.md says what to do and links there for how the
  tiers and the review's own resolving work.
- Saying who merges. Neither issue asks for it, and troupe's CLAUDE.md doesn't say today.

## Decisions

**D1. The config line is infrastructure's current line, with its reference qualified.** It goes last in the Working
list, after "Commit in small steps", as infrastructure has it:

```yaml
  - Before archiving, wait for Claude's review of the last push and act on each finding by its tier: fix or answer
    every must-fix and nit, resolve only nits, and raise decisions and disputed must-fixes with the owner. The
    review resolves its own must-fixes (troupe-run/infrastructure docs/development-workflow.md, "Claude's review");
    after answering a must-fix without a push, re-run the last `claude review` run (`gh run rerun <id>`) so the
    review judges the reply.
```

It includes the re-run sentence #185's quote predates: without it, a must-fix answered by reply stays unresolved and
blocks the merge, and troupe's workflow has the same name, so the command works here unchanged. Rejected: #185's
quote word for word, which would leave troupe one step behind infrastructure on the day it lands. Rejected: a
`rules: tasks:` entry instead of context. The context is where troupe keeps every working convention and reaches
every artifact, and infrastructure put it there, so the two stay comparable line by line.

**D2. The merge text goes in the archive step, not a step of its own.** The archive step already says "before
merging", so the merge belongs right after it:

```markdown
6. **`/opsx:archive`** runs on the branch before merging, so the PR lands code, tests and specs together. The pull
   request then goes into the merge queue, which merges it by rebase once `check`, `guard (workflow rules)` and `DCO`
   pass on the commit it tested: `gh pr merge <n>`, or "Merge when ready", queues it. `gh pr merge <n> --rebase
   --admin` skips the queue, and is only for emergencies, such as clearing a stuck queue.
```

"Queues it" is accurate whether or not checks have passed yet: gh enables auto-merge, which adds it to the queue when
they do. Rejected: a separate "merge" step, which would make the list eight steps for one sentence of how.

**D3. The review step is a new step 5, as infrastructure's is.** Owner, 2026-10-28: CLAUDE.md gets it as well as the
config line. It sits between the pull request and the archive, because the archive waits on it:

```markdown
5. **Claude's review is acted on**, after the review of the last push: fix or answer each finding, resolve only nits,
   and raise decisions and disputed must-fixes with the owner. The review resolves its own must-fixes once they're
   addressed; for a must-fix answered without a push, re-run the last `claude review` run (`gh run rerun <id>`). A
   merge needs every conversation resolved ([development-workflow.md, "Claude's review"](https://github.com/troupe-run/infrastructure/blob/main/docs/development-workflow.md#claudes-review)).
```

It's infrastructure's step 5 with the link made absolute, since the document lives in infrastructure. The archive and
after-merge steps renumber to 6 and 7. Nothing else in troupe cites CLAUDE.md's step numbers (task 2.3 checks).

## Risks / Trade-offs

- [No test catches drift between troupe's and infrastructure's wording] → Accepted: neither file is testable here
  (Context). The tasks diff each new text against infrastructure's by script, so they start out the same.
- [A broken link or anchor in CLAUDE.md] → Task 2.2 checks the anchor's heading from infrastructure.
- [`--admin` gets used as a shortcut] → The step names it an emergency path only. The guard, not CLAUDE.md, is what
  enforces the path (Guardrails section).

## Migration Plan

Two commits, one per file, so each carries its own issue: the config line (#185), then CLAUDE.md (#184 and #185).
Rollback: revert them.
