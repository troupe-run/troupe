# Proposal: the run host reads what the contract allows, and refuses what it doesn't

## Why

Four bugs where troupe's runner host and the runner contract disagree with each other, or a test disagrees with a
loaded machine:

- troupe-run/troupe#330: the host masks the run's credential in each raw line **before** parsing it. When a JSON
  escape sits right before the rest of the credential (`\n` before the rest of a credential starting with `n`), the
  masked line is invalid JSON (`"\[credential]"`). The run ends `crashed` with `runner.protocol`, blaming the runner
  for troupe's own masking.
- troupe-run/troupe#311: a transcript record holding a lone surrogate (`"a\ud800b"`, valid JSON) makes the host's
  `record.encode()` raise `UnicodeEncodeError`, so `run_actor` fails with an unhandled exception instead of an outcome.
- troupe-run/troupe#356: the contract doesn't say what a runner does with a second `initialize`. All six bundled
  runners (Claude Code, OpenAI, Ollama, Anthropic, mistral.rs, scripted) answer it and re-run the handshake. Since
  `transcript-kinds`, that can switch kinds on or off mid-run, and the host would blame the runner for the mix.
- troupe-run/troupe#397: a flake-hunt test's fixed 120 s limit doesn't fit four rounds on a heavily loaded machine;
  the bound measures how fast the machine starts processes, not whether the hunt works.

## What Changes

- **Parse, then mask (#330).** The host parses each runner line before masking it, then masks every string in the
  parsed message (keys included). Masking a string is escape-aware: wherever the credential appears in the string,
  or in the JSON text troupe would write for it (a `\n` before the rest of a credential that starts with `n`), the
  characters it covers become `[credential]`. A line the contract allows can no longer become a violation through
  masking, and no string troupe keeps, nor the JSON text it writes for one, holds the credential.
- Errors that quote the raw message (a duplicated key's name) are masked too.
- An oversized event is kept byte for byte when masking changed nothing in it; otherwise the stored event is the
  masked message.
- A transcript record holding a newline before the rest of a credential starting with `n` is now stored with
  `[credential]` in place of both, rather than as base64 of bytes that still decode to most of the credential.
- **Lone surrogates are a protocol violation (#311).** A string anywhere in a runner's message that holds a lone
  surrogate isn't Unicode text: the host ends the run `crashed` with `runner.protocol`, naming where in the message it
  was. A runner with bytes that aren't text sends them as a `base64` transcript record. The owner chose refusal on
  #311 (2026-11-16), and asked that no real run hit it. Testing found the Ollama runner could: an error body holding
  `\ud800` crashed its conversation thread, and five runners wrote any lone surrogate as that escape. The plugin
  SDK now writes every runner line with lone surrogates as U+FFFD, and all six bundled runners use it.
- **A second `initialize` is refused (#356).** After a successful handshake, a runner answers a further `initialize`
  with the new contract error `runner.already-initialized`, and the first handshake's answer stands. The plugin SDK
  carries the code and its refusal in one place; all six bundled runners use it; the conformance suite
  (`check_runner`) checks it.
- **The flake-hunt tests bound each round, not the whole hunt (#397).** The hunt tests wait for the hunt's own
  progress lines, each within a named per-round limit, instead of a fixed 120 s for the whole hunt, and fail naming
  what they waited for when a hunt really stops making progress.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `runner-protocol`: the handshake requirement says a second `initialize` is refused with `runner.already-initialized`;
  the error-shape scenario names it among the contract's codes; the message requirement says each string is Unicode
  text (no lone surrogate).
- `actor-runners`: protocol violations gain the lone-surrogate scenario; an oversized event is stored byte for byte
  only when masking left it unchanged; the kinds requirement's escape scenario stores `[credential]` instead of base64;
  the conformance suite checks the second `initialize`.
- `runs`: the masking requirement says the host masks after parsing, in each string and in the JSON text written for
  it, and that masking never turns a valid line into a violation.

## Impact

- `packages/troupe/src/troupe/core/masking.py`, `core/runners/host.py`, `core/runners/conformance.py`.
- `protocol/schemas/runner/errors.schema.json` (and its packaged copy): a new code, `runner.already-initialized`.
- `packages/troupe-plugin-sdk/src/troupe_plugin_sdk/runner.py`: the code and refusal; `parse_message`,
  `lone_surrogate`, `unicode_text` and `encode_line`.
- `plugins/runner-{claude-code,openai,ollama,anthropic,mistralrs,scripted}`: refuse a second `initialize`; write
  each line with the SDK's `encode_line`. Ollama: clean its error bodies.
- `scripts/tests/test_flake_hunt.py`, `scripts/tests/conftest.py`: the per-round bound.
- `contributing/runners.md`: the second `initialize`.
- No change to what the host sends. A runner's behaviour changes only for a second `initialize` and for text
  holding a lone surrogate.
