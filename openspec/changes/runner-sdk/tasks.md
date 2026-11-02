# Tasks

## 1. The package, its release and its checks

- [x] 1.1 Create `packages/troupe-plugin-sdk/` (`pyproject.toml` with no dependencies, `src/troupe_plugin_sdk/__init__.py`,
  `py.typed`, `tests/`, README stub, `CHANGELOG.md`, `LICENSE`), and add it to the root `pyproject.toml`'s workspace
  sources, dev group, ruff `src`, mypy `files` and `mypy_path`, and pytest `testpaths`. Verify `uv sync --locked`
  succeeds after `uv lock` and `uv run python -c "import troupe_plugin_sdk"` works.
- [x] 1.2 Add the release component to `release-please-config.json` (with its `uv.lock` extra-file) and `0.0.0` to
  `.release-please-manifest.json`, and add `troupe-plugin-sdk` bare to `packages/troupe-run/pyproject.toml`. Verify
  `scripts/tests/workspace/test_release_config.py` and `test_bundle.py` pass (D12).
- [x] 1.3 Add the `plugin_sdk` scope to `scripts/check-paths.toml`, with the `tests` list `uv run
  scripts/check_paths_reach.py` reports. Verify `scripts/tests/test_check_paths_reach.py` passes, and that `scripts/guard.py
  check-scope` on a path under the SDK's `src/` names `plugin_sdk` (quality-check delta, D14).
- [x] 1.4 Add `troupe_plugin_sdk` to import-linter's `root_packages`, the contract "the plugin SDK imports nothing of
  troupe's", and the SDK to the OS-specific modules contract's sources. Verify `uv run lint-imports` passes, and fails
  on a temporary `import troupe.core` in the SDK (plugin-sdk spec, D13).
- [x] 1.5 Write the workspace test that every package under `plugins/` is in the plugins contract's sources and in
  `root_packages`, and that the SDK declares no dependencies. Verify it passes, and fails naming the plugin when one
  is removed from the contract and naming the dependency when one is added (plugin-sdk spec, D13).

## 2. The runner contract's types move into the SDK

- [x] 2.1 Move `troupe/core/messages.py` to `troupe_plugin_sdk/messages.py` unchanged, update every importer in core
  (client messages and dispatch, config commands, runs), and move ruff's `extend-immutable-calls` entry. Verify
  `uv run scripts/check.py` passes: ruff, mypy, the import contracts and the full suite.
- [x] 2.2 Move `troupe/core/runners/protocol.py` to `troupe_plugin_sdk/runner.py`, and update core's importers (host,
  conformance, outcome, perform, client messages, tests). Verify the full check passes and `grep -r
  "core.runners.protocol\|core.messages" packages plugins scripts` finds nothing.
- [x] 2.3 Move `test_runner_protocol_types.py` into the SDK's tests, reading the schemas from `protocol/schemas/runner/`,
  and add tests that a field added to the `tool_result` schema and not the type fails, naming both, and that an
  unknown field fails to parse. Verify they pass, and that the drift test fails on a temporary schema edit (plugin-sdk
  spec: "checked against the contract's schemas").
- [x] 2.4 Allow core's dependency on the SDK in `scripts/bundle.py`, and add the check that a pinned component's
  released workspace dependencies are pinned too. Add `troupe-plugin-sdk` to core's dependencies. Verify the new
  `test_bundle.py` cases pass: core on the SDK passes, core on an adapter still fails, a pinned `troupe` with a
  released SDK bare fails naming both and the file, and with an unreleased SDK bare passes (installation delta, D12;
  owner, 2026-11-02, with #262 for the release-time check).
- [x] 2.5 Move the scripted runner onto the SDK: depend on it, drop its protocol versions and JSON-RPC codes, answer
  the handshake and refusals with the SDK's types, and parse event steps with the SDK's event types. Verify the
  scripted runner's suite, core's conformance suite and the seq-gap and raw-line steps' tests pass (scripted-runner
  delta, D4).
- [x] 2.6 Move the Claude Code runner's protocol versions and JSON-RPC codes onto the SDK and depend on it. Verify its
  suite passes and `grep -n "\-32\|PROTOCOL_VERSIONS =" plugins/*/src` finds no copy (plugin-sdk spec: "one
  definition").
- [x] 2.7 Update `plugins/README.md` (plugins import the SDK, never troupe), `contributing/runners.md` (where the
  contract's types are) and the two runners' `pyproject.toml` comments. Verify the docs tests pass
  (`uv run scripts/check.py --scope docs`).

## 3. Paths and effects

- [ ] 3.1 Write `paths`: the syntax rules, the `.git` rule and resolving inside the workspace (D6). Test each refused
  form (absolute, `..`, `\`, `:`, control characters, reserved names, a trailing dot or space, empty), `.` and `//`
  being dropped, and a property test that no generated path that's accepted resolves outside the workspace. Verify
  they pass (runner-tools: "Paths are workspace-relative").
- [ ] 3.2 Test links: a symlink, or a junction on Windows, leading out of the workspace is refused for every tool. A
  link inside the workspace is checked by the path it leads to. Verify they pass on all three platforms in CI, not
  skipped (runner-tools: links, "checked on the path that would change").
- [ ] 3.3 Write `effects`: `Effects` and the pattern matcher (D7). Test `*`, `**` and `?` against the spec's examples,
  each malformed pattern being refused with its list named, and a property test comparing the matcher with a regex
  translation of the same pattern. Verify they pass (runner-tools: "Effects are declared as path patterns").

## 4. The tools

- [ ] 4.1 Write `defaults` and `ToolLimits` (D10), and the tool definitions with closed input schemas (D5). Test that
  there are exactly the seven tools, that each schema is closed and validates the spec's example inputs, and that a
  limit above its default or at zero is refused. Verify they pass (runner-tools: "The tools are file tools",
  "Each tool's input").
- [ ] 4.2 Write `events`: `EventNumbering` and fitting summaries to `SUMMARY_MAX_BYTES` and `eventMaxBytes` at a UTF-8
  boundary (D11). Test that seq continues the runner's numbering and that a 200 KB output's event fits 65536 bytes with
  the full `outputBytes`, with a property test over multi-byte text. Verify they pass and each event validates against
  `run-event.schema.json` (runner-tools: "Run events fit the run's limits").
- [ ] 4.3 Write `Tools.run`'s handling of the call itself: arguments as a mapping or JSON text, unknown tools, input that
  breaks the schema, and an empty call id being a `ValueError`. Test each malformed case gives an error result naming
  the problem and the field, and a `tool_call` and `tool_result` pair. Verify they pass (runner-tools: "A malformed call
  is an error result").
- [ ] 4.4 Write `Read`, `Glob` and `Grep` (D9). Test the spec's scenarios: offset and limit, numbered lines, a binary
  file, a missing file, sorted globs, `path:line:text` matches, an invalid expression, skipped non-UTF-8 and oversized
  files, `.git` left out, and each cut result saying how to get the rest. Verify they pass (runner-tools: "Reading and
  searching", "Results are capped").
- [ ] 4.5 Write `Write` and `Edit` (D8). Test a new file in a new directory, exact bytes with `\n` and `\r\n` on every
  platform, an executable's mode kept, no match, two matches without `replace_all`, `replace_all`, and identical
  strings. Verify they pass (runner-tools: "Writing and editing").
- [ ] 4.6 Write `Delete` and `Move` (D8). Test deleting a file, a directory, a missing file, moving into a new directory,
  and onto an existing file. Verify they pass (runner-tools: "Deleting and moving").
- [ ] 4.7 Check every call against the effects before it runs. Test, against a fake model that issues calls: read-only with
  nothing declared; writing, editing, deleting and moving each allowed where declared and refused where not; `write`
  allowing neither delete nor move; a move whose destination isn't declared; each refusal naming the tool, the path and
  the effect, with the workspace unchanged and the next call still running. Verify they pass (runner-tools: effects
  requirements; #240's "done when").
- [ ] 4.8 Write the SDK's README: what it's for, the contract's types, the tools and their inputs, effects, limits and an
  example of a runner's tool loop. Add a docs test that the README's tools table matches the definitions. Verify it
  passes.

## 5. Integration

- [ ] 5.1 Run `uv run scripts/check.py` and show it passing, then confirm the matrix (Linux, macOS, Windows, every
  supported Python) passes on the pull request once it's ready.
- [ ] 5.2 Open the troupe-run/infrastructure pull request adding `plugin-sdk`'s and `runner-tools`' Purposes to
  `oob/troupe-spec-purposes.json` (its `oob/README.md` says how), on the roadmap board, and link it from this change's
  pull request. Verify its drift check passes against this branch.

## Workflow follow-up

- Open a draft pull request that closes #240, act on Claude's review of the last push, then mark it ready.
- Archive the change on the branch before merging; the owner merges, alongside the infrastructure pull request.
- After the merge, comment on #240 with the pull request and the archived change, and check its card says Done.
