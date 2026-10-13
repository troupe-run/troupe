# Design

## Context

See proposal.md for why. What exists on main (69d6c27):

- **The nulls.** A walk of every schema in `protocol/` and `plugins/*/schemas/` finds 33 nodes that accept `null`:
  the 32 that #76 lists, plus `lineage.schema.json#/$defs/stage/oneOf/0`, which is `stage` itself. Every one is
  `type: [T, "null"]`, `anyOf`/`oneOf` with `{"type": "null"}`, or `allowedBy: {"type": "null"}`. No plugin schema
  has one. The runner contract already uses absence for optional fields (`retry.maxAttempts`, `message`), so it is
  the precedent.
- **The walker** (`packages/troupe/tests/strictness.py`) knows every keyword it meets. An unknown keyword fails, so
  a marker keyword has to be added to its list. It walks `if` and `not` as conditions, which never widen what is
  accepted.
- **Python writes nulls in five places:**
  - `Lineage.to_data`, `VcsState.to_data` and `StageLineage.to_data` in `core/events/lineage.py`.
    `lineage_problem` requires the exact key set.
  - `encode_header` in `troupe_store_text/codec.py`. `_header` requires the exact key set.
  - The run aggregate (`core/runs/aggregate.py`). `eventsourcing` stores every parameter of an `@event` method as
    an event attribute, so `runner_reported=None` and `recording=None` are serialised as `null`. When an event is
    applied again, the library passes only the attributes the stored state has (`filter_kwargs_for_method_params`).
    A parameter that is missing from the state therefore needs a default.
  - `RunOutcome.to_data` (`core/runners/outcome.py`) and `_recording_failed` (`core/runs/perform.py`).
  - Raise sites: `cli/parser.py` (`suggestion`), `core/runners/outcome.py` (`exitCode`), `core/runs/perform.py`
    (`failedAt`, `endError`, `transcript`), `core/runners/host.py` (`maxAttempts`), and `troupe_store_text/store.py`
    (`events.other-branch`'s `branch`).
- **The client messages' codec** (`core/messages.py`) already leaves out a field whose default is `None`. The
  `nullable=True` option is what sends `null`, and only `core/client/messages.py` uses it, 8 times.
- **Readers that index fields which become optional:** `runs/projections.py` (`started["runner_reported"]`),
  `cli/render.py` (`run["error"]`, `run["endedAt"]`, `run["transcript"]`, `run["stderr"]`, `run["recording"]`), and
  `cli/commands.py` (`run["error"]`).
- **When a value exists.** A runner that never started has no exit code, transcript, stderr or result
  (`host._not_started`). One that started always has an exit code, a transcript and a stderr reference, because
  the child has been waited on and both sinks are opened before the start completes. A run summary's `outcome`
  and `endedAt` exist exactly when its end is recorded, which is what makes `state` `ended`
  (`queries.run_state`).
- **What else checks the shapes.** `tests/protocol_guard.py` validates every error, notice and recorded payload
  against its schema as tests make them. There is no theatre outside development, and none is committed to this
  repository.

## Goals / Non-Goals

**Goals:**
- Make the rule mechanical: the walker fails the build for an unmarked null, and for an optional property whose
  absence isn't described.
- Use structure where a field's presence follows from another field (`ending`, `state`), so a contradiction doesn't
  validate.
- Put the "leave it out" decision in as few places as possible on the Python side.

**Non-Goals:**
- Defining PATCH or "clear this" semantics. The `clear` marker kind exists so #60 has somewhere to put it, but no
  schema uses it yet.
- Reading event segments written before this change (D7).
- Validating at run time. Validation stays in the tests (runner-contract D11).

## Decisions

### D1. The marker is an `x-troupe-null` annotation naming its kind and meaning

A node that accepts `null` carries `"x-troupe-null": {"kind": "clear" | "external", "means": "<non-empty>"}`. The
walker treats it as a value keyword (data, not a subschema). On every node that accepts values (so not inside
`if`/`not`), it checks:

- The node accepts null (`type` is or contains `"null"`, `const` is `null`, or `enum` contains `null`) without a
  marker: report "accepts null without saying why".
- There is a marker, but the node accepts no null: report "marks a null it doesn't accept".
- The marker isn't an object with exactly `kind` (one of the two values) and a non-empty `means`: report "has a
  malformed null marker".

The one use is `runner/error-response.schema.json`'s `id`:
`{"type": "null", "x-troupe-null": {"kind": "external", "means": "the request couldn't be read (JSON-RPC 2.0)"}}`.

*Alternatives.*
- A bare `$comment` can't be checked.
- A boolean `"nullable": true` (OpenAPI 3.0's spelling) means something else in OpenAPI, and it says neither why
  nor which kind.
- A custom vocabulary (`$vocabulary`) is the formal route, but needs a meta-schema troupe would publish and every
  validator would have to load. An `x-` annotation is ignored by validators, as draft 2020-12 allows for unknown
  keywords, and is easy to replace with a vocabulary later.

### D2. Every optional property describes its absence, and the walker checks it

A property that a node declaring an object (its `type` includes `object`) doesn't list in `required` must have
a `description`. A branch that only refines a property the declaring node already has, such as each error code's
`{"code": {"const": ...}}`, doesn't repeat it. A property required only under a condition (`if`/`then`) is still
sometimes absent, so it still needs a description.

Today 39 optional properties have none:
- 26 in the scripted runner's options: `runId`/`seq` in a script line, `maxAttempts`, `message`, `usage`, `costUsd`.
- 9 in run events.
- 3 in the error fields.
- 1 in `status`'s request.

Each gets a description that says what its absence means.

The walker checks that a description exists, not what it says. A human reviews the wording.

*Alternative.* Check only the fields this change converts. That leaves the issue's rule ("each optional field's
schema description says what its absence means") unchecked everywhere else, and #60 would add schemas under a rule
nothing enforces. This goes beyond #76's list, and the owner agreed to include it (2026-10-13).

### D3. Where presence follows from another field, the schema says so

- **`Run.Ended.outcome`:** an `if`/`then`/`else` on `ending`. If `ending` is `never-started`, `exitCode`,
  `transcript`, `stderr` and `result` are not allowed. Otherwise `exitCode`, `transcript` and `stderr` are
  required. `error` and `result` stay optional, with their absence described.
- **The client run summary:** an `if`/`then`/`else` on `state`. If `state` is `ended`, `outcome` and `endedAt` are
  required. Otherwise both are not allowed.
- **`runner.crashed` and `run.unclean-exit`:** if `ending` is `never-started`, `exitCode` is not allowed. Otherwise
  it is required.
- **Lineage `stage`:** two closed branches. An `enforced` stage has no `allowedBy` property at all, and an
  `unenforced` one requires it.

"Not allowed" is written `"properties": {"x": false}`. The walker already accepts `false`, so the schemas need no
new keyword. The closure is unchanged: each branch sits under the enclosing object's `additionalProperties: false`,
or the conditional lists only properties that the object already declares.

*Alternative.* Leave every field independently optional, with descriptions only. That is simpler, but a run end
with `ending: exited` and no `exitCode` would validate, and the issue asks for "a meaningful value" where one
exists.

### D4. Python leaves absent fields out where each payload is built, with one exception for event fields

- **Lineage, the segment header, `RunOutcome`, the recording failure and every raise site** build their dict
  without the key when the value is `None`. `lineage_problem` and `codec._header` accept the key's absence and
  refuse `null` with the field named.
- **Client messages:** the `nullable` option is removed from `json_field`. The eight fields become
  `default=None`, which the codec already leaves out on write. On read, the codec refuses `null` for them: a value
  that is present has to match the field's non-null type. If #60 needs a "clear", it adds the marked form then.
- **Event fields:** the library gives every `@event` parameter an attribute, so the aggregate can't leave one out
  itself. `EventStore._stored` already rewrites each event's state to add lineage. It now also removes top-level
  keys whose value is `null`. Each aggregate method parameter that can be `None` gets the default `None`, so a
  record without the key reads back. A test checks that every `@event` parameter typed `X | None` defaults to
  `None`, so a new optional field can't be stored as absent and then fail to read back.

  Only top-level keys are removed. Nested values (the outcome, a reported run event) are written as built. A
  nested `null` is therefore a bug in what built it, and the guard catches it. A run event received from a runner
  is never rewritten.

*Alternatives.*
- A recursive "drop nulls" in `strict_json.dumps` or the transcoder would hide bugs, and would rewrite a runner's
  event as it was received. Payloads are recorded as received, never reformatted.
- A custom transcoding per event class is more code for the same effect as the one place in `_stored`.

### D5. No null in the catalogue needs its own value

| Field | What null meant | Decision |
|---|---|---|
| `suggestion` (2 codes) | No close match | Left out |
| `exitCode` (2 codes) | The runner never started | Left out, tied to `ending` (D3) |
| `failedAt` | Only the end failed to record | Left out |
| `endError` | The end was recorded | Left out |
| `transcript` (`run.recording-failed`) | The runner never started | Left out |
| `maxAttempts` (`run.retrying`) | The runner didn't say: unknown, not unbounded | Left out, as in the runner's own `retry` event |
| `branch` (`events.other-branch`, header, lineage) | Detached HEAD, or an adapter without branches | Left out. The adapter (`vcs`) says which, and nothing reads the difference today |

*Alternative for `branch`:* a `detached: true` flag. It would split one absence into two, but nothing consumes the
distinction. Adding the flag later is a compatible change. Removing it would not be.

### D6. Lineage's reversal is stated, not hidden

Lineage's schema description said "absent is explicit, never a missing field". The new descriptions say what each
absence means. The lineage spec's stage requirement, whose "Stage is never missing" scenario says the
opposite, is removed with its reason and replaced by "Lineage records the stage an event's run was on". The new
requirement has "a null stage is refused" and "an event outside a stage has no `stage`". Lineage is still left out of the content hash, so event ids are
unaffected by any of this. Run events' content does change for new events, because `runner_reported`, `recording`
and the outcome's fields are in the hashed state.

### D7. Old segments aren't read, and the record format isn't bumped

A segment written before this change has nulls. Its header (`"branch": null`) fails `_header`. Its payloads fail
the schemas and `lineage_problem`, but neither runs on read. They would read back through `.get()` as `None`.

The owner settled this (2026-10-13): there are no old segments, because troupe is early in development and no
theatre exists outside it. So troupe refuses the old form and keeps record format 1, which changes in place the way
the runner contract's version 0 does (strict-schemas D9).

*Alternatives.*
- Bumping the record format to 2 protects nobody, and `events.unknown-format`'s fix ("upgrade troupe") would be
  wrong for an older format.
- Reading both forms would mean the schemas keep accepting null, which defeats the rule.

## Risks / Trade-offs

- [A reader indexes a field that is now optional, and raises `KeyError` on a real payload] → The readers are listed
  in Context and switch to `.get()`. Tests for status, logs and perform cover a run that never started (no
  transcript), a running run (no outcome) and a recording failure, built from real runs rather than hand-written
  fixtures.
- [`_stored` removing top-level nulls hides a field the aggregate forgot to default] → The test on `@event`
  parameter defaults (D4) fails first. The round-trip tests load each run aggregate back from the store.
- [39 new descriptions are written quickly and say nothing] → Each must say what absence means, not restate the
  name. Review reads them as a list (`tasks.md` 1.4 prints them).
- [`if`/`then`/`else` schemas give worse validation messages] → The guard's failures name the schema location.
  Python gives its own messages and doesn't use the schema to explain them.

## Migration Plan

There is nothing to migrate (D7).
