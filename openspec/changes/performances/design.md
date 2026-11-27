# Design

## Context

See proposal.md for why. What the code looks like today:

- **Runs.** A run is the `Run` aggregate (`troupe.core.runs.aggregate`), its own stream keyed by a UUID that `perform`
  mints.
  - `perform` (`troupe.core.runs.perform`) records the run's start with the person's command (`person`), and the
    runner's events with the agent's (`agent = person.acting_as(...)`). Both carry the stage's admission in their
    lineage.
  - The run's end is recorded with the agent's lineage. A cue for a person-first gate is recorded in the same batch,
    with troupe's lineage (`gate.troupe_command`).
  - troupe's turn at the gate (`gate.troupes_step`) records an acceptance, or a pass and a cue, in a later batch.
- **Answering and settling.** `approve`/`reject` (`troupe.core.runs.gate`) and `accept`/`discard`
  (`troupe.core.runs.changes`) each build their own `store.command(...)`, with no stage.
- **Reading runs back.** Every query resolves a reference through `queries.resolve(ref, read_runs(store))`. That's
  one place, used by `status`, `logs`, `diff`, `accept`, `discard`, `approve` and `reject`. `read_runs` folds every
  `Run.*` topic into `RunView`s.
- **Lineage.** `Lineage` (`troupe.core.events.lineage`) is built by `Command.lineage()` and
  `EventStore.record_reaction()`, and checked by hand in `lineage_problem` before anything is written, mirroring
  `lineage.schema.json`. `stage` is the precedent for an optional field: left out when there's nothing to say.
- **Event schemas.** Each event's payload schema (`protocol/schemas/events/*.schema.json`) has `lineage: {$ref:
  ../lineage.schema.json}`.

## Goals / Non-Goals

**Goals:**

- A performance's stream and events are in their final shape, so `actor-sequences` adds steps to it, not fields.
- Every place that records an event in a run's or a performance's stream names the performance, and nothing else
  does. This is checked at record time and in the schemas.

**Non-Goals:**

- Performances of more than one step, and anything that only they need: grouping runs under a performance line,
  following a performance's logs across steps, a performance's own state in `status`, and settling a whole
  performance. These come with `actor-sequences`. Until then a performance's line and its run's line are the same
  line.
- A second lease or lock per performance. A performance's liveness is its run's.

## Decisions

### D1. A `Performance` aggregate beside `Run`

A new aggregate goes in `troupe.core.runs.performance`, with topics `troupe.core.runs.performance:Performance.Started`
and `...:Performance.Ended`. It's keyed by a UUID that `perform` mints next to the run id.

`Started` holds:

- `performed: {kind: "actor", name}`. Flows add `kind: "flow"` later.
- `steps: [{actor, approvers?}]`. `approvers` is the same `{value, source}` object `Run.Started` records, and is left
  out for a run in the theatre.
- `direction`: the artifact reference.
- `config`: the version heads.

`Ended` holds `outcome`, one of `completed`, `failed`, `rejected` or `cancelled`. A second end, or anything after it,
raises `performance.out-of-sequence`, mirroring `run.out-of-sequence`.

Alternatives:

- **The performance in the run's stream, as a `Run.Performed` event.** Rejected: flows need one stream that several
  runs name.
- **Steps without approvers.** Rejected: decision 5 asks for them, and a flow's step approvers can differ from its
  actor's.

### D2. The performance's start is in the run's start batch

`_Recorder._start` records `[*performance.collect_events(), *run.collect_events()]` with `person.record(...,
requires=config)`. Both are refused together when the config version is gone, so no run exists without its
performance, and no performance without a run.

The run's `Run.Started` gains `step` (an integer, at least 1; here always 1). It's a required field, since there are
no old records to read (2026-11-07).

### D3. When and by whom a performance's end is recorded

The end is recorded in the same batch as the event that settles the performance. Its lineage is that of the command
driving the performance: `perform`'s person command, or the `approve`/`reject` command.

| What happens | Batch |
|---|---|
| The run ends, and no gate follows: it failed, was cancelled, couldn't start, changed nothing, or ran in the theatre | the run's end (agent's lineage) + the performance's end (person's) |
| The run ends, and a person comes first | the run's end + the cue; no performance end |
| troupe keeps the work | troupe's acceptance (troupe's lineage, with its approval) + the performance's end (person's) |
| troupe passes | the pass + the cue; no performance end |
| `approve` | the acceptance (approver's lineage, with the approval) + the performance's end, `completed` |
| `reject` | the rejection + the performance's end, `rejected` |

`accept` and `discard` record nothing in the performance. They only apply to a run that didn't reach a gate, and its
performance ended with the run.

The outcome comes from the run's: `succeeded` → `completed`, `cancelled` → `cancelled`, every other outcome →
`failed`.

A `perform` that dies before the end leaves the performance with no end, as it leaves the run. Its state is the run's
state, worked out from the lease.

Alternative: **record the performance's end in a batch of its own, after the event that settles it.** Rejected: a
`perform` that died between the two would leave a performance that never ends although nothing more will happen in
it.

### D4. Lineage's `performance`, carried by the command

The parts:

- `Lineage` gains `performance: str | None`. It's left out of the data when `None`, as `stage` is.
- `Command` gains `performance`, and `acting_as` copies it. `store.command(..., performance=...)` sets it.
  `record_reaction` and `gate.troupe_command` take it from the command they derive from.
- `perform` gives its person command the new performance id. `approve`, `reject`, `accept` and `discard` give theirs
  the run's performance, read from the run's view.

The rule is checked in `record_with_lineages`, beside `lineage_problem`:

- An event whose topic is in a run's or a performance's family (`troupe.core.runs.aggregate:Run.` or
  `troupe.core.runs.performance:Performance.`) must have `performance`.
- Every other event must not.
- The value must be a canonical lowercase UUID. `lineage_problem` checks the format, and the topic check names
  `performance` in `events.lineage-invalid`.

The family list sits in one place in the lineage module, next to the record-time check.

Alternative: **the store fills `performance` from the stream it writes to.** Rejected: the event store doesn't know
runs, and a run's stream doesn't name its performance until its start is read.

### D5. Schemas

- `lineage.schema.json` gains an optional `performance` (a canonical UUID pattern). Its description says what its
  absence means.
- Each `run-*.schema.json` and the two new `performance-*.schema.json` refer to lineage as `allOf: [{$ref:
  lineage}, {required: [performance]}]`.
- `config-changed` and `config-settled` use `allOf: [{$ref: lineage}, {not: {required: [performance]}}]`.
- The protocol's strictness check already accepts `not`, which never widens what's accepted. If it trips on `allOf`
  with a `$ref`, that gets fixed in the check, with its own test, not worked round.
- `run-started.schema.json` gains a required `step`.

### D6. Resolving a reference

`queries.resolve` becomes `resolve(ref, runs) -> str`, still returning a run id. It builds the set of candidates from
the runs and their performances (each `RunView` now holds `performance` and `step`, from its start's lineage and
payload):

1. An exact run id gives that run.
2. An exact performance id gives that performance.
3. Otherwise every run id and performance id starting with the prefix is a match: none is `run.not-found`, and more
   than one is `run.ambiguous-id`, listing each with what it is.
4. A matched performance gives its one run. If it has several, the reference is refused with
   `performance.several-runs`, listing them (a new code, catalogued, with a test that raises it from a store holding
   two runs naming one performance). Choosing the step waiting at a gate among several comes with flows, since
   nothing records several steps yet.

Every caller already goes through `resolve`, so no command needs its own lookup.

### D7. Client protocol and CLI

- **Updates:** a new `performance-started` update, `{performanceId, performed}`, is sent once the batch in D2 is
  written. `started` gains `performanceId` and `step`.
- **Run summary:** `RunSummary` gains required `performanceId` and `step`.
- **Status:** `StatusResult` keeps its shape, a list of run summaries. Each one is a performance's line until flows.
  The limit counts lines, so it now counts performances.
- **CLI:**
  - perform's standard error first says `troupe: performance <id> (<actor>) starting`, then the run line as now.
  - Its standard output on success is `performance <id>: run <id> succeeded`.
  - Each status line starts with the performance's full id, then `run <first 8 of run id>`, then the line as now.
  - `status <run>` adds `performance: <id> (step 1 of 1)`.

Alternative: **give `StatusResult` a list of performance summaries holding runs, now.** Deferred to `actor-sequences`:
until a performance has more than one run, the extra level would hold exactly the run summary, and its shape is
easier to settle beside a flow's progress line.

### D8. Runs recorded before this change aren't read leniently

A `Run.Started` whose lineage has no `performance` fails its schema, and the fold raises `events.lineage-invalid`
naming the run and the field, rather than inventing a performance or skipping the run. There are no such stores to
migrate before 1.0 (owner, 2026-11-07, #296; decision 2 on #124). Test fixtures that hold recorded events are
regenerated or rewritten with the field.

## Risks / Trade-offs

- **The change touches every test that builds run events or lineage by hand.** → One fixture helper builds a run
  start with its performance, and tests use it rather than repeating the field.
- **The schema change can break the protocol's strictness and drift checks in unexpected places** (event examples,
  generated docs). → Run `scripts/check.py` after each schema task, and regenerate the events reference from the
  schemas.
- **troupe#540 (in review) adds run settling unit tests that build runs without performances.** → Rebase onto it once
  it merges, and give those tests a performance through the same helper.
- **The status line grows** (a second id in front). → The run id shown is its 8-character prefix, enough to name it.

## Migration Plan

None for data (D8). The protocol release is breaking (0.4.0 → 0.5.0), carried by a `feat(protocol)!:` commit with a
`BREAKING CHANGE:` footer. After this pull request merges, troupe-run/infrastructure gets the pull request that
records the `performances` spec's Purpose in `oob/troupe-spec-purposes.json`.
