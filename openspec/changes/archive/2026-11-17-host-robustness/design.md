# Design

## Context

See proposal.md for why. The relevant code today:

- `host.py`, `_Run.read`: `line = self.mask.bytes(line)` on the raw line, then `p.parse_line(line)`. Everything after
  (events, transcript records, responses, `on_message`, the oversized event's stored line) comes from the masked
  line, so masking a raw line is what keeps the credential out of everything the host passes on. It's also what
  breaks a valid line when a JSON escape ends just before the rest of the credential (#330).
- `masking.Masker` replaces every form of the credential (its UTF-8 text and its JSON-escaped forms, with and without
  non-ASCII escaped, with and without `\/`) in bytes, text or a JSON value's strings (`Masker.data`).
- `transcript_record` encodes a text record with `record.record.encode()`, which raises on a lone surrogate (#311).
  For kinds, #315 (transcript-record-kinds D3) frames the masked record, and when masking the framed line would change
  it (an escape completing the credential), stores the record as base64 of its masked bytes.
- A credential is refused unless every character is visible ASCII, `!` to `~`
  (`troupe_plugin_sdk.credential.well_formed`).
- Each of the six bundled runners dispatches requests itself (`_handle`, `_initialize`), with its own
  `_initialized` flag set only by a successful handshake. The SDK holds the contract's types, not a dispatch loop.
- `conformance.check_runner` runs named checks (`handshake`, `second_start`, ...) against a runner command.
- `scripts/tests/test_flake_hunt.py` runs each hunt through `conftest.run_within(command, HUNT_RUN_WITHIN)`, one
  fixed 120 s for the whole hunt.

## Goals / Non-Goals

**Goals:**

- A line the contract allows always parses, whatever the credential (#330).
- No string the host keeps holds the credential, and neither does the JSON text troupe writes for any one string,
  in either of the forms Python's `json` writes (non-ASCII kept, or escaped).
- A runner message troupe can't keep as text ends the run with an outcome, never an unhandled exception (#311).
- The second `initialize` has one defined answer, the same in the contract, the SDK, every bundled runner and the
  conformance suite (#356).
- The flake-hunt tests time each round, not the machine's whole run of rounds (#397).

**Non-Goals:**

- Masking a credential that only appears **across** separate JSON values: a string ending in `ab` followed by the
  next string starting `cd`, for a credential `ab","cd`; or digits of a number. No value the runner sent holds it,
  and with a credential of visible ASCII it takes a credential made of JSON's own syntax (`"`, `,`, `:`) or of a
  number's characters only. The old raw-line masking turned these into a crash; this design leaves them as text.
- A native (non-kinds) transcript record that is itself JSON text, such as Claude Code's stream-json line, holding
  `\n` before the rest of a credential starting with `n`, in its own text. The record is a string of the runner's
  format, which the host doesn't interpret (runner-protocol, "The native transcript is a separate stream"), so its
  backslash and `n` are two characters, and masking replaces `n` and the rest: the stored line reads `\[credential]`,
  which isn't valid JSON in the runner's format. That's what happens today, too, and it keeps the credential out.
  Making it valid would need the host to know the record is JSON.
- Deliberate disguise: a runner that sends the credential reversed or encoded isn't something masking can catch. It
  protects against an echo and against troupe's own escaping, as runtimes design D6 says.

## Decisions

### D1. Parse the raw line, then mask the parsed message

`read` parses the raw line as strict JSON first. A line that isn't valid JSON is a violation as now; its error
message (which can quote a duplicated key) is masked with `Masker.text` before it goes into the violation. Then
the host checks the message's strings for lone surrogates (D3), masks every string in it (D2), and only then checks
its JSON-RPC shape and handles it. Every later step works on the masked message, as it worked on the masked line.

- **Why masking can't break a valid line:** masking happens on Python strings after `json.loads`, so it can't make
  the parse fail: the parse is already done. The one exception is deliberate: an object two of whose keys mask to
  the same text is a violation rather than a message kept with a value lost (below). The property test (D6) checks
  both.
- **What `on_message` and the oversized event get:** the masked message. The oversized event's stored artifact is the
  raw line, byte for byte, when masking changed nothing in the parsed message and `Masker.bytes` changes nothing in
  the raw line; otherwise it's the masked message, written compactly. The second check catches a form that's in the
  raw line's escapes only, such as `\/` (the actor-runners spec's oversized scenario).
- **What the host can't read or mask without loss is a violation** (review of #437): a message nested past Python's
  recursion limit (the walks after `json.loads` would otherwise raise out of `run_actor`), and an object two of
  whose keys mask to the same text, which would keep one value and drop the other. A flake hunt of the property test
  found the second, with a credential of `0`: the key `é` is written `\u00e9` in ASCII JSON. With a real credential
  it takes two keys that each hold it, which the contract already forbids.
- **The SDK:** `parse_line(line)` becomes `loads_strict` plus `parse_message(data)`, the shape check on a parsed value,
  so the host can mask between them. `parse_line` stays for other callers.
- *Alternative:* make the wire masking escape-aware (the OpenAI runner's own `Mask` never takes in a backslash).
  Rejected: it has to be right about every escape and every form at the byte level, in a line it hasn't parsed. It
  would also still keep the `\n` + rest-of-credential text as it is, since that isn't the credential on the wire.

### D2. Escape-aware masking of a string

`Masker.text` today replaces each form in a string's text. It doesn't see a form that only appears when the string is
written as JSON: a newline before `secret…`, written `\nsecret…`, holds the credential `nsecret…`. The masked string
must not hold one in any text troupe writes for it.

`Masker.data` masks each string (keys included) like this:

1. Split the string into its characters, each with its text in each written form: as it is (UTF-8), as JSON with
   non-ASCII kept, and as JSON with non-ASCII escaped (`\uXXXX`, a surrogate pair for a character outside the BMP).
2. In each form's text, find every occurrence of every form of the credential. Each occurrence covers a run of
   characters (whole characters: an occurrence that starts or ends inside a character's escape covers that
   character).
3. Replace each maximal run of covered characters with `[credential]`.
4. Repeat on the result, treating each `[credential]` as one unit, until no occurrence covers a character the runner
   sent. An occurrence that lies wholly inside `[credential]` units is troupe's own marker, and is ignored.

It ends: each pass that changes anything replaces at least one character the runner sent, and there are finitely
many. When it ends, no written form of the string holds a form of the credential except inside the marker.

- The newline in #330's example is replaced with the rest of the credential: `"\nsecret-token-0123456789"` is kept
  as `"[credential]"`. Replacing only the credential's 23 characters after the newline wouldn't do: the newline's
  escape would still end with `n`, followed by `[`, and the 23 characters are most of the credential.
- The same masking applies to a text transcript record (kinds or native) and to an event's strings, so the framed
  transcript line and the event store's JSON hold no form of the credential either.
- **#315's base64 fallback stays** as a last check on the framed line: if `Masker.bytes(framed)` still changes it, the
  record is stored as base64 of its masked bytes, as now. After D2 it can only fire for a credential made of JSON
  syntax across the `kind` and `record` values; it keeps the guarantee for those, too. The actor-runners scenario for
  the escape case now says `[credential]`, since D2 removes the form before framing.
- *Alternative:* mask only the credential's own characters and escape the character before it differently (`\n` as
  `\u000a`). Rejected: the new escape can itself end in a form's first character (a credential starting with `a`),
  and the event store's serializer and every other writer would have to use the same trick.

### D3. A lone surrogate is a protocol violation (#311)

After parsing and before masking, the host walks the message. A string (key or value) holding a code point from
U+D800 to U+DFFF is a violation: "a string at `params.record` holds a lone surrogate (U+D800), which isn't text: send
bytes that aren't text as a base64 transcript record". The path is built from masked keys. The run ends `crashed`
with `runner.protocol`, like any violation.

- Covers events as well as records: a `log` event holding one would fail the event store's UTF-8 encode the same way.
- The runner contract's message requirement says strings are Unicode text (runner-protocol, "A message's strings are
  Unicode text"). When this was proposed, the bundled runners were thought not to send one. Testing showed they
  could (next bullets), so every runner now replaces each one with U+FFFD and records it (D3b).
- **The owner chose this on #311 (2026-11-16)**, over storing it a defined way (keeping the `\ud800` escape in a
  framed line, U+FFFD in a native one), which would have troupe choose a lossy conversion for the runner.
- **No real Ollama run may hit it** (owner, 2026-11-16). #311 says the Ollama runner writes a lone surrogate as a
  JSON escape when Ollama's output holds one; the proposal said it doesn't. Testing it found #311 right, and a worse
  bug beside it. Ollama's chat lines were cleaned (`_clean`, lone surrogates to `?`), but an error body wasn't: its
  message reached the SDK's `cut`, which raised `UnicodeEncodeError` on the conversation thread, so the run never
  got a result. And every runner but Claude Code and scripted wrote its lines with `backslashreplace`, which turns a
  lone surrogate in any string into exactly the `\ud800` escape the host now refuses; Claude Code and scripted
  raised on one instead.
- **So the SDK makes runner text Unicode text, in one place:** `unicode_text(value)` replaces each lone surrogate in
  a JSON value's strings, keys included, with U+FFFD, and `encode_line(message)` writes a message as one compact
  UTF-8 line through it. All six runners write every line with `encode_line`; Ollama's `_clean` and its error-body
  reader use `unicode_text` (U+FFFD, Unicode's replacement character, where `_clean` wrote `?`); and its
  standard-error diagnostics are written with `backslashreplace`, since that's not the contract. No bundled runner can
  then send a lone surrogate, so the refusal never fails a real run. Each runner's tests write a message holding one
  and read back U+FFFD; the Ollama runner is driven end to end with an error body and an answer holding `\ud800`.

### D3b. A runner records each replacement in a context event (owner, 2026-11-16)

The owner kept U+FFFD for an engine's lone surrogate, but never silently: the runner records that the engine sent
text that isn't Unicode, where, and how many characters were replaced.

- **A `context` event, kind `other`, by `runner`.** Its message names where and how many: "The engine's text wasn't
  Unicode: 2 lone surrogates in the turn event's text were replaced with U+FFFD." *Why not a notice:* notices are
  the host's (#327 keeps the ones the host raises); a runner has no way to raise one, and the host can't see a
  replacement made before the line was written. *Why a context event over a `log` warning:* the contract defines
  `context` as content lost while the run carries on, with `kind` `other` for a loss the list doesn't name and a
  message that names it. A replaced character is such a loss. It's numbered and kept with the run's events, so it's
  in the run's history; a `log` line is free text with no defined meaning.
- **Where it goes:** just before the event the replacement is in, so the event that holds U+FFFD follows the
  event that explains it. A replacement made before `init` (or in `init` itself) waits and goes just after `init`,
  since a `context` event before `init` is a violation. One before the `result` goes before it.
- **How, in one place:** `EventNumbering.numbered(body)` (SDK) numbers an event body the way each site did inline
  (`{"runId": …, "seq": take(), **body}`), after making its strings Unicode text. When it replaced any, or a
  replacement made elsewhere is waiting (`lost(where, count)`), it first sends each waiting `context` event through
  the sender the runner gave it, each taking the next `seq`, so `seq` stays gapless and the event follows them. Every
  site that numbered an event inline calls it instead. Claude Code and scripted kept their own counters; they use
  `EventNumbering` now, so all six share it.
- **Replacements made where the engine's text is read:** each runner reads its engine's JSON in one place, and
  replaces lone surrogates there, since tools, summaries and the next request need text. It counts them and calls
  `lost(where, n)`, so the context event names the engine's output, before the events built from it: "Ollama's
  answer" (each chat line), "the Responses API's answer" (OpenAI's stream parser), "the Messages API's answer"
  (Anthropic's events as the library exposes them), "Claude Code's output" (each stream-json line, through the
  mapper's `take_replaced`). OpenAI and Anthropic pass `on_lost` into `exchange`, as they pass `record`. A tool
  call's input and output are made text before `Tools.run` numbers either event, so its context event comes before
  both. Ollama's error body is no longer cleaned where it's read: its message reaches an event (`retry`, `result`)
  through `numbered`, which records it there. OpenAI's and Anthropic's error bodies are read as text the same way
  before they're classified, reported as "the Responses API's error" or "the Messages API's error", so the run ends
  for the service's own reason (review of #437). mistral.rs's engine gives Rust strings, which can't hold one, so
  `numbered` is its only check.
- **The transcript keeps what the engine sent:** a record is written before the text is cleaned, a lone surrogate
  as its JSON escape (Anthropic's `_json(..., as_sent=True)`, like Ollama's `encode`), never U+FFFD.
- **`send_context` is required** (owner, 2026-11-17, on review of #437): a keyword argument of `EventNumbering` with no
  default, so a runner can't build a counter that would have to drop or crash on a replacement; leaving it out fails
  where the counter is built. No compatibility shim, pre-1.0. The plugin-sdk spec says so.
- **One event per place:** `lost` adds a report to one already waiting for the same place, so a streamed answer
  whose deltas each hold one gives one `context` event, not one per delta (review of #437).
- **Ordering inside a site:** `numbered` comes before `fit`, because the SDK's `fit` encodes strictly and raises on a
  lone surrogate. That was the Ollama error-body crash, and the same path existed in OpenAI and Anthropic, whose
  streamed text reaches `fit` uncleaned.
- **The last resort:** `encode_line` returns the line and how many it replaced. A message no event carries (an
  error answer to `run/start`, before the run has events) has none counted by `numbered`; when its writer replaced
  any, the runner writes a line to standard error naming the message and the count. The host keeps standard error
  with the run.
- **Tests, per runner:** engine output holding `\ud800` (Ollama's answer and error body, an OpenAI and an Anthropic
  streamed text, a mistral.rs stand-in answer, a Claude Code stream-json line, a scripted step) gives a run whose
  events have gapless `seq`, a `context` event of kind `other` by `runner` naming where and the count just before
  the event with U+FFFD, and no lone surrogate in any line.

### D4. A second initialize is refused (#356)

- **The contract:** `runner.already-initialized` in `protocol/schemas/runner/errors.schema.json` (and the packaged
  copy), `details: false`, JSON-RPC code as for `runner.already-started`. Only a handshake the runner answered
  successfully counts: after a refusal for an unsupported version, the host may try again.
- **The SDK:** `troupe_plugin_sdk.runner` gains the code and its refusal (`ALREADY_INITIALIZED`, and a function giving
  the problem and fix for a runner's name), so the six runners say the same thing from one place.
- **The runners:** each `_handle` checks its `_initialized` flag before `_initialize`, and refuses with the SDK's code
  and words. The first answer's version and capabilities (`transcript-kinds`) stay as they were.
- **Conformance:** `check_runner` gains a `second_initialize` check: `initialize`, a second `initialize` offering no
  capabilities, expect `runner.already-initialized`; then `run/start` still starts the run. `test_runner_conformance`
  runs it against the scripted runner, and each runner's own tests check the refusal and that kinds stay on.
- `protocol_guard` needs the new code raised by a test (it fails a full run otherwise): the runners' tests raise it.

### D5. The flake-hunt tests bound each round (#397)

`conftest.run_within` takes one limit for the whole command. A new `conftest.run_with_progress(command, each_within)`
reads the command's standard output line by line (on a thread, so it works on Windows) and fails when no new line
arrives within `each_within` seconds: it stops the tree and fails naming what it was waiting for ("the hunt's next
line after `w0r1 failed in 34.3s…`") and the output so far. The hunt prints a line at its start, after each round and
at its end, so the gap between lines is at most one round, however many rounds the test asks for.

Once its output ends, the command must also exit, and its standard error close, within the same bound, or the
tree is stopped and the test fails (review of #437).

`HUNT_RUN_WITHIN` becomes `HUNT_ROUND_WITHIN = 120.0`: "seconds for one round of a small hunt (a fresh pytest on a
few trivial tests) to end on a slow machine". The issue's loaded round took 69.9 s. `run_hunt` uses it.
`run_within` stays for the tests that time one command.

*Alternative:* scale the limit by the rounds requested. Rejected: the test would have to parse its own arguments,
and a hunt's first round is slower (cold imports) than the rest, so a per-round share of a total is still a guess.

### D6. How each fix is tested first

Each test is written and run against today's code first, and must fail there:

- **#330:** the issue's repro through the run host (a stand-in runner writes the line after `init`), in a run whose
  credential is `nsecret-token-0123456789`: today `crashed`/`runner.protocol`; after, the run ends as its result
  says, and no stored byte (events, transcript, standard error, oversized artifacts) holds any form of the credential.
  **Property tests:** for arbitrary credentials of visible ASCII and arbitrary messages whose strings are built from
  fragments of the credential, escapes, a newline, `/`, non-ASCII and plain text: the raw line parses through the
  host's read path exactly when `json.loads` parses it (every valid line still parses), and every string the host
  keeps, and both JSON texts written for it, hold no form of the credential outside the marker.
- **#311:** the issue's repro: today `UnicodeEncodeError` out of `run_actor`; after, `crashed`/`runner.protocol`
  naming `params.record`. And a `log` event holding one.
- **#356:** each runner's test: `initialize` with `transcript-kinds`, `run/start`, a second `initialize` offering
  none: today it's answered; after, refused with `runner.already-initialized`, and later records keep their kind.
  The conformance check against a stand-in that answers the second `initialize` fails, naming it.
- **#397:** a test of `run_with_progress`: a command that prints a line every 0.3 s for 2 s passes a 1 s per-line
  bound, where `run_within` with 1 s fails; a command that prints one line and then sleeps fails within the bound,
  naming the last line it saw.

## Risks / Trade-offs

- [Escape-aware masking costs Python objects per character, on the event loop] → Only a string that holds a form
  pays it, and only near the form: `Masker.text` checks windows of `WINDOW_CHARS` characters at C speed and masks a
  character at a time only in windows that can hold one, with a margin of the longest form (review of #437). Measured
  on macOS: a 1 MB string holding the credential once, 5.0 s before the windows and 0.055 s after; 16 MB, 0.73 s. A
  string echoing it in every window still pays in full: 1 MB holding it 40,000 times took 1.8 s.

- [Escape-aware masking replaces a character the runner sent that isn't part of the credential (the newline)] →
  Only when its escape would complete the credential. Over-masking one character is safer than keeping a form, and
  the marker says something was there.
- [The oversized event's stored artifact is no longer byte for byte when masking changed it] → It never was: today
  it's the masked raw line. The spec now says which one is kept.
- [Parsing before masking means the unmasked message exists in memory for longer] → It did before, as the raw line.
  Nothing unmasked is passed on, stored or put in an error: the violation messages raised before masking are masked.
- [Owner chooses B on #311] → D3 only, as above.
- [A new error code is a protocol change] → The contract is version 0, the draft. A host that never sends a second
  `initialize` (troupe) sees no difference.
