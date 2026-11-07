# troupe-runner-openai

An actor runner for troupe that drives OpenAI's [Responses API](https://developers.openai.com/api/docs/guides/streaming-responses),
or any service that serves it (local Ollama does, under `/v1`), with troupe's own tool loop (#162). The model asks for
tool calls; the runner carries each one out with the [plugin SDK](../../packages/troupe-plugin-sdk/README.md)'s seven
file tools, checked against the actor's declared effects, and sends the result back. No Claude Code is involved.

It speaks the [runner contract](../../contributing/runners.md) over standard input and output, imports nothing of
troupe's but the SDK, and depends on nothing else: it talks to the service with the standard library, from one
module, `service.py`.

```yaml
# .troupe/actors/lead.yaml
runner: openai
runtime: openai
model: gpt-6-luna
options:
  maxTurns: 5
  maxTotalTokens: 20000
effects:
  write: ["**"]
expect: []
```

Start with low limits, as here, and raise them once the actor behaves: a run on a hosted model costs money.

## Options

Both are optional. Any option the runner doesn't define is refused (`openai.unknown-option`), and a value of the wrong
shape too (`openai.invalid-options`), naming the option. The endpoint, the model and the key come from the actor's
runtime, never from its options.

| Option | Shape | Default | What it does |
|---|---|---|---|
| `maxTurns` | a whole number, 1 or more | 50 | The requests one run may make. Reaching it ends the run with an `error` result |
| `maxTotalTokens` | a whole number, 1 or more | 1,000,000 | Input plus output tokens over the run, as the service reports them, checked after each response. Spending it ends the run with an `error` result |

With no price from the service, the token budget is what bounds a run's spend. Every request carries the whole
conversation, so a long run's input grows with the square of its turns.

## The runtime and its credential

An actor on this runner names a [runtime](../../docs/stagecraft/runtimes.md): troupe's built-in `openai`
(`https://api.openai.com/v1`, its key in `OPENAI_API_KEY`), or one of your own. troupe resolves its endpoint and model
and hands them over in `run/start`, and puts the key, when the runtime has one, in the runner's environment as
`TROUPE_RUNTIME_CREDENTIAL`, under no other name.

- The key goes only in each request's `Authorization: Bearer` header, to the runtime's endpoint.
- A runtime with a key and a plain `http` endpoint to another machine is refused (`openai.insecure-endpoint`). Plain
  `http` is for a server on this machine.
- A redirect is never followed, so neither the key nor the conversation goes anywhere the runtime didn't name.
- Everything the runner sends troupe, and its standard error, has the key masked as `[credential]`, and a masked echo
  of it too, such as OpenAI's `sk-proj-****...abcd` in a 401.

The built-in `ollama` runtime points at Ollama's own API, not its `/v1`. To run this runner on Ollama, give a runtime
the endpoint `http://127.0.0.1:11434/v1`.

## What it sends the service

Each request is `POST <endpoint>/responses`, streamed, with:

- `instructions`: the runner's fixed instructions, then the actor's character;
- `input`: the direction as the first user message, then, after each response that called tools, its output items
  unchanged (reasoning included) and one `function_call_output` per call;
- `tools`: the SDK's seven tools, as `function` tools with `strict` false (the API makes a tool strict unless told,
  and the SDK's optional fields don't fit strict mode);
- `store: false` and no previous response id, so the service keeps nothing of the run;
- `include: ["reasoning.encrypted_content"]`, so a reasoning model's reasoning can be sent back.

## Run events

| From the service | Run event |
|---|---|
| the runtime's model | `init`, with engine `responses` and the model; `effects` is `checked` |
| a response's output text | a `turn` |
| a response's reasoning | none; the transcript keeps it |
| each `function_call` output item | `tool_call` and `tool_result`, from the SDK |
| a request made again (see [Retries](#retries)) | `retry` |
| a model other than the one asked for | a `log` at `info`, once |
| a response with no usage | a `log` warning, once; the result then has no usage |
| a completed response with no function call | `result` `ok`, with its text |
| anything in [How a run ends](#how-a-run-ends) | `result` `error`, saying why |

`result.usage` sums each response's usage: `cacheReadTokens` is `input_tokens_details.cached_tokens`,
`cacheWriteTokens` is `cache_write_tokens` when every response reports it, and `inputTokens` is the input less both.
`costUsd` is set only when the service reports a cost; OpenAI reports none. When no cost is reported and the theatre
prices the run's model, the result carries `estimatedCostUsd` instead: the usage at that price, marked as an estimate.
Price a model with every rate its runs use, cache reads and writes included (OpenAI runs nearly always use the prompt
cache, and a run that used a kind of token the price has no rate for gets no estimate):

```sh
troupe config set 'runtimes.openai.prices.gpt-5-mini={"input": 0.25, "cacheRead": 0.025, "cacheWrite": 0, "output": 2}'
```

[Price a model](../../docs/stagecraft/runtimes.md#price-a-model-for-an-estimated-cost) says more. The runner never
estimates from a price of its own.

## Retries

A request is made again, up to 5 attempts, after a growing delay (1 s, doubled each time, at most 60 s), each reported
first as a `retry` event:

| What happened | `retry` reason |
|---|---|
| 429, unless its code is `insufficient_quota`. The delay is `Retry-After` when it gives one; a longer wait than 60 s ends the run instead | `rate-limit` |
| 500 or above | `server` |
| a failed response or an `error` event whose code is the service's own failure (`server_error`) | `server` |
| no connection, a timeout, or a stream cut short: silent for 120 s, broken, ended before its final event, or ended in the middle of an event | `network` |

## How a run ends

Besides a completed reply, each of these ends the run with an `error` result naming it, and nothing is retried:

| What happened | Its message says |
|---|---|
| 401 or 403 | the service refused the credential, with its message |
| 429 `insufficient_quota` | the account is out of quota |
| 400 `context_length_exceeded` | the conversation is longer than the model's context |
| 404 without OpenAI's error shape | the URL it tried, and that the endpoint must be the API's base, often ending in `/v1` |
| any other 4xx | the status and the service's message |
| a 3xx | the status and where it pointed; never followed |
| a failed response, or an `error` event, with any other code | the code and the service's message |
| `incomplete`, reason `max_output_tokens` or `content_filter` | the output limit, or the content filter |
| a refusal in an output message | the model refused, with its words |
| a function call with no `call_id` | it can't be answered |
| a status the runner doesn't know | the status |
| a response the service finished in a shape it can't read: an event (ended by its blank line, or whole JSON) that isn't JSON or has no type, or a final event with a field of the wrong type, such as a tool call's arguments as an object | what was wrong, and that retrying can't fix it; the response's usage is counted when it can be read |
| a 2xx whose `Content-Type` is set and isn't `text/event-stream`, such as a plain JSON body | the status, the type, and the service's message or the start of the body |
| `maxTurns` reached, or `maxTotalTokens` spent | which, and the option to raise |
| retries run out | the last failure, and the attempts made |

## The transcript

The runner conducts an HTTP exchange, so it accepts the contract's `transcript-kinds` capability and gives each
record a kind ([contributing/runners.md](../../contributing/runners.md#record-kinds)). In order:

| Record | Kind | What it holds |
|---|---|---|
| each request body | `sent` | the body as sent |
| each response's status | `note` | `{"status", "headers"}`, compact JSON, with only the headers in `TRANSCRIPT_HEADERS` and `TRANSCRIPT_HEADER_PREFIXES` |
| each line of a response's stream | `received` | the line unchanged, its `event:` and blank lines too |
| the body of an error, or of a 2xx that isn't a stream | `received` | the body's bytes, as base64 when they aren't UTF-8 |
| a stream cut short that it abandons | `note` | `{"dropped": "<why>"}` |

No request header is ever recorded, and neither is the request's URL: the run's start records the runtime's
endpoint, and the URL is that plus `/responses`. Offered no capability (a troupe from before it), the runner sends
the same records without a kind.

## Limits

Every setting is in [`defaults.py`](src/troupe_runner_openai/defaults.py):

| Setting | Default | What it limits |
|---|---|---|
| `DEFAULT_MAX_TURNS` | 50 | Requests in a run, when the options don't set `maxTurns` |
| `DEFAULT_MAX_TOTAL_TOKENS` | 1,000,000 | Tokens in a run, when the options don't set `maxTotalTokens` |
| `MAX_ATTEMPTS` | 5 | Attempts at one request, the first included |
| `RETRY_BASE_DELAY_SECONDS` | 1 | The first retry's delay, doubled each time |
| `RETRY_MAX_DELAY_SECONDS` | 60 | The longest delay, `Retry-After` included |
| `CONNECT_TIMEOUT_SECONDS` | 30 | Connecting and getting the response's status |
| `STREAM_TIMEOUT_SECONDS` | 120 | Silence between two reads of a stream |
| `SUMMARY_MAX_BYTES` | 4096 | One summary field, before `eventMaxBytes` cuts it further |
| `STOP_GRACE_SECONDS` | 5 | The loop's time to stop after a cancel |
| `STREAM_LINE_MAX_BYTES` | 16 MiB | One line of a stream |
| `ERROR_BODY_MAX_BYTES` | 1 MiB | How much of an error's body is read |
| `SERVICE_FAILURE_CODES` | `server_error` | A failed response's codes that are retried |
| `TRANSCRIPT_HEADERS` | `retry-after`, `x-request-id` | Response headers the transcript keeps |
| `TRANSCRIPT_HEADER_PREFIXES` | `x-ratelimit-` | Response header prefixes the transcript keeps |
| `INSTRUCTIONS` | (text) | The runner's fixed instructions, before the character |

## Schemas

[`options.schema.json`](src/troupe_runner_openai/schemas/options.schema.json) and
[`errors.schema.json`](src/troupe_runner_openai/schemas/errors.schema.json). Each error code refuses `run/start`, so
no request is sent:

| Error | When |
|---|---|
| `openai.unknown-option` | an option the runner doesn't define, such as `endpoint` or `model` |
| `openai.invalid-options` | an option's value has the wrong shape |
| `openai.no-runtime` | `run/start` names no runtime, or one whose endpoint or model can't be used |
| `openai.insecure-endpoint` | a key, and plain `http` to another machine |
| `openai.credential-mismatch` | `run/start` and `TROUPE_RUNTIME_CREDENTIAL` disagree about whether there's a key |
| `openai.malformed-credential` | the key holds whitespace or a control character, such as a line ending from a file |

## Fixtures

[`fixtures/responses/`](fixtures/responses) holds, for each run, the service's replies, their provenance, and the
events they map to. Recorded: a two-turn tool loop on OpenAI and one on local Ollama, and a rejected credential from
OpenAI with a deliberately invalid key. Derived from those, or built from OpenAI's shapes: a broken stream, a rate
limit, a server error, an incomplete response, a refusal, a failed response and a response in the wrong shape.
[`tools/capture_openai.py`](tools/capture_openai.py) records new ones, and scrubs the key and the host's home.

## Tests

Tests drive the runner as a process against a fake endpoint, and every run sets low limits (`TEST_LIMITS`: 5 turns,
20,000 tokens): the test harness refuses one that doesn't. The live test runs a real service only when asked:

```console
TROUPE_LIVE_OPENAI=1 uv run pytest packages/troupe/tests/test_openai_live.py -s
TROUPE_LIVE_OPENAI=1 TROUPE_LIVE_OPENAI_ENDPOINT=http://127.0.0.1:11434/v1 TROUPE_LIVE_OPENAI_MODEL=qwen3.5:4b \
  uv run pytest packages/troupe/tests/test_openai_live.py -s
```

The first needs `OPENAI_API_KEY` and costs a few cents; the second runs on local Ollama, free.
