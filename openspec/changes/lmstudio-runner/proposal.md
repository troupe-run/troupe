# Proposal: the LM Studio runner

Issue: [troupe#291](https://github.com/troupe-run/troupe/issues/291), the rest of
[troupe#56](https://github.com/troupe-run/troupe/issues/56). Built on
[troupe#278](https://github.com/troupe-run/troupe/issues/278) (runtimes), decided by
[troupe#319](https://github.com/troupe-run/troupe/issues/319) (runners may depend on maintained client libraries), and
installed through [troupe#333](https://github.com/troupe-run/troupe/issues/333) (library-backed runners are optional
extras of `troupe-run`).

## Why

#56 asked for Ollama and LM Studio, each through its own API, because "each engine's own API, with its own quirks, is
a harder test than one shared standard" of whether the runner contract is shaped around Claude Code. #277 did Ollama.
LM Studio was never started.

This change first planned LM Studio's REST API, `POST /api/v1/chat`. That API takes no custom tools, only MCP servers,
and #302's probe (LM Studio 0.4.28, 2026-11-07) found that LM Studio refuses any MCP server on this machine, so troupe
couldn't serve its tools to it. Decision #319 (owner, 2026-11-07) then let runners depend on maintained client
libraries. **LM Studio's own Python package, `lmstudio`** (MIT, 1.5.0), talks to LM Studio over its SDK's websocket
API and runs the tool loop on the client's side (`act()`): the model asks, and the library calls a Python function.
So troupe's `Tools` carry out and check every call, as they do in the Ollama and OpenAI runners, with no MCP server.

## What Changes

- **A new runner plugin, `lm-studio`** (`plugins/runner-lm-studio`), that drives a model in LM Studio through the
  `lmstudio` package, pinned. It's its own plugin, not an adapter beside Ollama's: the two share no API, and #332 moves
  Ollama onto its own library.
- **troupe's own tool calls.** Each tool LM Studio's model is offered is the plugin SDK's, described to the library
  from the SDK's definitions. Each call the library makes is carried out by the SDK and checked against the actor's
  declared effects (`init` says `checked`). A call the library rejects before it reaches troupe is still answered and
  reported as a paired error result.
- **It uses runtimes from the start.** An actor names a runtime (the runner table says `required`). The runtime's
  endpoint becomes the library's host and port, and its model the model the run uses. The options hold no endpoint
  or model.
- **BREAKING: the built-in `lm-studio` runtime moves to LM Studio's server root,** `http://127.0.0.1:1234`, instead of
  `http://127.0.0.1:1234/v1`, the base of LM Studio's OpenAI-compatible API (owner, 2026-11-07: don't keep a built-in
  nobody needs). The OpenAI runner on LM Studio uses a runtime the person defines at `/v1`. troupe is pre-release, and
  no audition or doc uses the old value.
- **No LM Studio API token, for now.** `lmstudio` 1.5.0 has no way to send one. A runtime with a credential is refused
  before anything is sent, with a fix that says why, rather than sent without its token. An `https` endpoint is
  refused too: the library speaks only plain `ws://`.
- **Every run is capped,** as the OpenAI runner's are: a turn limit (the library's prediction rounds) and a token
  budget (the stats each round reports), plus the context length the model is loaded with and temperature. Each
  default is named in one place in the runner.
- **troupe's guarantees, kept by the runner, not the library** (#319, point 2): retries follow troupe's named limits
  (the library makes none of its own, and a retry never runs a tool twice), redirects are never followed, the library
  never guesses LM Studio's port, cancel and end of input stop the run within troupe's grace, and the library's
  dependencies are pinned, Apache-compatible, and install on Linux, macOS and Windows for every Python troupe supports.
- **The transcript keeps what the library exposes:** the chat and tools sent, each round's result with its stats, and
  each tool request and result message, serialised, in #294's record kinds once that lands. The design says what that
  loses compared with wire bytes.
- **An audition:** `troupe init --audition --runner lm-studio` defines an actor on the `lm-studio` runtime with a small
  tool-capable model, named in one place in core.
- **Tests:** a live probe of LM Studio through the library first, recorded as fixtures; deterministic tests against a
  fake LM Studio endpoint that replays recorded websocket exchanges; the conformance suite; and an opt-in live test.
- **troupe ships it as an optional extra** (#333): the runner is in `troupe-run[lm-studio]` and `troupe-run[all]`, not
  the base install, and an actor on it without the extra installed is refused, naming the extra.
- **The contract and library gaps it finds are filed, one issue each, not worked around** (#239, #291). The candidates
  so far are in the design (D13).

Out: LM Studio's REST API and its OpenAI-compatible and Anthropic-compatible endpoints (the last is #162's runner on a
runtime of the person's own), sending an LM Studio API token (until the library can), shipping, downloading or
managing models beyond loading the run's model, starting LM Studio's server, and how extras work in general (#333).

## Capabilities

### New Capabilities

- `lm-studio-runner`: the LM Studio runner plugin, covering its library and its pins, runtime, options and limits, its
  pre-run check and model loading, troupe's tools offered through the library, how the library's rounds and messages
  map to run events, failures and retries, the transcript, cancel, schemas, fixtures and live test.

### Modified Capabilities

- `runtimes`: the built-in `lm-studio` runtime's endpoint becomes LM Studio's server root, `http://127.0.0.1:1234`.
- `cli`: `troupe init --audition --runner` knows `lm-studio`, and the unknown-runner error names it.
- `config`: the LM Studio audition's actor.
- `quality-check`: a check scope, `runner_lm_studio`, for `plugins/runner-lm-studio/`.

## Impact

- **New:** `plugins/runner-lm-studio/` (source, schemas, published requirements, fixtures, capture tool, tests,
  README), and the `lm-studio-runner` spec. Its Purpose is recorded in troupe-run/infrastructure's
  `oob/troupe-spec-purposes.json` in a pull request that merges first.
- **Dependencies:** `lmstudio` 1.5.0 and what it pulls in (httpx, httpx-ws, msgspec, anyio, typing-extensions), pinned
  in `uv.lock`, carried only by the `lm-studio` extra.
- **Core:** `defaults.RUNTIMES["lm-studio"]`, the runner table in `core/interim.py` (`runtime="required"`, no
  environment, and the extra it's installed by), the audition in `core/audition.py`, and their tests.
- **Workspace:** `pyproject.toml`, the import-linter contracts, `scripts/check.py`'s scopes, `release-please-config.json`
  and its manifest, the `troupe-run` extras (#333's mechanism), and `uv.lock`.
- **Docs:** `docs/stagecraft/runtimes.md` (the built-in's endpoint, and the OpenAI runner on LM Studio),
  `docs/stagecraft/bring-your-own-agent.md`, `plugins/README.md` and `contributing/runners.md` where they list runners.
- **Depends on:** #333 for the extra and the error that names it. The runner itself can be built before #333 lands.
- **People:** a run needs LM Studio running with its server on, with "Require Authentication" off, and the extra
  installed.
