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

Today troupe records config changes, performances and runs. A performance records its start and its end, and each
of its steps is a run. A run records its first event, the worktree made for it if it has one, one event for each
thing its runner reports, the notices troupe raised while it went, and its last event. Keeping or discarding its
changes is an event too. More events arrive as troupe grows, each listed here as it
does. The tables below are generated from troupe's schemas, so they can't drift from what troupe writes.

## The events

<!-- generated: events (from protocol/schemas/events/ and lineage; regenerate with `uv run scripts/docs_reference.py`) -->
### Config.Changed

The payload of one config change (topic troupe.core.config.aggregate:Config.Changed): every value one command changed (or the entity it renamed), and every config file it wrote or removed. A command records exactly one for its own change; the sweep before it records one more for each config file a person edited, by the unknown author, with the file in its lineage's vcs.source. Field names are as recorded.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `lineage` | object (Lineage) | Yes | Where the event came from. It names no performance: config isn't part of one. |
| `timestamp` | object (Library timestamp) | Yes | When the event-sourcing library created the event, as its transcoder writes a datetime. |
| `changes` | list of any or object (Rename entry) | Yes | Each value the change sets or unsets, at most once each. A change that would change nothing isn't recorded. |
| `files` | list of object (File written) | Yes | Each config file the change wrote or removed, so troupe can tell its own files from a person's. |

### Config.Settled

The payload of config's settling event (topic troupe.core.config.aggregate:Config.Settled), which ends a fork in the config stream: its parents are every head, and its state is the config the merge worked out from them. It's recorded with the first change after a merge, in the same batch. Field names are as recorded.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `lineage` | object (Lineage) | Yes | Where the event came from. It names no performance: config isn't part of one. |
| `timestamp` | object (Library timestamp) | Yes | When the event-sourcing library created the event, as its transcoder writes a datetime. |
| `topic` | `"troupe.core.config.aggregate:Config"` | Yes | The aggregate whose stream the event settles: config's. |
| `state` | object | Yes | The settled state: the config the merge worked out from every head. |

### Performance.Ended

The payload of a performance's end (topic troupe.core.runs.performance:Performance.Ended): nothing more will happen in it. Recorded in the same batch as the event that settled it: its run's end, troupe's acceptance at the gate, or a person's answer. At most one. Absent: the performance's work waits at a gate, or its perform stopped without an end.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `lineage` | object (Lineage) | Yes | Where the event came from. It names this performance. |
| `timestamp` | object (Library timestamp) | Yes | When the event-sourcing library created the event, as its transcoder writes a datetime. |
| `outcome` | one of `"completed"`, `"failed"`, `"rejected"`, `"cancelled"` | Yes | How it ended: completed when every step ran and its work was kept or there was none, failed when a step didn't succeed or its changes couldn't be captured, rejected when its work was turned down at a gate or discarded, cancelled when a step was cancelled. |

### Performance.Started

The payload of a performance's first event (topic troupe.core.runs.performance:Performance.Started): what was performed and its steps, recorded in the same batch as its first run's start, so neither is recorded without the other. Field names are as recorded.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `lineage` | object (Lineage) | Yes | Where the event came from. It names this performance. |
| `timestamp` | object (Library timestamp) | Yes | When the event-sourcing library created the event, as its transcoder writes a datetime. |
| `originator_topic` | `"troupe.core.runs.performance:Performance"` | Yes | The event-sourcing library's name for the aggregate the stream holds. |
| `performance_id` | string | Yes | The performance's id, which is also its stream's. |
| `performed` | object | Yes | What was performed. Until flows, always an actor, by its name then. |
| `steps` | list of object (Step) | Yes | The performance's steps, in the order they run. Until flows, exactly one. |
| `direction` | string | Yes | The direction the performance was given, as a reference to the artifact holding it. |
| `config` | list of string | Yes | The config version the performance started with: the ids of the config stream's heads, sorted. |

### Run.ChangesAccepted

The payload of a run's acceptance (topic troupe.core.runs.aggregate:Run.ChangesAccepted): the person applied its captured diff to the theatre's working tree, unstaged. Recorded after the diff applied. Final: nothing else settles the run's changes after it.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `lineage` | object (Lineage) | Yes | Where the event came from. It names the performance the run is a step of. |
| `timestamp` | object (Library timestamp) | Yes | When the event-sourcing library created the event, as its transcoder writes a datetime. |
| `diff` | string | Yes | The diff that was applied: the reference the run's end recorded. |
| `files` | list of string | Yes | The files it changed, relative to the repository's top level. |

### Run.ChangesDiscarded

The payload of a run's discard (topic troupe.core.runs.aggregate:Run.ChangesDiscarded): the person removed its worktree, and nothing reached the theatre. The diff's artifact is kept. It doesn't undo what the run changed in the repository's shared state. Final: nothing else settles the run's changes after it.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `lineage` | object (Lineage) | Yes | Where the event came from. It names the performance the run is a step of. |
| `timestamp` | object (Library timestamp) | Yes | When the event-sourcing library created the event, as its transcoder writes a datetime. |

### Run.ChangesRejected

The payload of a rejection at a worktree run's gate (topic troupe.core.runs.aggregate:Run.ChangesRejected): the role the open cue was for removed the run's worktree, and nothing reached the theatre. The reason is in the lineage. Final: nothing else settles the run's changes after it.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `lineage` | object (Lineage) | Yes | Where the event came from. It names the performance the run is a step of. |
| `timestamp` | object (Library timestamp) | Yes | When the event-sourcing library created the event, as its transcoder writes a datetime. |
| `role` | one of `"troupe"`, `"director"` | Yes | The role that rejected, which the cue was for. |

### Run.CueRaised

The payload of a cue at a worktree run's gate (topic troupe.core.runs.aggregate:Run.CueRaised): an open request to a role a person holds, to approve or reject the run's changes, with a brief that makes sense without the run's other events. At most one. The run's changes wait until the role answers.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `lineage` | object (Lineage) | Yes | Where the event came from. It names the performance the run is a step of. |
| `timestamp` | object (Library timestamp) | Yes | When the event-sourcing library created the event, as its transcoder writes a datetime. |
| `role` | one of `"troupe"`, `"director"` | Yes | The role the cue is for. |
| `brief` | object (Brief) | Yes | What the role needs to answer: whose run it was, how it ended, what it changed and where the diff is, and why the cue came to this role. |

### Run.Ended

The payload of a run's last event (topic troupe.core.runs.aggregate:Run.Ended): the outcome the run host derived, with what the audit of the run's changes found, and whether recording failed part-way.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `lineage` | object (Lineage) | Yes | Where the event came from. It names the performance the run is a step of. |
| `timestamp` | object (Library timestamp) | Yes | When the event-sourcing library created the event, as its transcoder writes a datetime. |
| `outcome` | object | Yes | How the run ended, as the run host derived it from what the runner reported, never from its exit code alone: the outcome, whether the runner exited, was killed or never started, the limits it ran under, and what the audit of its changes found. |
| `recording` | object (A run event wasn't recorded) or object (A notice wasn't recorded) | No | What wasn't recorded first, and why: the first run event, by its seq, or a notice troupe raised for the run, by its code. Absent: recording didn't fail. |
| `changes` | object | No | What a worktree run changed, captured when it ended. Present exactly when the run's workspace was a worktree. |

### Run.GatePassed

The payload of a pass at a worktree run's gate (topic troupe.core.runs.aggregate:Run.GatePassed): an approver couldn't act, so the gate went to the next approver in the run's list. Only troupe passes, when the run's diff doesn't apply cleanly to the working tree; nothing was applied. At most one, after the run's end and before any cue.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `lineage` | object (Lineage) | Yes | Where the event came from. It names the performance the run is a step of. |
| `timestamp` | object (Library timestamp) | Yes | When the event-sourcing library created the event, as its transcoder writes a datetime. |
| `approver` | one of `"troupe"`, `"director"` | Yes | The approver that passed. |
| `to` | one of `"troupe"`, `"director"` | Yes | The approver the gate went to next. |
| `reason` | one of `"conflict"` | Yes | Why it couldn't act: conflict, the diff doesn't apply cleanly to the working tree. A closed set. |
| `files` | list of string | Yes | The files whose part of the diff doesn't apply to the working tree, relative to the theatre. |

### Run.Noticed

The payload of one notice troupe raised for a run (topic troupe.core.runs.aggregate:Run.Noticed), kept in the run's stream in the order troupe raised it among the run's events, so status and logs show it after the run. Recorded by the person's command, between the run's start and its end; a notice raised before the start is recorded straight after it.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `lineage` | object (Lineage) | Yes | Where the event came from. It names the performance the run is a step of. |
| `timestamp` | object (Library timestamp) | Yes | When the event-sourcing library created the event, as its transcoder writes a datetime. |
| `notice` | object (Notice fields) | Yes | The notice as troupe raised it and sent it live, with the run's credential masked. |

### Run.Reported

The payload of one run event (topic troupe.core.runs.aggregate:Run.Reported): the runner's seq, and the event as troupe received it, or the oversized event troupe wrote in its place.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `lineage` | object (Lineage) | Yes | Where the event came from. It names the performance the run is a step of. |
| `timestamp` | object (Library timestamp) | Yes | When the event-sourcing library created the event, as its transcoder writes a datetime. |
| `seq` | integer | Yes | The runner's number for the event, counting from 0. Each run event is recorded in seq order, and one that isn't the next is refused. |
| `event` | object (init) or object (turn) or object (tool_call) or object (tool_result) or object (retry) or object (context) or object (log) or object (served_model) or object (result) or object (oversized) | Yes | A run event, or the oversized event troupe writes in place of one larger than the maximum event size. |

### Run.Started

The payload of a run's first event (topic troupe.core.runs.aggregate:Run.Started): who and what the run is, recorded before its workspace is made and its runner starts, once every check that can refuse it has passed. Field names are as recorded.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `lineage` | object (Lineage) | Yes | Where the event came from. It names the performance the run is a step of. |
| `timestamp` | object (Library timestamp) | Yes | When the event-sourcing library created the event, as its transcoder writes a datetime. |
| `originator_topic` | `"troupe.core.runs.aggregate:Run"` | Yes | The event-sourcing library's name for the aggregate the stream holds. |
| `run_id` | string | Yes | Chosen by troupe for each run attempt: a UUID in canonical lowercase form. |
| `actor` | string | Yes | The actor's name. It becomes the agent's id in lineage. |
| `runner_requested` | string | Yes | A runner troupe knows by name. A request never carries a command line. |
| `stage` | object | Yes | Where the actor whose run recorded this event ran, and whether troupe enforced its declared effects there. An unenforced stage names the policy setting, and the source of its value, that allowed the run; an enforced one has no allowedBy. |
| `effect_check` | object | Yes | How troupe checks, after a run, that it did what it was for. There is no default: none must be said explicitly. |
| `direction` | string | Yes | The artifact reference of the run's direction: what the actor was asked to do. |
| `config` | list of string | Yes | The config version the run used: the ids of the config stream's heads, sorted. Working out config at that version gives the actor's runner, options, effect check and character. |
| `workspace` | object (In the theatre) or object (In its own worktree) | Yes | Where the run works. |
| `on_context_full` | object | Yes | What the run does when its engine's context fills, as troupe resolved it when the run started, and where that came from: actor when the actor's onContextFull set it, policy when the compaction policy (all or none) decided it, default otherwise. |
| `step` | integer | Yes | The run's step in its performance, counting from 1. Every performance has one step until flows. |
| `approvers` | object (Approvers) | No | A worktree run's approvers, as troupe resolved them when the run started: the order its gate tries them in, and where they came from. Present exactly when the run works in a worktree. |
| `runtime` | object (Resolved runtime) | No | The runtime the run talked to, as troupe resolved it when the run started, each value with its source: the model is always resolved, and a credential is named by its variable, never its value. Absent: the actor named no runtime. |

### Run.WorktreeMade

The payload of a worktree run's second event (topic troupe.core.runs.aggregate:Run.WorktreeMade): its worktree, named by the run's start, is made and filled, and the runner hasn't started yet. Recorded by the person's command, which made it. Absent from a run: its worktree wasn't made.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `lineage` | object (Lineage) | Yes | Where the event came from. It names the performance the run is a step of. |
| `timestamp` | object (Library timestamp) | Yes | When the event-sourcing library created the event, as its transcoder writes a datetime. |
| `clones` | list of one of `"clonefile"`, `"ficlone"`, `"copyfile2"`, `"copy"`, `"symlink"` | Yes | The clone mechanisms used for the files that matched HEAD, sorted. Empty: every file was checked out. |

### Lineage

Where an event came from: who made it, through what, when, why, as part of which command and in reaction to what, with whose approval, and in what version-control state. Every event troupe records carries it. It is left out of the event's content hash, so two clones that make the same change agree on the event's id.

| Field | Holds | Always there | What it is |
|---|---|---|---|
| `actor` | object | Yes | Who made the event: a person or an agent resolved through an identity source, troupe itself (system), or, where nobody can be known, such as a hand edit to a file, an explicit unknown. Never null. |
| `via` | one of `"cli"`, `"file"`, `"runner"`, `"server"` | Yes | The surface the event came through. A closed set: a new surface is a schema change. |
| `at` | string | Yes | When troupe recorded the event, in UTC. |
| `reason` | string | No | Why, in the actor's words. Absent: none was given. |
| `change` | string | Yes | The correlation id: minted by the command that started this, and carried by every event that follows from it, reactions included. |
| `cause` | object | Yes | What made the event happen: the command that recorded it directly (its id is the change id), or the event it reacts to. Never null. |
| `approvals` | list of object (Approval) | Yes | Who approved the event, and in which role. Empty when nobody had to. |
| `vcs` | object (Version-control state) | Yes | The state the event was made in. |
| `stage` | object | No | Absent: the event was recorded outside a stage, such as by a person's command. |
| `performance` | string | No | The performance the event belongs to: every event in a performance's stream or a run's stream names one, whoever recorded it. Absent: the event isn't part of any performance, such as a config change. Each event's own schema says which. |
<!-- end generated: events -->
