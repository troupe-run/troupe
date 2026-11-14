# troupe-runner-anthropic

An actor runner for troupe that drives a model over the [Anthropic Messages
API](https://platform.claude.com/docs/en/api/messages), on Claude's own API or on a local engine that serves it (LM
Studio 0.4.1 and later, llama.cpp, LocalAI and Ollama do), with troupe's own tool loop
([#415](https://github.com/troupe-run/troupe/issues/415)). The model asks for tool calls; the runner carries each one
out with the [plugin SDK](../../packages/troupe-plugin-sdk/README.md)'s file tools, checked against the actor's
declared effects, and sends the result back. No Claude Code is involved: that runner reaches Claude through its CLI.

It speaks the [runner contract](../../contributing/runners.md) over standard input and output and imports nothing of
troupe's but the SDK. It talks to its service through the [`anthropic`](https://pypi.org/project/anthropic/) package,
pinned, from one module, `service.py`, which keeps troupe's guarantees rather than the library's defaults
([Runners with client libraries](../../contributing/runners.md#runners-with-client-libraries)). So it comes as
troupe-run's `anthropic` extra, not the base install:

```sh
uv tool install --no-sources "troupe-run[anthropic] @ git+https://github.com/troupe-run/troupe@<tag>#subdirectory=packages/troupe-run"
```

```yaml
# .troupe/actors/lead.yaml
runner: anthropic
runtime: anthropic
model: claude-haiku-5-5
options:
  maxTurns: 5
  maxTotalTokens: 20000
effects:
  write: ["**"]
expect: []
```

Start with low limits, as here, and raise them once the actor behaves: a run on Claude's API costs money.

## Options

All are optional. Any option the runner doesn't define is refused (`anthropic.unknown-option`), and a value of the
wrong shape too (`anthropic.invalid-options`), naming the option. The endpoint, the model and the key come from the
actor's runtime, never from its options.

| Option | Shape | Default | What it does |
|---|---|---|---|
| `maxTurns` | a whole number, 1 or more | 50 | The requests one run may make. Reaching it while the model still calls tools ends the run with an `error` result |
| `maxTotalTokens` | a whole number, 1 or more | 1,000,000 | Input, cache and output tokens over the run, as the service reports them, checked after each reply. Spending it ends the run with an `error` result |
| `maxOutputTokens` | a whole number, 1 or more | 16,000 | Each request's `max_tokens`, which the API requires: the most the model writes in one reply. A reply that reaches it ends the run with `output-limit` |
| `contextWindow` | a whole number, 1 or more | none | The engine's context window, in tokens, when you know it. See [The context](#the-context) |

Every request carries the whole conversation, so a long run's input grows with the square of its turns.

## The runtime and its credential

An actor on this runner names a [runtime](../../docs/stagecraft/runtimes.md). The runtime's endpoint is the API's base
URL, below which the library adds `/v1/messages`:

- **Claude's API**: troupe's built-in `anthropic` (`https://api.anthropic.com`, its key in `ANTHROPIC_API_KEY`).
- **A local engine**: a runtime of your own at the engine's server root. There's no built-in for one. For LM Studio:

  ```sh
  troupe config set runtimes.lm-studio-messages.endpoint=http://127.0.0.1:1234
  troupe config set actors.lead.runtime=lm-studio-messages actors.lead.model=google/gemma-4-e4b
  ```

  Ollama's is `http://127.0.0.1:11434`. A local engine takes no key unless you've set one up.

An endpoint whose path ends in `/v1`, copied from an OpenAI-style setup, is refused (`anthropic.unsupported-endpoint`),
naming the base without it: requests would otherwise go to `/v1/v1/messages`. A gateway's own path, such as
`https://gateway.example/anthropic`, is kept. troupe resolves the endpoint and model and hands them over in
`run/start`, and puts the key, when the runtime has one, in the runner's environment as `TROUPE_RUNTIME_CREDENTIAL`,
under no other name.

- The key goes only in each request's `Authorization: Bearer` header, which is how the library sends an API key, to
  the runtime's endpoint. LM Studio's API tokens are documented as Bearer tokens too; that's not been tried with
  "Require Authentication" on.
- **The library finds nothing for itself.** Given no key, `anthropic` would look for one in `ANTHROPIC_API_KEY`,
  `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_PROFILE`, workload identity variables and your profile on disk, and it reads
  `ANTHROPIC_BASE_URL` and `ANTHROPIC_CUSTOM_HEADERS` too. troupe passes the runner none of them, and the runner also
  removes every `ANTHROPIC_*` variable from its own environment and builds the library's client so that it never
  searches. Your own Claude key never reaches a local engine.
- A key holding a character a request header can't carry is refused by troupe before the runner starts, and again by
  the runner (`anthropic.malformed-credential`).
- A runtime with a key and a plain `http` endpoint to another machine is refused (`anthropic.insecure-endpoint`).
- A redirect is never followed (the library would follow it), so neither the key nor the conversation goes anywhere
  the runtime didn't name.
- Everything the runner sends troupe, and its standard error, has the key masked as `[credential]`, and a masked echo
  of it too.

## What it sends the service

Each request is `POST <endpoint>/v1/messages`, streamed, with:

- `system`: the runner's fixed instructions, then the actor's character;
- `messages`: the direction as the first user message, then, after each reply that called tools, an assistant message
  holding the reply's content blocks unchanged (`thinking` blocks and their signatures included), and one user message
  holding a `tool_result` per call, in order;
- `tools`: the SDK's tools as custom tools, each with its name, description and input schema unchanged;
- `max_tokens`: `maxOutputTokens`;
- the runtime's `model`.

Nothing else: no `tool_choice` (so it's `auto`), no `thinking` settings (so the model's default), and none of Claude's
server-side features, which a local engine doesn't serve.

## Run events

| From the service | Run event |
|---|---|
| the runtime's model | `init`, with engine `messages` and the model; `effects` is `checked` |
| a reply's `text` blocks | a `turn` |
| a reply's `thinking` | none; the transcript keeps it |
| each `tool_use` block | `tool_call` and `tool_result`, from the SDK |
| a request made again (see [Retries](#retries)) | `retry` |
| a reply's `model`, when it isn't the runtime's | `served_model`, the first time that model answers |
| a reply with no usage | a `log` warning, once; the result then has no usage |
| a reply that stops `end_turn` or `stop_sequence` | `result` `ok`, with its text |
| anything in [How a run ends](#how-a-run-ends) | `result` `error`, saying why |

A model whose reasoning arrives inside its text, rather than as `thinking` blocks, shows it in its turns: Gemma on LM
Studio writes its reasoning, then `<channel|>`, then its answer. The runner doesn't parse model-specific markers.

`result.usage` sums each reply's usage as the Messages API defines it: `inputTokens` is `input_tokens`, which excludes
the cache; `cacheReadTokens` is `cache_read_input_tokens` and `cacheWriteTokens` is `cache_creation_input_tokens`, each
when every reply reports it. LM Studio counts its cache reads inside `input_tokens` as well, so its runs over-report
input by them. The API reports no cost, so the result never has `costUsd`; when the theatre prices the run's model, it
carries `estimatedCostUsd` instead. Price a model with every rate its runs use, cache reads and writes included:

```sh
troupe config set 'runtimes.anthropic.prices.claude-haiku-5-5={"input": 0.1, "cacheRead": 0.01, "cacheWrite": 0.125, "output": 0.5}'
```

## The context

An engine can run out of context, and not every engine says so. The probe this runner was built on found that LM
Studio and Ollama both cut a conversation that outgrows their window and answer as if nothing happened, with nothing
in the Messages API to stop them. So the runner guards against acting on a reply made from less than it sent:

1. **A refusal.** Claude's `prompt is too long`, LM Studio's `api_error` about the context length, llama.cpp's
   `exceed_context_size_error`, and the stop reason `model_context_window_exceeded`, each named in one table in
   [`context.py`](src/troupe_runner_anthropic/context.py). None is retried.
2. **A shrinking prompt.** The conversation only grows, so a reply reported as answering a smaller prompt (its input
   and both cache counters) than the request before it was made from a cut conversation. Nothing in it is acted on.
3. **`contextWindow`, when you set it.** A reply whose prompt alone reaches it isn't acted on; once a reply's prompt and
   output reach it, its calls are carried out and no further request is sent.

In a run told `fail` (the default), each ends the run with `context-length`. **What it can't catch:** a first request
already over the window on an engine that cuts it silently (Ollama does): there's no earlier prompt to compare with,
and counting tokens needs the model's tokenizer. Claude's API and LM Studio refuse that case. On another engine, set
`contextWindow` and give the actor a direction that fits.

### Compaction

When `run/start`'s `onContextFull` is `compact`, each of the three compacts the conversation instead: the runner
replaces the oldest `tool_result`s with the plugin SDK's stub, saying what was removed and to call the tool again if
it's still needed, down to half the size of the last whole request. It sends a `context` event (kind `truncated`, by
`runner`), then the request again, as the same turn. It never changes the system prompt (the character), the first
message (the direction), any assistant message (sent back unchanged), or the latest turn's results. When only those
are left, the run ends with `context-length`.

## Retries

The library's own retries are off. The runner makes a request again, up to 5 attempts, after a growing delay (1 s,
doubled each time, at most 60 s), each reported first as a `retry` event:

| What happened | `retry` reason |
|---|---|
| 429 or `rate_limit_error`. The delay is `retry-after-ms` or `Retry-After` when given; a longer wait than 60 s ends the run instead | `rate-limit` |
| 500 or above, `overloaded_error` (529) included; a server error's wait is cut to 60 s | `server` |
| an `error` event in the stream of type `overloaded_error` or `api_error` | `server` |
| no connection, a timeout, or a stream cut short: silent for 120 s, broken, or ended before `message_stop` | `network` |

Every request is the whole conversation, and tools run only after a whole reply, so a retry never runs a tool twice.

## How a run ends

Besides a finished reply, each of these ends the run with an `error` result naming it and giving its `reason`, and
nothing is retried:

| What happened | Its message says | `reason` |
|---|---|---|
| 401, 403, `authentication_error` or `permission_error` | the service refused the credential, with its message | `authentication` |
| 402 or `billing_error` | the account can't pay for the request | `quota` |
| 429 asking to wait longer than the runner waits | the wait asked for, and the cap | `rate-limit` |
| a context refusal, a shrinking prompt or `contextWindow` reached (see [The context](#the-context)) | which, and, when told `compact`, that compaction found nothing more to remove | `context-length` |
| 404 without the API's error shape | the URL it tried, and that the endpoint must be the API's base URL | `configuration` |
| 404 with an error type | no such model, or no such API | `configuration` |
| a 3xx | the status and where it pointed; never followed | `configuration` |
| a 2xx whose `Content-Type` is set and isn't `text/event-stream` | the status and the type | `configuration` |
| any other 4xx, or a stream `error` event of another type | the status, the type and the service's message | `other` |
| `stop_reason` `refusal` | the model refused, with `stop_details` and any text | `refused` |
| `stop_reason` `max_tokens` | the output limit; no tool call in the reply was carried out | `output-limit` |
| `stop_reason` `model_context_window_exceeded` | the context window | `context-length` |
| `stop_reason` `pause_turn`, or one the runner doesn't know | the stop reason | `engine` |
| a reply it can't read: an event that isn't JSON, a delta for a block never started, a `tool_use` with no id or name | what was wrong; the reply's usage is counted when it can be read | `engine` |
| `maxTurns` reached | the limit, and the option to raise | `turn-limit` |
| `maxTotalTokens` spent | the budget and the tokens used | `budget` |
| retries run out | the last failure, and the attempts made | the last retry's |
| the runner fails itself | the error | `runner` |

A tool call whose input isn't a JSON object, or whose tool isn't one of the SDK's, isn't fatal: the SDK answers it
with an error the model is sent, and the call's block goes back with `input` `{}`, since the API takes only an object.

## Cancel

On `run/cancel`, or when standard input closes, the runner answers and stops. A request in flight can't be abandoned
from another thread (closing the library's stream doesn't interrupt a read), so the runner ends its own process,
which closes the connection; between requests, it stops at its next check, within `STOP_GRACE_SECONDS`. Either way,
nothing follows the answer: no further event, tool call or request, and no `result`.

## The transcript

The runner accepts the contract's `transcript-kinds` capability and gives each record a kind
([contributing/runners.md](../../contributing/runners.md#record-kinds)). In order:

| Record | Kind | What it holds |
|---|---|---|
| each request's parameters | `sent` | as passed to the library, compact JSON |
| each response's status | `note` | `{"status", "headers"}`, with only the headers in `TRANSCRIPT_HEADERS` and `TRANSCRIPT_HEADER_PREFIXES` |
| each stream event | `received` | the event as the library parsed it, compact JSON |
| the body of an error, a stream's `error` event, or a 2xx that isn't a stream | `received` | the body |
| a stream cut short that it abandons | `note` | `{"dropped": "<why>"}` |

Compared with the bytes on the wire, it leaves out the stream's framing (`event:` lines, blank lines and comments, such
as Claude's `ping` events), any event the library reads and drops, and request headers, which are never recorded. The
library's own logging is kept off standard output: only its warnings reach standard error, masked and cut to
`LIBRARY_LOG_MAX_BYTES`, whatever `ANTHROPIC_LOG` says, and its OpenTelemetry tracing is off.

## Limits

Every setting is in [`defaults.py`](src/troupe_runner_anthropic/defaults.py). The library's timeouts are set from
these, never left at its ten-minute default:

| Setting | Default | What it limits |
|---|---|---|
| `DEFAULT_MAX_TURNS` | 50 | Requests in a run, when the options don't set `maxTurns` |
| `DEFAULT_MAX_TOTAL_TOKENS` | 1,000,000 | Tokens in a run, when the options don't set `maxTotalTokens` |
| `DEFAULT_MAX_OUTPUT_TOKENS` | 16,000 | Each request's `max_tokens`, when the options don't set `maxOutputTokens` |
| `MAX_ATTEMPTS` | 5 | Attempts at one request, the first included |
| `RETRY_BASE_DELAY_SECONDS` | 1 | The first retry's delay, doubled each time |
| `RETRY_MAX_DELAY_SECONDS` | 60 | The longest delay, `Retry-After` included |
| `CONNECT_TIMEOUT_SECONDS` | 30 | Connecting, the library's connect and pool timeouts |
| `WRITE_TIMEOUT_SECONDS` | 30 | Sending a request, the library's write timeout |
| `STREAM_TIMEOUT_SECONDS` | 120 | Silence while reading a response, the library's read timeout |
| `SUMMARY_MAX_BYTES` | 4096 | One summary field, before `eventMaxBytes` cuts it further |
| `STOP_GRACE_SECONDS` | 5 | The loop's time to stop after a cancel, between requests |
| `LIBRARY_LOG_MAX_BYTES` | 2048 | One library warning on standard error |
| `TRANSCRIPT_HEADERS` | `content-type`, `request-id`, `retry-after`, `retry-after-ms`, `x-should-retry` | Response headers the transcript keeps |
| `TRANSCRIPT_HEADER_PREFIXES` | `anthropic-ratelimit-` | Response header prefixes the transcript keeps |
| `INSTRUCTIONS` | (text) | The runner's fixed instructions, before the character |

## Schemas

[`options.schema.json`](src/troupe_runner_anthropic/schemas/options.schema.json) and
[`errors.schema.json`](src/troupe_runner_anthropic/schemas/errors.schema.json). Each error code refuses `run/start`,
so no request is sent:

| Error | When |
|---|---|
| `anthropic.unknown-option` | an option the runner doesn't define, such as `endpoint` or `model` |
| `anthropic.invalid-options` | an option's value has the wrong shape |
| `anthropic.no-runtime` | `run/start` names no runtime, or one with no model |
| `anthropic.unsupported-endpoint` | an endpoint ending in `/v1`, or with a query, fragment or user info, or that isn't an http or https URL |
| `anthropic.insecure-endpoint` | a key, and plain `http` to another machine |
| `anthropic.credential-mismatch` | `run/start` and `TROUPE_RUNTIME_CREDENTIAL` disagree about whether there's a key |
| `anthropic.malformed-credential` | the key holds a character a request header can't carry |

## Fixtures

[`fixtures/`](fixtures) holds, for each run, the service's replies, their provenance, and the events they map to.
Recorded from LM Studio with `google/gemma-4-e4b`: a tool loop, its refusal of an over-long prompt, a conversation it
cut, and the output limit. Recorded from Claude's API with `claude-haiku-5-5`, by the owner with a working key: a tool
loop and its refusal of a prompt over the model's context; and with a deliberately invalid key, a rejected credential. Derived or
built from the API's documented shapes: a broken stream, a rate limit, an overload, an `error` event in a stream, and a
refusal. [`tools/capture_anthropic.py`](tools/capture_anthropic.py) records new ones, and scrubs the key, request ids
and the host's home; without a key it records nothing from a service that isn't on this machine.

## Tests

Tests drive the runner as a process against a fake Messages endpoint, and every run sets low limits (`TEST_LIMITS`: 5
turns, 20,000 tokens): the test harness refuses one that doesn't. The live tests run a real service only when asked:

```console
TROUPE_LIVE_ANTHROPIC=1 uv run pytest packages/troupe/tests/test_anthropic_live.py -s
TROUPE_LIVE_ANTHROPIC_LOCAL=1 TROUPE_LIVE_ANTHROPIC_ENDPOINT=http://127.0.0.1:1234 \
  TROUPE_LIVE_ANTHROPIC_MODEL=google/gemma-4-e4b uv run pytest packages/troupe/tests/test_anthropic_live.py -s
```

The first needs `ANTHROPIC_API_KEY` and costs a few cents; the second runs on a local engine, free.
