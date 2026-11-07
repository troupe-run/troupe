# Design

## Context

See proposal.md for why. Observed today:

- **The host** (`packages/troupe/src/troupe/core/runners/host.py`, `transcript_record`) parses each `run/transcript`
  with the SDK's `TranscriptRecord`, decodes base64 if asked, masks the bytes, and writes them plus `\n` to the
  transcript's artifact writer, counting those bytes against `transcript_max_bytes`. Nothing reads a transcript back:
  a run keeps its `sha256:` reference (`Run.Ended`'s outcome, the client's run summary, `troupe status`).
- **The host offers no capabilities** (`OFFERED_CAPABILITIES = ()`), and refuses an answer naming one it didn't offer.
  The schemas type capability names as any non-empty string. Every runner answers `[]`.
- **OpenAI** (`exchange.py`, design D10 of `2026-11-06-openai-style-runner`) wraps each record in its own JSON object:
  `request` (URL and body), `response` (status and kept headers), `stream`, `body` (decoded with `replace`) and
  `dropped`. Its masking has to cope with the credential inside JSON escapes partly because of that wrapping.
- **Ollama** (`conversation.py`, design D7 of `2026-11-04-local-model-runner`) sends the first request's body, each
  message it adds, and each answer line and error body, as raw bytes, base64 when they aren't UTF-8. That design
  rejected an `origin` field because "the field would need a stored form".
- **Claude Code** and **scripted** pass native lines through. The scripted runner's tests drive the host with argv
  they choose (`test_run_host.py`, `test_runner_conformance.py`).

## Goals / Non-Goals

**Goals:**
- One vendor-neutral way to label records, so an API runner's records read the same whichever runner wrote them.
- A stored form that is never guessed: a reader knows from the run's end whether each line is a raw record or a
  framed one.
- Native transcripts unchanged, byte for byte.

**Non-Goals:**
- Reading or showing transcripts (a `logs --transcript` or a UI). Nothing reads them yet. This change makes them
  readable, and leaves the reading to the change that first needs it.
- Defining a `note`'s content. It's the runner's own text. This change says only that a note isn't traffic.
- Kinds for Claude Code. Its output is its engine's native stream, and what it is sent (the prompt) is an argument,
  not a record.
- Migrating stored transcripts or run ends. Pre-1.0 there are none to keep.

## Decisions

### D1. Three kinds: `sent`, `received`, `note`

`sent` is what the runner sent its engine, verbatim: a request body, or a message it added to the conversation it
holds. `received` is what came back, verbatim: a stream line, a body. `note` is the runner's own record about the
exchange, such as a status line and the headers it keeps, or a stream it gave up on. Absent means the engine's native
output, which is every record today.

- *Why these:* a reader's first question about an API transcript is which way a record went, and whether it is
  traffic or commentary. Anything finer (stream line or body, request or added message) is vendor vocabulary, and the
  record's own content already shows it.
- *Alternative:* OpenAI's five (`request`, `response`, `stream`, `body`, `dropped`). Rejected because they're HTTP-
  and OpenAI-shaped, and Ollama has no `response` record.
- *Alternative:* Ollama D7's `origin: runner | engine`. Rejected because it has no place for a note, so OpenAI's
  status records would have to pass as traffic.

### D2. A capability turns kinds on for the whole run

troupe offers `transcript-kinds` at `initialize`. A runner that accepts it gives every record a kind, and one that
doesn't gives none. A record that breaks the rule is a protocol violation (the host's existing `_violation`, so no new
error code), and nothing is stored for it.

- *Why all or nothing:* the stored form is chosen once per run. A run that mixed forms would leave each line to be
  guessed, and a native line can look exactly like a framed one.
- *Why `initialize`:* capabilities are the contract's negotiation, and they're what make this compatible both ways.
  An older host offers nothing, so a new runner sends records without kinds. An older runner never accepts, so a new
  host stores it natively. One run per process means a per-process choice is a per-run choice.
- *Alternative:* declare it in `run/start`'s answer. Rejected because it needs the capability anyway, so an older
  host doesn't refuse an unknown field, and then it would be two declarations for one choice.
- **Capability names become a closed list** (`enum: ["transcript-kinds"]`) in both `initialize` schemas, and in the
  SDK's types, per the strictness rule that unknown values are errors. The host's existing check (a name it didn't
  offer) stays as the runtime check.

### D3. The stored form of a framed line

In a run that uses kinds, each stored line is compact JSON, its keys in this order:
`{"kind":"<kind>","record":"<text>"}`, plus `"encoding":"base64"` exactly when the runner sent the record as base64.
It's serialised with `ensure_ascii=False` and `(",", ":")` separators, followed by `\n`. A new schema,
`protocol/schemas/transcript-record.schema.json` ("one line of a transcript whose run used kinds"), defines it, and the
strictness test covers it.

- **Masking comes before framing.** The host masks the record's bytes as today, then frames them. A UTF-8 record is
  stored as the masked text. Masking replaces a valid UTF-8 needle with ASCII, and UTF-8 is self-synchronising, so
  the masked bytes still decode. A base64 record is decoded, masked, and base64-encoded again. Masking raw bytes
  before JSON escapes them is what removes the escape problem OpenAI's masking had to handle.
- **The encoding the runner chose is kept,** rather than troupe choosing it again from the bytes, so a reader gets
  back exactly what the runner sent, minus the credential.
- **The limit counts stored bytes**, the framing included. The limit protects the store, and a framed line is what
  goes there.
- *Alternative:* store kinds in a second artifact beside native lines. Rejected because two artifacts have to be
  kept in step, and a run would need two references.
- *Alternative:* frame every run, with Claude Code's records as kind `native`. Rejected (owner, 2026-11-07, when
  choosing between the options) because it costs Claude Code its byte-for-byte stream-json, and makes it 10–20%
  bigger from escaping.

### D4. The run's end names the form

`Run.Ended`'s outcome gains `transcriptFormat`: `native` or `kinds`. The host decides it at `initialize` and it travels
in the outcome (`outcome.py`) beside `transcript`. Schema: `transcript` and `transcriptFormat` each require the other
(`dependentRequired` both ways), and `never-started` forbids both, as it forbids `transcript` today.

- **No leniency for older ends.** Pre-1.0 there are no recorded runs to read back, so the field is required wherever
  a transcript is, with no "absent: recorded before this" form (owner, 2026-11-07, on #296). The `audit` precedent
  isn't followed.

The client's run summary carries `transcriptFormat` exactly when it carries `transcript` (`dependentRequired` both
ways), projected straight from the end. `troupe status` shows it after the reference: `transcript: sha256:… (kinds)`,
and nothing extra for `native`.

### D5. The OpenAI runner's records

| Was | Now |
|---|---|
| `{"kind":"request","url":…,"body":…}` | `sent`: the body as sent |
| `{"kind":"response","status":…,"headers":…}` | `note`: `{"status":…,"headers":{…}}`, compact JSON |
| `{"kind":"stream","line":…}` | `received`: the line |
| `{"kind":"body","body":…}` (decoded with `replace`) | `received`: the body's bytes, base64 when they aren't UTF-8 |
| `{"kind":"dropped","reason":…}` | `note`: `{"dropped":"<reason>"}` |

- **The URL leaves the transcript.** `Run.Started` records the runtime's resolved `endpoint`, and the URL is that
  plus the runner's fixed `/responses` path, so the transcript doesn't need to repeat it. This is a deliberate
  narrowing, stated here.
- **An error body is now verbatim.** Before, it went through `decode("utf-8", "replace")`; now non-UTF-8 bytes go as
  base64, which is what the spec's "byte for byte" asks.
- **Masking a base64 record:** the runner masks the bytes *before* base64-encoding them. Its current masking works on
  the text it writes, and wouldn't see a credential inside base64. troupe masks it anyway (D3), but the runner's own
  masking is defence in depth (OpenAI design D11).
- The record function `exchange.py` is given takes `(kind, data)` rather than a dict. The runner's sink adds `kind`
  only when the capability was accepted.

### D6. The Ollama runner's records

The records' bytes and order don't change. The first request's body and each added message are `sent`, each answer
line and error body `received`. `Sink.transcript` takes the kind, and the runner's sink adds it only when the
capability was accepted. The fixtures' `transcript.jsonl` files hold what the runner sent: they gain each record's
kind, regenerated with `fixture_replay`'s writer, not by hand.

### D7. The scripted runner

Capabilities are chosen at `initialize`, before `run/start`'s options arrive, so a script can't choose them. A
command-line flag, `--transcript-kinds`, makes the runner accept the capability when offered. Tests already choose
the runner's argv. A transcript step's object form gains an optional `kind`, checked against the three kinds
(`scripted.invalid-script` otherwise, as for any malformed step) and sent as given whatever the run negotiated, so tests can break the rule on
purpose (the spec's "A deliberate violation still plays"). Recordings (`{"transcript": …}` lines) are Claude Code's
and stay native.

### D8. The SDK

`TranscriptRecord` gains `kind: Literal["sent", "received", "note"] | None`. The SDK exports the kinds and the
capability names as constants (`TRANSCRIPT_KINDS`, `CAPABILITIES`). Its `InitializeParams` and `InitializeResult`
refuse a capability not in `CAPABILITIES`, matching the schema. Runners import the constants rather than spelling the
strings.

### D9. Testing

- **Differential, for native runs:** the existing byte-for-byte tests (`test_run_host.py`, Claude Code fixtures) must
  pass unchanged on the new host. That is the check that native storage didn't move. They run before the host changes
  and after.
- **Property test for framing:** for arbitrary records (text including escapes and non-ASCII, and arbitrary bytes as
  base64), each with a kind and with or without the credential embedded, the stored line validates against
  `transcript-record.schema.json`, parses back to the same kind and encoding, and its record decodes to the masked
  bytes.
- **Violations:** the scripted runner with and without `--transcript-kinds`, sending a record without and with a kind.
- **Limit:** records under the limit whose framed lines pass it.
- **Runners:** each runner's tests, with and without the capability offered. Records are compared to what the
  fixtures say, and the same records with no kind.
- **Schemas:** the strictness test picks up the new schema. Examples for each changed schema (`Run.Ended` without
  `transcriptFormat`, `never-started` with one, a summary with one and not the other) validate or fail as the specs
  say.

## Risks / Trade-offs

- [An end recorded before this change no longer validates, since `transcriptFormat` is required] → Pre-1.0 there are
  no theatres in use (owner, 2026-11-07). The CHANGELOG's breaking note says so.
- [Lone surrogates: Ollama's runner writes a lone surrogate in a record as a JSON escape, and the host's
  `record.encode()` would raise on it] → Apply's first host task checks what happens today. Framing uses the same
  conversion, so it changes nothing about that path. If today's host fails on it, that's a separate bug, filed as an
  issue on the board and named in the PR, not fixed quietly here.
- [Framing makes a transcript bigger than its records] → Measured against the same limit (D3). API transcripts are
  mostly JSON, so escaping adds about 10–20%. `RUN_TRANSCRIPT_MAX_BYTES` is a setting.
- [Closing the capability list means a host and runner can't try out a capability without a schema change] → That's
  the strictness rule's intent: a capability is a contract term, released as one.

## Migration Plan

One pull request, released by release-please per package: protocol (`feat(runner-protocol)`), troupe, the plugin
SDK, and the OpenAI, Ollama and scripted runners. Ends recorded before it no longer validate, which is accepted pre-1.0.
Rolling back means reverting the PR.
