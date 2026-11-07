# Proposal: require the fields troupe always writes

Issue: troupe-run/troupe#305.

## Why

Several schemas keep a field optional, or keep a field troupe no longer writes, only so that event records from
before a change still read. troupe is pre-1.0 and there are no old records (owner, 2026-11-07, on #296): each such form
is flexibility nobody needs. It weakens the contract, and it keeps code paths and tests that check shapes troupe can
no longer produce. A field troupe always writes should be required wherever it appears.

## What Changes

The four places #305 names:

- **`init.effects`** is required in the runner contract's `init`, so it's required in what a runner sends and in what
  troupe records and reads back (`$defs/hostEvent`). The SDK's `InitEvent.effects` is no longer optional, and
  `parse_event` loses its separate check for it.
- **`Run.Started`'s `workspace`** is required. The runs projection no longer reads a start without one as a run in
  the theatre.
- **`Run.Started`'s `runtime`** stays optional, because an actor with no runtime is a real absence. Its description
  loses "or the run was recorded before runtimes".
- **`Run.Ended`'s `outcome.audit`** is required whenever the runner started, as `exitCode`, `transcript` and `stderr`
  already are. The client run summary's `audit` is present exactly when the summary has a `transcript`, that is when
  the run ended and its runner started. Both descriptions lose "or the end was recorded before audits".

What the search for other "recorded before" leniency found (in scope by #305's third bullet):

- **`Run.Started`'s `runner_reported`** is removed. troupe stopped writing it when a run's start came to be recorded
  before its runner. It's kept only so a start recorded by an older troupe reads, and the projection still falls back
  to it.
- **`Run.Started`'s `workspace.clones`** is removed from the worktree workspace for the same reason: clones are
  recorded in `Run.WorktreeMade`. The client run summary keeps `clones` on its worktree workspace (absent until the
  worktree is made, a real absence), so the client schema gets its own worktree workspace instead of sharing
  `Run.Started`'s. `Run.WorktreeMade`'s description loses "or its start was recorded by an older troupe".

Code and tests: drop the core and SDK code paths that exist only for the old shapes (the theatre fallback, the
`runner_reported` and start `clones` fallbacks, the aggregate's optional `workspace` and its `runner_reported`
parameter) and the tests that check them. Tests that build records "as an older troupe would have" are rewritten
to build what troupe writes now, or removed.

Not changed: what any field means, and the actor rule that refuses at perform an actor written before a config rule
was tightened (`check_actor`). That rule is strictness, not leniency: config is written by people and can be edited by
hand, so perform keeps checking it.

**BREAKING** (protocol): records and messages that omit these fields, or carry the removed ones, no longer validate.
The protocol changes in place at version 0, as earlier pre-1.0 changes did, and the release is marked breaking, which
before 1.0 bumps the minor version. There are no theatres to migrate.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `runner-protocol`: "Init says how the runner applies the effects" says an init without `effects` doesn't validate
  wherever troupe reads one, as a runner sends it or as troupe recorded it.
- `runs`: "What a run was asked to do is kept" says a start without its workspace, or with clone mechanisms in it,
  doesn't validate. Two requirements are replaced under new names, because a MODIFIED block can't drop a scenario: "A
  run's summary leaves out a runner that never reported" becomes "The reported runner comes from the run's init",
  without the older-troupe scenario; "A run's end records its audit" becomes "A run's end records its audit whenever
  its runner started", without the before-audits scenario.
- `client-protocol`: "A run summary carries its run's audit" says `audit` is present exactly when the run ended and its
  runner started.

## Impact

- `protocol/schemas/runner/run-event.schema.json`, `events/run-started.schema.json`, `events/run-ended.schema.json`,
  `events/run-worktree-made.schema.json`, `client/run.schema.json`, and their packaged copies.
- `packages/troupe-plugin-sdk`: `InitEvent`, `parse_event`, their tests.
- `packages/troupe`: `core/runs/aggregate.py`, `core/runs/projections.py`, `core/client/messages.py`
  (`RunSummary`'s audit rule), and the tests in `test_run_aggregate.py`, `test_event_payloads.py`,
  `test_run_queries.py`, `test_run_changes_recording.py`, `test_perform.py`, `test_client_messages.py`.
- `docs/prompt-book/events.md`, regenerated from the schemas.
- #296 (`failure-reason`) edits `run-event.schema.json` in parallel; whichever lands second rebases. No runner plugin
  changes: every runner already sends `effects`.
