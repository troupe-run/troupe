# Design

## Context

See proposal.md for why. The relevant code, on host-robustness (#437):

- `host.parse_runner_line` parses a runner's line strictly, then masks every string in the message with
  `Masker.data`, which masks each string with `Masker.text` (host-robustness D2: escape-aware, so no writing of the
  string, raw or as JSON with non-ASCII kept or escaped, holds a form of the credential outside `[credential]`). A
  `run/transcript` record is one of those strings, so it's masked as text: its own backslashes are just characters,
  and `\n` + `secret…` loses `n` and the rest to `[credential]`, leaving `\[credential]`.
- `_Run.transcript_record` stores a text record's (already masked) text, or masks a base64 record's bytes with
  `Masker.bytes`. With kinds it frames the record (`framed_record`), and stores it as base64 if the framed line still
  holds a form (#315's fallback).
- What the bundled runners send as records: Claude Code, each stream-json line; OpenAI, each line of a streamed answer
  (`data: {…}`, `event: …`, blank lines) and whole request and error bodies; Anthropic, request bodies and each event as
  JSON; Ollama and mistral.rs, request bodies, each NDJSON line, error bodies. Some are UTF-8 sent as base64 when the
  runner couldn't send them as text.
- A credential is visible ASCII (`!` to `~`) and at least 8 bytes (`CREDENTIAL_MIN_BYTES`). It holds no whitespace,
  so no form of it holds a raw line break.

## Goals / Non-Goals

**Goals:**

- A record whose text is JSON, a JSON line, or a `data:` line holding JSON is still that after masking, and none of
  its text, the JSON writings of its text, or the strings it decodes to holds a form of the credential outside
  `[credential]`.
- Only what held the credential changes: every byte of the record outside a rewritten value stays as sent.
- A record that is none of these is masked as now (D2).

**Non-Goals:**

- JSON nested inside a string of the record (a tool result whose text is itself JSON). Its string is masked as a
  string, so its own escapes can still end up as `\[credential]` one level down. The record's own format is kept
  valid; reading a string as more JSON would have the host interpret what runners send, without end.
- Pretty-printed JSON split over several records, or a server-sent event whose `data:` spans several lines: each
  record and line is masked on its own.
- A credential one of whose forms holds a quote next to a bracket (`"[` or `]"`), so troupe's own replacement,
  `"[credential]"`, could complete it with the text round it: no replacement is sure to be valid JSON then. Masking
  still keeps such a credential out (the last step masks as text), but the record may not stay JSON. The property
  test leaves these credentials out by name (`_usable`).
- Deliberate disguise beyond JSON's own escapes, as host-robustness says.

## Decisions

### D1. A record's shape decides how it's masked

`Masker.record(text)` classifies the record:

1. **JSON text**: the whole record, after optional whitespace, is a JSON object or array (`json.loads` succeeds,
   NaN and Infinity refused as not JSON; duplicate keys allowed, since they're valid JSON text and kept as sent).
2. **Lines**: otherwise, the record is split at `\n` and each line is classified on its own: a **JSON line** (a JSON
   object or array, with optional whitespace and `\r`), a **data line** (`data:`, an optional space, then a JSON
   object or array), or a **text line**.
3. **Text**: when no line is JSON or data, the record is masked with `Masker.text`, as now.

Only objects and arrays count as JSON. A bare scalar such as `12345678` or `true` reads as plain text far more often
than as JSON, and masking it as JSON would put quotes round it.

- **Cost:** a record is parsed only when it could need it: some writing of it holds a form, or it holds a `\u`
  escape of a visible ASCII character (`\u0020` to `\u007f`), which can spell a credential's character where no
  writing shows it. JSON writers escape only control characters and, when asked, non-ASCII ones, so a gate on any
  `\u` would parse most Claude Code lines (ANSI escapes are `\u001b`) for nothing. Every other record is returned
  as it is. Timed on a 1.1 MB stream-json line: 5.2 ms before and 5.6 ms after without the credential, with or
  without `\u` escapes.
- *Alternative (the issue's second option):* widen the text mask to take in the backslash before the credential.
  Rejected: right for `\n`, but not for `\\` (an escaped backslash before the credential is two characters, and
  taking one leaves an odd count), `A`, or a credential holding `"`; and it still can't tell a backslash in a
  JSON string from one in plain text.

### D2. In JSON, the strings and numbers are masked, in place

Within a JSON record or line's value, each string token (key or value) and number token is found by scanning the
validated text. A string token is rewritten when its decoded string masks differently (`Masker.text`, D2 of
host-robustness) or its raw text holds a form (the credential written with `\/` or `\u` escapes); the new token is
`json.dumps` of the masked string, with non-ASCII kept unless the string holds a lone surrogate (which JSON text can
escape, and the stored record must still encode as UTF-8). A number token whose text holds a form becomes
`"[credential]"`. Everything else, whitespace, punctuation, literals, key order, other tokens' escapes, is kept byte
for byte.

- The #438 record `{"text":"key:\nsecret-token-0123456789"}` decodes to `key:` + newline + `secret…`; D2 masks the
  newline and the rest, and the record is stored `{"text":"key:[credential]"}`.
- *Alternative:* parse, mask with `Masker.data`, and write the whole value with `json.dumps`. Rejected: it rewrites
  every number, escape and space in a record that held the credential once, which config.yaml's "never rewrite
  anything not asked to change" rules out, and loses duplicate keys and float digits.

### D3. A credential that spans values: replace the smallest value that holds it (owner, 2026-11-17)

After D2 no single string or number holds a form. One can still remain across tokens, only with a credential holding
JSON syntax: `ab","cd` in `["xab","cdy"]`, or a credential ending in `"` that a string's closing quote completes.
The owner chose (B) on 2026-11-17: replace the smallest value that holds it.

`Masker.record` checks the whole masked record the way D2 of host-robustness checks a string: it finds each form, in
each writing of the record, that covers a character outside a `[credential]`. For each maximal run of covered
characters:

1. If the run lies inside one JSON record or line's value, the smallest value (string, number, literal, array or
   object) whose text holds the whole run is replaced with `"[credential]"`.
2. Otherwise (it reaches the record's or line's edge, a data line's `data:` prefix, or across lines), each JSON or
   data line it touches has its whole value replaced with `"[credential]"`, the `data: ` prefix kept, and each text
   line it touches has its covered characters replaced, as D2 does.

Each round replaces every covered run it finds, choosing the smallest value for each in one sweep over the
record's values and dropping a value inside another being replaced. Then check again, until nothing is covered. Each round replaces at least one character the runner sent, so it ends.
If a round would change nothing (only troupe's own text, a line break or a data prefix is left covered), the whole
record becomes `"[credential]"` (a data line, `data: "[credential]"`).

- **How a replacement shows in the stored record:** the value that held the credential reads as the JSON string
  `"[credential]"` where an array, object, number or string was. A reader sees `[credential]` exactly where the value
  was, as with every other mask, and a type that changed tells it that a whole value went, not just a string. Nothing
  else in the record changes. troupe doesn't add a notice: masking is silent everywhere else, and the marker in the
  record is the record of it.
- *Alternatives the owner weighed:* (A) replace the whole line's value, simpler and losing more; (C) mask as text,
  leaving invalid JSON.

### D4. Where the host calls it

- **Text records:** `parse_runner_line` masks a `run/transcript` message (when `params.record` is a string and
  `encoding` isn't `base64`) with the record left empty, then puts the record back masked with `Masker.record`, at
  the key's place among `params`. The record is masked once: masking it again as a string would mask inside its own
  `[credential]` when the credential is part of that text (the message property test found it with a credential of
  `i`), and would cost a second pass over a large record. The line kept for the message (`on_message`, the
  oversized-event path) is written from the masked message as now.
- **Base64 records:** `transcript_record` masks the decoded bytes with `Masker.record_bytes`: when they're UTF-8 and
  `Masker.record` would treat them as JSON (D1, cases 1 and 2), the masked text's UTF-8; otherwise `Masker.bytes`, as
  now (plain bytes aren't text, and widening the mask to JSON writings would eat bytes round them for nothing).
- #315's base64 fallback for the framed line stays as the last check.
- One place: the record's shape rules and replacement live in `masking.py`; the host only says "this is a record".

### D5. Tests

- A Hypothesis property test, through `parse_runner_line` and the stored-line path, over credentials of 8 to 24
  printable ASCII characters (escape letters and JSON syntax included, weighted toward them) and records built from
  generated JSON values with the credential put into strings after generated escapes, across strings, into numbers,
  and as `data:` lines and multi-line records. It checks that the stored record is valid in its own shape (each JSON
  line parses), that no form of the credential is in its text, its writings, or any string it decodes to outside
  `[credential]`, and, for (B), that every value outside the replaced one is unchanged. It fails on today's code.
- Named examples for each spec scenario, in `test_masking.py` and `test_run_host.py`.

## Risks / Trade-offs

- [Parsing records costs time on big Claude Code lines] → only records whose writings hold a form or that hold `\u`
  are parsed; the scan is a C regex, and only changed tokens are re-encoded. Check timing on a large line in the
  tests.
- [A record with many spans across values costs a pass each] → each pass replaces every run it finds (review of
  #439): 2000 spans took 61 s replaced one a pass, and take 79 ms now; 20 000 spans (0.34 MB) take 1.2 s. A test
  counts the passes.
- [A replaced value loses data next to the credential] → only for a credential made of JSON's syntax, which a real
  key never is; D3 keeps the loss to the smallest value.
- [A record that's JSON by accident (a plain text line that happens to be `[1, 2]`)] → masking it as JSON keeps it
  as it was except where it held the credential, so nothing worse than text masking.

## Migration Plan

None: stored transcripts aren't rewritten. Records stored before this change keep what they hold. Pre-1.0, no
compatibility forms.
