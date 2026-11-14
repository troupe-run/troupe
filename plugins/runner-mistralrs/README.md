# troupe-runner-mistralrs

troupe's in-process runner. It loads a GGUF model inside its own process with
[mistral.rs](https://github.com/EricLBuehler/mistral.rs)'s Python package, `mistralrs`, and drives it with troupe's
own tool loop, checking each tool call against the actor's declared effects (`effects: checked`). There's no server,
no network and no credential, and a run costs nothing.

The spec is `openspec/specs/mistralrs-runner/spec.md`, and the design is in the `in-process-runner` change (under
`openspec/changes/`, or `openspec/changes/archive/` once it's archived).

## Install

The runner comes as an extra of `troupe-run`: `troupe-run[mistralrs]`, or `troupe-run[all]`. `mistralrs` 0.9.5 is
MIT-licensed, has no Python dependencies, and ships one wheel per platform for Python 3.12 to 3.15: macOS on Apple
silicon (Metal), Linux on x86_64 and aarch64, and Windows on x86_64 (CPU). There's no wheel for Intel Macs, Windows
on Arm or musl Linux, so the extra doesn't install there.

**On macOS, install troupe on a uv-managed Python** (`uv tool install --managed-python ...`). mistral.rs compiles its
Metal kernels when it loads a model, and whether they compile depends on the macOS SDK the Python was built with.
python.org's 3.12 and Homebrew's Pythons on macOS 27 fail, and uv's own Pythons work. The runner checks before it
starts a run, and refuses an unsupported Python with `mistralrs.unsupported-python`.

## The model

The model is a GGUF file on your machine. The runner never downloads one, and never asks Hugging Face for anything.
Point the built-in in-process runtime at it, in your environment rather than the theatre's shared config, since the
path is your machine's:

```sh
export TROUPE_RUNTIME_MISTRALRS_MODEL=/Users/you/models/Qwen3-0.6B-Q8_0.gguf
```

An actor can name its own file with `model`. Use a model that can call tools, such as Qwen3. Qwen's own GGUF of
Qwen3-0.6B (`Qwen/Qwen3-0.6B-GGUF`, `Qwen3-0.6B-Q8_0.gguf`) is the one the fixtures were captured with.

The model runs inside the runner, so it takes the runner's memory: a model too large for the machine ends the runner,
and troupe reports a runner that exited without a result.

## Before the run starts

Before it acknowledges a run, the runner checks only what it can check quickly. Each check refuses the run if it
fails:
- the options;
- the runtime: the built-in `mistralrs`, with no endpoint and no credential;
- the model: an absolute path to a file that starts with the GGUF signature;
- the installed `mistralrs`: exactly the version in [requirements.json](src/troupe_runner_mistralrs/requirements.json),
  0.9.5;
- on macOS, that mistral.rs can compile its Metal kernels under this Python. It checks this by loading a 1.2 MB model
  the package carries ([provenance](src/troupe_runner_mistralrs/check_model/PROVENANCE.md), MIT).

The run's model loads after the acknowledgement, with a `log` event saying so. A model the engine won't load ends the
run with an error result, reason `configuration`. So does a load that passes `LOAD_TIMEOUT_SECONDS`.

## The context window

The window is `contextLength`, or 16384 lowered to the model's own length. The runner keeps to it on every OS:
- **Counting.** It counts the conversation with the model's tokenizer before each request.
- **Bounding.** It asks for at most the room left, less `TOKEN_MARGIN`.
- **Full window.** A conversation or answer that reaches the window ends the run with `context-length`. Told
  `compact`, it replaces old tool results with a stub instead, and says so with a `context` event.
- **Metal.** On macOS the window is also the engine's KV budget, which keeps a small Mac from running out of GPU
  memory. The CPU builds take no budget.

## Stopping

The engine's work can't be interrupted, so on `run/cancel`, end of input or `shutdown` the runner acknowledges, sends
nothing more, and ends its process within `STOP_GRACE_SECONDS`, abandoning whatever the engine was doing. The engine's
log lines go to standard error, never to the protocol channel.

## Options

| Option | |
|---|---|
| `maxTurns` | The requests one run may make, 1 to 1000. Default 50. |
| `contextLength` | The context window in tokens, 2048 to 1048576, at most the model's own length. |
| `temperature` | Sampling temperature, 0 to 2. Default: the model's own. |
| `seed` | Sampling seed, given to the engine when it loads the model. |
| `think` | Whether a thinking model thinks first. Its thinking is kept in the transcript only. |

## Limits

Each is a named setting in [defaults.py](src/troupe_runner_mistralrs/defaults.py).

| Setting | Default | |
|---|---|---|
| `MAX_TURNS` | 50 | Requests per run when `maxTurns` isn't set. |
| `MAX_TURNS_LIMIT` | 1000 | The largest `maxTurns`. |
| `DEFAULT_CONTEXT_LENGTH` | 16384 | The window when `contextLength` isn't set, lowered to the model's length. |
| `CONTEXT_LENGTH_MIN` | 2048 | The smallest `contextLength`: the tool definitions take about 1,400 tokens. |
| `CONTEXT_LENGTH_MAX` | 1048576 | The largest `contextLength`. |
| `TOKEN_MARGIN` | 256 | Tokens kept free below the window, for error in counting the chat template. |
| `TOOLS_OVERHEAD_TOKENS` | 128 | Tokens counted for the chat template's preamble around the tool definitions. |
| `MESSAGE_OVERHEAD_TOKENS` | 8 | Tokens counted for the chat template around each message. |
| `TOOL_OUTPUT_SHARE` | 0.25 | The share of the window one tool result may take. |
| `GLOB_PATH_BYTES` | 64 | Bytes one Glob path is taken to need. |
| `GREP_MATCH_BYTES` | 128 | Bytes one Grep match is taken to need. |
| `READ_NOTE_BYTES` | 128 | Bytes kept for the note after a capped Read. |
| `LOAD_TIMEOUT_SECONDS` | 600 | How long loading the model may take. |
| `STOP_GRACE_SECONDS` | 2 | How long the runner waits for its worker before exiting on a stop. |
| `SUMMARY_MAX_BYTES` | 4096 | Bytes one summary field of an event keeps. |

## Tests

The tests never download a model. They run the real engine with the check model the package carries (the protocol
channel, stopping), and replay [fixtures](fixtures) captured from Qwen3-0.6B by
[tools/capture_mistralrs.py](tools/capture_mistralrs.py) through an engine stand-in. The live tests run a real model
only when `TROUPE_LIVE_MISTRALRS` names one:

```sh
TROUPE_LIVE_MISTRALRS=/path/to/Qwen3-0.6B-Q8_0.gguf uv run pytest plugins/runner-mistralrs
```
