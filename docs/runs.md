# Runs

`troupe perform` runs one actor and records the run in the theatre's event store. `troupe status` and `troupe logs`
read runs back. This page describes runs as built by the `perform-status-logs` change (#36); the decisions behind it
are #3 (what a local stage does about declared effects) and #14 (no run server yet: commands and queries are
messages in `protocol/`).

## A run

`troupe perform <actor>` runs one actor through its runner, on its stage, and records the run in the theatre's
event store ([docs/event-store.md](event-store.md)). The runner contract is in [docs/runners.md](runners.md).

1. **Everything that can refuse goes first:** who you are (the identity chain), the policy, the stage's admission,
   and the runner's name. A refused `perform` runs nothing and writes nothing.
2. **The run id** is a new UUID. `perform` shows it at once, so you can follow the run from another terminal.
3. **The run's lease** is taken: a lock on `.troupe/local/runs/<run id>/`, held while `perform` runs.
4. **The instructions and the runner's options** are stored as artifacts and referenced by hash, since they can be
   large or hold what shouldn't be in git.
5. **Each run event is recorded as it arrives,** then the run's end, with the outcome the run host derived.

### Run events

A run is its own stream, keyed by its run id. Its events, in order:

| Event | When | Actor and via |
|---|---|---|
| `Run.Started` | When the runner's `init` arrives (or, if it never sends one, at the end). It holds the actor's name, the runner asked for and the name and version `init` reported, the stage's admission, the effect check, and the instructions' and options' references | You, through `cli` |
| `Run.Reported` | Once per run event, in `seq` order. It holds the event's `seq` and the event as received | The agent (`source: troupe`), through `runner` |
| `Run.Ended` | Once, when the run host returns. It holds the outcome, its error, the result, the exit code, the transcript's and standard error's references and the limits; and, if recording failed part-way, where and why | The agent, through `runner` |

All of a run's events share one change id. `seq` is the runner's numbering, kept in the payload; it isn't the
stream's version, which counts `Run.Started` too. Recording a `seq` that isn't the next one is refused
(`run.out-of-sequence`).

**If an event can't be recorded,** the run is cancelled and no later event is recorded, because a gap would break the
`seq` rule. The run's end is still recorded if it can be, saying from which `seq` recording stopped and why, and
`perform` fails with `run.recording-failed`. The transcript is always kept.

### Ctrl-C

The first Ctrl-C cancels the run: troupe sends the runner `run/cancel`, gives it `RUNNER_CANCEL_GRACE_SECONDS`, then
stops it and everything it started. The run's end is recorded as `cancelled`, and `perform` exits 130. A second Ctrl-C
only repeats the notice (`run.cancelling`): stopping troupe then is what would leave the run unrecorded.

### States

A run's state isn't recorded. It's worked out each time it's read:

| State | When |
|---|---|
| `ended` | The run's end is recorded |
| `running` | No end yet, and the `perform` running it holds its lease in this clone |
| `interrupted` | No end, and its lease in this clone is free: the `perform` that ran it stopped without recording an end (it was killed, or its end couldn't be written) |
| `unfinished-elsewhere` | No end, and no lease in this clone: it was started in another clone, which this one can't see |

Nothing is ever recorded on behalf of an interrupted run: how it ended would be a guess. Its events and transcript
show how far it got. Lease directories stay in `.troupe/local/runs/` (they're local and small); removing one while a
`perform` is starting would race with it.

## Reading runs

`troupe status` lists the most recent runs, newest first (`STATUS_RUNS_LIMIT` of them, or `--limit`). `troupe status
<run>` shows one run: its actor, who started it, its runner, its stage, its state, its outcome and error, how many
events it has, its times, and its transcript's and standard error's references.

`troupe logs <run>` shows a run's events in order, each with the time troupe recorded it. `--follow` then waits for
more, showing each event as it's recorded, and stops when the run's end is recorded, when it stops running, or at
Ctrl-C, saying why.

- **Woken by the write.** Following subscribes to the event store, which wakes it when anything is recorded, by
  this process or another, so each event appears as soon as `perform` writes it. It never looks on a timer
  ([docs/event-store.md](event-store.md#subscriptions)).
- **Polling is announced.** If the store can only poll (its directory can't be watched, or its watch was found to
  miss a write), the notice `events.subscription-polling` is shown as following starts, and events arrive up to
  `SUBSCRIBE_POLL_SECONDS` late.
- **A `perform` that dies is still noticed.** It writes nothing, so nothing wakes following. Every
  `LOGS_LEASE_CHECK_SECONDS` following checks the run's lease, one try of a lock, and stops with `run.interrupted`
  once nobody holds it.

A run is named by its full id or by a prefix of at least 8 hex digits that matches exactly one run. Both commands
work from another terminal while a run is going: they read the event store, which `perform` writes as it goes.

## Stages

A **stage** is where an actor runs. Whether troupe can enforce what the actor may touch (its declared effects)
depends on the stage. Stages are found by name (the `troupe.stages` entry point group); troupe never imports one.

Before a runner starts, the stage **admits** the actor or refuses it. A refused actor isn't run, and nothing is
recorded: no event, no artifact.

### The local stage

The local stage (`troupe-stage-local`, registered as `local`) runs the actor as a process on your machine, with the
theatre's root as its workspace. It's the only stage so far, and the default.

**It enforces nothing.** A process on your machine can write any file and reach any host you can. So the local stage
treats every actor's effects as unenforceable, including an actor that declares none: "no effects" is a claim it
can't check either. It refuses every actor with `stage.effects-unenforced` unless the policy setting
`allow_unenforced_local_stage` is true (decision [#3](https://github.com/troupe-run/troupe/issues/3), option C).

When policy allows it, every event the run records says so in its lineage:

```json
"stage": {"name": "local", "effects": "unenforced",
          "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"}}
```

A run's effect check (`--expect`) isn't enforcement. It checks after the run that the actor produced what it was
for, and a passing check doesn't make the run's effects count as enforced. A stage that can enforce effects, such
as a Docker stage, comes later.

## Policy

Policy settings decide what troupe may do, whoever asks. troupe reads them through one place (`troupe.core.policy`),
and never from a command's request, so no client can loosen them.

| Setting | Default | What it allows |
|---|---|---|
| `allow_unenforced_local_stage` | `false` | Running an actor on a stage that can't enforce its declared effects, such as the local stage |

**Setting it, for now.** Until config brings policy files (#8), the only way to set a policy is an environment
variable: `TROUPE_POLICY_` and the setting's name in capitals. This is interim, and config replaces it.

```console
export TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE=true
```

- The value must be exactly `true` or `false`. Anything else (`yes`, `TRUE`, `1`) fails the command with
  `policy.invalid-value`; it never falls back to the default.
- Unset or empty means the default.
- Lineage records where the value came from (`env` or `default`) for every run it allowed.

## Notices and errors

| Code | When |
|---|---|
| `theatre.not-found` | No directory from here upwards holds `.troupe/` |
| `runner.unknown` | `--runner` names a runner troupe doesn't know |
| `stage.unknown` | No stage of that name is installed |
| `stage.effects-unenforced` | The stage can't enforce the actor's effects, and policy doesn't allow running it anyway |
| `policy.invalid-value` | A policy variable is set to something other than `true` or `false` |
| `run.out-of-sequence` | A run event isn't the next one its run expects, or arrived after the run ended: a fault, never retried |
| `run.recording-failed` | A run event, or the run's end, couldn't be recorded, so the run was stopped |
| `run.not-found` | No run here has an id starting with what was given |
| `run.ambiguous-id` | More than one run's id starts with what was given; it lists them |
| `run.cancelling` | (notice) Ctrl-C was pressed: the run is stopping within its grace period |
| `run.interrupted` | (notice) A run has no recorded end, and the `troupe perform` that ran it has stopped |
| `run.unfinished-elsewhere` | (notice) A run started in another clone has no recorded end here |
| `perform.options-invalid` | The file given to `--runner-options` can't be read, isn't strict JSON, or isn't a JSON object |
| `perform.path-outside-theatre` | An `--expect` path isn't a file inside the theatre. Exits 2 |
| `client.invalid-request` | A command's or query's request doesn't match its schema; it names the field. Exits 2 |
| `client.unknown-method` | A surface called a command or query troupe doesn't offer. Exits 2 |

## Defaults

Every limit and default runs use has its default in `troupe.core.defaults`.

| Setting | Default | What it is |
|---|---|---|
| `LOGS_LEASE_CHECK_SECONDS` | 1 | How often `troupe logs --follow` checks that the run it follows is still running |
| `STATUS_RUNS_LIMIT` | 20 | How many runs `troupe status` lists when it isn't given `--limit` |
| `ALLOW_UNENFORCED_LOCAL_STAGE` | false | The policy setting `allow_unenforced_local_stage`, when nothing sets it |
