---
title: Read the lineage
description: Following the record.
status: written
prerelease: true
---

Every event troupe records carries its [lineage](../the-company/lineage.md): who, through what, when, why, and as
part of what. This page shows how to answer questions about runs from it today, including who let a run's work
through its [gate](../the-company/gates-and-decisions.md). Saying which person held which role needs
[roles](../the-company/roles-and-actors.md), which aren't built yet.

## Who ran this, and on what?

```sh
troupe status <run>
```

`troupe status` with a run's id, or its first 8 characters, shows the run: its actor, who started it, its runner,
its stage, its state, its outcome and error, what the audit of its changes found, how many events it has, its times,
and references to its transcript and standard error. Without an id, it lists the most recent runs, newest first. A
run whose `troupe perform` was killed before it recorded an end shows as `interrupted`
([A run's state](../the-company/performances-and-runs.md#a-runs-state)).

## What happened, in order?

```sh
troupe logs <run>
```

`troupe logs` shows each of a run's events in order, with when troupe recorded it, then the run's outcome, what
its audit found, and what happened at its gate. Add `--follow` to keep watching until the run ends.

## Who let its work through?

`troupe status <run>` shows a worktree run's approvers, with where they came from, and each step at its gate: a pass
when troupe couldn't keep the changes, the cue that asked you, and the answer, with who gave it, in which role, and
why. troupe's own approval shows as `core@<host>`, troupe acting by itself. In the event files, the event that kept
the work carries the approval in its lineage's `approvals`.

## The whole record

Add `--json` to either command to get its answer in full, in the shape troupe's
[client protocol](https://github.com/troupe-run/troupe/tree/main/protocol/schemas/client/) gives it, for a script or
another tool to read. `troupe status <run> --json` includes who started the run (`startedBy`, with where their id
came from) and its `stage`: whether troupe could enforce what the actor touched and, if it couldn't, the policy
setting that let it run anyway.

```sh
troupe status <run> --json
```

Each event's full lineage is in the event files themselves, in `.troupe/events/`, one JSON record per line. There,
every event of a run carries the same `change` id, so you can tell what one command caused, and each event's `cause`
says whether the command made it directly or it was recorded in reaction to another event. Every event of a run, and
of the performance it's part of, names that performance in its `performance`, so you can gather everything one
`troupe perform` led to, including an approval given later. No command shows that part yet.

## In git

The history is text in `.troupe/events/`, one event per line, committed with the rest of your theatre. So git's own
tools work on it too: `git log .troupe/events/` shows when each part of the history was committed, and by whom.

## Still to come

- **Which person, in which role.** Lineage records the raw identity today, such as an email address. Mapping it to
  a person, and recording the role they acted in, waits on roles
  ([#61](https://github.com/troupe-run/troupe/issues/61), [#44](https://github.com/troupe-run/troupe/issues/44)).
- **Approvals from other roles.** Every approval is in role `troupe` or `director` until roles config lets a gate
  name others ([#148](https://github.com/troupe-run/troupe/issues/148)).
