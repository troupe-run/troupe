# Proposal

## Why

troupe#124 brings flows, starting with actors in sequence. Its first change, `performances` (#546, merged in #545),
made every perform a performance with one step. This second change gives a performance several steps: a **flow** in
config names actors in order, and performing it runs them one after another, each building on the work before.

The owner's decisions on #124 (2026-11-27/28) set the shape. A sequence runs unattended unless a gate stops it:
"needing to accept every run defeats the purpose of what we are orchestrating". This change closes #124.

## What Changes

- **A new config kind, `flows`** (decision 1).
  - One file per flow, `.troupe/flows/<name>.yaml`, holding an ordered list of steps. Each step names an actor, and
    may give that step's own `direction` and `approvers`.
  - Flows and actors share one namespace: a flow named like an actor is refused, naming both.
  - These are refused:
    - a step naming an actor that doesn't exist;
    - removing an actor a flow uses;
    - an empty step list;
    - a step whose actor works in the theatre.
  - Renaming an actor carries the flows that name it, as renaming a runtime carries its actors. A flow can be
    renamed.
- **`troupe perform <flow>` performs a flow** (decisions 2 and 2b). It records one performance, with one step per
  actor and one run per step. It prints the performance id once, then `step <n>/<total> <actor>: run <id>` as each
  step starts. `--rehearse` checks every step's actor first, and one refusal refuses the whole flow.
- **Each step builds on the steps before it** (decision 3).
  - Each step gets its own worktree, made at HEAD with the performance's changes so far applied to it.
  - Its diff holds only what that step changed.
  - Your files are untouched until the flow's end.
- **What a step is told** (decision 3c):
  - up front: the performance's direction, the step's own direction, the previous step's brief in full (actor,
    outcome, files changed, final message), and one line for each earlier step;
  - on demand: read-only history files in `.troupe/performance/<n>-<actor>/` for every earlier step (brief, diff,
    log). They're never part of a diff.
- **Gates between steps** (decision 4a).
  - Every step with changes passes a gate. A step's approvers come from the step, else its actor, else
    `[troupe, director]`.
  - Before the last step, approving means "go on", recorded as a new `Run.ChangesApproved` event carrying the
    approval.
  - The last step's gate applies the whole performance's diff to your files, all or nothing. It's passed whenever the
    performance has changes.
  - **Lineage's approval rule widens** from "the event that keeps the work" to "the event that lets it through".
- **Carrying on, stopping and settling** (decision 4b).
  - `troupe approve <performance>` records the approval, then runs the remaining steps in the foreground, with
    config as it was at the performance's start. It exits as perform does.
  - `troupe reject` ends the performance `rejected`, removing every worktree it made.
  - A failed step ends it `failed`. Its work so far is accepted or discarded whole through the performance, and
    naming one of its runs is refused.
  - Ctrl-C ends it `cancelled`. A waiting performance never times out.
- **Reading a flow back** (the two calls `performances` deferred).
  - `troupe status` shows one line per performance. A flow's line shows its progress, with its runs indented under
    it.
  - A performance id names the step waiting at a gate, when one waits.
  - `troupe diff <performance>` shows the whole flow's change so far.
- **Docs:** `docs/the-company/flows.md` and `docs/stagecraft/build-a-flow.md` are written in full. Performances and
  runs, gates and decisions, the glossary (flow, step), the config schema, the events reference and the CLI reference
  are updated.

**BREAKING** (protocol): a new event topic (`Run.ChangesApproved`), the `flow` kind in `Performance.Started`'s
`performed`, a new config schema, and status and approve results that change shape.

## Capabilities

### New Capabilities

- `flows`: how a flow is defined and performed in sequence. Covers the `flows` config kind and its rules (in this spec
  rather than `config`, whose spec is near the size gate), what each step works on and is told, the history it can
  read, gates between steps, and carrying a waiting flow on.

### Modified Capabilities

- `config-files`: each flow is projected to `.troupe/flows/<name>.yaml`.
- `config-renames`: an actor's rename carries the flows that name it, and a flow can be renamed.
- `performances`: performances of several steps. Ids name the step waiting at a gate, a failed or interrupted
  performance is settled whole, and status groups a flow's runs.
- `gates`: what a gate means between steps, `Run.ChangesApproved`, and approve carrying a flow on.
- `lineage`: approvals come from the event that lets a run's work through its gate.

## Impact

- **Code:**
  - `troupe.core.config` (the kind, its schema-generated model, cross-kind rules, projection, renames);
  - `troupe.core.runs` (perform split into a performance driver that runs steps, per-step worktrees, briefs and
    history files, gates between steps, approve carrying on, settling a performance whole);
  - the VCS port and its git adapter (applying a diff inside a worktree and capturing against the tree that leaves);
  - client messages and the CLI.
- **Protocol:**
  - `config/flow.schema.json`;
  - `run-changes-approved.schema.json`;
  - `performance-started`'s `performed` and `steps` widened;
  - status, logs and approve results and updates.

  This is a breaking release.
- **Specs:** a new `flows` spec, so troupe-run/infrastructure needs its Purpose recorded after this merges. `cap:flows`
  exists. `cap:config`'s description, which lists only actors and runtimes, needs updating then too.
- **Size:** large. The tasks are grouped so that each group lands as its own reviewable push on one pull request. If
  a push grows past what the review reads well, the orchestrator is told before anything is split.
