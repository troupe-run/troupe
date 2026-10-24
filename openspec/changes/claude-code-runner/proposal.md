# Proposal

## Why

troupe was designed around Claude Code, but `troupe perform` can only run the scripted runner, which plays a script
instead of running an agent. #55 adds the Claude Code runner. The runner contract and its "Mapping an engine: Claude
Code" table already say how it behaves, and the scripted runner's fixtures pin that behaviour. Decision #16 (option D)
puts it next, after the scripted runner and before a local model (#56).

## What Changes

- **A new plugin, `plugins/runner-claude-code/`** (package `troupe-runner-claude-code`, runner name `claude-code`). It
  speaks the runner contract, uses only the standard library and imports nothing from troupe, as the scripted runner
  does. It runs `claude -p` with stream-json output in the run's workspace, and:
  - passes the direction on standard input, never on the command line;
  - appends the character to Claude Code's system prompt from a file;
  - sends every native line as a `run/transcript` record, unchanged;
  - maps each record onto run events, as the contract's table says.
- **The failure shapes spike B found are mapped as the contract says:**
  - `is_error` under a `"success"` subtype is an `error` result;
  - `system/api_retry` with `authentication_failed` is a `retry` with reason `authentication`, which troupe's
    `RUNNER_FAIL_FAST_ON_AUTH_RETRY` stops at once;
  - a run that Claude Code ends without a `result` (as it does after SIGTERM) gets no invented one, so troupe derives
    the outcome.
- **The mapping covers what the table leaves open**, and the contract's table is updated to say so:
  - a retry with no HTTP status is `network`; Claude Code reports a refused connection as `"error":"unknown"` with
    `error_status: null`, checked against the real CLI while drafting this change;
  - tools that permissions denied become a `log` warning before the `result`, so "nothing happened" has a visible
    reason;
  - a record type the mapping doesn't know gets a `debug` log the first time it appears, and a line that isn't JSON
    gets a `warning` log. Both stay in the transcript.
  - summaries are cut to fit below `limits.eventMaxBytes`, saying how much was left out.
- **Cancel, end of input and shutdown stop Claude Code on Linux, macOS and Windows** before the runner exits. On
  POSIX that's SIGTERM, then a kill after a short named grace. On Windows Claude Code is terminated. The runner never
  exits while Claude Code is still running, and it sends no events after a cancel.
- **Options, closed and published as `options.schema.json`:** `model`, `maxBudgetUsd`, `permissionMode`,
  `allowedTools`, `disallowedTools` and `settingSources`. An unknown option is refused, naming it.
- **Every run has a budget:** USD 5 when `maxBudgetUsd` isn't set, a named default in the runner (owner,
  2026-10-24). The permission mode is Claude Code's own unless `permissionMode` sets it, so troupe never grants more
  than config asks for (owner, 2026-10-24). In print mode that default denies edits, and the denials are reported.
- **By default the actor doesn't see the person's Claude Code settings, hooks or MCP servers**
  (`--setting-sources ""`, `--strict-mcp-config`). A run doesn't depend on whoever runs it, and the actor doesn't run
  the hooks of the repository it works in. This repository's own guard hooks are an example. `settingSources` opts
  back in (owner, 2026-10-24). Login still works: it isn't a setting, and `--bare`, which would block OAuth, isn't
  used.
- **The Claude Code fixtures and their capture tool move to the new plugin** (owner, 2026-10-24), because they are
  Claude Code's output.
  The scripted runner's tests and core's replay tests read them from there. New offline fixtures cover the other retry
  reasons: `network-retries`, `server-retries` and `rate-limit-retries`. The existing hand-written events are
  corrected where they disagree with the contract. `success-with-tools` leaves out the cache counters that the
  contract's `usage` mapping requires.
- **`perform` knows the runner by name:** a `claude-code` entry in the interim runner table (#36, design D4). The
  table also names the environment variables a runner needs, which `perform` passes from its own environment: the
  path, the home and temporary directories, the locale, proxies, `CLAUDE_CONFIG_DIR`, `CLAUDE_CODE_OAUTH_TOKEN` and
  `ANTHROPIC_API_KEY`. It needs them because the host starts a runner with nothing it isn't given. Without them,
  Claude Code can't be found and can't find the person's login.
- **Tests:**
  - the deterministic tests replay the fixtures, through the mapping and through a fake `claude` on `PATH`;
  - the runner passes the conformance suite;
  - cancelling is tested on all three operating systems;
  - an **opt-in live test** runs real Claude Code with a pinned model and a budget cap. It never runs in CI, and needs
    `TROUPE_LIVE_CLAUDE_CODE=1` and a credential or an existing login.

Out of scope, as #55 says:
- credentials inside containers (#11): this runs on the local stage, with the person's existing login;
- choosing runners from config and loading their schemas at run time (#38, #60);
- pointing Claude Code at another endpoint (`ANTHROPIC_BASE_URL`), such as a local model on Ollama: that's #160,
  which has to keep a repo's config from redirecting the person's credential;
- Bedrock, Vertex and other providers' variables, and multi-turn or resumed sessions.

## Capabilities

### New Capabilities
- `claude-code-runner`: The Claude Code runner plugin. It covers how it starts Claude Code, the mapping of
  stream-json onto run events, cancel and end of input, its options and errors, its published schemas, the Claude Code
  fixtures and their capture, and the opt-in live test.

### Modified Capabilities
- `scripted-runner`: The Claude Code fixtures' requirements ("Fixtures pair real engine output with protocol events",
  "Fixtures hold no secrets") move to `claude-code-runner`. The scripted runner keeps replaying recordings.
- `runs`: `perform` can run an actor whose runner is `claude-code`. It starts a runner with the environment
  variables that runner is known to need, taken from its own environment, and with nothing else.

## Impact

- New: `plugins/runner-claude-code/`, containing its `pyproject.toml`, `README.md`, `LICENSE`, the package
  `src/troupe_runner_claude_code/`, its published schemas, tests, `fixtures/claude-code/` and
  `tools/capture_claude.py` (both moved).
- Core: `packages/troupe/src/troupe/core/interim.py` (the entry and the `environment` names) and
  `core/runs/perform.py`, which passes them. Tests: `test_claude_fixtures.py` (the new path), and new perform and
  conformance tests.
- Workspace wiring: the root `pyproject.toml` (sources, dev group, ruff, mypy, pytest paths, import-linter roots and
  contracts), `scripts/check-paths.toml`, `release-please-config.json` and `.release-please-manifest.json`, and
  `uv.lock`.
- Docs: `contributing/runners.md` (the mapping table and the runners troupe ships), `plugins/README.md`,
  `plugins/runner-scripted/README.md`, `docs/stagecraft/bring-your-own-agent.md` and
  `docs/opening-night/first-performance.md`.
- Nothing changes for existing users. An actor whose runner is `scripted` runs as before, with no new variables.
