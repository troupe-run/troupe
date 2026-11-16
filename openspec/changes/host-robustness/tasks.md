# Tasks

Each "failing first" test is run against the code as it was before the fix, and its failure is recorded in the
commit message or PR, before the fix is written.

## 1. Parse, then mask (#330)

- [ ] 1.1 Failing first: the issue's repro through the run host (credential `nsecret-token-0123456789`, a stand-in
  runner sends `"\nsecret-token-0123456789"` as a record after `init`) ends as its result says, not
  `crashed`/`runner.protocol`. Verify: it fails on today's code with "Invalid \escape".
- [ ] 1.2 Failing first: `Masker` property tests: for credentials of visible ASCII and strings built from credential
  fragments, escapes, `/`, newlines and non-ASCII, `Masker.data` leaves no form of the credential in the string or in
  either JSON text written for it (outside the marker), and changes nothing in a string with no form. Verify: fails
  on today's `Masker.data` (the `\n` + rest case).
- [ ] 1.3 Escape-aware string masking in `masking.py` (design D2), with its termination rule. Verify: 1.2 passes.
- [ ] 1.4 SDK: split `parse_line` into `loads_strict` + `parse_message(data)`; `parse_line` unchanged for callers.
  Verify: the SDK's runner-type tests pass.
- [ ] 1.5 Host: parse the raw line, mask the parsed message, then shape-check and handle it; mask the text of
  violations raised before masking (a duplicated key); `on_message` gets the masked message; the oversized event
  stores the raw line only when masking changed nothing, else the masked message (design D1). Verify: 1.1 passes; a
  test that a duplicated key holding the credential is named with `[credential]`; the oversized tests, including one
  with the credential.
- [ ] 1.6 Property test through the host's read path: for arbitrary credentials and messages, a line parses exactly
  when `json.loads` parses it (every valid line still parses), and no string passed on or stored, nor its JSON texts,
  holds a form of the credential. Verify: it passes, and fails when 1.5's order is reverted (mask the raw line first).
- [ ] 1.7 The kinds escape test (#315's base64 case) now expects `[credential]` in a text record; the base64
  fallback stays as a last check. Verify: `test_run_host.py` passes.

## 2. Lone surrogates are a violation (#311)

- [ ] 2.1 Failing first: the issue's repro (a record `"a\ud800b"` after `init`) ends `crashed`/`runner.protocol`
  naming `params.record`, and a `log` event holding one does too. Verify: both fail on today's code (an unhandled
  `UnicodeEncodeError`, or whatever the event path does, recorded).
- [ ] 2.2 Host: refuse a lone surrogate in any string, key or value, before masking, with its path (design D3).
  Remove the `assume` that excludes surrogates from the existing property test. Verify: 2.1 passes.
- [ ] 2.3 The Ollama runner, driven with Ollama output holding `\ud800` escapes (in content, a tool call's arguments
  and an error body), writes no message holding a lone surrogate once parsed; and the same check for every other
  bundled runner whose engine output is JSON (OpenAI, Anthropic, mistral.rs, Claude Code). Fix any runner that does.
  Verify: the tests pass, and a run of each through the host doesn't end `runner.protocol`.

## 3. A second initialize is refused (#356)

- [ ] 3.1 Contract: `runner.already-initialized` in `protocol/schemas/runner/errors.schema.json` and the packaged copy.
  Verify: the schema tests and `test_runner_schemas.py` pass; the SDK's error-type strategy includes it.
- [ ] 3.2 SDK: the code and its refusal words in `troupe_plugin_sdk.runner`. Verify: a unit test of the words.
- [ ] 3.3 Failing first, per runner (Claude Code, OpenAI, Ollama, Anthropic, mistral.rs, scripted): `initialize`
  (with `transcript-kinds` where the runner uses kinds), `run/start`, a second `initialize` offering none; the second
  is refused with `runner.already-initialized`, and later records keep their kind. Verify: each fails on today's code.
- [ ] 3.4 Each runner refuses it through the SDK. Verify: 3.3 passes in every runner's tests.
- [ ] 3.5 Failing first: `check_runner` against a stand-in runner that answers a second `initialize` fails, naming it.
- [ ] 3.6 `check_runner` gains `second_initialize` (design D4). Verify: 3.5 passes, and the conformance suite passes
  against the scripted runner and every bundled runner it runs against.
- [ ] 3.7 `contributing/runners.md` says what a runner does with a second `initialize`. Verify: read it.

## 4. The flake-hunt tests bound each round (#397)

- [ ] 4.1 Failing first: a test of `conftest.run_with_progress`: a command printing a line every 0.3 s for 2 s passes
  a 1 s per-line bound (where `run_within` with 1 s fails), and a command that prints one line then sleeps fails
  within the bound, naming the last line. Verify: fails on today's code (no such helper).
- [ ] 4.2 `run_with_progress` in `scripts/tests/conftest.py`; `HUNT_ROUND_WITHIN` replaces `HUNT_RUN_WITHIN` and
  `run_hunt` uses it (design D5). Verify: 4.1 and `scripts/tests/test_flake_hunt.py` pass.

## 5. Checks

- [ ] 5.1 `openspec validate host-robustness --strict` passes.
- [ ] 5.2 `uv run scripts/check.py` passes, its output kept in a scratch file.
- [ ] 5.3 With the 1-minute load under ~40: `scripts/flake_hunt.py --load 2` on the new host and flake-hunt tests;
  then no processes left (`pgrep -fl "python.*(fake_claude.py|while True: pass)"`). Verify: 0 rounds failed.

## Workflow follow-up

- Draft PR closing #330, #311, #356 and #397; act on Claude's review; mark ready; `/openspec-archive-change` on the
  branch; the owner merges; comment on each issue and check each card says Done.
