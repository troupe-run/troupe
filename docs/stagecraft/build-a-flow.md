---
title: Build a flow
description: Designing how work moves.
status: written
prerelease: true
---

A flow runs several actors one after another, as one [performance](../the-company/performances-and-runs.md). Each
step builds on the work of the steps before it. This page shows how to write one. [Flows](../the-company/flows.md)
says how they work.

## Write a flow

A flow is part of your config, like an actor. Each flow has its own file, `.troupe/flows/<name>.yaml`, holding its
steps in the order they run:

```yaml
steps:
  - actor: writer
  - actor: reviewer
    direction: Review what the writer changed, and fix what's wrong.
  - actor: tester
```

Or set it with `troupe config set`:

```sh
troupe config set 'flows.review.steps=[{"actor": "writer"}, {"actor": "reviewer", "direction": "Review what the writer changed."}, {"actor": "tester"}]'
```

Each step has:

| Field | Required | What it is |
|---|---|---|
| `actor` | Yes | The actor the step runs, by its name in your config |
| `direction` | No | What this step is asked to do, on top of the direction you give the whole flow |
| `approvers` | No | Who may let this step's work through, written as an actor's [approvers](../the-company/gates-and-decisions.md) are. Without it, the step uses its actor's approvers, or troupe's default |

## What a flow must hold

troupe refuses a flow it couldn't perform, when you set it or when it sweeps a hand edit, naming the flow, the step
and what's wrong:

- **At least one step.**
- **Each step names an actor your config has.** Removing an actor a flow uses is refused too, naming the flow.
- **Each step's actor works in its own worktree.** A flow's steps build on each other away from your files, so an
  actor that works in the theatre (`workspace: theatre`) can't be a step.
- **A flow's name isn't an actor's.** Flows and actors share one set of names, so `troupe perform <name>` knows
  which to run.

The same actor can appear in more than one step: writer, reviewer, writer is a valid flow.

## Rename a flow, or its actors

`troupe config mv flows.review flows.check` renames a flow and moves its file. Renaming an actor, with
`troupe config mv actors.writer actors.author`, also renames it in every flow step that names it, in the same change.
