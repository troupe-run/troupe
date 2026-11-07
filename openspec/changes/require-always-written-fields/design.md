# Design: require the fields troupe always writes

See [proposal.md](proposal.md) for why. Behaviour is in the deltas to [runner-protocol](specs/runner-protocol/spec.md),
[runs](specs/runs/spec.md) and [client-protocol](specs/client-protocol/spec.md).

## Context

- **`init.effects`.** `run-event.schema.json` makes `effects` optional in `$defs/init`. `$defs/event` (what a runner
  sends) adds it back with `allOf [init, {required: [effects]}]`; `$defs/hostEvent` (what `Run.Reported` and a client's
  logged event hold) uses the plain `init`. The SDK mirrors this: `InitEvent.effects` defaults to `None`, and
  `parse_event` refuses a runner's init without it in a separate check. Every runner already sends it: claude-code
  and ollama write it into their init, openai passes it to `InitEvent`, and scripted fills it in (`setdefault`) when a
  script leaves it out. The scripted runner's options schema refers to `$defs/init/properties/effects`, which stays.
- **`Run.Started`.** The aggregate's `__init__` (the `Started` event) takes `runner_reported`, `workspace` and
  `runtime` as keyword arguments defaulting to `None`, and a field with nothing to say is left out of the stored event.
  `perform` always passes `workspace`, never `runner_reported`. `RunView.workspace` reads a start without a workspace
  as the theatre, and `RunView.summary` reads `runner_reported` before the init's runner. `RunView.workspace` also
  adds `Run.WorktreeMade`'s clones only when the start doesn't hold its own.
- **Shared workspace definitions.** `client/run.schema.json`'s summary uses `run-started.schema.json#/$defs/workspace`
  for its `workspace`, and that definition's worktree carries `clones`. So `clones` is in `Run.Started`'s schema only
  because the summary needs it. `run-worktree-made.schema.json` refers to `run-started.schema.json#/$defs/clones`.
- **The audit.** `Run.Ended`'s `outcome` requires `exitCode`, `transcript` and `stderr` in the `else` (runner started)
  branch of its `if ending is never-started`, but not `audit`. `RunOutcome.audit` is `None` when the runner never
  started or the caller passed `NoAudit`. Only the conformance suite passes `NoAudit`, and it records nothing.
  `perform` always audits. In the summary, `RunSummary._check` refuses `audit` on a run that hasn't ended, and nothing
  else.
- **Generated copies.** `packages/troupe/src/troupe/protocol/` is generated from `protocol/schemas/` by
  `scripts/package_schemas.py`, and `docs/prompt-book/events.md` by `scripts/docs_reference.py`. A test checks each.

## Goals / Non-Goals

**Goals:**
- Each schema says what troupe writes now, and nothing that only an older troupe wrote.
- The SDK's and core's message classes enforce the same rules as the schemas, so a client reading a message and a
  schema validating it agree.

**Non-Goals:**
- Changing `check_actor`, which re-checks an actor at perform (proposal, "Not changed").
- Making `runtime` conditionally required. A start can't tell whether its actor named a runtime without working out
  its config, so the schema can't express that rule. Only the description changes.
- Changing the protocol version number (D6).

## Decisions

### D1. `effects` is required in `$defs/init` itself

`$defs/init` lists `effects` in `required`, and `$defs/event` refers to `init` directly. So the runner's form and the
recorded form are one definition again. `hostEvent`'s description loses its sentence about older inits.

In the SDK, `InitEvent.effects` becomes `Literal["checked", "translated"]` with no default. It moves above `engine`
in the dataclass, since a field with no default can't follow one with a default. Order in the JSON is unaffected.
`parse_event` loses its own check: `from_data` now refuses a missing `effects` with the SDK's usual "missing required
field 'effects'". That is the message `parse_event` gave before, so a runner sees the same refusal.

*Alternative:* keep the `allOf` in `event` and add `required` to `hostEvent` too. Rejected: two places saying the
same thing, for a distinction that no longer exists.

### D2. `Run.Started`'s `workspace` is a required argument, and the projection trusts it

`workspace` joins the schema's `required` list. The aggregate's `__init__` takes it as a required argument, placed
before the optional `runtime`. The eventsourcing library rebuilds the event from its stored state by name, so the
order of the arguments doesn't matter for reading. `RunView.workspace` reads `self.started["workspace"]` and drops
the theatre fallback. A start without one is refused by the schema, and the projection doesn't guess.

### D3. `runner_reported` and the start's `clones` are removed, not made required

troupe no longer writes either, so requiring them would be wrong. Both leave `Run.Started`'s schema. The aggregate
loses its `runner_reported` parameter. `RunView.summary` takes the reported runner only from the init. `RunView.workspace`
adds `Run.WorktreeMade`'s clones to a worktree whenever they're recorded, with no check for clones in the start.

The summary still shows `clones` on a worktree workspace once the worktree is made. So `client/run.schema.json` gets
its own `$defs/workspace` (`oneOf` the start's theatre workspace and its own worktree workspace). Its worktree
workspace lists `kind`, `path`, `prefix`, `base` and `dirty`, each a `$ref` to the matching property of the start's
worktree workspace, plus `clones`. Its own description says `clones` is absent until the worktree is made. The
summary's `if workspace is a worktree` condition refers to the client's own worktree definition. `$defs/clones` moves
to `run-worktree-made.schema.json`, the event that records it, and both the start's old references and the client's
point there.

*Alternative:* keep `clones` in the shared definition and forbid it in `Run.Started` with an `allOf`. Rejected: the
event's schema, and the events reference generated from it, would still list a field the event may never hold.

Core's `WorktreeWorkspace` message (client side) keeps `clones: ... | None`, since that absence is real.

### D4. The end's audit is required in the runner-started branch

`audit` joins `exitCode`, `transcript` and `stderr` in the `else` branch's `required`. The `then` branch already
forbids it. `RunOutcome.audit` stays optional in core, because the conformance suite runs with `NoAudit` and records
no end. Its docstring says that `perform` always audits, so a recorded end whose runner started always has one. The
payload tests, which validate what `perform` records against the schema, check that rule. The aggregate doesn't add a
check of its own, as it doesn't for `exitCode` either.

### D5. An ended summary's audit is present exactly when its transcript is

An ended summary carries a `transcript` exactly when its runner started, and so it carries an audit. The client
schema's first `allOf` entry (`if state is ended`) gets the rule in its `then`: `if required [transcript] then required
[audit] else audit: false`. Its `else` (not ended) already forbids `audit` and stays. `RunSummary._check` adds the same
rule for an ended summary, naming `audit`, beside its existing "audit only when ended".

The rule is scoped to ended summaries because the schema doesn't forbid a `transcript` on a run that hasn't ended,
although its description says it's absent then, and the property test generates one. A rule of "audit exactly when
transcript" for every state would quietly make such a summary invalid, which tightens `transcript`. That's outside
#305 (it isn't leniency for old records), so it's raised as its own issue, troupe-run/troupe#313, rather than folded in.

*Alternative:* key the rule on the end's `ending`. Rejected: the summary doesn't carry `ending`, and `transcript` is
already specified as present exactly when the runner started.

### D6. The protocol changes in place, and the release is marked breaking

The protocol's version stays 0, as it did for earlier pre-1.0 changes (#272 added `audit` in place). The commit that
changes the schemas is a Conventional Commit marked breaking (`feat(protocol)!: ...`), so release-please bumps the
minor version before 1.0, as #305 asks. Nothing reads records from before this change, so there's no migration.

### D7. Tests that build old shapes are rewritten or removed

- Removed: the SDK test that an init without `effects` reads as a host event (`test_runner_types.py`), the query test
  that a recorded init without `effects` still reads (`test_run_queries.py`), and the query test of a start that holds
  `runner_reported` and clones (`started(..., runner_reported=...)`).
- Rewritten: `test_run_aggregate.py`'s and `test_event_payloads.py`'s starts with `runner_reported` and clones,
  `test_run_changes_recording.py`'s run without a workspace and end without an audit, and `test_perform.py`'s check
  of `loaded.runner_reported`. Each builds what troupe writes now.
- Added, one per spec scenario that's new: an init without `effects` fails `hostEvent` and `InitEvent.from_data`; a
  start without `workspace`, with `runner_reported`, or with workspace `clones` fails the start schema; an end whose
  runner started and that has no audit fails the end schema; a summary with a transcript and no audit, or an audit
  and no transcript, fails the client schema and `RunSummary.from_data`. The existing property test that generates
  summaries (`test_client_messages.py`) generates `audit` for an ended summary exactly when it generates `transcript`.

## Risks / Trade-offs

- [A test fixture somewhere still builds an old shape, and only fails once a schema tightens] → the full check runs
  every test and validates every recorded payload, so a missed fixture fails loudly. Fix it to the current shape. Don't
  loosen the schema.
- [#296 edits `run-event.schema.json` at the same time] → the edits are in different definitions (`init` and
  `result`). Whichever lands second rebases and re-runs the full check, and the packaged copy and events reference are
  regenerated after the rebase.
- [A theatre made during pre-release testing holds old records] → none exists (owner, 2026-11-07). The projection
  no longer reads one without a workspace as the theatre, so such a record would fail to read instead of being
  misread. Pre-1.0, that's accepted (proposal, BREAKING).
