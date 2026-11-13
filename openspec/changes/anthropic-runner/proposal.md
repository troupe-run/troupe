# Proposal: the Anthropic Messages API runner

Issue: [troupe#415](https://github.com/troupe-run/troupe/issues/415), decided in
[troupe#412](https://github.com/troupe-run/troupe/issues/412). Built on
[troupe#278](https://github.com/troupe-run/troupe/issues/278) (runtimes),
[troupe#319](https://github.com/troupe-run/troupe/issues/319) (runners may depend on maintained client libraries, kept
to troupe's guarantees by the runner) and [troupe#333](https://github.com/troupe-run/troupe/issues/333) (installed as
optional extras), and held to [troupe#279](https://github.com/troupe-run/troupe/issues/279) and
[troupe#394](https://github.com/troupe-run/troupe/issues/394) (a full context ends the run with `context-length`, never
silently).

## Why

Decision #412 removes the LM Studio runner and, in its place, proves troupe's runner port against two runtimes of a
different structure. This change is one of them: the **Anthropic Messages API**, a third API shape beside OpenAI's
Responses API and Ollama's native API (content blocks, `tool_use` and `tool_result`), served both by local engines
(llama.cpp, LM Studio 0.4.1+, LocalAI, Ollama) and by Claude's own API. So one runner is proved against a local engine
and a hosted one. Claude Code reaches Claude through its CLI, not this API, so it doesn't duplicate that runner.

The probe this proposal rests on (design D12, 2026-11-14) found that both local engines on this machine serve the API
with working tool calls, and that **both drop content silently when the conversation outgrows their context**: LM
Studio 0.4 keeps the system prompt and cuts the middle, Ollama 0.40 keeps a fraction of the prompt, and each answers
`200` as if nothing happened. Nothing in the Messages API lets a client turn that off. So the runner can't leave
#279's rule to the engine: it has to notice the loss itself.

## What Changes

- **A new runner plugin, `anthropic`** (`plugins/runner-anthropic`), that drives a model over the Anthropic Messages
  API through the `anthropic` package, pinned, with troupe's own tool loop: each tool the model is offered is the
  plugin SDK's, and each call is carried out by the SDK and checked against the actor's declared effects (`init` says
  `checked`). Requests are streamed. Its `init` names the engine `messages`.
- **It uses runtimes from the start.** An actor names a runtime (the runner table says `required`). The runtime's
  endpoint is the API's base URL (the library adds `/v1/messages`), its model the model asked for, and its credential,
  when it has one, the only credential sent. The options hold no endpoint, model or credential.
- **A new built-in runtime, `anthropic`**: endpoint `https://api.anthropic.com`, credential from `ANTHROPIC_API_KEY`,
  no model, no price. A local engine is a runtime the person defines (for LM Studio, its server root); the docs show
  how.
- **Every run is capped**, as the OpenAI runner's are: a turn limit, a token budget, and the output limit each request
  asks for (the API requires one), each default named in one place. An optional `contextWindow` option names the
  engine's window when the person knows it.
- **A full context never passes silently.** A context-length refusal (Claude's API) ends the run with
  `context-length`; so does a reply the runner can tell was made from less than the conversation it sent: a request
  whose reported input is smaller than the previous one's (the conversation only grows), or one that reaches the
  `contextWindow` the person named. A reply made from a cut conversation is never acted on. A run told `compact`
  compacts its own conversation and asks again, as the OpenAI runner does, reporting it with a `context` event.
- **troupe's guarantees, kept by the runner, not the library** (#319): the library's retries are off and troupe's loop
  retries within its named limits, honouring `Retry-After`; redirects are never followed (the library follows them by
  default, so the runner gives it a client that doesn't); the credential goes only in its header, is never logged, and
  the library never finds one of its own (it otherwise reads `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` and profiles
  on disk); cancel and end of input abandon the request in flight within troupe's grace; every timeout the library
  applies is one of the runner's named settings; and the library's dependencies are pinned, Apache-compatible, and
  install on Linux, macOS and Windows for every Python troupe supports.
- **The transcript keeps what the library exposes:** each request as passed to the library (`sent`), and each stream
  event and error body as the library gives them (`received`), in #294's record kinds. The design says what that
  loses compared with wire bytes.
- **An audition:** `troupe init --audition --runner anthropic` defines an actor on the `anthropic` runtime with
  Claude's cheapest current model, named in one place in core.
- **Tests:** deterministic tests against a fake Messages endpoint that replays recorded exchanges, fixtures recorded
  from LM Studio and, by the owner, from Claude's API, the conformance suite, and opt-in live tests for each
  (`TROUPE_LIVE_ANTHROPIC`, `TROUPE_LIVE_ANTHROPIC_LOCAL`).
- **troupe ships it as an optional extra,** `troupe-run[anthropic]`, and in `troupe-run[all]`, never the base install.
- **The contract and library gaps it finds are filed, one issue each, not worked around** (design D13).

Out: Claude's server-side features (server tools, the tool runner helper, server-side compaction, message threads,
batches, prompt caching controls, fallbacks), extended-thinking settings beyond the model's default, the Bedrock,
Vertex and Foundry clients, removing the LM Studio runner (#413), and choosing which built-in runtime LM Studio users
get once #413 lands (raised with the owner, design D3).

## Capabilities

### New Capabilities

- `anthropic-runner`: the Anthropic Messages API runner plugin: its library and pins, runtime and credential, options
  and limits, troupe's tools over the API, how replies map to run events, failures, retries and their reasons, the
  context guard and compaction, the transcript, cancel, schemas, fixtures and live tests.

### Modified Capabilities

- `runtimes`: a new built-in runtime, `anthropic`.
- `cli`: `troupe init --audition --runner` knows `anthropic`, and the unknown-runner error names it.
- `config`: the Anthropic audition's actor.
- `quality-check`: a check scope, `runner_anthropic`, for `plugins/runner-anthropic/`.

## Impact

- New: `plugins/runner-anthropic/` (package, schemas, fixtures, capture tool, tests).
- Core: `core/defaults.py` (the built-in runtime), `core/interim.py` (the runner table entry: runtime required, in an
  extra, its fit), `core/audition.py` and `cli/init.py` (the audition), and the tests that list runners and runtimes.
- Workspace: root `pyproject.toml` (member, dev group, lint, type and import contracts, including a seam contract that
  one module alone imports `anthropic`), `uv.lock` (`anthropic` and what it pulls in: `httpx2`, `pydantic`, `anyio`,
  `jiter`, `opentelemetry-api` and others), `packages/troupe-run/pyproject.toml` (the extra), `scripts/check.py` and
  `scripts/check-paths.toml` (the scope), `scripts/licences.toml`, release-please's config and manifest.
- Docs: the plugin's README, `plugins/README.md`, `contributing/runners.md`, `docs/stagecraft/runtimes.md`,
  `docs/stagecraft/bring-your-own-agent.md`, `docs/opening-night/install.md` (the extra's row) and the changelog page.
- troupe-run/infrastructure: the new spec's Purpose in `oob/troupe-spec-purposes.json`, merged right after this change.
