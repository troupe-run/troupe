---
title: "Flows: fork, join, swarm, loop"
description: How work branches.
status: written
prerelease: true
---

A flow is how work moves through your process. troupe is built toward work that branches: tasks fork, join, swarm
and loop, instead of one agent working in a line. The first kind of flow is a sequence: actors that work one after
another.

## A sequence of actors

A flow in your config names actors in order. [Build a flow](../stagecraft/build-a-flow.md) shows how to write one.
`troupe perform <flow>` runs its steps one after another as one [performance](performances-and-runs.md), each step a
run:

- **Each step builds on the work before it.** A step works in its own worktree, made from the work of the steps
  before it, so your files don't change while the flow runs.
- **Each step is told what came before.** It gets the direction you gave the flow, its own direction, the previous
  step's brief, and one line for each earlier step. Each earlier step's brief, diff and log are in its worktree, under
  `.troupe/performance/`.
- **A [gate](gates-and-decisions.md) sits after every step.** Before the last step, troupe lets the work go on by
  itself, unless the step's approvers put a person first: then the flow waits for them. The last step's gate keeps the
  whole flow's work at once, as a single run's gate keeps its own.
- **A step that doesn't succeed stops the flow**, and the performance ends failed. Nothing reaches your files.

## Not decided yet

Forking and joining ([#145](https://github.com/troupe-run/troupe/issues/145)), looping
([#146](https://github.com/troupe-run/troupe/issues/146)) and swarming
([#147](https://github.com/troupe-run/troupe/issues/147)) come later, and each decides then what it means.
