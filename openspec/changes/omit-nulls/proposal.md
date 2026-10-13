# Proposal

Issue: troupe-run/troupe#76. It extends the strict-schemas rule from #7 and #70 (PR #72), and records the owner's
decision in review of #72: prefer a smaller payload with the key left out over a key sent as `null`, define clearly
what absence means, and never force a sentinel (`""`, `-1`) that loses meaning. Blocks #60: the config model, and
every file it projects, should start from this rule instead of being converted later.

## Why

Main has 33 places where a schema accepts `null`. Every one is the `x: T | null` pattern: the field is required and
sometimes null. A null that means "nothing to say" makes each payload bigger and hides the meaning in a value, and
it blurs a distinction the protocol will need soon. In an update, `{ "x": null }` means "clear x" and `{ }` means
"leave x alone". #60's config `set` is the first command that needs that. Nothing stops the next schema from adding
another null, so the rule has to exist and be checked before the config schemas arrive.

## What Changes

- **The rule, in the protocol spec.** A field with nothing to say is left out, and each optional field's description
  says what its absence means. Where a real value has its own meaning, that value is used instead of absence. A
  sentinel that loses meaning is never used. `null` is accepted only where it says something absence can't: "clear
  this" in an update, or a format troupe doesn't own. Such a node carries an explicit marker.
- **The strictness check enforces it.** The walker in `tests/strictness.py` refuses a schema that accepts `null`
  (by `type`, `const` or `enum`) unless the node carries the marker. It also refuses a marker that is malformed, or
  that sits on a node that accepts no `null`. A bad-schema test covers each case.
- **One exception, marked:** `runner/error-response.schema.json#/properties/id`. JSON-RPC 2.0 requires `"id": null`
  when the failed request couldn't be read.
- **Every other nullable field becomes optional, or gets a meaningful shape.** This covers the 32 fields #76 lists,
  plus one it missed: lineage's `stage` itself.
  - **Lineage:** `reason`, `stage` (with `allowedBy`), `vcs.branch`, `vcs.head`, `vcs.source`, and the source's
    `before`/`after` are left out when absent. **BREAKING:** this reverses lineage's earlier choice that "absent is
    explicit, never a missing field". `allowedBy` appears only on an `unenforced` stage, as the schema already
    implies.
  - **Segment header:** `branch` is left out when the segment was written with no branch.
  - **Recorded run events:** `Run.Started.runner_reported` and `Run.Ended.recording` are left out when absent.
    Inside the outcome, `error` and `result` are left out when there are none. `exitCode`, `transcript` and
    `stderr` are present exactly when the runner started (`ending` isn't `never-started`), and the schema says so.
  - **Client run summary:** `outcome` and `endedAt` are present exactly when `state` is `ended`. `error`,
    `transcript`, `stderr`, `recording` and `runner.reported` are left out when absent.
  - **Error and notice details:** `suggestion` (two codes), `exitCode` (two codes, present unless the runner never
    started), `failedAt`, `endError` and `transcript` on `run.recording-failed`, `maxAttempts` on `run.retrying`,
    and `branch` on `events.other-branch` are all left out when absent. None of their nulls carries a meaning that
    needs its own value (design D5).
- **The Python side writes no `null`.** Lineage, the segment header, the run aggregate's events, the run outcome,
  the client messages (the `nullable` option on `json_field` is removed) and every raise site leave absent fields
  out. Readers accept a field's absence and nothing else. The test guard already validates every error, notice and
  recorded payload as tests make it, so a leftover `null` fails the test that produced it.
- **Stored events change shape in place.** A segment written before this change would hold nulls that the
  schemas and the segment-header reader no longer accept. There are none: troupe is early in development and has
  no theatres to migrate. troupe doesn't read the old form, and the record format stays 1 (design D7).
- **Docs:** `protocol/README.md` and `docs/event-store.md` state the rule and the new lineage shape.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `protocol`: adds the null rule, the marker, and the strictness check's enforcement and self-tests. The JSON-RPC
  `id` is the one exception.
- `lineage`: `reason`, `stage`, `allowedBy`, `vcs.branch`, `vcs.head`, `vcs.source` and its `before`/`after` are left
  out when absent, never sent as null. The "stage is never missing" scenario is reversed.
- `event-store`: a segment header leaves out `branch` when there is none. No troupe event payload holds a null.
- `runs`: a run's start and end leave out what didn't happen. The outcome's exit code, transcript and stderr are
  present exactly when the runner started.
- `client-protocol`: a run summary carries `outcome` and `endedAt` exactly when the run has ended, and leaves out
  every other absent field.
- `runner-protocol`: an error response's `id` is `null` only when the request couldn't be read, and is the one null
  marked as an external constraint.

## Impact

- `protocol/schemas/`: `lineage`, `event-record`, `error`, `notice`, `events/run-started`, `events/run-ended`,
  `client/run` and `runner/error-response`. No plugin schema has a null today.
- `packages/troupe/tests/strictness.py` and `test_protocol_strict.py`: the null rule, the marker, and the bad-schema
  fixtures.
- `packages/troupe`: `core/events/lineage.py` (`to_data` and `lineage_problem`), `core/runs/aggregate.py` (optional
  event fields default to `None` so a record without them reads back), `core/events/service.py` (a `None` event
  field isn't stored), `core/runners/outcome.py`, `core/runs/perform.py`, `core/runs/projections.py`,
  `core/client/messages.py`, `core/messages.py` (`nullable` removed), and the raise sites of the seven detail fields.
- `packages/troupe-store-text`: `codec.py` (header encode and decode).
- Tests that assert null-valued shapes are updated to assert absence. Fixtures are taken from real output, not
  written by hand.
- Docs: `protocol/README.md`, `docs/event-store.md`.
- No new dependency.
