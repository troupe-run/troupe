# Design

## Context

See proposal.md for why. This change builds on two archived designs and doesn't restate them:

- **runner-contract** (`openspec/changes/archive/2026-10-12-runner-contract/design.md`, `docs/runners.md`):
  `run_actor(command, request, *, store, effect, limits, on_event, on_announce, cancel)` is async and returns one
  `RunOutcome`. `on_event` gets each `RunEvent` (or an `OversizedEvent`) in `seq` order and is awaited before the next
  message is read. Announcements arrive as `Notice`s. The effect check has no default (`NoEffectExpected` or
  `ExpectedFiles`). Runners start with nothing from troupe's environment (`RUNNER_ENVIRONMENT`). The artifact store
  is found by name (`load_store("local", root)`).
- **event-store** (`openspec/changes/archive/2026-10-12-event-store/design.md`, `docs/event-store.md`):
  `EventStore.open(theatre)` is synchronous. `store.command(via=…, actor=…)` mints a change id, and
  `Command.record(events)` records one all-or-nothing batch with a command cause. Lineage is a closed schema. Reads
  return notices beside results. `notifications(low, limit, stop, topics)` reads in local order, and the recorder's
  `listen`/`unlisten` with a `SUBSCRIBE_POLL_SECONDS` poll hears other processes' writes. Its D-Runner section and
  the runner contract's "Assumptions about the event format" are this change's inputs.
- **#36's three comments (owner, 2026-10-12)** fix the run stream, the `seq` rule, `via: runner` with the agent as
  actor, `init` first, recording through `asyncio.to_thread`, the artifact root, shared notices, #3 (option C) and
  #14 (no server; commands and queries as JSON Schema; the CLI calls the core through them in process).

What doesn't exist yet: any CLI subcommand (`COMMANDS` is empty), a way to find the theatre, a stage, a policy, a
client protocol, and config. Config is the next change, so everything this change needs from config is an interim
decision, kept in one place so that change can replace it (D4).

## Goals / Non-Goals

**Goals:**
- One run, end to end, recorded so that `status` and `logs` in another terminal can read it while it's going.
- The client protocol's shape is the one a run server will serve. Nothing a client sends can widen what troupe does
  (no host paths, command lines or policy values in a message).
- Every way a run can end, including Ctrl-C, a recording failure and troupe itself dying, leaves history that says
  what happened, never a run that looks as if it's still going.
- Everything config will replace is in one named place.

**Non-Goals:**
- A persisted read model. Projections are rebuilt from the store on each query (D12). The house (#5) brings
  long-lived ones.
- A vocabulary for declared effects. It comes with actor config. The local stage's rule doesn't need one (D5).
- Recording anything in reaction to a run event. No policy or projection records yet; `record_reaction` stays
  unused here.

## Decisions

### D1. Where things live

| Module or package | Holds |
|---|---|
| `protocol/schemas/client/` | The client protocol: one schema per message (D2) |
| `troupe.core.client` | Message types (hand-written, checked against the schemas), the session context and the dispatcher |
| `troupe.core.runs` | The run aggregate and its events (D8), the perform command (D9), the projections and queries (D12, D13) |
| `troupe.core.stages` | The stage port and `load_stage(name)` (D5) |
| `packages/troupe-stage-local/` | The local stage, registered as `local` in the `troupe.stages` entry point group |
| `troupe.core.policy` | The policy seam (D6) |
| `troupe.core.theatre` | Finding the theatre (D3) |
| `troupe.core.interim` | Everything config will replace that isn't a limit: the runner table (D4) |
| `troupe.platform.interrupts` | Catching Ctrl-C on every OS (D10) |
| `troupe.cli.commands` | `perform`, `status` and `logs`: argument parsing, building requests, rendering updates and results |

- **The local stage is its own package**, like every other bundled adapter (bootstrap D1; event-store D1;
  runner-contract D10). An import contract stops `troupe` importing `troupe_stage_local`. It runs in process (#37:
  what ships in the box runs direct).
- **`troupe.cli` imports `troupe.core.client` and nothing else from `troupe.core.runs`.** An import-linter contract
  enforces it, so the CLI can't reach behaviour except through the protocol. That's how "no behaviour exists only in
  one surface" is checked rather than hoped for.

### D2. The client protocol (#14)

Methods: `perform` (a command), `status` and `logs` (queries). Each has a request, a result and, where it streams,
updates:

| Schema | Shape |
|---|---|
| `perform-request` | `actor`, `runner`, `options`, `instructions`, `effectCheck` (D4) |
| `perform-update` | `oneOf`: `started {runId}`, `event {runId, seq, at, event}`, `notice {notice}` |
| `perform-result` | `run` (a run summary), with `outcome` and `error` |
| `status-request` | `run` (an id or a prefix, optional), `limit` (optional) |
| `status-result` | `runs` (run summaries), `notices` |
| `logs-request` | `run`, `follow` (optional, default false) |
| `logs-update` | `event {runId, seq, at, event}` |
| `logs-result` | `run` (a run summary), `events`, `notices` |
| `run-summary` | `$defs` shared by the above: run id, actor, who started it, runner, stage, state (D11), outcome, error, event count, times, transcript and stderr references |

- **Transport-free.** The schemas define the messages, not an envelope. In process, the dispatcher is
  `await call(method, params, session, on_update) -> result`. A run server later wraps the same messages in
  whatever its transport is (#14 leans towards HTTP with SSE for updates). JSON-RPC was considered and rejected for
  now: it would choose the server's transport before #14 does.
- **The CLI calls through data.** It builds `params` as a dict, the dispatcher parses it strictly (unknown field,
  missing field, wrong type or bad pattern → `client.invalid-request`, naming the field), and the result comes back
  as the result type's data, which the CLI renders. Going through data rather than Python objects proves that a
  surface needs nothing the messages don't carry.
- **The session context isn't part of any message.** `Session` holds the theatre (D3), the environment that the
  identity chain and the policy seam read, the clock, and the cancel signal. In process, the CLI builds it. A run
  server builds it from its own configuration and the authenticated user. That's why no message carries a host path
  (theatres are addressed by id, not path), a command line (the runner is named, D4), or a policy value (policy is
  read from the session's sources, never the request, D6).
- **Types are hand-written, as in the runner contract (its D11):** frozen dataclasses with strict `from_data` and
  `to_data`, and tests validate every message both ways against the schemas, including hypothesis-generated ones.
  The generator is still the config change's decision.
- **Errors** are `TroupeError`s, raised by `call`, in the existing `error.schema.json` shape. A run that ends badly
  isn't an error at this level: `perform`'s result carries its outcome and error, and the surface decides the exit
  code (D14).

### D3. Finding the theatre

The theatre is the nearest directory, from the working directory upwards, that contains `.troupe/`. If there's none,
the command fails with `theatre.not-found`, naming the directory searched from, and the fix: create `.troupe/` at the
project's root, or run troupe inside a project that has one.

- **Not guessed from git.** Using the git work tree's root would create `.troupe/` in whatever repository the person
  happens to be in, including one they never meant to use with troupe. A theatre exists because someone made it.
- The run server finds a theatre by id instead. That's why the theatre is in the session, not in a message (D2).
- `troupe init` arrives with config, which is what a new theatre's first content is.

### D4. Interim: how `perform` names its runner, options and effect check (replaced by config)

Until actors are configured, a `perform` request says what an actor's config will later say. The CLI shape:

```console
troupe perform <actor> --runner <name> [--runner-options <file.json>] [--instructions <text>]
                       (--expect <path> ... | --no-effect-check)
```

| Request field | Now | After config |
|---|---|---|
| `actor` | A name, `^[a-z][a-z0-9-]{0,63}$`. Not looked up anywhere; it becomes the agent's id in lineage | Looked up in config; unknown is an error |
| `runner` | A name from `troupe.core.interim.RUNNERS`. Today one entry: `scripted` → `[sys.executable, "-m", "troupe_runner_scripted"]`. Unknown → `runner.unknown`, naming the known ones | From the actor's config, resolved to a plugin named and pinned there (#38) |
| `options` | A JSON object, passed to the runner untouched. The CLI reads it from `--runner-options` (strict JSON: duplicate keys and `NaN` refused), or sends `{}` | From the actor's config |
| `instructions` | `--instructions`, or the empty string when absent | The actor's prompt |
| `effectCheck` | `{"kind": "files", "paths": [...]}` from `--expect` (repeatable), or `{"kind": "none"}` from `--no-effect-check`. One of the two is required; neither, or both, is a usage error | From the actor's config, or a stage's audit |

- **The runner is named, never given as a command line.** A request that could carry `argv` would let any client of
  a later run server run any program. The table is the only place a name becomes a command. The conformance suite
  keeps its own `TROUPE_CONFORMANCE_RUNNER` for arbitrary runners.
- **The script is the runner's business.** The scripted runner's script goes in its options (`{"script": {...}}`
  inline, or `{"scriptPath": "..."}`, which the runner resolves from its working directory, the theatre root). A
  file avoids JSON on the command line, which needs different quoting in every shell and is unusable in Windows'
  `cmd`. troupe doesn't learn any runner's option names.
- **Effect check paths** are given relative to the working directory, as a person would type them. The CLI turns them
  into theatre-relative paths with `/`, and refuses one outside the theatre (`perform.path-outside-theatre`). In the
  request they're theatre-relative only; the core resolves them against the theatre root. An absolute path, a drive,
  or `..` in a request is `client.invalid-request`.
- **No default effect check.** The run host already refuses to guess one; the CLI doesn't add one.
- **What the config change does:** delete `troupe.core.interim`, make `runner`, `options`, `instructions` and
  `effectCheck` come from the actor's config, and decide whether a request may still carry them as overrides. Every
  field above is replaced in place; nothing else depends on where they came from.

Alternatives considered:
- **An interim actor file** (say, `.troupe/actors/<name>.json`). It would pre-empt config's layout (#6) and format,
  and then need migrating. Rejected.
- **`--runner-command '<json array>'`.** Lets a request carry a command line (see above), and needs shell quoting.
  Rejected.
- **A `--script` flag.** The CLI would need to know the scripted runner's option names, and the next runner would
  need its own flag. Rejected in favour of the options file.

### D5. Stages, and the local stage's rule (#3, option C)

`Stage` is a port: `name`, `workspace(theatre) -> Path`, and `admit(policy) -> Admission`. `Admission` says whether
the actor's effects are enforced and, when they aren't, which policy setting and source allowed it. A refusal raises
`stage.effects-unenforced`. Docker stages implement the same port later, and the port gains the actor's declared
effects when config defines them.

**The local stage enforces nothing, so it admits no actor unless `allow_unenforced_local_stage` is true.** Its
workspace is the theatre root.

- **Why every actor, including one that declares nothing.** A process on the host can write any path and reach any
  host, so the local stage can't enforce "no effects" any more than "writes `src/`". A declaration of none is a claim
  it can't check. If only actors that declare an effect were refused, then in this change, where no actor can declare
  anything yet, #3 would never refuse anything, and lineage would never say the run was unenforced. That's the
  quiet fall-through the project rules out. This is the conservative reading of #3, and the one that can't run an
  agent unconfined without someone having said yes.
- **The runner's post-run effect check isn't enforcement** (#3). The two are recorded separately: the stage's
  admission in lineage (D7), the effect check's verdict in the outcome.
- **The check comes first.** `perform` resolves the person's identity and admits the actor before starting the
  runner or recording anything, so a refused `perform` changes nothing and leaves no run.
- The default stage is the named default `STAGE = "local"`. An unknown stage name is `stage.unknown`.

Alternative considered: refusing only actors that declare effects. Rejected for the reason above. If the owner reads
#3 that way, the rule changes in the local stage's `admit` and in one requirement; nothing else depends on it.

### D6. Policy

`troupe.core.policy` is the only code that reads a policy value (#8: "nothing reads a policy value except through one
seam"). It has one setting, `allow_unenforced_local_stage`, whose default is `False`, held in `troupe.core.defaults`
as `ALLOW_UNENFORCED_LOCAL_STAGE`.

- **Interim source: the environment.** `TROUPE_POLICY_ALLOW_UNENFORCED_LOCAL_STAGE`, read from the session's
  environment. It takes exactly `true` or `false`. Unset or empty means absent, which falls through to the default.
  Anything else is `policy.invalid-value`, naming the variable, the value and the two accepted ones. The name rule
  (`TROUPE_POLICY_` and the setting's name in capitals) covers later settings.
- **Each value knows its source** (`default` or `env`), because lineage records what allowed an unenforced run (D7).
- **Not a flag, and not in the request.** A flag would have to travel in `perform`'s request, so any client of a later
  run server could loosen policy. An environment variable is set once, by the person, outside any request, which is
  as close to #3's "user policy" as the skeleton gets.
- **Tighten-only isn't enforceable yet.** There's one source above the built-in default. The config change brings
  policy files and #8's combinators, and decides whether the environment stays a source and at which level.

### D7. Lineage records the stage

`lineage.schema.json` gains a required, nullable `stage`:

```json
"stage": null
"stage": {"name": "local", "effects": "unenforced",
          "allowedBy": {"setting": "allow_unenforced_local_stage", "source": "env"}}
"stage": {"name": "docker", "effects": "enforced", "allowedBy": null}
```

- `allowedBy` is required, and non-null, exactly when `effects` is `unenforced`. The schema says so with one
  `oneOf` branch per kind of stage record, and `lineage_problem` checks the same rule.
- Every event a run records (D8) carries the run's stage. Every other event has `null`.
- **Required and nullable, like `reason`,** so an absent value is explicit. Lineage is checked when an event is
  written, never when it's read, so events recorded before this change still read. None exist outside tests
  (pre-alpha), and the content hash leaves lineage out, so no id changes.
- Alternative considered: putting the admission only in the run-started payload. #3 says "recorded in lineage",
  and lineage is where every reader already looks for where an event came from. Rejected.

### D8. The run stream

A run is its own stream. The run id is a UUID minted by `perform`, the stream's originator id. The library numbers
versions from 1. `seq` stays in the payload.

| Event | Recorded | Payload | Lineage actor and via |
|---|---|---|---|
| `Run.Started` | When `init` arrives, before it; or at the end, if the run ended with no `init` | `actor` (name), `runner {requested, reported}` (`reported` is `init`'s `runner {name, version}`, or null), `stage` (the admission), `instructions` and `options` (artifact references), `effectCheck` | The person who ran `perform` (identity chain), `cli` |
| `Run.Reported` | For each run event, as it arrives | `seq`, `event` (the run event's data, or the `oversized` stand-in, as received) | The agent (`{kind: agent, id: <actor>, source: troupe}`), `runner` |
| `Run.Ended` | Once, after the run host returns | `RunOutcome.to_data()` without `runId`, plus `recording` (D9) | The agent, `runner` |

- **One change id for the whole `perform`.** `Command` gains `acting_as(actor, via)`, a view that shares its change id
  and command cause but records with another actor and via. The event-store service needs no other change, and the
  lineage spec already says a command's events share its change id.
- **The person and the agent are both recorded.** `Run.Started` says who started the run; the run's own events are
  the agent's (#36). The identity chain runs first, so a `perform` with no identity fails before anything starts.
- **Why `Run.Started` waits for `init`:** the owner put the runner's name and version, which only `init` carries, in
  the run-started payload (#36). The cost is that a starting run isn't visible to `status` until its runner answers,
  which is bounded by `RUNNER_START_TIMEOUT_SECONDS`. `perform` itself shows "starting" at once. Recording an extra
  "requested" event first was considered, and rejected as a second event saying what `Run.Started` says.
- **Batches.** `Run.Started` is one batch, then each `Run.Reported` is one batch (one runner message, one fsynced
  append), and `Run.Ended` is one batch. Batches are all or nothing, so a crash never leaves half an event.
- **The aggregate's rules.** `Run` is an `eventsourcing` aggregate. It refuses a `seq` that isn't the next one
  (`run.out-of-sequence`: a bug or a replay, never retried), a `Run.Reported` before `Run.Started` or after
  `Run.Ended`, and a second `Run.Started` or `Run.Ended`. The store's `events.version-conflict` still guards two
  writers racing for one version.
- **Instructions and options go to the artifact store**, referenced by hash. They can be large (an inline script, a
  prompt), and options may hold what shouldn't be in git (#4). Recording them keeps a run reproducible.
- **Topics are the event classes' import paths.** Moving them later needs the library's topic registration for
  renames; the risk is noted below.

### D9. Recording from the async run host

`perform` runs the host under `asyncio.run`, with an `on_event` that records each event through
`asyncio.to_thread(...)` (#36), so fsyncs and git calls stay off the event loop and recording applies back-pressure.

- **A recording failure stops the run; it never raises into the host.** `on_event` catches the failure, keeps it, sets
  the run's cancel signal, and returns. Later events aren't recorded, because a gap would break the `seq` rule. When
  the host returns, `perform` still tries to record `Run.Ended`, with `recording: {"failedAt": <seq>, "error":
  {...}}` (otherwise `recording: null`). Then it reports `run.recording-failed`, naming the run, the first error, and
  the transcript's reference, which the host always keeps.
- **If `Run.Ended` can't be recorded either,** the error says so, and `status` shows the run as interrupted (D11).
  Nothing is lost that the artifact store holds.
- Raising from `on_event` was rejected: the host would unwind without its outcome, and the runner's exit and
  transcript wouldn't be finished cleanly.

### D10. Ctrl-C

- **`troupe.platform.interrupts`** turns Ctrl-C into a callback, on every OS: `signal.signal` for `SIGINT`, and also
  `SIGBREAK` on Windows (Ctrl-Break). It's the only module outside `processes` that touches `signal`, which the import
  contract already confines to `platform`.
- **The first Ctrl-C** sets the host's cancel signal (through `loop.call_soon_threadsafe`) and shows the notice
  `run.cancelling`, with the grace period. The host sends `run/cancel` and kills the runner's tree after
  `RUNNER_CANCEL_GRACE_SECONDS`, so it always ends. `Run.Ended` records `cancelled`.
- **A later Ctrl-C** repeats the notice and does nothing else. Stopping troupe at that point is what would leave a run
  unrecorded, and the grace period is already bounded.
- **The runner never sees the terminal's Ctrl-C.** It's in its own session (POSIX) or process group (Windows), per
  the runner contract's D6, so only troupe decides how it stops.

### D11. Running, ended, interrupted

A run's state is derived, never recorded as "running":

| State | When |
|---|---|
| `ended` | `Run.Ended` is recorded |
| `running` | No `Run.Ended`, and the run's lease is held in this clone |
| `interrupted` | No `Run.Ended`, the run's lease exists in this clone, and nobody holds it: the `perform` that ran it has gone |
| `unfinished-elsewhere` | No `Run.Ended`, and there's no lease for it in this clone: it was started in another clone, and this clone can't tell whether it's still going |

- **The lease** is the platform's directory lock on `.troupe/local/runs/<run-id>/`, taken by `perform` before the
  runner starts and held until `Run.Ended` is recorded. The OS releases it when the process dies, so a killed
  `perform` leaves no stale lease (platform D6). `status` and `logs` try the lock without waiting, as the event store
  does for incomplete batches.
- **Nothing is recorded for an interrupted run.** Recording an ending on behalf of a process that died would be a
  guess about how the run ended. `status` shows the state with the notice `run.interrupted` (or
  `run.unfinished-elsewhere`), which explains it.
- Lease directories are local and small, and they stay. Removing one races with a `perform` that's starting, so
  cleaning them up is left to a later maintenance command, like the artifact store's `tmp/`.

### D12. Projections

Status and logs read two projections, defined in `troupe.core.runs` as pure folds over recorded events:

- **Runs:** every run's summary, from `Run.Started` and `Run.Ended` (and a count of `Run.Reported`), in local
  notification order.
- **Run log:** one run's `Run.Reported` events in `seq` order, with each event's lineage time.

Each query rebuilds what it needs from the store: the runs projection from `notifications(…, topics=[…])`, and a run
log from its stream. There's no persisted read model. A persisted one would need its own file format, its own
tracking and a rebuild rule, and nothing needs it until the house (#5) keeps projections live. The folds take one
recorded event at a time, so they can later run as followers that record their position in the store's tracking log,
without changing.

### D13. Queries: `status` and `logs`

- **Run ids:** a full id, or a prefix of at least 8 hex digits that matches exactly one run. No match is
  `run.not-found`. More than one is `run.ambiguous-id`, listing the matches. The rule is in the core, so every surface
  resolves ids the same way.
- **`status`** with no run lists the most recent runs, newest first, up to `STATUS_RUNS_LIMIT` (20, a named default;
  `--limit` overrides it). With a run, it shows that run's summary.
- **`logs <run>`** prints the run's events in order. `--follow` prints them, then waits for more using the store's
  subscription (`SUBSCRIBE_POLL_SECONDS`). It stops when `Run.Ended` arrives, or when the run is no longer `running`
  (D11), and says why. It never waits on a run that can't progress.
- **`--json`** on `status` and `logs` prints the query's result exactly as its schema shapes it (for `logs --follow`,
  one update per line, then the result). That gives scripts and tests the protocol's own shape, not a parse of
  human text.
- Reads return the store's notices (such as `events.other-branch`) with their results, and the CLI shows them on
  standard error.

### D14. What `perform` prints, and its exit code

- **Standard error** gets progress: the run id at once (`run <id> starting`, with how to follow it from another
  terminal), one line per event as it's recorded, and notices (silence, retries, cancelling).
- **Standard output** gets the result only when the run succeeds: the run id and `succeeded`. Otherwise it stays
  empty, and the outcome's error is rendered on standard error with the run id, following the CLI spec ("a failing
  command never prints something that looks like a result").
- **Exit codes:** `succeeded` → 0. `cancelled` → 130, a new `ExitCode.CANCELLED`, so a script can tell a person's
  Ctrl-C from a failure. Every other outcome → 1. A refused `perform` (identity, policy, a bad request) → the error's
  own code.
- 130 is the shell convention for an interrupt (128 + SIGINT). It's used on Windows too, so scripts see the same code
  on every OS.

### D15. New error and notice codes

- Errors: `theatre.not-found`, `client.invalid-request`, `client.unknown-method`, `runner.unknown`, `stage.unknown`,
  `stage.effects-unenforced`, `policy.invalid-value`, `run.not-found`, `run.ambiguous-id`, `run.out-of-sequence`,
  `run.recording-failed`, `perform.options-invalid`, `perform.path-outside-theatre`. All exit 1, except
  `client.invalid-request`, `client.unknown-method` and `perform.path-outside-theatre`, which exit 2 (`USAGE`): a
  request that isn't understood is a usage error from any surface, and the CLI's values reach the core only as a
  request.
- Notices: `run.cancelling`, `run.interrupted`, `run.unfinished-elsewhere`.
- `stage.effects-unenforced`'s fix names the policy setting and the environment variable, and says the run will be
  recorded as unenforced.

## Risks / Trade-offs

- [Rebuilding the runs projection reads every run's start and end on each `status`] → It reads only two topics. The
  store already reads every segment on open (1.7 s for 10,000 segments, `docs/event-store.md`). A persisted
  projection is the fix if it becomes slow, and the folds are shaped for it (D12).
- [A run isn't visible to `status` until its runner sends `init`] → Bounded by `RUNNER_START_TIMEOUT_SECONDS`.
  `perform` shows the run id at once (D8).
- [Every local run needs the policy turned on, even a scripted test run] → That's #3's point: an unconfined run needs
  a yes. Tests set the variable explicitly, and the refusal's fix says how (D5).
- [Ctrl-C handling differs across OSes] → Only `SIGINT`/`SIGBREAK` through `signal.signal` in the main thread, which
  CPython supports on all three. Tests send the interrupt to a real `troupe perform` process on each OS in CI, the
  way the runner contract's tests kill process trees.
- [A topic rename breaks reading recorded runs] → Topics are fixed by the module path in D1. A move registers the old
  topic with the library.
- [Interim CLI flags become habits] → `docs/runs.md` marks them as interim, and the config change replaces them.

## Migration Plan

Nothing to migrate: no runs exist yet, and lineage's new `stage` field is checked only on write (D7). Rollback is
reverting the change.
