---
title: "Flows: fork, join, swarm, loop"
description: How work branches.
status: written
prerelease: true
---

A flow is how work moves through your process. troupe is built toward work that branches: tasks fork, join, swarm
and loop, instead of one agent working in a line.

Flows aren't built, and almost nothing about them is decided yet. Today troupe runs one actor at a time
([Performances and runs](performances-and-runs.md)).

## What's decided

- **Tasks fork, join, swarm and loop.** That's the aim, from troupe's [principles](../programme/principles.md).
- **A flow can stop at a [gate](gates-and-decisions.md)** that needs a role's approval.

## Not decided yet

What a flow is in your config, what forking, joining, swarming and looping each mean, how a flow relates to a
performance and its runs, and how its progress is recorded: all of these are open, in
[#124](https://github.com/troupe-run/troupe/issues/124). [Build a flow](../stagecraft/build-a-flow.md) will show how to
write one once they're decided.
