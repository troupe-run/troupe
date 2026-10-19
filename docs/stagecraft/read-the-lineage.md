---
title: Read the lineage
description: Following the record.
status: written
prerelease: true
---

Every event troupe records carries its [lineage](../the-company/lineage.md): who, through what, when, why, and as
part of what. This page shows how to answer questions about runs from it today. Answering "who decided this?" for a
decision needs [gates](../the-company/gates-and-decisions.md) and [roles](../the-company/roles-and-actors.md), which
aren't built yet.

## Who ran this, and on what?

```sh
troupe status <run>
```

`troupe status` with a run's id, or its first 8 characters, shows the run: its actor, who started it, its runner,
its stage, its state, its outcome and error, how many events it has, its times, and references to its transcript
and standard error. Without an id, it lists the most recent runs, newest first.

## What happened, in order?

```sh
troupe logs <run>
```

`troupe logs` shows each of a run's events in order, with when troupe recorded it. Add `--follow` to keep watching
until the run ends.

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
says whether the command made it directly or it was recorded in reaction to another event. No command shows that
part yet.

## In git

The history is text in `.troupe/events/`, one event per line, committed with the rest of your theatre. So git's own
tools work on it too: `git log .troupe/events/` shows when each part of the history was committed, and by whom.

## Still to come

- **Which person, in which role.** Lineage records the raw identity today, such as an email address. Mapping it to
  a person, and recording the role they acted in, waits on roles
  ([#61](https://github.com/troupe-run/troupe/issues/61), [#44](https://github.com/troupe-run/troupe/issues/44)).
- **Who approved it.** `approvals` fills in once gates exist
  ([#62](https://github.com/troupe-run/troupe/issues/62)).
