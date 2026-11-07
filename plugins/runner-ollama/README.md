# troupe-runner-ollama

An actor runner for troupe that drives a model served by [Ollama](https://ollama.com), through Ollama's own
`/api/chat`, with troupe's own tool loop (#277). The model asks for tool calls; the runner carries each one out with
the [plugin SDK](../../packages/troupe-plugin-sdk/README.md)'s seven file tools, checked against the actor's declared
effects, and sends the result back. No Claude Code is involved, no credential is needed, a run costs nothing, and it
works offline.

It speaks the [runner contract](../../contributing/runners.md) over standard input and output, imports nothing of
troupe's but the SDK, and depends on nothing else: it talks to Ollama with the standard library. It starts no
process. Ollama has to be running already, with the model pulled.

```yaml
# .troupe/actors/lead.yaml
runner: ollama
options:
  model: qwen3.5:4b
effects:
  write: ["**"]
expect: []
```

## Options

Only `model` is required. Any option the runner doesn't define is refused (`ollama.unknown-option`), and a value of
the wrong shape too (`ollama.invalid-options`), naming the option.

| Option | Shape | Default | What it does |
|---|---|---|---|
| `model` | text | — | The model, as Ollama names it, such as `qwen3.5:4b`. It must be pulled, and able to call tools |
| `endpoint` | `http` or `https` URL: a host and an optional port | `http://127.0.0.1:11434` | Where Ollama listens. No user name, password, path, query or fragment; a port up to 65535, and each part of a host name 1 to 63 characters |
| `maxTurns` | 1 to 1000 | 50 | The requests one run may make. Reaching it ends the run with an `error` result |
| `contextLength` | a whole number of tokens, at most the model's maximum | 16384, or the model's maximum if smaller | The context window, sent as Ollama's `num_ctx` on every request. See [The context window](#the-context-window) |
| `temperature` | a number, 0 or more | Ollama's | Sent as `options.temperature` |
| `seed` | a whole number | Ollama's | Sent as `options.seed` |
| `think` | `true`, `false`, `low`, `medium` or `high` | Ollama's | Whether a thinking model thinks. The thinking is kept in the transcript only |

The runner reads nothing from its environment: not `OLLAMA_HOST`, not a proxy. Configuration comes only from
`run/start`, so a run doesn't depend on who runs it.

**Any endpoint is accepted.** A run sends the workspace's contents (whatever the model reads) to wherever `endpoint`
points, and config lives in the repository. Restricting where a run may send them is policy's job, later.

## Before the run starts

Before it acknowledges `run/start`, the runner asks Ollama for its version and for the model, within 10 s for both, and
refuses the run, so it ends `could-not-start` with the reason, when:

| Error | When | Fix |
|---|---|---|
| `ollama.unreachable` | Nothing answers at the endpoint, or what answers isn't Ollama | Start Ollama (`ollama serve`), or set `endpoint` |
| `runner.requirement-unmet` | Ollama is older than the runner needs, or reports a version the runner can't read | Upgrade Ollama |
| `ollama.model-not-found` | Ollama has no model of that name | `ollama pull <model>` |
| `ollama.model-without-tools` | Ollama doesn't list `tools` among the model's capabilities, or doesn't say what it can do | Use a model that can call tools |
| `ollama.invalid-options` | `contextLength` is above the model's maximum, which `/api/show` gives as `model_info["<architecture>.context_length"]` | Lower `contextLength` |

### What it requires

What the runner requires of the platform is published as data, in
[`requirements.json`](src/troupe_runner_ollama/requirements.json), beside its schemas: today, **Ollama 0.12.6 or
later**, the first that understands the `truncate` and `shift` fields (next section). An older Ollama ignores them and
cuts conversations silently, so it's refused with the contract's `runner.requirement-unmet`, whose details name the
requirement, what's wanted and what was found. How troupe's components declare what they require in general is
Decision #281.

## The context window

Ollama's window (`num_ctx`) is how much of the conversation the model can hold. By default, Ollama doesn't refuse a
conversation that outgrows it: it silently drops the start, which in a runner with its own tool loop is the actor's
character and direction, and its token counts don't show it. Checked against Ollama 0.40.14 on 2026-11-04: a prompt
of about 3,000 tokens in a 512-token window was answered, reporting 258 prompt tokens.

So the runner:

- **always sets the window**: `contextLength`, or 16384 tokens lowered to the model's maximum, never Ollama's own
  default, which differs between versions and machines. A larger window holds more, and needs more memory for its
  cache: raise `contextLength` for long tasks if the machine has it.
- **asks Ollama to refuse rather than cut**: every request sends `truncate` and `shift` as `false`. A conversation
  that outgrows the window is then refused with status 400 (`request (1226 tokens) exceeds the available context size
  (512 tokens), try increasing it`, in the [`context-overflow`](fixtures/ollama/context-overflow/answers.json)
  fixture), and the run ends with an `error` result holding Ollama's message, the window, and how to raise it. An
  answer that reaches the window stops with `done_reason` `length`, which is a `log` warning.
- **keeps each tool result to a quarter of the window**, counted at 3 bytes per token: about 12 KB at 16384 tokens.
  It lowers the SDK's limits to fit (`Read`'s bytes, `Glob`'s paths, `Grep`'s matches), whose capped results say where
  they stopped and how to read on, and cuts anything still over, with a note saying it was cut to fit the window and
  how to narrow the call. One large file can't end a run.

What a run should do instead of failing when it outgrows its window is Decision #279.

## What it sends Ollama

Each request is a streamed `/api/chat` request: the conversation's messages, the SDK's seven tools as function tools
(their descriptions name the run's scratch directory), `num_ctx`, `truncate` and `shift` `false`, and the options that
are set. The first request's messages are the character, as a `system` message when the actor has one, and the
direction, as a `user` message. After each answer with tool calls, the runner adds the answer (its text, its thinking
and its calls, as Ollama gave them) and one `tool` message per call, naming the tool, holding the SDK's output, error
or not. A call Ollama gives no id gets `call-<request>-<position>`.

The run ends when an answer has no tool call (`ok`, with the answer's text, or `(no text)`), when `maxTurns` requests
have been made (`error`), or when Ollama refuses (`error`).

## Run events

| From Ollama | Run event |
|---|---|
| the preflight's version, and the options' model | `init`: engine `ollama`, its version and the model; the seven tools; `effects` `checked` |
| an answer's text, once its last line has come | one `turn` (`assistant`), when the text isn't empty |
| an answer's thinking | none: the transcript keeps it |
| each tool call | `tool_call` and `tool_result`, from the SDK |
| a request made again | `retry` (see [Retries](#retries)) |
| `done_reason` `length` | `log` warning |
| the run's end | one `result`, with `turns` (the requests made), the duration, and `usage` |

`usage.inputTokens` is the sum of each answer's `prompt_eval_count`, and `outputTokens` the sum of its `eval_count`.
Ollama reports the prompt tokens it took from its cache apart, as `prompt_eval_cached_count` (for example, 4 cached
beside 258 evaluated): they aren't in `inputTokens`, which is what the runner contract means by it (the input not
counted in a cache counter). Until #282 reports them as `cacheReadTokens`, a run's counters add up to less than its
whole input. A run reports no cost: nothing tells the runner a price.

## The transcript

The runner holds the conversation, so the transcript is the exchange as it happened, each record verbatim and once:

1. the first request's body, exactly as sent, kind `sent`;
2. before each later request, each message the runner added to the conversation (the answer, then its `tool`
   messages), encoded exactly as it is inside that request, kind `sent`;
3. every line of every answer, and every error body, kind `received`.

The runner accepts the contract's `transcript-kinds` capability to label them
([contributing/runners.md](../../contributing/runners.md#record-kinds)). Offered no capability (a troupe from before
it), it sends the same records without a kind.

Request *n* is the first request's messages, followed by every message recorded under 2 up to it, with the first
request's other fields. Re-sent history isn't recorded again, so a transcript grows with the run, not its square.

## Retries

A request is made again, up to 3 attempts, after 1 s and then 2 s, when the connection fails, drops before the
answer's last line, or sends a line that isn't a JSON object (`network`), when the stream is silent for 300 s
(`network`; Ollama sends nothing while it loads a model), or on status 500, 502, 503 or 504 (`server`). Each retry is a
`retry` event. Any other status, and an `error` line in a stream, end the run with an `error` result at once.

## How a run ends

`run/cancel`, end of input, and `shutdown` each stop the run at once: the request in flight is closed, no further tool
call is carried out, and nothing is sent after the answer to `run/cancel` or `shutdown`. The runner exits within 2 s,
with code 0. It exits 1 only when it fails itself, after a `log` error and an `error` result.

## Limits

Each is a named setting in [`defaults.py`](src/troupe_runner_ollama/defaults.py).

| Setting | Default | What it limits |
|---|---|---|
| `DEFAULT_ENDPOINT` | `http://127.0.0.1:11434` | Where requests go without `endpoint` |
| `MAX_TURNS` | 50 | Requests per run without `maxTurns` |
| `MAX_TURNS_LIMIT` | 1000 | The largest `maxTurns` |
| `DEFAULT_CONTEXT_LENGTH` | 16384 | The window without `contextLength`, lowered to the model's maximum |
| `TOOL_OUTPUT_SHARE` | 0.25 | The share of the window one tool result may take |
| `BYTES_PER_TOKEN` | 3 | The bytes taken to make a token, to turn the window into a byte budget |
| `GLOB_PATH_BYTES` | 64 | The bytes one `Glob` path is taken to need |
| `GREP_MATCH_BYTES` | 128 | The bytes one `Grep` match is taken to need |
| `READ_NOTE_BYTES` | 128 | Room kept in a tool result's budget for the SDK's note saying where a capped `Read` stopped |
| `PREFLIGHT_TIMEOUT_SECONDS` | 10 | The whole preflight: both requests share one deadline |
| `STREAM_IDLE_TIMEOUT_SECONDS` | 300 | A stream's silence before it's retried |
| `LINE_MAX_BYTES` | 16 MiB | The longest line read from Ollama |
| `RETRY_MAX_ATTEMPTS` | 3 | Attempts per request, the first included |
| `RETRY_DELAY_SECONDS` | 1 | The first retry's delay, doubled for each later one |
| `STOP_GRACE_SECONDS` | 2 | How long the runner waits for its loop to stop before exiting |
| `SUMMARY_MAX_BYTES` | 4096 | One summary field of an event, before `eventMaxBytes` |

## Schemas

[`options.schema.json`](src/troupe_runner_ollama/schemas/options.schema.json) and
[`errors.schema.json`](src/troupe_runner_ollama/schemas/errors.schema.json), installed with the package, fill the
contract's extension points. The options parser and the schema accept exactly the same options (a hypothesis test
checks).

## Fixtures

[`fixtures/ollama/`](fixtures/ollama/) holds real exchanges with Ollama 0.40.14, each with its provenance:

- captured by [`tools/capture_ollama.py`](tools/capture_ollama.py): `success-with-tools`, `refused-by-effects`,
  `thinking`, `context-overflow`, `model-not-found` and `no-tools-capability`;
- hand-written from `success-with-tools`, with a failure put in front: `server-retries`, `network-retries` and
  `stream-error`.

Each holds what Ollama answered (`preflight.json`, `answers.json`) and what the runner sent for it (`transcript.jsonl`,
each line a record and its kind as troupe stores it, and `events.json`), recorded and then reviewed by hand. The tests replay each through the runner against a fake Ollama and
check it sends exactly that. To capture again, with Ollama running on this machine:

```console
uv run python plugins/runner-ollama/tools/capture_ollama.py --list
uv run python plugins/runner-ollama/tools/capture_ollama.py success-with-tools
```

It needs no credential, refuses an Ollama that isn't on this machine, and replaces host paths with `<workspace>` and
`<scratch>`.

## Tests

The tests run against a fake Ollama (`tests/fake_ollama.py`), a loopback HTTP server that plays scripted answers, so
they need no Ollama and run on Linux, macOS and Windows. A test against a real model runs only when asked:
`TROUPE_LIVE_OLLAMA=1`, with `TROUPE_LIVE_OLLAMA_MODEL` naming the model (`packages/troupe/tests/test_ollama_live.py`).
