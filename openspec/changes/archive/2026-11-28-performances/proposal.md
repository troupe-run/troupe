# Proposal

## Why

troupe#124 brings flows, starting with actors in sequence. Its owner decisions (2026-11-27 and 2026-11-28) make
**every `troupe perform` a performance**: one run of your process, with its own id and record. Each step of a
performance is a run, and an actor's perform is a performance of one step. Every event a performance causes also
names it in its lineage.

The docs already say a performance is "one run of your process", but nothing records one. Today a run stands alone,
and nothing could group a flow's steps, hold its direction, or say where it waits.

This is the first of #124's two changes. It records a performance for every perform, so that the second change,
`actor-sequences`, can add flows of several steps onto a shape that already exists. This change is part of #124 and
doesn't close it.

## What Changes

- **Every `troupe perform` records a performance.** A performance is its own stream, with a new UUID minted by
  `perform`. It records two events:
  - `Performance.Started` is recorded in the same batch as its run's start. It holds what was performed (an actor,
    by name), its steps (each step's actor and approvers, with where they came from), the direction by reference,
    and the config version.
  - `Performance.Ended` is recorded once nothing more will happen in it. It holds the outcome: `completed`, `failed`,
    `rejected` or `cancelled`. A performance whose work waits at a gate hasn't ended.
- **Each step is a run, as now.** A run's start names its step (`1`, since every performance has one step until
  flows), and its lineage names its performance.
- **Lineage gains `performance`,** the id of the performance an event belongs to.
  - It's required on every event of a performance's stream and of its runs' streams. That includes the gate's pass,
    cue and answer, accept and discard.
  - It's refused on every other event, such as config changes, hand-edit sweeps and fork settling.
  - It's checked both when an event is recorded and in the protocol's schemas. **BREAKING** (protocol): a new lineage
    field that older readers refuse, and a required field in `Run.Started`.
- **`perform` prints both ids.** It prints the performance's id first, as `performance <id> (<actor>)`, then the run's
  id as the run starts. Its client updates gain a `performance-started` update, and `started` names the performance
  and the step. **BREAKING** (client protocol).
- **A performance id names a run wherever a run id does,** when it points at exactly one run. That covers `status`,
  `logs`, `diff`, `accept`, `discard`, `approve` and `reject`.
  - Until flows, every performance points at exactly one run. A performance that points at more is refused, naming
    its runs.
  - A prefix that matches both a run and a performance is refused as ambiguous.
  - Run ids keep working everywhere.
- **`troupe status` shows one line per performance.** A one-step performance's line is its run's line with the
  performance id in front. Run summaries in `status`, `logs` and `perform` name their performance and step.
  **BREAKING** (client protocol: a new required field in the run summary).
- **Runs recorded before this change** get no performance, and aren't migrated. Pre-1.0 there are no theatres to
  migrate, so a stored run event without `performance` is a fault, not a form to read leniently.
- **Docs:** performances-and-runs, lineage, read-the-lineage, the first-performance page (perform's output), the CLI
  reference, the events reference and the glossary.

Not in this change (it's `actor-sequences`): the `flows` config kind, performances of more than one step, gates
between steps (`Run.ChangesApproved`), approve carrying a flow on, briefs and history files, and settling a whole
performance's work. Grouping a flow's runs under one line in `status` comes with flows too, since until then a
performance's line and its run's line are the same line.

## Capabilities

### New Capabilities

- `performances`: a performance as troupe records it. Covers its stream and events, how a perform starts and ends
  one, its outcome, what a step records about it, and how a performance id names a run.

### Modified Capabilities

- `lineage`: every event of a performance or its runs carries `performance`, and no other event does.
- `runs`: perform records a performance around its run. A run's start names its step. `status` lists performances.
  Queries accept a performance id that points at one run. Run summaries name their performance.
- `cli`: perform writes the performance id before the run id. Status's line for a performance puts its id in front.

## Impact

- **Code:**
  - `troupe.core.runs` (a new `Performance` aggregate beside `Run`; `perform`, `gate`, `changes` and `queries`
    record and resolve performances);
  - `troupe.core.events` (lineage's `performance`, and the record-time check);
  - `troupe.core.client.messages`;
  - the CLI's perform and status rendering.
- **Protocol:**
  - `lineage.schema.json`;
  - new `performance-started` and `performance-ended` event schemas;
  - `run-started.schema.json` and every run event schema (lineage must name a performance);
  - the config event schemas (lineage mustn't);
  - the client's run summary, perform update and status result.

  This is a breaking release: 0.4.0 → 0.5.0.
- **Specs:** a new `performances` spec, so troupe-run/infrastructure's `oob/troupe-spec-purposes.json` needs the
  spec's Purpose in a pull request merged after this one. The spec uses the existing labels `cap:runs` and
  `cap:lineage`.
- **Tests:** perform, status, logs, gate and settling tests gain performances. troupe#540, in review, adds unit tests
  for run settling, so this change rebases onto it.
