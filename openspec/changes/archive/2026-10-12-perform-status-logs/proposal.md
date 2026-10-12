# Proposal

Issue: troupe-run/troupe#36 (part C of the walking skeleton, #33). Builds on #34 (runner-contract, archived) and #35
(event-store, archived). Settles #3 (option C) and #14 (no run server in the skeleton), both decided by the owner on
2026-10-12 and recorded on #36.

## Why

Parts A and B each work alone: the run host can run an actor and derive its outcome, and the event store can record
events with lineage. Nothing yet connects them, and troupe has no command a person can run. This change is the
slice that proves they fit together through the core, with the CLI as a thin client: `troupe perform` runs one actor
on a local stage and records the run, and `troupe status` and `troupe logs` read it back from projections, from the
same terminal or another one.

It also fixes two things every later slice depends on. The first is the shape of the client protocol: commands and
queries as JSON Schema in `protocol/`, which the CLI calls in process now and a run server will serve later (#14).
The second is what a local stage does about declared effects: it refuses unless policy allows it, and records the
allowance in lineage (#3).

## What Changes

- **`troupe perform <actor>`** runs one actor through a runner on the local stage. It mints the run id, records the
  run in its own stream (`init` first, every run event in `seq` order, then the derived outcome), shows events and
  notices as they arrive, and exits by outcome. Ctrl-C cancels the run through the run host, and the cancelled
  outcome is still recorded.
- **`troupe status [<run>]`** lists recent runs, or shows one run's state and outcome. **`troupe logs <run>`** prints
  a run's events in order, and `--follow` waits for new ones until the run ends. Both read projections of the event
  store, so they work from another terminal while a run is going. A run whose `perform` died without recording an
  outcome shows as interrupted, not running.
- **A run aggregate** keeps the rules agreed on #36: a run is its own stream, keyed by its UUID, and `seq` stays in
  the payload. Recording a `seq` that isn't the next one is refused. The runner's name and version from `init` go in
  the run-started event. The person who ran `perform` is recorded as starting the run, and the agent is recorded as
  the actor of the run's own events (`via: runner`, `source: troupe`).
- **Commands and queries in the core, defined in `protocol/`** (#14): `perform`, `status` and `logs`, with their
  requests, live updates and results as JSON Schema. The CLI builds each request as data and calls the core through
  one dispatcher in process. A request never carries a host path, a command line or a policy value, so a later run
  server can serve the same messages to an untrusted client.
- **A stage port and the local stage** (#3, option C). The local stage can't enforce any declared effect, so it
  refuses every actor unless the policy setting `allow_unenforced_local_stage` allows it (default: deny). Every run it
  allows records in its lineage that effects weren't enforced, and which policy source allowed it.
- **A policy seam with one setting.** Policy is read only through `troupe.core.policy`. Until config brings policy
  files (#8), the only source is an environment variable, and a malformed value is an error.
- **How `perform` names its runner, its options and its effect check before config exists** (an interim design
  decision that the config change replaces): the runner by name from one interim table, the runner's options (the
  scripted runner's script) from a JSON file, and the effect check by `--expect <path>` or an explicit
  `--no-effect-check`, never by default.
- **Lineage gains a `stage` field**: null for events recorded outside a stage, otherwise the stage's name, whether
  effects were enforced, and what allowed an unenforced run.
- **A new exit code, 130,** for a run cancelled with Ctrl-C, so a script can tell a cancel from a failure.

## Capabilities

### New Capabilities
- `client-protocol`: commands and queries as language-neutral messages that every surface calls the core through.
  The dispatcher, live updates, the session context that is never part of a message, and what a message may not
  carry.
- `runs`: recording a run in the event store (its stream, events, lineage and outcome), the run aggregate's rules,
  and the run projections that `status` and `logs` read, including interrupted runs.
- `stages`: the stage port and the local stage: where an actor runs, and admitting or refusing it according to the
  effects the stage can enforce and what policy allows.
- `policy`: the one seam through which policy settings are read, their named defaults, and the interim environment
  source.

### Modified Capabilities
- `cli`: adds `perform`, `status` and `logs`, finding the theatre from the working directory, live output, and the
  cancelled exit code.
- `lineage`: adds the `stage` field, which records whether a run's effects were enforced.

## Impact

- New: `protocol/schemas/client/` (requests, updates and results for `perform`, `status` and `logs`),
  `troupe.core.client` (the dispatcher and message types), `troupe.core.runs` (the run aggregate, the recorder that
  wires the run host to the event store, and the projections), `troupe.core.stages` (the port),
  `packages/troupe-stage-local/` (the local stage, found by the `troupe.stages` entry point), `troupe.core.policy`,
  the theatre finder, and an interrupt hook in `troupe.platform`.
- Changed: `protocol/schemas/lineage.schema.json` and `troupe.core.events.lineage` (`stage`), `troupe.cli` (three
  commands), `troupe.core.exit_codes` and `docs/cli/exit-codes.md` (130), `troupe.core.errors` and
  `troupe.core.notices` (new codes), `troupe.core.defaults` (interim names and the policy default), `pyproject.toml`
  (the new package and import contracts), `docs/cli/README.md`, `docs/runners.md`, `docs/event-store.md`,
  `protocol/README.md`, and new `docs/runs.md`.
- Dependencies: none new at runtime.
- Out of scope: config files and an actor registry (the next change), declared-effect vocabulary (it arrives with
  actor config), a git worktree per run on the local stage (a Feature after the skeleton, #3), Docker stages, more
  than one actor, flows, gates, a run server or house, persisted projections, and reading a run's transcript from
  the CLI.
- Closes #36 and #3. #14's skeleton question is answered here: no server, and the protocol is the one a later server
  speaks. #14 stays open for the server itself.
