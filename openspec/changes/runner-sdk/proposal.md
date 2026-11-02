# Proposal: a minimal plugin SDK, with the runner contract's types and a model's tool calls

Issue: troupe-run/troupe#240. Decided in #239. Starts #58. Blocks #241, #56 and #162.

## Why

troupe's next runners, a local model (#56) and any OpenAI-style API (#162), get only the model's reply back, so the
runner itself has to carry out the model's tool calls in the workspace. #239 decided that both build on one small
SDK, rather than each writing that code, and that core uses the same SDK for the runner contract's types. Today
those types exist twice: core mirrors the schemas in `troupe.core.runners.protocol`, and the scripted runner (and,
for its constants, the Claude Code runner) carries its own copy. #241's effects and #56's runner both need this
first.

## What Changes

- **A new package, `troupe-plugin-sdk`** (`packages/troupe-plugin-sdk`, imported as `troupe_plugin_sdk`), named
  for #58's plugin SDK, which grows it later. It's framework-free: plain functions and frozen value objects,
  standard library only. It imports nothing of troupe's.
- **The runner contract's types move into it.** The strict message base (`Message`, `json_field`, `ProtocolError`)
  and every runner message type move from core into the SDK, still checked against `protocol/schemas/runner/` by
  tests. Core imports them from the SDK, so there is one definition. Core's client protocol keeps building on the
  same message base.
- **The scripted runner uses the SDK's types** instead of its own copy, and the Claude Code runner uses its
  contract constants (protocol versions, JSON-RPC error codes). Both still import nothing from troupe.
- **Running a model's tool calls.** The SDK takes a tool call, checks it against the actor's declared effects,
  carries it out in the workspace, and returns the result for the model, recording the call and the result as the
  contract's `tool_call` and `tool_result` events. The tools are `Read`, `Write`, `Edit`, `Glob` and `Grep` (named as
  Claude Code names them) and troupe's own `Delete` and `Move`. There's no shell. The SDK also gives each tool's
  definition (name, description, input schema), so every runner offers the same tools.
- **Declared effects, as a value object.** With nothing declared an actor is read-only. Writing, deleting and moving
  are each declared separately, as workspace-relative path patterns. #241 adds the form in actor config and passes
  it to the runner. This change defines what the check takes, not how an actor declares it.
- **Every path stays in the workspace.** A path that's absolute, climbs out with `..`, or resolves out through a
  link is refused, whatever the effects allow.
- **A refused, failing or malformed call is a `tool_result` with `isError` true** that says why, and, for a refusal,
  which effect it would need. It's never a silent no-op, and it never ends the run.
- **Plugins depend on the SDK, never on core.** The import check covers every plugin under `plugins/`, so a new
  plugin can't be left out of it.
- **Its own release and version.** The SDK is a release-please component with its own changelog and tag. Core and
  the plugins depend on it bare, as the adapters depend on `troupe`. `troupe-run` lists it, as it lists every package
  under `packages/`, so that installing a bundle tag with `--no-sources` resolves it from its pinned tag, never from
  an index (owner, 2026-11-02). The SDK has its own check scope.

Not in this change: the effects' form in config and passing it to the runner (#241); a runner that drives a model
(#56, #162); the JSON-RPC plumbing, a server loop and plugin docs (#58); moving the Claude Code runner's dict-based
event mapping onto typed events; any change to `protocol/`.

## Capabilities

### New Capabilities

- `plugin-sdk`: the SDK package: what it holds (the runner contract's types), what it may depend on, that core and
  plugins take the contract's types from it, that plugins never import core, and how it's released and installed.
- `runner-tools`: running a model's tool calls: the tools and their definitions, how each call is checked against
  declared effects and kept in the workspace, and how calls and results are reported to the model and as run
  events.

### Modified Capabilities

- `installation`: core may depend on the plugin SDK, and on no other workspace member.
- `quality-check`: the SDK gets its own check scope, `plugin_sdk`.
- `scripted-runner`: the scripted runner builds on the SDK, and still never imports troupe.

## Impact

- **New:** `packages/troupe-plugin-sdk/` (source, tests, `pyproject.toml`, README, changelog, licence).
- **Core:** `troupe.core.messages` and `troupe.core.runners.protocol` move to the SDK; every importer changes
  (`runners/host.py`, `conformance.py`, `outcome.py`, `runs/`, `client/`, `config/commands.py`); core's
  `pyproject.toml` depends on `troupe-plugin-sdk`. The schema-check tests for the runner types move with them.
- **Plugins:** `runner-scripted` and `runner-claude-code` depend on `troupe-plugin-sdk` and drop their copies.
- **Workspace:** the root `pyproject.toml` (workspace sources, dev group, ruff, mypy, pytest, import-linter roots and
  contracts), `release-please-config.json`, `.release-please-manifest.json`, `packages/troupe-run/pyproject.toml`,
  `scripts/bundle.py` (core may depend on the SDK), `scripts/check-paths.toml`, `uv.lock`.
- **Docs:** `plugins/README.md`, `contributing/runners.md`, and the new SDK README.
- **Infrastructure:** two new specs, so `oob/troupe-spec-purposes.json` in troupe-run/infrastructure gets their
  Purposes in a pull request merged alongside this one. No new capability label: they use `cap:plugins`,
  `cap:actor-runners` and `cap:protocol`.
- **Protocol:** unchanged. No schema changes, so no protocol release.
