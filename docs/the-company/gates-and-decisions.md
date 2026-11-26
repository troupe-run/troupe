---
title: Gates and decisions
description: Where work waits for a person.
status: written
prerelease: true
---

A **gate** is a point where work waits for a decision from whoever owns it. Every run that works in its own
worktree passes one when it ends: its actor's **approvers** say who may let its work through. Gates between the
steps of a [flow](flows.md), and gates addressed to roles you define, come later
([#124](https://github.com/troupe-run/troupe/issues/124), [#148](https://github.com/troupe-run/troupe/issues/148)).

## Who approves

An actor lists its approvers in order, in its config:

```yaml
approvers: [troupe, director]
```

- **`troupe`** is troupe itself. It approves a run whose changes apply cleanly to your files, and keeps them: so by
  default, work lands without anyone having to accept it. When the changes conflict with what you've changed since,
  it can't act, and passes the gate to the next approver.
- **`director`** is held by whoever runs troupe in the theatre. When the gate reaches it, the run waits for you.

An actor that sets no approvers gets `troupe`, then `director`. `approvers: [director]` makes every run wait for you,
as the [first run](../opening-night/first-performance.md)'s example actor does. A list must end with `director`,
so work never waits with nobody asked, and `troupe` can come only first. An actor that works in the theatre
(`workspace: theatre`) has no gate: its work lands as it's made.

Only a run that succeeded with changes reaches its gate. A run that failed or was cancelled leaves its changes for
you to `troupe accept` or `troupe discard`, as before.

## When a run waits for you

A gate that reaches `director` raises a **cue**: an open request to a role, with a brief. It says whose run it was,
how it ended, what it changed, and why it came to you, such as the files that conflict. ("Cue" is a provisional
name.)

- `troupe perform` says the run waits, and exits 4.
- `troupe status` lists every open cue above the runs.
- `troupe diff <run>` shows the changes. `troupe approve <run>` keeps them, and `troupe reject <run>` throws them
  away. Both take `--reason` and `--rehearse`. While a cue is open, `troupe accept` and `troupe discard` are refused,
  so nothing gets round the gate.

## The answer is recorded

Every answer is recorded with its [lineage](lineage.md): who answered, in which role, why, and when. The event that
keeps a run's work carries the approval in its `approvals`: troupe's own, in role `troupe`, or a person's, in role
`director`. `troupe status <run>` shows a run's approvers and each step at its gate.

## Decisions go to roles

- **A gate is addressed to a role,** never to "the human" or to a particular person. Whoever holds the role, a
  person or an agent, picks it up. So when someone else takes the role over, decisions follow them without your
  process changing. See [Roles and actors](roles-and-actors.md).
- **Until roles exist, `director` is the only role a person answers in,** and any person who runs troupe in the
  theatre holds it. An agent can't answer a cue yet. Roles config will say who holds `director`, and add roles of
  your own ([#61](https://github.com/troupe-run/troupe/issues/61), [#148](https://github.com/troupe-run/troupe/issues/148)).
- **An [escalation](escalation.md)** that can't resolve itself will raise a cue too
  ([#126](https://github.com/troupe-run/troupe/issues/126)).

## Nobody has to be watching

The [house](the-house.md) will run whether or not anyone's at a terminal, so a cue can reach whoever owns it as soon
as it's raised, not when someone happens to look. Until then, you find cues with `troupe status`.

## Across computers

The person who owns a decision may be working on another computer, with their own copy of the theatre. Nothing
about gates may only work for one person on one computer. How a cue reaches them and how their answer comes back,
whether through git or another transport, isn't decided yet: it's open in
[#12](https://github.com/troupe-run/troupe/issues/12).
