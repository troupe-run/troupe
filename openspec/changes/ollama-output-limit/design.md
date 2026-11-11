# Design: a cut Ollama answer ends the run

## Context

See proposal.md for why. What's there today, in `plugins/runner-ollama/src/troupe_runner_ollama/conversation.py`:

- `_gather` reads an answer's lines and, on the `done` line, keeps `done_reason`, `prompt_eval_count`,
  `prompt_eval_cached_count` and `eval_count` on the `_Answer`.
- `_loop` calls `_request`, then `_after(answer)`, then returns the answer's text when it has no tool call (an `ok`
  result), or `_call_tools(answer)` and goes round again.
- `_after` notes a served model, adds the answer's counts to the run's usage, sends a `log` warning when
  `done_reason` is `length`, then sends the answer's text as a `turn`.
- A run ends early by raising `_RunEnded(message, reason)`, which `_run` turns into an `error` result. Retries live in
  `_request`, for `RetryableError` only.
- The runner sets `num_ctx` (the window) and `shift` `false` on every request, and never `num_predict`. In Ollama
  0.40.x, with no `num_predict`, an answer that fills the window stops with `done_reason` `length` (with `shift`
  `false` Ollama doesn't drop the conversation's start to make room). A model's own Modelfile can set `num_predict`,
  which also ends with `length`; the runner can't tell the two apart from the answer.
- `output-limit` is on the contract's list (`failure-reason`), and troupe's outcome already has its title and fix:
  "Raise the output limit in the actor's runner options if it has one, or give the actor a smaller task."
- The fixtures are captured by `tools/capture_ollama.py` from Ollama on this machine (0.40.14, `qwen3:0.6b` is
  pulled), and replayed by `tests/test_ollama_fixtures.py`.

## Goals / Non-Goals

**Goals:** a cut answer ends the run with `output-limit` whether it holds text, a tool call or both; nothing from a cut
answer is acted on; the message says what limit it hit and how to raise it; fixtures of both shapes from a real Ollama.

**Non-Goals:** a `num_predict` option; a retry or a "continue" request; reading the model's Modelfile parameters; the
`context` event (#307) or compaction (#310); any other runner.

## Decisions

### D1. The check runs after the answer is counted and its text sent, before its tool calls

`_after` keeps its order (served model, usage, `turn`), and in place of the `log` warning raises
`_RunEnded(message, "output-limit")` when `done_reason` is `length`. So:

- the result's `usage` includes the cut answer's tokens: Ollama spent them;
- the cut answer's text is a `turn`, as every answer's text is (the transcript has its lines either way). A `turn` is
  what the model said, not what the run accepted; the `error` result after it says it was cut;
- `_call_tools` is never reached, so no tool call from a cut answer runs, whether its arguments look whole or not. A
  call whose JSON parsed may still be cut short in its content (a `Write` of half a file), so "whole-looking" isn't
  safe to act on (#279 rejected "fail only cut tool calls");
- `_loop` never returns the cut text as an `ok` result.

Alternative: check in `_loop` after `_after`. Same effect, but splits "what an answer's end means" across two methods;
`_after` is where `done_reason` is read today.

### D2. The message names the window, and the tokens when Ollama gives them

> Ollama cut the model's answer at its output limit (done_reason length) after 81 tokens. The runner sets no output
> limit, so Ollama stops an answer when the conversation fills the run's context window of 1300 tokens: raise
> contextLength, or give the actor a smaller task. A num_predict the model sets also cuts its answers.

"after N tokens" is left out when the answer's `eval_count` is missing or malformed (as `_count` already treats it).
The window is named because, with the runner setting no `num_predict`, it is the limit in every case the runner
controls. The last sentence covers a Modelfile's `num_predict`, which the runner doesn't read: naming it is cheaper
and more honest than guessing. The wording lives in one place, beside the context-length message in
`conversation.py`.

### D3. No retry, and not a `RetryableError`

`_RunEnded` is raised outside `_request`'s retry loop, so it can't be retried. Same request, same window, same cut
(#279 point 4).

### D4. Fixtures: two capture scenarios with a window just over the prompt

`capture_ollama.py` gets two scenarios, each with `think` `false`, `temperature` 0, `seed` 1 and a `contextLength`
just above the first request's prompt (about 1222 tokens with the seven tools; the exact value is set at capture,
from the first request's `prompt_eval_count`, so that the answer, not the prompt, fills the window):

- `cut-answer`: a direction asking for a long text answer and no tools. Expected: text, then `done_reason` `length`.
- `cut-tool-call`: a direction asking to `Write` a long file, with the effects allowing it. Expected: the answer is cut
  while the model writes the call.

What Ollama sends for a cut tool call is what the fixture is for: a partial `tool_calls` entry, the call's raw text in
`content`, or nothing (Ollama's tool parser may hold back a call it can't finish). The runner ends the run the same
way in each case (D1), and the README says which one 0.40.14 sends. If a scenario doesn't reach `length` (the model
stops early), the direction or window is adjusted and the provenance records what was used; a scenario is never
committed without `done_reason` `length` in its answers.

Each fixture's events are reviewed by hand before committing, as the capture tool says.

### D5. The spec requirement for failure reasons is replaced, not modified

The main spec's "Each failure reports its reason" has a scenario, "A cut answer is still not a failure", that this
change makes false. OpenSpec refuses a MODIFIED block that drops a scenario, and a requirement can't be both REMOVED
and ADDED under one name. So the delta removes it and adds "Each failed run reports its reason": the same text with
`output-limit` added, every other scenario unchanged, and "A cut answer" in place of the false one. Its place in the
main spec moves to the end; nothing links to it by heading (task 1.2 checks).

## Risks / Trade-offs

- **A long run whose last answer is cut now fails** where it ended `ok` before. That's the decision: the `ok` was
  built on a cut answer. The message says how to raise the window.
- **A small model can fill a small window often.** The default window is 16384 tokens; a cut there means the
  conversation is near the window anyway, which already ends the run on the next request with `context-length`.
- **Capture depends on the model's behaviour.** `qwen3:0.6b` at temperature 0 and seed 1 is deterministic enough for
  the existing fixtures; D4 says what happens if a scenario doesn't cut.
- **The property test samples `done_reason` `length`.** Any of its invariants that assume a text-only answer ends `ok`
  need the cut case (task 2.3).
