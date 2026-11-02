# Design: a minimal plugin SDK

See [proposal.md](proposal.md) for why, and the specs for the behaviour: [plugin-sdk](specs/plugin-sdk/spec.md),
[runner-tools](specs/runner-tools/spec.md) and the deltas to installation, quality-check and scripted-runner.

## Context

- **Core's runner types** are `troupe.core.runners.protocol`, hand-mirrored from `protocol/schemas/runner/` and
  checked by `packages/troupe/tests/test_runner_protocol_types.py`. They build on `troupe.core.messages`
  (`Message`, `json_field`, `ProtocolError`, `fail`, `decode`), which imports only the standard library. The client
  protocol (`troupe.core.client.messages`) and config commands use the same base.
- **The scripted runner** keeps its own protocol versions and JSON-RPC codes, and builds every message as a dict.
  **The Claude Code runner** keeps the same constants, and maps Claude Code's stream onto event dicts, with its own
  summary cutting (`SUMMARY_MAX_BYTES`, `_fit`).
- **The import contract** `plugins import nothing from troupe` names each plugin by hand, so a new plugin is only
  checked if someone remembers to add it.
- **Installs:** adapters depend on `troupe` bare, and the bundle's tag pin is what an install with `--no-sources`
  resolves (installation spec). `scripts/bundle.py` fails when core depends on any workspace member.

## Goals / Non-Goals

**Goals:**
- One definition of the runner contract's types, in a package plugins can depend on.
- A tool-call API that #56 and #162 use as is: definitions to offer the model, one call in, events and the
  model's answer out.
- A path and effect check that's the same on Linux, macOS and Windows.

**Non-Goals:**
- Enforcement. The check stops a model acting outside its declaration through these tools. It doesn't contain the
  runner process, so lineage keeps recording the local stage's effects as `unenforced` (stages spec).
- Reading effects from config or passing them over `run/start` (#241).
- A model loop, a transcript writer, JSON-RPC framing or a server loop (#56, #162, #58).
- Moving the Claude Code runner's event mapping onto the SDK's types, or onto its summary cutting. It takes only the
  constants now. A follow-up can move the rest.

## Decisions

### D1. `packages/troupe-plugin-sdk`, a library, not a plugin

The package is `troupe-plugin-sdk`, imported as `troupe_plugin_sdk` (owner, 2026-11-02: #58 grows it, so it's named
for #58). It lives in `packages/` because it runs in process, inside core and inside each plugin. It isn't a JSON-RPC
plugin. Modules:

| Module | Holds |
|---|---|
| `messages` | The strict message base, moved from `troupe.core.messages` unchanged |
| `runner` | The runner contract's types, constants and error codes, moved from `troupe.core.runners.protocol` |
| `effects` | `Effects` and the path pattern matcher |
| `paths` | Turning a model's path into a checked workspace path (the one seam for path rules, D6) |
| `tools` | The seven tools, their definitions, and running a call |
| `events` | Numbering events and fitting summaries to the limits |
| `defaults` | Every limit's default, in one place |

*Alternatives:* `troupe-runner-sdk` (#240's title) would need a rename when stages and channels use it. A module
inside core breaks "plugins never import core".

### D2. Move the types, don't re-export them

`troupe.core.messages` and `troupe.core.runners.protocol` are deleted, and every importer imports from the SDK. The
client protocol's messages keep using the same base, now `troupe_plugin_sdk.messages`. ruff's
`extend-immutable-calls` entry follows `json_field` to its new home.

*Alternative:* leave a re-exporting module in core. Rejected: two import paths for one type, and nothing stops new
code using the core path.

### D3. Hand-mirrored types, checked against the schemas

The types stay hand-written, as now, until #58 chooses a generator. `test_runner_protocol_types.py` moves to the
SDK's tests and reads the schemas from `protocol/schemas/runner/` in the checkout. The SDK carries no copy of the
schemas, since it only needs them in tests. Core's `runner_schemas.py` helper stays for core's conformance tests.

### D4. The runners take the SDK's types

- **Scripted runner:** its constants go, and it answers the handshake, refusals and event steps with the SDK's
  types. An event step's body is parsed with the SDK's event type when the script is read. A `runId` or `seq` override
  is valid for the type (the options schema already refers to the contract's definitions), so a gap or another run's
  id still plays. Raw lines and recordings stay as they are: they're the way to send what the contract forbids.
- **Claude Code runner:** its protocol versions and JSON-RPC codes come from the SDK.
- Both depend on `troupe-plugin-sdk` bare. Their `pyproject.toml` comments change from "standard library only" to
  "the plugin SDK only".

### D5. The tool API returns what happened, and sends nothing

```python
tools = Tools(workspace, effects, limits=ToolLimits())
tools.definitions()   # each tool's name, description and input schema, for the model
tools.names()         # for the init event's `tools`
step = tools.run(call_id, name, arguments, numbering)
step.events           # (ToolCallEvent, ToolResultEvent), numbered and fitted
step.output           # the text to give the model
step.is_error
```

`arguments` is a mapping, or the text of one, because Chat Completions sends JSON text and Ollama sends an object.
`numbering` is the run's event counter (`EventNumbering(run_id, next_seq, event_max_bytes)`), which the runner uses
for its other events too, so `seq` never gaps. The runner sends the events and gives the model the output. The SDK
does no I/O except on the workspace.

An empty `call_id` is a `ValueError`, because it's the runner's mistake, not the model's. A runner whose engine
gives no ids makes them up. Everything the model can get wrong is an error result (runner-tools spec).

*Alternative:* the SDK sends events through a callback. Rejected: it would dictate how a runner writes, and a value
is easier to test.

### D6. One portable path rule, then resolve

`paths` does every check in this order, the same on every platform:

1. **Syntax.** Non-empty, relative, `/` between parts. Refused: `..`; `\`; `:` (drive letters and Windows
   alternate streams); control characters; Windows' reserved names (`CON`, `NUL`, `COM1` and the rest, with any
   extension); parts ending in a dot or space. `.` parts and repeated `/` are dropped. The same rules apply on
   every OS, so a model gets the same answer wherever the runner runs.
2. **`.git`.** A path whose first part is `.git` is refused.
3. **Resolve.** Join to the workspace and `resolve()`, which follows symlinks and Windows junctions. The result
   must be inside the resolved workspace. For a path that doesn't exist yet, the existing part of it resolves.
4. **The changed path.** The resolved path, made workspace-relative again, is what the effects and the `.git` rule
   are checked against (runner-tools spec: "Effects are checked on the path that would change").

Matching is case-sensitive everywhere. On a case-insensitive filesystem that refuses more, never less.

### D7. Effects are a value, and patterns have one language

`Effects(write=(), delete=(), move=())` holds patterns, parsed when it's made. A malformed pattern raises a
`ValueError` that names the list and the pattern (absolute, `..`, `\`, empty, `***`). The matcher is the SDK's own:
`*` matches within one part, `**` matches zero or more whole parts, `?` matches one character. `fnmatch` lets `*`
cross `/`, and `PurePath.full_match` needs Python 3.13. `Glob` uses the same matcher, so a model's pattern and an
actor's declaration mean the same thing.

`Move` needs `move` for both its source and its destination. #241 builds an `Effects` from actor config, and may
change its shape if config needs it, since the SDK is pre-1.0.

### D8. Writes never leave a file half written, and never translate newlines

- `Write`, `Edit` and `Move` create missing parent directories. `Write` and `Edit` write the new bytes to a temporary
  file beside the target and `os.replace` it into place. When the target already exists, its mode is copied to the
  temporary file, so an executable stays executable.
- Content is encoded as UTF-8 and written as bytes, so Windows never adds `\r`. `Read` and `Edit` decode bytes, so
  `\r\n` survives an edit untouched.
- `Edit` counts `old_string`'s occurrences first. Zero, or more than one without `replace_all`, is an error that
  gives the count. An `old_string` equal to `new_string` is an error too.
- `Move` refuses an existing destination (checked, then `os.rename`). `Delete` removes files only.

### D9. Searching doesn't follow links out, or into `.git`

`Glob` and `Grep` walk with `os.walk(followlinks=False)` from their checked start directory, skip the top-level
`.git`, and include a linked file only if it resolves inside the workspace. Results are sorted by path. `Grep` uses
Python's `re`. An invalid expression is an error result naming it. It skips files that aren't UTF-8 or are over the
size limit, and says how many it skipped. Its lines are `path:line:text`. `Read` returns `line<TAB>text`, like
Claude Code's.

### D10. Limits: defaults in one place, lowered only

`defaults` holds `READ_MAX_BYTES` (256 KiB), `READ_MAX_LINES` (2000), `FILE_MAX_BYTES` (16 MiB, the largest file
`Read` and `Edit` load whole), `GLOB_MAX_PATHS` (1000), `GREP_MAX_MATCHES` (500), `GREP_FILE_MAX_BYTES` (1 MiB) and
`SUMMARY_MAX_BYTES` (4096, the Claude Code runner's). Only regular files are loaded: a pipe or device is refused by
`Read` and `Edit` and skipped by `Grep`, so no call waits on one (added after review: `FILE_MAX_BYTES` and the
regular-file check). `ToolLimits` defaults to
them and refuses a value that's zero, negative, or above the default, naming it. A cut result ends with a line saying
what was left out and how to get it (`offset` for `Read`, a narrower `path` or `glob` for the others).

### D11. Event summaries

`inputSummary` is the input as compact JSON, or the arguments text when it didn't parse. `outputSummary` is the
output given to the model. Each is cut at a UTF-8 boundary to `SUMMARY_MAX_BYTES`, then further until the event's
encoded size fits `eventMaxBytes`, which is how the Claude Code runner fits them. `outputBytes` is the full output's
UTF-8 size.

### D12. Releasing and installing

- `release-please-config.json` gets the component `troupe-plugin-sdk`, with the `uv.lock` extra-file, as every
  package has. `.release-please-manifest.json` gets `0.0.0` (no tag yet), so the first release is the configured
  `0.1.0`.
- Core, both runners and `troupe-run` depend on it bare, with a workspace source. The pinning pull request moves
  the bundle's pin after the SDK's first release, as it does for every member.
- `scripts/bundle.py` lets core depend on the SDK and nothing else in the workspace. It also checks that when the
  bundle pins a component, every workspace member that component depends on and that has released (its manifest
  version is above 0.0.0) is pinned too (installation delta). Otherwise a tag install would look the SDK up on a
  package index, where someone else could register the name. An unreleased member is left out of the check, because
  the bundle can't pin it yet: main is in that state from this change until the SDK's first release is pinned
  (owner, 2026-11-02).
- **Until that pin, the bundle must not release.** A bundle released while it names the SDK bare would send a tag
  install to a package index. So this change's commits that touch `packages/troupe-run/` use a type that doesn't
  release (`build`). #262 covers refusing a release pull request that releases `troupe-run` while it
  names any member bare.

### D13. Import contracts and their coverage

- `troupe_plugin_sdk` joins `root_packages`.
- New forbidden contract: **the plugin SDK imports nothing of troupe's** (sources: the SDK; forbidden: `troupe`,
  every adapter and every plugin).
- The SDK joins the sources of "only troupe.platform imports OS-specific modules". It uses `os` and `pathlib`
  only.
- The plugins contract doesn't forbid the SDK. It now also forbids `troupe_run`, the one workspace package it had
  missed. A new independence contract, **plugins are independent of each other**, keeps one plugin from importing
  another, so "no workspace package except the SDK" holds for plugins too.
- `scripts/plugin_imports.py`, run as a test in `scripts/tests/workspace/`, finds each plugin's import package under
  `src/`, and fails when one is missing from `root_packages` or from either contract, when the plugins contract
  forbids the SDK or leaves out another workspace package, and when the SDK's `pyproject.toml` declares a dependency.

### D14. Check scope

`scripts/check-paths.toml` gets `plugin_sdk` for `packages/troupe-plugin-sdk/` except its `pyproject.toml`. Its
`tests` list is what `scripts/check_paths_reach.py` works out. Core reaches it, so that's nearly every suite. The
quality-check delta also lists `run` and `runner_claude_code`, which the file already declares and the spec had
left out.

## Risks / Trade-offs

- **A link swapped between the check and the write** → The workspace is the run's own worktree, and only the model
  acts in it, one call at a time through these tools, so nothing swaps a link mid-call. It's also why this isn't
  enforcement (non-goals). A stage that contains the process (#65) closes it.
- **A regular expression that backtracks for ever** → `re` can't be interrupted. The file size limit bounds each
  search, and the host's run timeout bounds the run. A `Grep` that hangs makes the runner time out and be killed, so
  it's never a silent wait.
- **Windows links in tests** → Creating a symlink needs a privilege the runner may lack. Tests use a directory
  junction on Windows (`_winapi.CreateJunction`, test-only), so the link-escape cases run on all three platforms
  rather than being skipped.
- **Moving the message base touches many core imports** → It's mechanical, and mypy and the import contracts
  catch any import that was missed. It's done in its own commit, before the tool code.
- **#241 may want a different `Effects`** → It's pre-1.0, and #241 is blocked by this change, so it changes the
  value in the same release if it needs to.

## Migration Plan

Nothing changes for users: no protocol change, no config change. One pull request lands the package, the move and
the tools. An infrastructure pull request adds the two new specs' Purposes to `oob/troupe-spec-purposes.json` and
merges alongside it. The first release pull request after the merge releases `troupe-plugin-sdk` at 0.1.0 with core
and both runners, and the pinning pull request then pins it in the bundle. To roll back, revert the pull request.
