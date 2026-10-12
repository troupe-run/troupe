# Design

## Context

See proposal.md for why. The `context:` block is plain prose that OpenSpec passes to every artifact (its limit is
51,200 bytes; the file is about 4.9 KB). Nothing parses it, and no test reads it. `plugins/README.md` is linked from
`README.md`'s layout table, which already calls `plugins/` "out-of-process plugins" and stays correct.

## Goals / Non-Goals

**Goals:**
- Each rule states the decision as taken, in the context's own voice, without restating the decision issues.
- Every line that the decisions changed is updated, not only the one #37 names.

**Non-Goals:**
- Reorganising or rewording the rest of the context. Lines the decisions don't touch stay byte for byte as they are.

## Decisions

### D1. The wording, line by line

**Replaces "Third-party code only ever runs out of process":**
> - Every port is defined in core, with a direct (in-process) and a JSON-RPC transport. Core, the adapters bundled
>   with it and the libraries it pins run direct. Plugins, ours included, and anything acquired by config run over
>   JSON-RPC. In-process code is trusted and its effects aren't enforced; policy can restrict which transports are
>   allowed. Neither transport is a sandbox: stages and policy decide what code can touch.

This corrects #37's draft, which said "what ships with troupe runs direct". Our own runners ship in this repo but
run over JSON-RPC (#34; #37 itself says "JSON-RPC first is right" for runners), so the line is drawn between core
with its bundled adapters and everything else, not between shipped and acquired. A comment on #37 records the
correction.

**The pluggable-extensions line** keeps its first sentence and qualifies the second:
> - Stages (sandboxes), actor runners, notification channels and guests are pluggable. Declared effects are enforced
>   on code that runs over JSON-RPC.

**The repo-layout line:**
> - One repo until 1.0: packages/ (core and its bundled adapters, run direct), plugins/ (JSON-RPC plugins, ours
>   included), protocol/ (language-neutral). Plugins stay self-contained so they can be split into their own repos
>   later. The site and other deliverables live in their own repos.

**The lineage line:**
> - Every event carries lineage: actor (human, agent, or explicit unknown, never null), via, time, reason, change id
>   (the correlation ID that one command's events share, and that events recorded in reaction to them inherit), cause
>   (the command, or the event it was recorded in reaction to), approvals. Fail when there is no identity.

**New, directly after "Refuse rather than guess":**
> - A malformed or ambiguous input is an error that names the input and the fix, never a quiet fall-through to a
>   default. Only an absent input may fall through.

Alternative considered: a separate "Decisions" list in the context that links each issue. Rejected: the context is
for constraints an agent can't infer, and a list of links invites reading the issues instead of applying the rule.

### D2. `plugins/README.md`

- **Opening paragraph:** "Out-of-process plugins: actor runners, stages, guests and notification channels. They run
  over JSON-RPC, ours included, so declared effects can be enforced on them and a plugin can be written in any
  language (decision #37)."
- **The in-process adapters paragraph:** "Adapters bundled with troupe (storage, version control, built-in identity
  sources) are not plugins. They live under `packages/` and run direct, in process, because they ship with core and
  sit deep in the house. #37 gives every port a JSON-RPC transport too, so an adapter acquired by config runs as a
  plugin (#38)."
- The rules list between them is unchanged.

### D3. Overlap with #34

#34 (runner contract) edits `plugins/README.md`'s rules list and its last paragraph. This change edits the opening
paragraph and the in-process adapters paragraph, which sit next to #34's last edit. Whichever change lands second
rebases onto `main` (never merges) and resolves the adjacent hunk by keeping both edits. `config.yaml` isn't
touched by #34 or #35.

## Risks / Trade-offs

- [The context grows, and every artifact pays for it in tokens] → About 600 bytes net, well inside the limit. Each
  new clause replaces a rule that was wrong, rather than adding commentary.
- [In-flight designs (#34, #35) cite the old rule or #37's draft] → Both have already been reworded around #37 in
  their own sessions; neither copies the context into its artifacts.

## Migration Plan

None. Rolling back is reverting the commit.
