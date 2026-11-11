# Proposal: a cut Ollama answer ends the run

Issue: [troupe#309](https://github.com/troupe-run/troupe/issues/309), from Decision
[#279](https://github.com/troupe-run/troupe/issues/279) point 4 (owner, 2026-11-07). It uses the reason
`output-limit` that [#296](https://github.com/troupe-run/troupe/issues/296) added (change `failure-reason`), and
unblocks [#332](https://github.com/troupe-run/troupe/issues/332) (the Ollama runner onto the `ollama` package).

## Why

When an Ollama answer reaches its output limit, Ollama ends it with `done_reason` `length`. The runner today sends a
`log` warning and carries on with the cut answer: it runs a cut answer's tool calls, and ends the run `ok` with a cut
final answer. A cut answer, or a tool call whose arguments were cut, is unreliable, and nothing on the result says so.
#279 decided that cut output fails the run with `output-limit`, without a retry (the same request would be cut the
same way). The OpenAI runner already does this on `incomplete` / `max_output_tokens`; this brings the Ollama runner
into line, as design D5 of `local-model-runner` left it to.

## What Changes

- **An answer that ends with `done_reason` `length` ends the run** with an `error` result and reason `output-limit`.
  The runner makes no further request and carries out none of that answer's tool calls. Its text, if any, is still a
  `turn`, and its lines are in the transcript, so what the model said isn't lost.
- **The result's message names the limit**: that Ollama cut the answer (`done_reason` `length`), how many tokens it
  had produced when Ollama reports them, and the run's context window and `contextLength`, which is where Ollama stops
  an answer when no output limit is set (the runner sets none), with how to raise it.
- **No retry.** A cut answer isn't a `retry`.
- **The `log` warning goes**: the `result` says it.
- **Two new fixtures**, captured from a real Ollama with the capture tool: `cut-answer` (a text answer cut at the
  window) and `cut-tool-call` (an answer cut while the model writes a tool call's arguments). The replay test checks
  each.
- **Docs**: the runner's README (what a cut answer does, its run-event table, its reasons) and the Ollama row of
  `contributing/runners.md` say the run ends with `output-limit`.

Out: the other runners (the OpenAI runner already fails on its output limit; the Claude Code runner already maps
`max_output_tokens` to `output-limit`); an option to set Ollama's `num_predict` (nothing asks for one); the context
event and compaction opt-in of #307 and #310; Claude Code's compaction (#308).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `ollama-runner`: a cut answer (`done_reason` `length`) ends the run with an `error` result and `output-limit`
  instead of a `log` warning; the loop's `ok` ending and the failure-reason table say so; two fixtures added.

## Impact

- `plugins/runner-ollama/src/troupe_runner_ollama/conversation.py`: `_after` / `_loop`.
- `plugins/runner-ollama/tests/`: the conversation test of a cut answer, its property test, the fixture replay.
- `plugins/runner-ollama/tools/capture_ollama.py` and `plugins/runner-ollama/fixtures/ollama/`: two scenarios.
- `plugins/runner-ollama/README.md`, `contributing/runners.md`.
- No contract, schema or core change: `output-limit` is already on the contract's list, and troupe's outcome already
  has its fix text. No spec Purpose changes, so no infrastructure `oob` update.
- Behaviour change for users: a run whose answer Ollama cut, which today ends `ok` (or carries on), now fails. Pre-1.0,
  with no compatibility to keep.
