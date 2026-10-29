---
title: Events
description: Every event troupe records, and its fields.
status: written
prerelease: false
---

troupe records what happens as events, in your theatre's `.troupe/events/`: one line per event, appended and never
rewritten, so git can merge two people's history. Everything else troupe shows you, such as a run's state, is read
back from these events.

Every event carries its [lineage](../the-company/lineage.md): who made it, through what, when, why, as part of which
command, with whose approval, and in what version-control state. Lineage is listed once, at the end.

Today troupe records runs: a run's first event, one event for each thing its runner reports, and its last event.
More events arrive as troupe grows, each listed here as it does. The tables below are generated from troupe's
schemas, so they can't drift from what troupe writes.

## The events

<!-- generated: events (from protocol/schemas/events/ and lineage; regenerate with `uv run scripts/docs_reference.py`) -->
### Config.Changed

The payload of one config change (topic troupe.core.config.aggregate:Config.Changed): every value one command changed, and every config file it wrote or removed. One command records exactly one. Field names are as recorded.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `lineage` | object (Lineage) | Yes | Where an event came from: who made it, through what, when, why, as part of which command and in reaction to what, with whose approval, and in what version-control state. Every event troupe records carries it. It is left out of the event's content hash, so two clones that make the same change agree on the event's id. |
| `timestamp` | object (Library timestamp) | Yes | When the event-sourcing library created the event, as its transcoder writes a datetime. |
| `changes` | list of any | Yes | Each value the command changed, at most once each. A change that would change nothing isn't recorded. |
| `files` | list of object (File written) | Yes | Each config file the change wrote or removed, so troupe can tell its own files from a person's. |

### Config.Settled

The payload of config's settling event (topic troupe.core.config.aggregate:Config.Settled), which ends a fork in the config stream: its parents are every head, and its state is the config the merge worked out from them. It's recorded with the first change after a merge, in the same batch. Field names are as recorded.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `lineage` | object (Lineage) | Yes | Where an event came from: who made it, through what, when, why, as part of which command and in reaction to what, with whose approval, and in what version-control state. Every event troupe records carries it. It is left out of the event's content hash, so two clones that make the same change agree on the event's id. |
| `timestamp` | object (Library timestamp) | Yes | When the event-sourcing library created the event, as its transcoder writes a datetime. |
| `topic` | `"troupe.core.config.aggregate:Config"` | Yes | The aggregate whose stream the event settles: config's. |
| `state` | object | Yes | The settled state: the config the merge worked out from every head. |

### Run.ChangesAccepted

The payload of a run's acceptance (topic troupe.core.runs.aggregate:Run.ChangesAccepted): the person applied its captured diff to the theatre's working tree, unstaged. Recorded after the diff applied. Final: nothing else settles the run's changes after it.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `lineage` | object (Lineage) | Yes | Where an event came from: who made it, through what, when, why, as part of which command and in reaction to what, with whose approval, and in what version-control state. Every event troupe records carries it. It is left out of the event's content hash, so two clones that make the same change agree on the event's id. |
| `timestamp` | object (Library timestamp) | Yes | When the event-sourcing library created the event, as its transcoder writes a datetime. |
| `diff` | string | Yes | The diff that was applied: the reference the run's end recorded. |
| `files` | list of string | Yes | The files it changed, relative to the repository's top level. |

### Run.ChangesDiscarded

The payload of a run's discard (topic troupe.core.runs.aggregate:Run.ChangesDiscarded): the person removed its worktree, and nothing reached the theatre. The diff's artifact is kept. It doesn't undo what the run changed in the repository's shared state. Final: nothing else settles the run's changes after it.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `lineage` | object (Lineage) | Yes | Where an event came from: who made it, through what, when, why, as part of which command and in reaction to what, with whose approval, and in what version-control state. Every event troupe records carries it. It is left out of the event's content hash, so two clones that make the same change agree on the event's id. |
| `timestamp` | object (Library timestamp) | Yes | When the event-sourcing library created the event, as its transcoder writes a datetime. |

### Run.Ended

The payload of a run's last event (topic troupe.core.runs.aggregate:Run.Ended): the outcome the run host derived, and whether recording failed part-way.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `lineage` | object (Lineage) | Yes | Where an event came from: who made it, through what, when, why, as part of which command and in reaction to what, with whose approval, and in what version-control state. Every event troupe records carries it. It is left out of the event's content hash, so two clones that make the same change agree on the event's id. |
| `timestamp` | object (Library timestamp) | Yes | When the event-sourcing library created the event, as its transcoder writes a datetime. |
| `outcome` | object | Yes | How the run ended, as the run host derived it from what the runner reported, never from its exit code alone: the outcome, whether the runner exited, was killed or never started, and the limits it ran under. |
| `recording` | object | No | Where recording the run's events failed, and why. Absent: recording didn't fail. |
| `changes` | object | No | What a worktree run changed, captured when it ended. Present exactly when the run's workspace was a worktree. |

### Run.Reported

The payload of one run event (topic troupe.core.runs.aggregate:Run.Reported): the runner's seq, and the event as troupe received it, or the oversized event troupe wrote in its place.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `lineage` | object (Lineage) | Yes | Where an event came from: who made it, through what, when, why, as part of which command and in reaction to what, with whose approval, and in what version-control state. Every event troupe records carries it. It is left out of the event's content hash, so two clones that make the same change agree on the event's id. |
| `timestamp` | object (Library timestamp) | Yes | When the event-sourcing library created the event, as its transcoder writes a datetime. |
| `seq` | integer | Yes | The runner's number for the event, counting from 0. Each run event is recorded in seq order, and one that isn't the next is refused. |
| `event` | object (init) or object (turn) or object (tool_call) or object (tool_result) or object (retry) or object (log) or object (result) or object (oversized) | Yes | A run event, or the oversized event troupe writes in place of one larger than the maximum event size. |

### Run.Started

The payload of a run's first event (topic troupe.core.runs.aggregate:Run.Started): who and what the run is, recorded before its workspace is made and its runner starts, once every check that can refuse it has passed. Field names are as recorded.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `lineage` | object (Lineage) | Yes | Where an event came from: who made it, through what, when, why, as part of which command and in reaction to what, with whose approval, and in what version-control state. Every event troupe records carries it. It is left out of the event's content hash, so two clones that make the same change agree on the event's id. |
| `timestamp` | object (Library timestamp) | Yes | When the event-sourcing library created the event, as its transcoder writes a datetime. |
| `originator_topic` | `"troupe.core.runs.aggregate:Run"` | Yes | The event-sourcing library's name for the aggregate the stream holds. |
| `run_id` | string | Yes | Chosen by troupe for each run attempt: a UUID in canonical lowercase form. |
| `actor` | string | Yes | The actor's name. It becomes the agent's id in lineage. |
| `runner_requested` | string | Yes | A runner troupe knows by name. A request never carries a command line. |
| `runner_reported` | object (Name and version) | No | The runner's name and version from its init, as troupe recorded them before a run's start came before its runner. Absent: recorded since, when the run's first reported event, its init, names the runner; or the runner never sent one. |
| `stage` | object | Yes | Where the actor whose run recorded this event ran, and whether troupe enforced its declared effects there. An unenforced stage names the policy setting, and the source of its value, that allowed the run; an enforced one has no allowedBy. |
| `effect_check` | object | Yes | How troupe checks, after a run, that it did what it was for. There is no default: none must be said explicitly. |
| `direction` | string | Yes | The artifact reference of the run's direction: what the actor was asked to do. |
| `config` | list of string | Yes | The config version the run used: the ids of the config stream's heads, sorted. Working out config at that version gives the actor's runner, options, effect check and character. |
| `workspace` | object (In the theatre) or object (In its own worktree) | No | Where the run worked. Absent: recorded before runs had workspaces, so in the theatre. |

### Run.WorktreeMade

The payload of a worktree run's second event (topic troupe.core.runs.aggregate:Run.WorktreeMade): its worktree, named by the run's start, is made and filled, and the runner hasn't started yet. Recorded by the person's command, which made it. Absent from a run: its worktree wasn't made, or its start was recorded by an older troupe, which held the clone mechanisms itself.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `lineage` | object (Lineage) | Yes | Where an event came from: who made it, through what, when, why, as part of which command and in reaction to what, with whose approval, and in what version-control state. Every event troupe records carries it. It is left out of the event's content hash, so two clones that make the same change agree on the event's id. |
| `timestamp` | object (Library timestamp) | Yes | When the event-sourcing library created the event, as its transcoder writes a datetime. |
| `clones` | list of one of `"clonefile"`, `"ficlone"`, `"copyfile2"`, `"copy"`, `"symlink"` | Yes | The clone mechanisms used for the files that matched HEAD, sorted. Empty: every file was checked out. |

### Lineage

Where an event came from: who made it, through what, when, why, as part of which command and in reaction to what, with whose approval, and in what version-control state. Every event troupe records carries it. It is left out of the event's content hash, so two clones that make the same change agree on the event's id.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `actor` | object | Yes | Who made the event. Never null: where nobody can be known, such as a hand edit to a file, the kind is an explicit unknown. |
| `via` | one of `"cli"`, `"file"`, `"runner"`, `"server"` | Yes | The surface the event came through. A closed set: a new surface is a schema change. |
| `at` | string | Yes | When troupe recorded the event, in UTC. |
| `reason` | string | No | Why, in the actor's words. Absent: none was given. |
| `change` | string | Yes | The correlation id: minted by the command that started this, and carried by every event that follows from it, reactions included. |
| `cause` | object | Yes | What made the event happen: the command that recorded it directly (its id is the change id), or the event it reacts to. Never null. |
| `approvals` | list of object (Approval) | Yes | Who approved the event, and in which role. Empty when nobody had to. |
| `vcs` | object (Version-control state) | Yes | The state the event was made in. |
| `stage` | object | No | Absent: the event was recorded outside a stage, such as by a person's command. |
<!-- end generated: events -->
