# Proposal

## Why

The runner contract's transcript is "the engine's native output, record by record and unchanged". Claude Code has one
(stream-json). A runner that drives an API has none: it conducts an HTTP exchange, and what it sends matters as much
as what comes back. So the OpenAI runner invents a framing (a JSON object per record, with its own `kind`), the Ollama
runner sends unlabelled bodies and lines, and nothing outside each runner can read either. Issue
[#294](https://github.com/troupe-run/troupe/issues/294), found building the OpenAI runner (#162, design D10 and D12
gap 4).

## What Changes

- **The contract gains a record kind.** `run/transcript` takes an optional `kind`, one of a closed list: `sent`
  (what the runner sent its engine, verbatim), `received` (what the engine sent back, verbatim) and `note` (the
  runner's own record about the exchange, such as a response's status). Absent: the record is the engine's native
  output, as today.
- **A capability turns it on for a whole run.** troupe offers `transcript-kinds` at `initialize`, the contract's
  first capability. A runner that accepts it gives every record a kind; one that doesn't gives none. A record that
  breaks this is a protocol violation, so a transcript's form is never guessed.
- **troupe stores the kind with the record.** In a run that uses kinds, each stored transcript line is a JSON object
  `{"kind", "record"}` (with `"encoding": "base64"` for bytes that aren't text), defined by a new protocol schema.
  troupe frames it, after masking, so no runner invents a framing. A run without kinds is stored exactly as today,
  so Claude Code's transcript stays its stream-json, byte for byte.
- **A run's end says which form its transcript is.** `Run.Ended`'s outcome and the client's run summary carry
  `transcriptFormat` (`native` or `kinds`) exactly when they carry `transcript`, required with it: pre-1.0 there are no older
  ends to read back.
- **The OpenAI and Ollama runners use it.** OpenAI: each request body is `sent`, each stream line and error body
  `received`, and a response's status and kept headers, or an abandoned stream, a `note`. Records are now the bytes
  themselves rather than JSON wrapping them, and the request URL leaves the transcript, since the run's start records
  the runtime's endpoint. Ollama: the first request's body and each message it adds are `sent`, each answer line and
  error body `received`. Offered no capability (an older troupe), both send the same records without a kind.
- **The scripted runner can exercise it.** A `--transcript-kinds` flag makes it accept the capability, and a
  transcript step can carry a `kind`, so troupe's tests can drive a run that uses kinds, and one that breaks the rule.
- **The SDK's `TranscriptRecord` gains `kind`,** and its `initialize` types name the one capability.
- This is a runner contract change in its own pull request, released as a protocol change. It's additive for
  runners: one that never accepts the capability is unaffected. **BREAKING** for anyone reading the OpenAI runner's
  stored transcripts, whose records change shape, and **BREAKING** for run ends recorded before it, which no longer
  validate without `transcriptFormat` (pre-1.0: there are no theatres in use, and nothing outside this repository
  reads them).

## Capabilities

### New Capabilities

None. The stored transcript's form belongs to `actor-runners`, which already owns how the host stores the transcript.

### Modified Capabilities

- `runner-protocol`: `run/transcript` gains an optional `kind`; `initialize` defines the `transcript-kinds`
  capability and when a record must or mustn't carry a kind.
- `actor-runners`: the host stores a run's records in the framed form when the run uses kinds, enforces the
  capability's rule, and counts the stored bytes against the transcript limit.
- `runs`: a run's end records `transcriptFormat` exactly when it records `transcript`.
- `client-protocol`: a run summary carries `transcriptFormat` with `transcript`.
- `openai-runner`: the transcript requirement says which kind each record of the exchange is, and records the bytes
  rather than wrapping them.
- `ollama-runner`: the transcript requirement says which kind each record is.
- `scripted-runner`: a flag to accept the capability, and a `kind` on transcript steps.

## Impact

- **Protocol:** `protocol/schemas/runner/run-transcript.schema.json` (`kind`), `initialize.schema.json` (the
  capability, now a closed list), a new `protocol/schemas/transcript-record.schema.json` (one stored line of a framed
  transcript), `events/run-ended.schema.json` and `client/run.schema.json` (`transcriptFormat`),
  `protocol/README.md`'s table.
- **Core:** `packages/troupe/src/troupe/core/runners/host.py` (offer, enforce, frame), `outcome.py`,
  `runs/projections.py`, `client/messages.py`, `cli/render.py`.
- **SDK:** `packages/troupe-plugin-sdk/src/troupe_plugin_sdk/runner.py`.
- **Runners:** `plugins/runner-openai` (exchange, runner sink, tests, fixtures' expected transcripts),
  `plugins/runner-ollama` (conversation, runner sink, tests, fixture replay), `plugins/runner-scripted` (flag, script
  step, options schema). `plugins/runner-claude-code` is unchanged.
- **Docs:** `contributing/runners.md` ("The transcript"), the generated event reference.
- **Not affected:** no spec is added or removed and no Purpose changes, so infrastructure's
  `oob/troupe-spec-purposes.json` needs no update.
