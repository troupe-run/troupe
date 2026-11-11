# troupe-runner-lm-studio

An actor runner for troupe that drives a model in [LM Studio](https://lmstudio.ai) through LM Studio's own client
library, [`lmstudio`](https://pypi.org/project/lmstudio/) (#291). The library runs the model's rounds and asks for each
tool call. The runner carries each one out with the [plugin SDK](../../packages/troupe-plugin-sdk/README.md)'s seven
file tools, checked against the actor's declared effects, so its `init` says `effects: checked`.

It speaks the [runner contract](../../contributing/runners.md) over standard input and output, imports nothing of
troupe's but the SDK, and reaches LM Studio only through `lmstudio` 1.5.0, from one module, `engine.py`. It comes as
troupe-run's `lm-studio` extra, so only an install that asks for it carries the library:

```sh
uv tool install --no-sources "troupe-run[lm-studio] @ git+https://github.com/troupe-run/troupe@<tag>#subdirectory=packages/troupe-run"
```

```yaml
# .troupe/actors/lead.yaml
runner: lm-studio
runtime: lm-studio
model: google/gemma-4-e4b
options:
  maxTurns: 10
  maxTotalTokens: 100000
effects:
  write: ["**"]
expect: []
```

## Before you start

- **LM Studio's server is running** on the machine the runtime names: `lms server start`. The built-in `lm-studio`
  runtime is `http://127.0.0.1:1234`, LM Studio's default. A runtime of your own can name another host: the traffic is
  plain `ws://`, which the library can't encrypt, so keep it to a network you trust.
- **"Require Authentication" is off** in LM Studio's server settings. `lmstudio` 1.5.0 has no way to send an LM Studio
  API token, so a runtime with a credential is refused (`lm-studio.credential-unsupported`) rather than run without
  its token.
- **The model is downloaded** (`lms get <model>`) and LM Studio marks it as trained for tool use. The run loads it if
  it isn't loaded, with the run's context length. A model already loaded keeps its own, and the run says so in a
  `log` event.
- The runtime's endpoint is LM Studio's server root, with no path. A runtime at `/v1` is LM Studio's
  OpenAI-compatible API, for the OpenAI runner ([runtimes](../../docs/stagecraft/runtimes.md)).

## Options

Each is optional. Any option the runner doesn't define is refused (`lm-studio.unknown-option`), and a value of the
wrong shape too (`lm-studio.invalid-options`), naming the option. The endpoint and the model come from the actor's
runtime.

| Option | What it sets |
|---|---|
| `maxTurns` | The most prediction rounds a run makes, each offered the tools. A run whose last round still asks for a tool ends `turn-limit` once that round's calls are carried out; one that answers on its last round ends `ok`. |
| `maxTotalTokens` | The most prompt plus predicted tokens a run may use, as LM Studio reports them each round. Checked once a round's tool calls have finished, so a run can pass it by one round; one that would go on ends `budget`. |
| `contextLength` | The context length the model is loaded with, when the run loads it. |
| `temperature` | The model's sampling temperature, from 0 to 1. Absent: the model's own default. |

## Limits

Every limit is a named setting in [`defaults.py`](src/troupe_runner_lm_studio/defaults.py), and every timeout the
library applies is set from one of them, never left to the library's default.

| Setting | What it is |
|---|---|
| `DEFAULT_MAX_TURNS` | `maxTurns` when the options don't set it: 20. |
| `DEFAULT_MAX_TOTAL_TOKENS` | `maxTotalTokens` when the options don't set it: 200,000. |
| `DEFAULT_CONTEXT_LENGTH` | `contextLength` when the options don't set it: 16,384. |
| `CHECK_TIMEOUT_SECONDS` | Each step of the pre-run check, before `run/start` is answered: LM Studio's greeting, and listing its models. |
| `MESSAGE_TIMEOUT_SECONDS` | Waiting for LM Studio's next message. Load and prompt-processing progress and each fragment count, so only real silence reaches it. |
| `WEBSOCKET_CLOSE_TIMEOUT_SECONDS` | Closing the websocket, so a stop isn't held up by the library's own 10 seconds. |
| `MAX_ATTEMPTS` | Attempts at a connection that fails or drops, while no tool call has run. |
| `RETRY_BASE_DELAY_SECONDS` | The first retry's delay, doubled each time after. |
| `RETRY_MAX_DELAY_SECONDS` | The longest delay before a retry. |
| `SUMMARY_MAX_BYTES` | The bytes one summary field of an event keeps, before `eventMaxBytes` cuts it further. |
| `STOP_GRACE_SECONDS` | How long the run has to stop after a cancel before the runner exits anyway: below troupe's own grace. |
| `INSTRUCTIONS` | The system prompt's fixed part, before the actor's character. |

## How a run goes

1. **Before `run/start` is answered:** the runtime, the options, the workspace, and LM Studio itself. It answers its
   greeting at the runtime's host and port (a redirect isn't followed), its library lists the downloaded models, and
   the run's model is among them, trained for tool use. The library is always given the host and port, so it never
   looks for LM Studio on ports of its own.
2. **After it, a worker** sends `init`, loads the model (reporting a load that starts as `log` events), and runs the
   library's tool loop, `act()`, over at most `maxTurns` rounds.
3. **Each round's answer text** is a `turn`: what streamed before the round's first tool call, when that call starts,
   and the rest when the round ends. Text the library marks as reasoning is never a turn, though LM Studio puts it in
   a round's content too.
4. **Each tool call** is carried out by the SDK and reported as a `tool_call` and `tool_result` pair. A call the
   library rejects (an unknown tool, or arguments that don't fit) is answered with the SDK's own error for that input.
   One thing the runner can't keep: the library drops an argument name a tool doesn't define, without error, so troupe
   never sees it. The call is still checked against the effects.
5. **A round with no tool call** ends the run `ok` with its text, unless the prediction stopped short: the context
   length (`context-length`), the predicted-token limit (`output-limit`), the model unloaded or the prediction failed
   (`engine`), or a stop reason the runner or its library doesn't know (`other`).
6. **A connection that fails or drops** is retried, with a `retry` event, only while no tool call has run: after one
   has, starting again could run a tool twice, so the run ends `network` saying so. A message that doesn't arrive in
   time ends it `network` too.
7. **Cancel, end of input or shutdown** close the library's client, which ends the prediction at once. No call the
   library asks for after that is carried out, and no result is sent.

The result's usage is each round's prompt tokens summed as `inputTokens` and predicted tokens as `outputTokens`, and
its `turns` the rounds made. LM Studio reports no cost and no cache counters. When the theatre prices the model,
the result carries `estimatedCostUsd` at that price, unless the price has a cache rate. When LM Studio names a model
other than the run's, the run reports it once as `served_model`.

## The transcript

The transcript holds the exchange as the library exposes it, serialised, with troupe's record kinds: the model's
downloaded info (`received`), the chat and tools the run passes the library (`sent`), each round's result with its
stats (`received`), and each tool result message (`sent`). That leaves out what's on the wire: the websocket frames
(the handshake, channel framing and ids), the fragments as they streamed (a round's result has the whole text), the
prompt as LM Studio rendered it through the model's template, and any message the library reads and drops. The
library's own logging stays off standard output, and only its warnings reach standard error.

LM Studio's own logs are outside troupe, and may hold what the run sent.

## Schemas

[`options.schema.json`](src/troupe_runner_lm_studio/schemas/options.schema.json) is the options above, and
[`errors.schema.json`](src/troupe_runner_lm_studio/schemas/errors.schema.json) the runner's own error codes. Each
refuses `run/start`, so no run is acknowledged:

| Code | When |
|---|---|
| `lm-studio.unknown-option` | An option the runner doesn't define, such as `endpoint` or `model`. |
| `lm-studio.invalid-options` | An option's value has the wrong shape. |
| `lm-studio.no-runtime` | No runtime, or one with no model. |
| `lm-studio.unsupported-endpoint` | An `https` endpoint, which the library can't reach, or one with a path, user info, a query or a fragment. |
| `lm-studio.credential-unsupported` | The runtime has a credential, which the library can't send. |
| `lm-studio.credential-mismatch` | `TROUPE_RUNTIME_CREDENTIAL` is set, but `run/start` says the run has no credential. |
| `lm-studio.unreachable` | Nothing answered as LM Studio at the endpoint, or it answered with a redirect. |
| `lm-studio.incompatible` | LM Studio answered, but its library couldn't list the models. The fix names the LM Studio version tested. |
| `lm-studio.model-not-found` | No downloaded model has the run's model as its key. The fix names its `lms get`. |
| `lm-studio.model-without-tools` | The model isn't an LLM, or isn't trained for tool use. |

[`requirements.json`](src/troupe_runner_lm_studio/requirements.json) names the LM Studio version tested, 0.4.28.
LM Studio reports no version the runner could check, so that's the version a failed pre-run check names.

## Gaps

Filed rather than worked around (lmstudio-runner design D13):

- `lmstudio` can't send an LM Studio API token, so LM Studio with authentication on can't be used.
- `lmstudio` drops a tool argument a tool doesn't define without error, where troupe's own tools refuse it.
- The contract's `retry` event can't say that a run wasn't retried because a retry could run a tool twice.

## Fixtures and tests

[`fixtures/`](fixtures) holds runs recorded from LM Studio 0.4.28 by
[`tools/capture_lm_studio.py`](tools/capture_lm_studio.py), a recording proxy between the library and LM Studio that
scrubs the library's client passkeys and the capturing host's paths. Each pairs the websocket exchange with the events
the runner maps it to. The tests drive the runner as a process against a fake LM Studio,
[`tests/fake_lm_studio.py`](tests/fake_lm_studio.py), which replays those recordings, or rounds built from their
shapes, rewriting the ids the library picks. The live test runs a real LM Studio only when asked:

```console
TROUPE_LIVE_LM_STUDIO=1 uv run pytest packages/troupe/tests/test_lm_studio_live.py -s
```
