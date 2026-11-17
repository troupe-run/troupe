# Proposal

## Why

Masking a run's credential can leave a stored transcript record that was valid JSON text no longer valid JSON
(troupe-run/troupe#438). When the credential starts with a letter that ends a JSON escape (`n`, `t`, `r`, `b`, `f`,
`u`, `"`, `\` or `/`) and the record's own JSON text holds a backslash right before the rest of it, masking replaces
the letter and the rest and leaves the backslash: `{"text":"key:\nsecret-…"}` is stored as `{"text":"key:\[credential]"}`
(`Invalid \escape`). The credential never leaks, but a reader that parses the stored record fails on it. It hits
Claude Code's native stream-json lines, the text of kinds records (an engine's request and answer bodies), and the
`data:` lines of a streamed answer (the OpenAI runner records each one). host-robustness (#437) fixed the same shape
for the runner's *messages* by parsing before masking (its design D1 and D2), and filed this as the one non-goal it
left.

## What Changes

- A transcript record whose text is JSON is masked **as JSON**: each string in it (keys included) is decoded, masked
  with the escape-aware masking of host-robustness D2, and written back in place. Only the string tokens masking
  changes are rewritten; the rest of the record (spacing, key order, numbers, escapes) stays byte for byte.
- The same holds per line for a record of several lines, and for a line that is a server-sent-events field holding
  JSON (`data: {…}`): the JSON after the field name is masked as JSON, the field name kept.
- A record sent as base64 whose bytes are UTF-8 text is masked the same way; other bytes are masked as bytes, as now.
- A number in a record's JSON whose digits hold the credential becomes the string `"[credential]"`.
- What can't be masked string by string, because the credential spans JSON's own syntax (only a credential holding
  `"`, `,`, `:` or a bracket can), replaces the smallest value that holds it, often an array or object, with
  `"[credential]"`, the rest of the record kept; a span past every value replaces that line's value, a `data:` line
  keeping its field name (owner's decision, 2026-11-17, option B; design D3).
- A property test over generated credentials (every printable ASCII, escape letters included) and generated JSON
  records shows both guarantees for every record shape, through the run host: the stored record is still valid in
  its own format, and no form of the credential is in it or in any string it decodes to. It fails on today's code.
- Specs: the runs masking requirement says a record stays valid in its own format; actor-runners' kinds and native
  scenarios gain the escape case for a record that is JSON; runner-protocol's "the host doesn't interpret records"
  names masking's reading of JSON as the one exception.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `runs`: "troupe masks the credential in everything it keeps from a run" gains that a transcript record masks to a
  record still valid in its own format (JSON text, a JSON line, a `data:` line), with no form of the credential in it
  or in its decoded strings.
- `actor-runners`: the kinds and the native-transcript requirements gain scenarios for a record that is JSON holding
  an escape before the rest of the credential.
- `runner-protocol`: "The native transcript is a separate stream" says masking reads a JSON record's strings, and
  changes nothing else in it.

## Impact

- `packages/troupe/src/troupe/core/masking.py`: a record-masking entry point (`Masker.record` for text,
  `Masker.record_bytes` for base64 bytes) beside `text`, `bytes` and `data`.
- `packages/troupe/src/troupe/core/runners/host.py`: `parse_runner_line` masks a `run/transcript` message's text
  record with `Masker.record` before the rest of the message is masked; `transcript_record` masks base64 bytes with
  `Masker.record_bytes`. #315's base64 fallback for the framed line stays.
- Tests: `test_masking.py`, `test_run_host.py`, `masking_checks.py` (a JSON-record check), a property test.
- No protocol, schema or runner change: records are still strings or base64, and runners send what they send.
- Builds on host-robustness (PR #437); this change's PR opens after #437 merges, rebased onto main.
